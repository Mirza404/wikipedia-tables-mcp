"""Tier 2: wikitext to a list of tables, each a headers list plus a
rectangular row grid. Cell values here are still raw wikitext; Tier 3
(inline.py, templates.py) cleans them.

See docs/specs/002-table-parsing.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .sections import HeadingStack, classify_heading, clean_heading_text, update_literal_state
from .tokenizer import (
    LineKind,
    classify_line,
    extract_class_tokens,
    extract_colspan,
    extract_rowspan,
    split_attrs_content,
    split_cells,
)

DEFAULT_MAX_TABLES = 50
DEFAULT_MAX_ROWS_PER_TABLE = 400
DEFAULT_MAX_CELLS_PER_ROW = 60
DEFAULT_MAX_CELL_CHARS = 2000


@dataclass
class Limits:
    max_tables: int = DEFAULT_MAX_TABLES
    max_rows_per_table: int = DEFAULT_MAX_ROWS_PER_TABLE
    max_cells_per_row: int = DEFAULT_MAX_CELLS_PER_ROW
    max_cell_chars: int = DEFAULT_MAX_CELL_CHARS


@dataclass
class TableWarning:
    """A machine-readable table-integrity warning.

    Warnings are data-quality controls, not parser diagnostics that callers
    may safely ignore.  ``values`` contains the same raw-wikitext row stored
    in ``ParsedTable.rows`` so a client can surface the warning independently
    without losing the evidence that caused it.
    """

    kind: str
    reason: str
    table_index: int | None = None
    row: int | None = None
    expected_columns: int | None = None
    occupied_columns: int | None = None
    source_cells: int | None = None
    values: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "table_index": self.table_index,
            "row": self.row,
            "expected_columns": self.expected_columns,
            "occupied_columns": self.occupied_columns,
            "source_cells": self.source_cells,
            "values": self.values,
        }


@dataclass
class ParsedTable:
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    caption: str | None = None
    index: int = 0
    parent_table_index: int | None = None
    truncated: bool = False
    warnings: list[TableWarning] = field(default_factory=list)
    section: str = ""
    section_path: list[str] = field(default_factory=list)


def _collapse_ws(text: str) -> str:
    return " ".join(text.split())


@dataclass
class _RawCell:
    is_header: bool
    content: str
    colspan: int
    rowspan: int


class _TableFrame:
    def __init__(self, attrs_line: str) -> None:
        self.attrs_line = attrs_line
        self.caption: str | None = None
        self.committed_rows: list[list[_RawCell]] = []
        self._current_row: list[_RawCell] | None = None
        self._pending_lines: list[str] | None = None
        self._pending_is_header = False
        self._pending_attrs: str | None = None

    def start_row(self) -> None:
        self._flush_cell()
        if self._current_row is not None:
            self.committed_rows.append(self._current_row)
        self._current_row = []

    def add_cell_part(self, is_header: bool, raw_part: str) -> None:
        self._flush_cell()
        split = split_attrs_content(raw_part)
        self._pending_is_header = is_header
        self._pending_attrs = split.attrs
        self._pending_lines = [split.content]

    def add_continuation(self, line: str) -> None:
        if self._pending_lines is not None:
            self._pending_lines.append(line)

    def _flush_cell(self) -> None:
        if self._pending_lines is None:
            return
        if self._current_row is None:
            self._current_row = []
        text = _collapse_ws(" ".join(self._pending_lines))
        self._current_row.append(
            _RawCell(
                is_header=self._pending_is_header,
                content=text,
                colspan=extract_colspan(self._pending_attrs),
                rowspan=extract_rowspan(self._pending_attrs),
            )
        )
        self._pending_lines = None
        self._pending_attrs = None
        self._pending_is_header = False

    def finish(self) -> list[list[_RawCell]]:
        self._flush_cell()
        if self._current_row is not None:
            self.committed_rows.append(self._current_row)
            self._current_row = None
        return self.committed_rows


def parse_tables(
    wikitext: str,
    *,
    table_class: str | None = None,
    limits: Limits | None = None,
) -> list[ParsedTable]:
    limits = limits or Limits()
    lines = wikitext.splitlines()

    stack: list[_TableFrame] = []
    id_stack: list[int] = []
    parent_id_of: dict[int, int | None] = {}
    id_to_output_index: dict[int, int] = {}
    finished: list[ParsedTable] = []
    next_id = 0

    heading_stack = HeadingStack()
    section_snapshot_of: dict[int, list[str]] = {}
    in_literal = False

    for raw_line in lines:
        classified = classify_line(raw_line)

        if classified.kind == LineKind.TABLE_OPEN:
            parent_id = id_stack[-1] if id_stack else None
            table_id = next_id
            next_id += 1
            parent_id_of[table_id] = parent_id
            section_snapshot_of[table_id] = heading_stack.snapshot()
            stack.append(_TableFrame(classified.payload))
            id_stack.append(table_id)
            continue

        if not stack:
            # A '='-looking line inside <nowiki>/<pre> is not a heading
            # (spec 004 section 2); a table body is handled above since
            # this branch only runs when no table is currently open.
            in_literal = update_literal_state(raw_line, in_literal)
            if not in_literal:
                heading = classify_heading(raw_line)
                if heading is not None:
                    level, raw_text = heading
                    heading_stack.push(level, clean_heading_text(raw_text))
            continue

        frame = stack[-1]

        if classified.kind == LineKind.TABLE_CLOSE:
            raw_rows = frame.finish()
            table_id = id_stack.pop()
            stack.pop()

            if len(finished) >= limits.max_tables:
                continue
            if table_class is not None and table_class not in extract_class_tokens(
                frame.attrs_line
            ):
                continue

            # parent_table_index is filled in as a raw internal id here; a
            # nested table always closes before its parent does, so the
            # parent's final output index is not known yet. Resolved in the
            # post-pass below once every table that will be kept has one.
            parsed = _build_parsed_table(raw_rows, frame.caption, parent_id_of[table_id], limits)
            parsed.index = len(finished)
            parsed.section_path = section_snapshot_of[table_id]
            parsed.section = HeadingStack.join(parsed.section_path)
            for warning in parsed.warnings:
                warning.table_index = parsed.index
            id_to_output_index[table_id] = parsed.index
            finished.append(parsed)
            continue

        if classified.kind == LineKind.ROW_SEP:
            frame.start_row()
            continue

        if classified.kind == LineKind.CAPTION:
            frame.caption = _collapse_ws(classified.payload) or None
            continue

        if classified.kind == LineKind.HEADER_CELL:
            for part in split_cells(classified.payload, "!!"):
                frame.add_cell_part(True, part)
            continue

        if classified.kind == LineKind.DATA_CELL:
            for part in split_cells(classified.payload, "||"):
                frame.add_cell_part(False, part)
            continue

        frame.add_continuation(classified.payload)

    for parsed in finished:
        parent_id = parsed.parent_table_index
        parsed.parent_table_index = (
            id_to_output_index.get(parent_id) if parent_id is not None else None
        )

    return finished


def _expand_headers(header_row: list[_RawCell], limits: Limits) -> tuple[list[str], bool]:
    row_map: dict[int, str] = {}
    col_ptr = 0
    truncated = False
    for cell in header_row:
        for _ in range(max(1, cell.colspan)):
            if col_ptr >= limits.max_cells_per_row:
                truncated = True
                break
            row_map[col_ptr] = cell.content
            col_ptr += 1
        if truncated:
            break
    width = max(row_map.keys()) + 1 if row_map else 0
    return [row_map.get(i, "") for i in range(width)], truncated


def _build_parsed_table(
    raw_rows: list[list[_RawCell]],
    caption: str | None,
    parent_id: int | None,
    limits: Limits,
) -> ParsedTable:
    warnings: list[TableWarning] = []
    truncated = False

    headers: list[str] = []
    data_rows = raw_rows
    if raw_rows and raw_rows[0] and all(c.is_header for c in raw_rows[0]):
        headers, header_truncated = _expand_headers(raw_rows[0], limits)
        if header_truncated:
            truncated = True
            warnings.append(
                TableWarning(
                    kind="truncated",
                    reason=f"header truncated at max_cells_per_row={limits.max_cells_per_row}",
                )
            )
        data_rows = raw_rows[1:]

    pending: dict[int, tuple[str, int]] = {}
    grid: list[list[str]] = []
    row_shapes: list[tuple[int, int]] = []

    for raw_row in data_rows:
        if len(grid) >= limits.max_rows_per_table:
            truncated = True
            warnings.append(
                TableWarning(
                    kind="truncated",
                    reason=f"truncated at max_rows_per_table={limits.max_rows_per_table}",
                )
            )
            break

        row_map: dict[int, str] = {}
        for col_idx, (value, remaining) in list(pending.items()):
            row_map[col_idx] = value
            if remaining - 1 <= 0:
                del pending[col_idx]
            else:
                pending[col_idx] = (value, remaining - 1)

        col_ptr = 0
        for cell in raw_row:
            content = cell.content
            if len(content) > limits.max_cell_chars:
                content = content[: limits.max_cell_chars]
                truncated = True
            for _ in range(max(1, cell.colspan)):
                while col_ptr in row_map:
                    col_ptr += 1
                if col_ptr >= limits.max_cells_per_row:
                    truncated = True
                    break
                row_map[col_ptr] = content
                if cell.rowspan > 1:
                    pending[col_ptr] = (content, cell.rowspan - 1)
                col_ptr += 1
            if col_ptr >= limits.max_cells_per_row:
                break

        if not row_map:
            continue

        width = max(row_map.keys()) + 1
        grid.append([row_map.get(i, "") for i in range(width)])
        row_shapes.append((len(row_map), len(raw_row)))

    overall_width = len(headers)
    for row in grid:
        overall_width = max(overall_width, len(row))
    if headers:
        headers = headers + [""] * (overall_width - len(headers))
    grid = [row + [""] * (overall_width - len(row)) for row in grid]

    for row_index, (row, (occupied_columns, source_cells)) in enumerate(
        zip(grid, row_shapes, strict=True)
    ):
        if occupied_columns >= overall_width:
            continue
        warnings.append(
            TableWarning(
                kind="ambiguous_row_alignment",
                reason=(
                    f"row occupies {occupied_columns} of {overall_width} columns after "
                    "rowspan/colspan expansion; missing cells are not necessarily trailing, "
                    "so positional values may be shifted"
                ),
                row=row_index,
                expected_columns=overall_width,
                occupied_columns=occupied_columns,
                source_cells=source_cells,
                values=row.copy(),
            )
        )

    return ParsedTable(
        headers=headers,
        rows=grid,
        caption=caption,
        parent_table_index=parent_id,
        truncated=truncated,
        warnings=warnings,
    )
