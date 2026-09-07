"""Tier 5 tests: SpecialExportClient end to end, fixture XML through a
mocked transport. See docs/specs/005-public-api.md section 6."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from special_export_mcp import SpecialExportClient
from special_export_mcp.errors import FetchError, PageNotFoundError

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        pass


@pytest.fixture
def mock_session(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    session = MagicMock()
    monkeypatch.setattr("special_export_mcp.fetch.requests.Session", lambda: session)
    return session


MISSING_PAGE_XML = """<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
<siteinfo></siteinfo>
</mediawiki>"""


def test_get_page_tables_against_the_real_fixture(mock_session: MagicMock) -> None:
    xml_text = (FIXTURES / "volkswagen_golf_mk4.xml").read_text(encoding="utf-8")
    mock_session.request.return_value = FakeResponse(xml_text)

    client = SpecialExportClient(min_request_interval=0)
    result = client.get_page_tables("Volkswagen Golf Mk4")

    assert result["exists"] is True
    assert len(result["tables"]) >= 1
    assert any(t["section"] == "Engine choices > Golf and Jetta" for t in result["tables"])


def test_missing_page_does_not_raise(mock_session: MagicMock) -> None:
    mock_session.request.return_value = FakeResponse(MISSING_PAGE_XML)

    client = SpecialExportClient(min_request_interval=0)
    result = client.get_page_tables("Some Nonexistent Article")

    assert result["exists"] is False
    assert result["error"]
    assert result["tables"] == []


def test_http_500_after_retries_raises_fetcherror_not_exists_false(
    mock_session: MagicMock,
) -> None:
    mock_session.request.return_value = FakeResponse("", status_code=500)

    client = SpecialExportClient(min_request_interval=0, max_retries=1)

    with pytest.raises(FetchError):
        client.get_page_tables("Volkswagen Golf Mk4")


def test_import_needs_no_mcp_package() -> None:
    # special_export_mcp/__init__.py must not import server.py (the mcp
    # extra) at module load time. The import succeeding is the assertion.
    import special_export_mcp  # noqa: F401


def test_cache_dir_makes_two_calls_produce_one_http_request(
    mock_session: MagicMock, tmp_path: Path
) -> None:
    xml_text = (FIXTURES / "volkswagen_golf_mk4.xml").read_text(encoding="utf-8")
    mock_session.request.return_value = FakeResponse(xml_text)

    client = SpecialExportClient(min_request_interval=0, cache_dir=tmp_path)
    client.get_page_tables("Volkswagen Golf Mk4")
    assert mock_session.request.call_count == 1

    mock_session.request.side_effect = AssertionError("must not be called again")
    result = client.get_page_tables("Volkswagen Golf Mk4")
    assert result["exists"] is True


def test_get_wikitext_returns_raw_text(mock_session: MagicMock) -> None:
    xml_text = (FIXTURES / "volkswagen_golf_mk4.xml").read_text(encoding="utf-8")
    mock_session.request.return_value = FakeResponse(xml_text)

    client = SpecialExportClient(min_request_interval=0)
    text = client.get_wikitext("Volkswagen Golf Mk4")

    assert "==Engine choices==" in text


def test_get_wikitext_raises_page_not_found_on_missing_page(mock_session: MagicMock) -> None:
    mock_session.request.return_value = FakeResponse(MISSING_PAGE_XML)

    client = SpecialExportClient(min_request_interval=0)

    with pytest.raises(PageNotFoundError):
        client.get_wikitext("Some Nonexistent Article")


def test_cells_are_cleaned_through_tier_3(mock_session: MagicMock) -> None:
    xml_text = (FIXTURES / "volkswagen_golf_mk4.xml").read_text(encoding="utf-8")
    mock_session.request.return_value = FakeResponse(xml_text)

    client = SpecialExportClient(min_request_interval=0)
    result = client.get_page_tables("Volkswagen Golf Mk4")

    engine_table = result["tables"][0]
    for row in engine_table["rows"]:
        for cell in row:
            assert "{{" not in cell
            assert "[[" not in cell


def test_get_pages_tables_one_bad_title_does_not_sink_the_batch(
    mock_session: MagicMock,
) -> None:
    xml_text = (FIXTURES / "volkswagen_golf_mk4.xml").read_text(encoding="utf-8")
    mock_session.request.return_value = FakeResponse(xml_text)

    client = SpecialExportClient(min_request_interval=0)
    results = client.get_pages_tables(["Nonexistent Article Xyz", "Volkswagen Golf Mk4"])

    assert results[0]["exists"] is False
    assert results[1]["exists"] is True


def test_strict_mode_raises_on_a_malformed_template(mock_session: MagicMock) -> None:
    from special_export_mcp.errors import TemplateResolutionError

    xml_text = (
        '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        "<page><title>X</title><id>1</id>"
        "<revision><id>1</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
        '<text>{| class="wikitable"\n|-\n! A\n|-\n| {{convert|abc|kW}}\n|}</text>'
        "</revision></page></mediawiki>"
    )
    mock_session.request.return_value = FakeResponse(xml_text)

    client = SpecialExportClient(min_request_interval=0, strict=True)

    with pytest.raises(TemplateResolutionError):
        client.get_page_tables("X")


def test_heading_template_warning_reaches_table_and_page_results(
    mock_session: MagicMock,
) -> None:
    xml_text = (
        '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        "<page><title>X</title><id>1</id>"
        "<revision><id>1</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
        '<text>== {{unsupported_heading|Engines}} ==\n{| class="wikitable"\n'
        "|-\n! A\n|-\n| x\n|}</text>"
        "</revision></page></mediawiki>"
    )
    mock_session.request.return_value = FakeResponse(xml_text)

    client = SpecialExportClient(min_request_interval=0)
    result = client.get_page_tables("X")

    warning = result["tables"][0]["warnings"][0]
    assert warning["kind"] == "unknown_template"
    assert warning["table_index"] == 0
    assert result["warnings"] == [warning]


def test_strict_mode_raises_on_an_unknown_heading_template(
    mock_session: MagicMock,
) -> None:
    from special_export_mcp.errors import TemplateResolutionError

    xml_text = (
        '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        "<page><title>X</title><id>1</id>"
        "<revision><id>1</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
        '<text>== {{unsupported_heading|Engines}} ==\n{| class="wikitable"\n'
        "|-\n! A\n|-\n| x\n|}</text>"
        "</revision></page></mediawiki>"
    )
    mock_session.request.return_value = FakeResponse(xml_text)

    client = SpecialExportClient(min_request_interval=0, strict=True)

    with pytest.raises(TemplateResolutionError):
        client.get_page_tables("X")


def test_table_class_filter_is_passed_through(mock_session: MagicMock) -> None:
    xml_text = (
        '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        "<page><title>X</title><id>1</id>"
        "<revision><id>1</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
        '<text>{| class="wikitable"\n|-\n! A\n|-\n| x\n|}\n'
        '{| class="navbox"\n|-\n! A\n|-\n| y\n|}</text>'
        "</revision></page></mediawiki>"
    )
    mock_session.request.return_value = FakeResponse(xml_text)

    client = SpecialExportClient(min_request_interval=0, table_class="wikitable")
    result = client.get_page_tables("X")

    assert len(result["tables"]) == 1
    assert result["tables"][0]["rows"] == [["x"]]
