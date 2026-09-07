"""Tier 4: heading stack and breadcrumb ancestry.

See docs/specs/004-section-ancestry.md. tables.py drives the actual scan
(it already walks every line and tracks table nesting); this module
supplies the pure heading-classification and stack logic it calls into.
"""

from __future__ import annotations

import re

from .inline import clean_cell

SECTION_SEPARATOR = " > "

# The spec's own grammar (section 2) reads "{2,6}" but its prose says
# "Accept levels 1 to 6. Treat level 1 the same as any other" -- level 1
# (`= X =`) is valid MediaWiki heading syntax, so this accepts it too.
_HEADING_RE = re.compile(r"^(={1,6})\s*(.+?)\s*\1$")

_LITERAL_OPEN_RE = re.compile(r"<(nowiki|pre)\b[^>]*>", re.IGNORECASE)
_LITERAL_CLOSE_RE = re.compile(r"</(nowiki|pre)\s*>", re.IGNORECASE)


def classify_heading(line: str) -> tuple[int, str] | None:
    """Return (level, raw_text) if line is a heading line, else None."""
    match = _HEADING_RE.match(line.strip())
    if match is None:
        return None
    return len(match.group(1)), match.group(2)


def clean_heading_text(raw_text: str) -> str:
    """Run heading text through the Tier 3 inline cleaner (spec 004 section 2)."""
    text, _ = clean_cell(raw_text)
    return text


def update_literal_state(line: str, in_literal: bool) -> bool:
    """Track whether `line` sits inside a <nowiki> or <pre> block.

    A '='-looking line inside one of those is not a heading. This is a
    line-level approximation (does not handle a literal block opened and
    closed on the very same line specially), sufficient for suppressing
    heading detection across a multi-line block.
    """
    if _LITERAL_CLOSE_RE.search(line):
        return False
    if _LITERAL_OPEN_RE.search(line):
        return True
    return in_literal


class HeadingStack:
    """Ancestry per spec 004 section 3: pop every entry with level >= L,
    then push (L, text)."""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def push(self, level: int, text: str) -> None:
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, text))

    def snapshot(self) -> list[str]:
        return [text for _, text in self._stack]

    @staticmethod
    def join(path: list[str]) -> str:
        return SECTION_SEPARATOR.join(path)
