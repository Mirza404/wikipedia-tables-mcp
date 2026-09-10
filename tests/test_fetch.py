"""Tier 1 tests. No test here makes a live network call."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wikipedia_tables_mcp.errors import ExportParseError, FetchError, RateLimitError
from wikipedia_tables_mcp.fetch import Fetcher

FIXTURES = Path(__file__).parent / "fixtures"

MISSING_PAGE_XML = """<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
<siteinfo></siteinfo>
</mediawiki>"""


def _page_xml(*titles: str) -> str:
    pages = "".join(
        f"""<page>
<title>{title}</title>
<id>1</id>
<revision>
<id>10</id>
<timestamp>2026-09-05T00:00:00Z</timestamp>
<text>wikitext for {title}</text>
</revision>
</page>"""
        for title in titles
    )
    return f'<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">{pages}</mediawiki>'


class FakeResponse:
    def __init__(
        self, text: str, status_code: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        pass


@pytest.fixture
def mock_session(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    session = MagicMock()
    monkeypatch.setattr("wikipedia_tables_mcp.fetch.requests.Session", lambda: session)
    return session


def test_fetch_wikitext_returns_real_fixture_content(mock_session: MagicMock) -> None:
    xml_text = (FIXTURES / "volkswagen_golf_mk4.xml").read_text(encoding="utf-8")
    mock_session.request.return_value = FakeResponse(xml_text)

    fetcher = Fetcher(min_request_interval=0)
    result = fetcher.fetch_wikitext("Volkswagen Golf Mk4")

    assert result.exists is True
    assert result.wikitext is not None
    assert "==Engine choices==" in result.wikitext
    assert '{| class="wikitable"' in result.wikitext


def test_fetch_many_issues_one_post_for_a_batch(mock_session: MagicMock) -> None:
    mock_session.request.return_value = FakeResponse(
        _page_xml("Volkswagen Golf Mk4", "Skoda Octavia")
    )

    fetcher = Fetcher(min_request_interval=0)
    results = fetcher.fetch_many(["Volkswagen Golf Mk4", "Skoda Octavia"])

    assert mock_session.request.call_count == 1
    method = mock_session.request.call_args.args[0]
    assert method == "POST"
    assert len(results) == 2
    assert all(r.exists for r in results)


def test_missing_page_is_not_an_exception(mock_session: MagicMock) -> None:
    mock_session.request.return_value = FakeResponse(MISSING_PAGE_XML)

    fetcher = Fetcher(min_request_interval=0)
    result = fetcher.fetch_wikitext("Some Nonexistent Article Xyz")

    assert result.exists is False
    assert result.error == "Page not found: Some Nonexistent Article Xyz"


def test_missing_title_within_a_batch(mock_session: MagicMock) -> None:
    mock_session.request.return_value = FakeResponse(_page_xml("Volkswagen Golf Mk4"))

    fetcher = Fetcher(min_request_interval=0)
    results = fetcher.fetch_many(["Volkswagen Golf Mk4", "Nonexistent Article"])

    assert results[0].exists is True
    assert results[1].exists is False
    assert results[1].error == "Page not found: Nonexistent Article"


def test_every_request_carries_the_compliant_user_agent(mock_session: MagicMock) -> None:
    mock_session.request.return_value = FakeResponse(_page_xml("Golf"))

    fetcher = Fetcher(min_request_interval=0, user_agent_contact="test@example.com")
    fetcher.fetch_wikitext("Golf")

    headers = mock_session.request.call_args.kwargs["headers"]
    assert headers["User-Agent"].startswith("wikipedia-tables-mcp/")
    assert "test@example.com" in headers["User-Agent"]


def test_empty_user_agent_is_rejected() -> None:
    from wikipedia_tables_mcp.errors import ConfigurationError

    with pytest.raises(ConfigurationError):
        Fetcher(user_agent="")


def _redirect_page_xml(title: str, target: str) -> str:
    return (
        '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        f"<page><title>{title}</title><id>1</id>"
        "<revision><id>10</id><timestamp>2026-09-05T00:00:00Z</timestamp>"
        f"<text>#REDIRECT [[{target}]]</text></revision></page></mediawiki>"
    )


def test_redirect_is_followed_to_the_real_target(mock_session: MagicMock) -> None:
    # Special:Export's redirects=1 query parameter is a no-op in practice
    # (verified against en.wikipedia.org/wiki/Special:Export/UK): a
    # requested redirect page comes back as itself, containing only
    # "#REDIRECT [[Target]]". Resolving it takes a second real request.
    mock_session.request.side_effect = [
        FakeResponse(_redirect_page_xml("Golf Mk4", "Volkswagen Golf Mk4")),
        FakeResponse(_page_xml("Volkswagen Golf Mk4")),
    ]

    fetcher = Fetcher(min_request_interval=0)
    result = fetcher.fetch_wikitext("Golf Mk4")

    assert result.exists is True
    assert result.requested_title == "Golf Mk4"
    assert result.resolved_title == "Volkswagen Golf Mk4"
    assert result.wikitext == "wikitext for Volkswagen Golf Mk4"
    assert mock_session.request.call_count == 2


def test_redirect_chain_stops_at_the_hop_limit(mock_session: MagicMock) -> None:
    # Each hop redirects to the next, forever: without a limit this would
    # recurse without bound. Every response is a fresh redirect stub, so
    # the number of requests made is the proof the limit was enforced.
    mock_session.request.side_effect = lambda *a, **k: FakeResponse(
        _redirect_page_xml("Whatever", "Next")
    )

    fetcher = Fetcher(min_request_interval=0)
    result = fetcher.fetch_wikitext("Start")

    assert result.exists is True
    assert mock_session.request.call_count == 6  # 1 initial + MAX_REDIRECT_HOPS


def test_a_matched_page_that_is_not_a_redirect_is_returned_as_is(
    mock_session: MagicMock,
) -> None:
    mock_session.request.return_value = FakeResponse(_page_xml("Golf"))

    fetcher = Fetcher(min_request_interval=0)
    result = fetcher.fetch_wikitext("Golf")

    assert result.resolved_title == "Golf"
    assert mock_session.request.call_count == 1


def test_batch_does_not_guess_by_position_for_unmatched_titles(
    mock_session: MagicMock,
) -> None:
    # Only "Skoda Octavia" comes back; "Volkswagen Golf Mk4" is genuinely
    # missing. A prior version paired unmatched requests with leftover
    # pages positionally, which would have wrongly assigned Octavia's
    # content to the Golf Mk4 title here.
    mock_session.request.return_value = FakeResponse(_page_xml("Skoda Octavia"))

    fetcher = Fetcher(min_request_interval=0)
    results = fetcher.fetch_many(["Volkswagen Golf Mk4", "Skoda Octavia"])

    assert results[0].exists is False
    assert results[0].error == "Page not found: Volkswagen Golf Mk4"
    assert results[1].exists is True
    assert results[1].wikitext == "wikitext for Skoda Octavia"


def test_batch_redirect_is_followed_with_a_followup_request(
    mock_session: MagicMock,
) -> None:
    mock_session.request.side_effect = [
        FakeResponse(_redirect_page_xml("Golf Mk4", "Volkswagen Golf Mk4")),
        FakeResponse(_page_xml("Volkswagen Golf Mk4")),
    ]

    fetcher = Fetcher(min_request_interval=0)
    results = fetcher.fetch_many(["Golf Mk4"])

    assert results[0].exists is True
    assert results[0].resolved_title == "Volkswagen Golf Mk4"
    assert mock_session.request.call_count == 2


def test_non_export_xml_response_raises_instead_of_reporting_missing(
    mock_session: MagicMock,
) -> None:
    # A well-formed XML document that is not a mediawiki export (an error
    # page, a maintenance notice) must not be read as "zero pages", which
    # the caller would otherwise report as every requested title missing.
    mock_session.request.return_value = FakeResponse(
        "<error><info>Not confirmed, blocked, or something else went wrong.</info></error>"
    )

    fetcher = Fetcher(min_request_interval=0)

    with pytest.raises(ExportParseError):
        fetcher.fetch_wikitext("Golf")


def test_retries_on_503_then_succeeds(mock_session: MagicMock) -> None:
    mock_session.request.side_effect = [
        FakeResponse("", status_code=503),
        FakeResponse(_page_xml("Golf")),
    ]

    fetcher = Fetcher(min_request_interval=0)
    result = fetcher.fetch_wikitext("Golf")

    assert result.exists is True
    assert mock_session.request.call_count == 2


def test_429_after_retries_raises_rate_limit_error(mock_session: MagicMock) -> None:
    mock_session.request.return_value = FakeResponse("", status_code=429)

    fetcher = Fetcher(min_request_interval=0, max_retries=1)

    with pytest.raises(RateLimitError):
        fetcher.fetch_wikitext("Golf")

    assert mock_session.request.call_count == 2


def test_honours_retry_after_header(
    mock_session: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("wikipedia_tables_mcp.fetch.time.sleep", slept.append)
    mock_session.request.side_effect = [
        FakeResponse("", status_code=503, headers={"Retry-After": "7"}),
        FakeResponse(_page_xml("Golf")),
    ]

    fetcher = Fetcher(min_request_interval=0)
    fetcher.fetch_wikitext("Golf")

    assert 7.0 in slept


def test_404_is_not_retried(mock_session: MagicMock) -> None:
    mock_session.request.return_value = FakeResponse("", status_code=404)

    fetcher = Fetcher(min_request_interval=0)

    with pytest.raises(FetchError):
        fetcher.fetch_wikitext("Golf")

    assert mock_session.request.call_count == 1


def test_invalid_xml_raises_export_parse_error(mock_session: MagicMock) -> None:
    mock_session.request.return_value = FakeResponse("not xml at all <<<")

    fetcher = Fetcher(min_request_interval=0)

    with pytest.raises(ExportParseError):
        fetcher.fetch_wikitext("Golf")


def test_cache_hit_skips_the_second_http_request(mock_session: MagicMock, tmp_path: Path) -> None:
    mock_session.request.return_value = FakeResponse(_page_xml("Golf"))

    fetcher = Fetcher(min_request_interval=0, cache_dir=tmp_path)
    fetcher.fetch_wikitext("Golf")
    assert mock_session.request.call_count == 1

    mock_session.request.side_effect = AssertionError("must not be called again")
    result = fetcher.fetch_wikitext("Golf")

    assert result.exists is True
    assert result.wikitext == "wikitext for Golf"


def test_refresh_bypasses_the_cache(mock_session: MagicMock, tmp_path: Path) -> None:
    mock_session.request.return_value = FakeResponse(_page_xml("Golf"))

    fetcher = Fetcher(min_request_interval=0, cache_dir=tmp_path)
    fetcher.fetch_wikitext("Golf")
    fetcher.fetch_wikitext("Golf", refresh=True)

    assert mock_session.request.call_count == 2


def test_no_titles_returns_empty_list(mock_session: MagicMock) -> None:
    fetcher = Fetcher(min_request_interval=0)
    assert fetcher.fetch_many([]) == []
    mock_session.request.assert_not_called()
