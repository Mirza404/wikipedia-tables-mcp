"""Tier 4: heading stack and breadcrumb ancestry.

See docs/specs/004-section-ancestry.md. tables.py drives the actual scan
(it already walks every line and tracks table nesting); this module
supplies the pure heading-classification and stack logic it calls into.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from .inline import clean_cell
from .templates import TemplateWarning

SECTION_SEPARATOR = " > "

# The spec's own grammar (section 2) reads "{2,6}" but its prose says
# "Accept levels 1 to 6. Treat level 1 the same as any other" -- level 1
# (`= X =`) is valid MediaWiki heading syntax, so this accepts it too.
_HEADING_RE = re.compile(r"^(={1,6})\s*(.+?)\s*\1$")

_LITERAL_TAG_RE = re.compile(r"<\s*(/?)\s*(nowiki|pre)\b([^>]*)>", re.IGNORECASE)


def classify_heading(line: str) -> tuple[int, str] | None:
    """Return (level, raw_text) if line is a heading line, else None."""
    match = _HEADING_RE.match(line.strip())
    if match is None:
        return None
    return len(match.group(1)), match.group(2)


def clean_heading(raw_text: str, *, strict: bool = False) -> tuple[str, list[TemplateWarning]]:
    """Clean a heading while preserving Tier 3 integrity warnings."""
    return clean_cell(raw_text, strict=strict)


def clean_heading_text(raw_text: str) -> str:
    """Return cleaned heading text for callers that do not need warning metadata."""
    text, _ = clean_heading(raw_text)
    return text


class WikitextContext:
    """Track contexts where line-leading wikitext syntax is literal.

    Tags are processed in source order, self-closing literal tags do not enter
    literal mode, and tags inside HTML comments are ignored.  The return value
    describes the context at the start of the line: syntax after a closing tag
    on that same line is not line-leading syntax and therefore remains
    suppressed.
    """

    def __init__(self) -> None:
        self._in_comment = False
        self._literal_tag: str | None = None

    def suppresses_markup(self, line: str) -> bool:
        suppressed = self._in_comment or self._literal_tag is not None
        self._advance(line)
        return suppressed

    def _advance(self, line: str) -> None:
        position = 0
        while position < len(line):
            if self._in_comment:
                close = line.find("-->", position)
                if close < 0:
                    return
                self._in_comment = False
                position = close + 3
                continue

            if self._literal_tag is not None:
                match = _LITERAL_TAG_RE.search(line, position)
                if match is None:
                    return
                is_close = bool(match.group(1))
                name = match.group(2).lower()
                if is_close and name == self._literal_tag:
                    self._literal_tag = None
                position = match.end()
                continue

            comment = line.find("<!--", position)
            literal = _LITERAL_TAG_RE.search(line, position)
            if comment >= 0 and (literal is None or comment < literal.start()):
                self._in_comment = True
                position = comment + 4
                continue
            if literal is None:
                return

            is_close = bool(literal.group(1))
            self_closing = literal.group(3).rstrip().endswith("/")
            if not is_close and not self_closing:
                self._literal_tag = literal.group(2).lower()
            position = literal.end()


def update_literal_state(line: str, in_literal: bool) -> bool:
    """Compatibility helper for the former boolean-only context API."""
    state = in_literal
    for match in _LITERAL_TAG_RE.finditer(line):
        is_close = bool(match.group(1))
        self_closing = match.group(3).rstrip().endswith("/")
        if is_close:
            state = False
        elif not self_closing:
            state = True
    return state


@dataclass
class _HeadingEntry:
    level: int
    text: str
    warnings: list[TemplateWarning] = field(default_factory=list)


class HeadingStack:
    """Ancestry per spec 004 section 3: pop every entry with level >= L,
    then push (L, text)."""

    def __init__(self) -> None:
        self._stack: list[_HeadingEntry] = []

    def push(
        self,
        level: int,
        text: str,
        warnings: Sequence[TemplateWarning] = (),
    ) -> None:
        while self._stack and self._stack[-1].level >= level:
            self._stack.pop()
        self._stack.append(_HeadingEntry(level, text, list(warnings)))

    def snapshot(self) -> list[str]:
        return [entry.text for entry in self._stack]

    def warning_snapshot(self) -> list[TemplateWarning]:
        """Copy active warnings so each table owns independently indexed entries."""
        return [replace(warning) for entry in self._stack for warning in entry.warnings]

    @staticmethod
    def join(path: list[str]) -> str:
        return SECTION_SEPARATOR.join(path)


@dataclass
class SectionInfo:
    section: str
    section_path: list[str]
    table_count: int


def list_sections(wikitext: str) -> list[SectionInfo]:
    """The heading tree: one entry per heading, in document order, each with
    a count of the top-level tables opened directly under it.

    Deliberately a separate, much lighter pass than tables.py's own scan --
    this needs no cell/row/rowspan bookkeeping, only heading and table-open
    tracking. See docs/specs/006-mcp-surface.md, list_page_sections.
    """
    lines = wikitext.splitlines()
    heading_stack = HeadingStack()
    context = WikitextContext()
    table_depth = 0
    sections: list[SectionInfo] = []
    current: SectionInfo | None = None

    for raw_line in lines:
        if table_depth == 0 and context.suppresses_markup(raw_line):
            continue
        stripped = raw_line.strip()

        if table_depth == 0:
            heading = classify_heading(raw_line)
            if heading is not None:
                level, raw_text = heading
                text, _ = clean_heading(raw_text)
                heading_stack.push(level, text)
                current = SectionInfo(
                    section=HeadingStack.join(heading_stack.snapshot()),
                    section_path=heading_stack.snapshot(),
                    table_count=0,
                )
                sections.append(current)
                continue

        if stripped.startswith("{|"):
            if table_depth == 0 and current is not None:
                current.table_count += 1
            table_depth += 1
            continue
        if table_depth > 0 and stripped.startswith("|}"):
            table_depth -= 1
            continue

    return sections


def extract_section(wikitext: str, query: str) -> str | None:
    """Raw wikitext (heading line included) of the first heading whose
    joined breadcrumb contains `query` case-insensitively, through to the
    next heading at the same or a shallower level. None if no match.
    """
    lines = wikitext.splitlines()
    heading_stack = HeadingStack()
    context = WikitextContext()
    table_depth = 0
    query_lower = query.lower()

    match_start: int | None = None
    match_level: int | None = None

    for i, raw_line in enumerate(lines):
        if table_depth == 0 and context.suppresses_markup(raw_line):
            continue
        stripped = raw_line.strip()

        if table_depth == 0:
            heading = classify_heading(raw_line)
            if heading is not None:
                level, raw_text = heading
                if match_start is not None and match_level is not None and level <= match_level:
                    return "\n".join(lines[match_start:i])
                text, _ = clean_heading(raw_text)
                heading_stack.push(level, text)
                if (
                    match_start is None
                    and query_lower in HeadingStack.join(heading_stack.snapshot()).lower()
                ):
                    match_start = i
                    match_level = level
                continue

        if stripped.startswith("{|"):
            table_depth += 1
            continue
        if table_depth > 0 and stripped.startswith("|}"):
            table_depth -= 1
            continue

    if match_start is not None:
        return "\n".join(lines[match_start:])
    return None
