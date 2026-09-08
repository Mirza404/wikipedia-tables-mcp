"""Tier 6: the MCP server surface. Optional extra: pip install special-export-mcp[mcp].

Thin adapter: no fetch logic, no parse logic. Constructs one
SpecialExportClient and calls it. See docs/specs/006-mcp-surface.md.
"""

from __future__ import annotations

import argparse
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__
from .client import PageResult, SpecialExportClient
from .wikitext.sections import extract_section, list_sections

MCP_MAX_TABLES_DEFAULT = 10
MAX_WIKITEXT_CHARS_DEFAULT = 100_000

INSTRUCTIONS = (
    "Fetches Wikipedia wikitext via Special:Export and returns parsed "
    "wikitables. warnings in a result are data-quality controls, not "
    "optional diagnostics. On a warning with kind=ambiguous_row_alignment, "
    "never trust that row's positionally assigned fields and never silently "
    "repair them -- import the other rows normally and quarantine only the "
    "ambiguous one. Recover only facts explicit in the evidence (a value "
    "labelled '132 kW' is power, regardless of which column it landed in). "
    "get_wikitext gives nearby raw source as a bounded fallback when that is "
    "needed. Anything still inferred must stay null or pending review, "
    "recorded with its source and confidence. See docs/data-integrity.md."
)


def _matches_section_filter(section: str, section_filter: str | None) -> bool:
    if not section_filter:
        return True
    return section_filter.lower() in section.lower()


def _apply_response_bounds(
    result: PageResult, section_filter: str | None, max_tables: int
) -> dict[str, Any]:
    tables = list(result["tables"])
    if section_filter:
        tables = [t for t in tables if _matches_section_filter(t["section"], section_filter)]

    truncated = len(tables) > max_tables
    if truncated:
        tables = tables[:max_tables]

    out: dict[str, Any] = dict(result)
    out["tables"] = tables
    if truncated:
        out["truncated"] = True
    return out


def build_server(client: SpecialExportClient) -> MCPServer:
    server: MCPServer = MCPServer(
        name="special-export-mcp",
        version=__version__,
        instructions=INSTRUCTIONS,
    )

    @server.tool(
        description=(
            "Fetch one Wikipedia page via Special:Export and return its parsed "
            "wikitables, each with its section breadcrumb. warnings are "
            "data-quality controls: on ambiguous_row_alignment, do not trust "
            "that row's positional field assignments or silently repair it."
        )
    )
    def get_page_tables(
        title: str,
        section_filter: str | None = None,
        table_class: str | None = None,
        max_tables: int | None = None,
    ) -> dict[str, Any]:
        # max_tables is enforced post-parse (_apply_response_bounds), not
        # passed to parse_tables as a Limits cap: that would silently
        # discard the extras before this tool could ever detect and report
        # the truncation it just caused.
        result = client.get_page_tables(title, table_class=table_class)
        return _apply_response_bounds(result, section_filter, max_tables or MCP_MAX_TABLES_DEFAULT)

    @server.tool(
        description=(
            "Same as get_page_tables, for up to 20 titles in one call. This is "
            "the tool a bulk loading phase uses."
        )
    )
    def get_pages_tables(
        titles: list[str],
        section_filter: str | None = None,
        table_class: str | None = None,
        max_tables: int | None = None,
    ) -> list[dict[str, Any]]:
        results = client.get_pages_tables(titles, table_class=table_class)
        cap = max_tables or MCP_MAX_TABLES_DEFAULT
        return [_apply_response_bounds(r, section_filter, cap) for r in results]

    @server.tool(
        description=(
            "Return raw wikitext for a page. Optional section returns only the "
            "wikitext under a heading whose breadcrumb contains it "
            "(case-insensitive). Use this to see the source when the table "
            "parser produced a warning or an unexpected shape on a new "
            "article, not as the normal retrieval path."
        )
    )
    def get_wikitext(
        title: str,
        section: str | None = None,
        max_chars: int = MAX_WIKITEXT_CHARS_DEFAULT,
    ) -> dict[str, Any]:
        text = client.get_wikitext(title)
        if section:
            extracted = extract_section(text, section)
            text = extracted if extracted is not None else ""

        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]
        return {"wikitext": text, "truncated": truncated}

    @server.tool(
        description=(
            "List the heading tree of a page: each heading's section "
            "breadcrumb and the number of tables directly under it. Cheap; "
            "use it to choose a section_filter before pulling a large "
            "get_page_tables payload."
        )
    )
    def list_page_sections(title: str) -> list[dict[str, Any]]:
        text = client.get_wikitext(title)
        return [
            {
                "section": info.section,
                "section_path": info.section_path,
                "table_count": info.table_count,
            }
            for info in list_sections(text)
        ]

    return server


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="special-export-mcp")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--language", default="en")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--contact", default=None, help="User-Agent contact segment")
    parser.add_argument("--user-agent", default=None, help="Full User-Agent override")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--table-class", default=None)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--min-request-interval", type=float, default=1.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    client = SpecialExportClient(
        language=args.language,
        base_url=args.base_url,
        user_agent=args.user_agent,
        user_agent_contact=args.contact,
        max_retries=args.max_retries,
        min_request_interval=args.min_request_interval,
        cache_dir=args.cache_dir,
        strict=args.strict,
        table_class=args.table_class,
    )
    try:
        server = build_server(client)
        server.run(transport=args.transport)
    finally:
        client.close()


if __name__ == "__main__":
    main()
