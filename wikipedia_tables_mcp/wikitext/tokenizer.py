"""Line-level classification of wikitable syntax.

See docs/specs/002-table-parsing.md sections 1 and 2.1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class LineKind(Enum):
    TABLE_OPEN = auto()
    TABLE_CLOSE = auto()
    ROW_SEP = auto()
    CAPTION = auto()
    HEADER_CELL = auto()
    DATA_CELL = auto()
    OTHER = auto()


@dataclass
class ClassifiedLine:
    kind: LineKind
    payload: str


def classify_line(line: str) -> ClassifiedLine:
    stripped = line.strip()
    if stripped.startswith("{|"):
        return ClassifiedLine(LineKind.TABLE_OPEN, stripped[2:].strip())
    if stripped.startswith("|}"):
        return ClassifiedLine(LineKind.TABLE_CLOSE, stripped[2:].strip())
    if stripped.startswith("|-"):
        return ClassifiedLine(LineKind.ROW_SEP, stripped[2:].strip())
    if stripped.startswith("|+"):
        return ClassifiedLine(LineKind.CAPTION, stripped[2:].strip())
    if stripped.startswith("!"):
        return ClassifiedLine(LineKind.HEADER_CELL, stripped[1:])
    if stripped.startswith("|"):
        return ClassifiedLine(LineKind.DATA_CELL, stripped[1:])
    return ClassifiedLine(LineKind.OTHER, line)


def _unnested_mask(text: str) -> list[bool]:
    """True at index i if that position is outside [[...]], {{...}}, <...>,
    and a quoted value. Shared by find_unnested_pipe and split_cells so a
    piped wikilink, or a template argument containing '||' or '!!', is
    never mistaken for a cell attribute separator or a cell boundary."""
    mask = [False] * len(text)
    bracket_depth = 0
    brace_depth = 0
    in_angle = False
    quote: str | None = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        two = text[i : i + 2]
        mask[i] = bracket_depth == 0 and brace_depth == 0 and not in_angle and quote is None
        if quote is not None:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            i += 1
            continue
        if two == "[[":
            bracket_depth += 1
            i += 2
            continue
        if two == "]]":
            bracket_depth = max(0, bracket_depth - 1)
            i += 2
            continue
        if two == "{{":
            brace_depth += 1
            i += 2
            continue
        if two == "}}":
            brace_depth = max(0, brace_depth - 1)
            i += 2
            continue
        if ch == "<":
            in_angle = True
            i += 1
            continue
        if ch == ">":
            in_angle = False
            i += 1
            continue
        i += 1
    return mask


def split_cells(payload: str, separator: str) -> list[str]:
    """Split one header/data line's payload into raw cell strings.

    Ignores an occurrence of the separator inside [[...]], {{...}},
    <...>, or a quoted value, so a template argument that happens to
    contain a literal '||' or '!!' is never split into two cells.
    """
    mask = _unnested_mask(payload)
    parts: list[str] = []
    start = 0
    i = 0
    n = len(payload)
    sep_len = len(separator)
    while i <= n - sep_len:
        if mask[i] and payload[i : i + sep_len] == separator:
            parts.append(payload[start:i])
            i += sep_len
            start = i
            continue
        i += 1
    parts.append(payload[start:])
    return parts


def find_unnested_pipe(text: str) -> int | None:
    """Index of the first '|' outside [[...]], {{...}}, <...>, and quotes."""
    mask = _unnested_mask(text)
    for i, ch in enumerate(text):
        if ch == "|" and mask[i]:
            return i
    return None


#  key=value, key="value", key='value', or a bare {{template}} token (e.g.
#  colspan="7" {{rh}}|content, seen in real car-article engine tables: a
#  styling template with no args of its own, interleaved with a real
#  attribute). Real MediaWiki would have already expanded that template
#  before its own table parser ever saw this line; this project does not
#  expand templates at this tier, so it tolerates the token structurally
#  instead, without guessing at what {{rh}} renders to.
_ATTR_TOKEN = r'(?:[A-Za-z-]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|\S+)|\{\{[^{}]*\}\})'
_ATTR_RE = re.compile(rf"^\s*{_ATTR_TOKEN}(?:\s+{_ATTR_TOKEN})*\s*$")


@dataclass
class SplitCell:
    attrs: str | None
    content: str


def split_attrs_content(raw_cell: str) -> SplitCell:
    """Split one raw cell into its attribute list and content, per spec 2.1."""
    pipe_index = find_unnested_pipe(raw_cell)
    if pipe_index is None:
        return SplitCell(None, raw_cell.strip())
    prefix = raw_cell[:pipe_index]
    if _ATTR_RE.match(prefix):
        return SplitCell(prefix.strip(), raw_cell[pipe_index + 1 :].strip())
    return SplitCell(None, raw_cell.strip())


_ROWSPAN_RE = re.compile(r"rowspan\s*=\s*(\"(\d+)\"|'(\d+)'|(\d+))", re.IGNORECASE)
_COLSPAN_RE = re.compile(r"colspan\s*=\s*(\"(\d+)\"|'(\d+)'|(\d+))", re.IGNORECASE)


def _extract_span(attrs: str | None, pattern: re.Pattern[str]) -> int:
    if not attrs:
        return 1
    match = pattern.search(attrs)
    if not match:
        return 1
    value = next(g for g in match.groups()[1:] if g is not None)
    try:
        n = int(value)
    except ValueError:
        return 1
    return n if n > 0 else 1


def extract_rowspan(attrs: str | None) -> int:
    return _extract_span(attrs, _ROWSPAN_RE)


def extract_colspan(attrs: str | None) -> int:
    return _extract_span(attrs, _COLSPAN_RE)


_CLASS_RE = re.compile(r"class\s*=\s*(\"([^\"]*)\"|'([^']*)'|(\S+))", re.IGNORECASE)


def extract_class_tokens(attrs: str) -> set[str]:
    match = _CLASS_RE.search(attrs)
    if not match:
        return set()
    value = next(g for g in match.groups()[1:] if g is not None)
    return set(value.split())
