"""Tier 5: SpecialExportClient, the public API assembling Tiers 1-4.

See docs/specs/005-public-api.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

from .errors import PageNotFoundError
from .fetch import Fetcher, FetchResult
from .wikitext.inline import clean_cell
from .wikitext.tables import Limits, ParsedTable, parse_tables


class TableResult(TypedDict):
    headers: list[str]
    rows: list[list[str]]
    section: str
    section_path: list[str]
    caption: str | None
    index: int
    parent_table_index: int | None
    truncated: bool
    warnings: list[dict[str, object]]


class PageResult(TypedDict):
    exists: bool
    tables: list[TableResult]
    error: str | None
    requested_title: str
    resolved_title: str | None
    page_id: int | None
    revision_id: int | None
    revision_timestamp: str | None
    warnings: list[dict[str, object]]


class SpecialExportClient:
    """Title in, structured tables out. The core the MCP server wraps."""

    def __init__(
        self,
        *,
        language: str = "en",
        base_url: str | None = None,
        user_agent: str | None = None,
        user_agent_contact: str | None = None,
        timeout: tuple[float, float] = (5.0, 30.0),
        max_retries: int = 3,
        min_request_interval: float = 1.0,
        cache_dir: str | Path | None = None,
        strict: bool = False,
        table_class: str | None = None,
        limits: Limits | None = None,
    ) -> None:
        self._fetcher = Fetcher(
            base_url=base_url,
            language=language,
            user_agent=user_agent,
            user_agent_contact=user_agent_contact,
            timeout=timeout,
            max_retries=max_retries,
            min_request_interval=min_request_interval,
            cache_dir=cache_dir,
        )
        self.strict = strict
        self.table_class = table_class
        self.limits = limits

    def close(self) -> None:
        self._fetcher.close()

    def __enter__(self) -> SpecialExportClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def get_wikitext(self, title: str) -> str:
        """Tier 1 escape hatch. Raises PageNotFoundError, unlike get_page_tables."""
        result = self._fetcher.fetch_wikitext(title)
        if not result.exists:
            raise PageNotFoundError(result.error or f"Page not found: {title}", title=title)
        assert result.wikitext is not None
        return result.wikitext

    def get_page_tables(self, title: str, *, refresh: bool = False) -> PageResult:
        return self.get_pages_tables([title], refresh=refresh)[0]

    def get_pages_tables(self, titles: Sequence[str], *, refresh: bool = False) -> list[PageResult]:
        fetch_results = self._fetcher.fetch_many(list(titles), refresh=refresh)
        return [self._build_page_result(result) for result in fetch_results]

    def _build_page_result(self, fetch_result: FetchResult) -> PageResult:
        if not fetch_result.exists:
            return PageResult(
                exists=False,
                tables=[],
                error=fetch_result.error,
                requested_title=fetch_result.requested_title,
                resolved_title=None,
                page_id=None,
                revision_id=None,
                revision_timestamp=None,
                warnings=[],
            )

        assert fetch_result.wikitext is not None
        parsed_tables = parse_tables(
            fetch_result.wikitext,
            table_class=self.table_class,
            limits=self.limits,
            strict=self.strict,
        )

        table_results = [self._clean_table(table) for table in parsed_tables]
        all_warnings = [w for table in table_results for w in table["warnings"]]

        return PageResult(
            exists=True,
            tables=table_results,
            error=None,
            requested_title=fetch_result.requested_title,
            resolved_title=fetch_result.resolved_title,
            page_id=fetch_result.page_id,
            revision_id=fetch_result.revision_id,
            revision_timestamp=fetch_result.revision_timestamp,
            warnings=all_warnings,
        )

    def _clean_table(self, table: ParsedTable) -> TableResult:
        warnings: list[dict[str, object]] = [w.to_dict() for w in table.warnings]

        headers: list[str] = []
        for col, raw_header in enumerate(table.headers):
            text, template_warnings = clean_cell(
                raw_header,
                strict=self.strict,
                table_index=table.index,
                row=None,
                column=col,
            )
            headers.append(text)
            warnings.extend(w.to_dict() for w in template_warnings)

        rows: list[list[str]] = []
        for row_idx, raw_row in enumerate(table.rows):
            row: list[str] = []
            for col_idx, raw_cell in enumerate(raw_row):
                text, template_warnings = clean_cell(
                    raw_cell,
                    strict=self.strict,
                    table_index=table.index,
                    row=row_idx,
                    column=col_idx,
                )
                row.append(text)
                warnings.extend(w.to_dict() for w in template_warnings)
            rows.append(row)

        caption: str | None = None
        if table.caption is not None:
            caption, template_warnings = clean_cell(
                table.caption, strict=self.strict, table_index=table.index
            )
            warnings.extend(w.to_dict() for w in template_warnings)

        return TableResult(
            headers=headers,
            rows=rows,
            section=table.section,
            section_path=table.section_path,
            caption=caption,
            index=table.index,
            parent_table_index=table.parent_table_index,
            truncated=table.truncated,
            warnings=warnings,
        )
