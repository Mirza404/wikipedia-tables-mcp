"""Tier 6 tests: tool registration and passthrough.

See docs/specs/006-mcp-surface.md section 5.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.types import CallToolResult, TextContent

from wikipedia_tables_mcp.client import SpecialExportClient
from wikipedia_tables_mcp.server import _parse_args, build_server

FIXTURES = Path(__file__).parent / "fixtures"


def _text(result: object) -> str:
    assert isinstance(result, CallToolResult)
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        pass


@pytest.fixture
def mock_session(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    session = MagicMock()
    monkeypatch.setattr("wikipedia_tables_mcp.fetch.requests.Session", lambda: session)
    return session


@pytest.fixture
def golf_xml() -> str:
    return (FIXTURES / "volkswagen_golf_mk4.xml").read_text(encoding="utf-8")


async def test_server_lists_exactly_the_four_tools(mock_session: MagicMock) -> None:
    client = SpecialExportClient(min_request_interval=0)
    server = build_server(client)

    tools = await server.list_tools()

    assert {t.name for t in tools} == {
        "get_page_tables",
        "get_pages_tables",
        "get_wikitext",
        "list_page_sections",
    }


async def test_get_page_tables_matches_the_library_with_no_extra_transformation(
    mock_session: MagicMock, golf_xml: str
) -> None:
    mock_session.request.return_value = FakeResponse(golf_xml)
    client = SpecialExportClient(min_request_interval=0)
    server = build_server(client)

    direct = client.get_page_tables("Volkswagen Golf Mk4")
    via_tool = await server.call_tool("get_page_tables", {"title": "Volkswagen Golf Mk4"})
    tool_result = json.loads(_text(via_tool))

    assert tool_result == direct


async def test_section_filter_keeps_only_matching_tables(
    mock_session: MagicMock, golf_xml: str
) -> None:
    mock_session.request.return_value = FakeResponse(golf_xml)
    client = SpecialExportClient(min_request_interval=0)
    server = build_server(client)

    result = await server.call_tool(
        "get_page_tables", {"title": "Volkswagen Golf Mk4", "section_filter": "jetta"}
    )
    data = json.loads(_text(result))

    assert len(data["tables"]) == 1
    assert "jetta" in data["tables"][0]["section"].lower()


async def test_table_class_reaches_through_to_parsing(mock_session: MagicMock) -> None:
    xml_text = (
        '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        "<page><title>X</title><id>1</id>"
        "<revision><id>1</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
        '<text>{| class="wikitable"\n|-\n! A\n|-\n| x\n|}\n'
        '{| class="navbox"\n|-\n! A\n|-\n| y\n|}</text>'
        "</revision></page></mediawiki>"
    )
    mock_session.request.return_value = FakeResponse(xml_text)
    client = SpecialExportClient(min_request_interval=0)
    server = build_server(client)

    result = await server.call_tool("get_page_tables", {"title": "X", "table_class": "wikitable"})
    data = json.loads(_text(result))

    assert len(data["tables"]) == 1
    assert data["tables"][0]["rows"] == [["x"]]


async def test_max_tables_truncates_and_reports_it(mock_session: MagicMock) -> None:
    tables_wikitext = "\n".join(
        f'{{| class="wikitable"\n|-\n! A\n|-\n| {i}\n|}}' for i in range(15)
    )
    xml_text = (
        '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        "<page><title>X</title><id>1</id>"
        "<revision><id>1</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
        f"<text>{tables_wikitext}</text>"
        "</revision></page></mediawiki>"
    )
    mock_session.request.return_value = FakeResponse(xml_text)
    client = SpecialExportClient(min_request_interval=0)
    server = build_server(client)

    result = await server.call_tool("get_page_tables", {"title": "X"})
    data = json.loads(_text(result))

    assert len(data["tables"]) == 10  # MCP_MAX_TABLES_DEFAULT
    assert data["truncated"] is True


async def test_max_tables_override_raises_the_cap(mock_session: MagicMock) -> None:
    tables_wikitext = "\n".join(
        f'{{| class="wikitable"\n|-\n! A\n|-\n| {i}\n|}}' for i in range(15)
    )
    xml_text = (
        '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        "<page><title>X</title><id>1</id>"
        "<revision><id>1</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
        f"<text>{tables_wikitext}</text>"
        "</revision></page></mediawiki>"
    )
    mock_session.request.return_value = FakeResponse(xml_text)
    client = SpecialExportClient(min_request_interval=0)
    server = build_server(client)

    result = await server.call_tool("get_page_tables", {"title": "X", "max_tables": 15})
    data = json.loads(_text(result))

    assert len(data["tables"]) == 15
    assert "truncated" not in data or data["truncated"] is False


async def test_get_wikitext_returns_raw_text(mock_session: MagicMock, golf_xml: str) -> None:
    mock_session.request.return_value = FakeResponse(golf_xml)
    client = SpecialExportClient(min_request_interval=0)
    server = build_server(client)

    result = await server.call_tool("get_wikitext", {"title": "Volkswagen Golf Mk4"})
    data = json.loads(_text(result))

    assert "==Engine choices==" in data["wikitext"]
    assert data["truncated"] is False


async def test_get_wikitext_section_extracts_only_that_subtree(
    mock_session: MagicMock, golf_xml: str
) -> None:
    mock_session.request.return_value = FakeResponse(golf_xml)
    client = SpecialExportClient(min_request_interval=0)
    server = build_server(client)

    result = await server.call_tool(
        "get_wikitext", {"title": "Volkswagen Golf Mk4", "section": "Golf Cabriolet (Mk3"}
    )
    data = json.loads(_text(result))

    assert data["wikitext"].startswith("===Golf Cabriolet")
    assert "==Engine choices==" not in data["wikitext"]


async def test_get_wikitext_max_chars_truncates_and_flags_it(
    mock_session: MagicMock, golf_xml: str
) -> None:
    mock_session.request.return_value = FakeResponse(golf_xml)
    client = SpecialExportClient(min_request_interval=0)
    server = build_server(client)

    result = await server.call_tool(
        "get_wikitext", {"title": "Volkswagen Golf Mk4", "max_chars": 50}
    )
    data = json.loads(_text(result))

    assert len(data["wikitext"]) == 50
    assert data["truncated"] is True


async def test_list_page_sections_reports_the_heading_tree(
    mock_session: MagicMock, golf_xml: str
) -> None:
    mock_session.request.return_value = FakeResponse(golf_xml)
    client = SpecialExportClient(min_request_interval=0)
    server = build_server(client)

    result = await server.call_tool("list_page_sections", {"title": "Volkswagen Golf Mk4"})
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    sections = result.structured_content["result"]

    with_tables = [s for s in sections if s["table_count"] > 0]
    assert {s["section"] for s in with_tables} == {
        "Engine choices > Golf and Jetta",
        "Engine choices > Golf Cabriolet (Mk3 platform)",
    }


def test_import_mcp_package_absent_breaks_only_server(monkeypatch: pytest.MonkeyPatch) -> None:
    # Purge both wikipedia_tables_mcp's own cached modules and mcp's, or a
    # prior test's import of e.g. mcp.server.mcpserver would still resolve
    # from cache regardless of what sys.modules["mcp"] is set to.
    for name in list(sys.modules):
        if (
            name == "wikipedia_tables_mcp"
            or name.startswith("wikipedia_tables_mcp.")
            or name == "mcp"
            or name.startswith("mcp.")
        ):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "mcp", None)

    import wikipedia_tables_mcp  # noqa: F401
    import wikipedia_tables_mcp.client  # noqa: F401

    with pytest.raises(ImportError):
        import wikipedia_tables_mcp.server  # noqa: F401


def test_cli_flags_map_onto_client_constructor_arguments() -> None:
    args = _parse_args(
        [
            "--transport",
            "sse",
            "--language",
            "de",
            "--contact",
            "you@example.com",
            "--cache-dir",
            "/tmp/cache",
            "--strict",
            "--table-class",
            "wikitable",
        ]
    )

    assert args.transport == "sse"
    assert args.language == "de"
    assert args.contact == "you@example.com"
    assert args.cache_dir == "/tmp/cache"
    assert args.strict is True
    assert args.table_class == "wikitable"


def test_cli_defaults() -> None:
    args = _parse_args([])

    assert args.transport == "stdio"
    assert args.language == "en"
    assert args.strict is False
