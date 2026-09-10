"""Tier 3: a bounded template registry, not a general MediaWiki expander.

See docs/specs/003-inline-and-templates.md section 3.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass

from ..errors import TemplateResolutionError
from .tokenizer import split_cells

_MAX_TEMPLATE_RESOLUTIONS = 200

_NAMED_ARG_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_ ]*)\s*=\s*(.*)$", re.DOTALL)


@dataclass
class TemplateWarning:
    kind: str
    name: str
    raw: str
    reason: str
    table_index: int | None = None
    row: int | None = None
    column: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "raw": self.raw,
            "reason": self.reason,
            "table_index": self.table_index,
            "row": self.row,
            "column": self.column,
        }


class _UnknownTemplateShape(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


Handler = Callable[[list[str], dict[str, str]], str]

_REGISTRY: dict[str, Handler] = {}


def _register(*names: str) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        for name in names:
            _REGISTRY[name] = fn
        return fn

    return decorator


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().replace("_", " ").split())


def _find_innermost_template(text: str) -> tuple[int, int, str] | None:
    """Locate the first-closing (innermost) {{...}} span in text."""
    stack: list[int] = []
    i = 0
    n = len(text)
    while i < n - 1:
        two = text[i : i + 2]
        if two == "{{":
            stack.append(i)
            i += 2
            continue
        if two == "}}":
            if stack:
                start = stack.pop()
                return start, i + 2, text[start + 2 : i]
            i += 2
            continue
        i += 1
    return None


def resolve_templates(
    text: str,
    *,
    strict: bool = False,
    warnings: list[TemplateWarning],
    table_index: int | None = None,
    row: int | None = None,
    column: int | None = None,
) -> str:
    """Resolve every {{template}} in text, innermost first."""
    result = text
    for _ in range(_MAX_TEMPLATE_RESOLUTIONS):
        found = _find_innermost_template(result)
        if found is None:
            break
        start, end, inner = found
        replacement = _resolve_one(
            result[start:end],
            inner,
            strict=strict,
            warnings=warnings,
            table_index=table_index,
            row=row,
            column=column,
        )
        result = result[:start] + replacement + result[end:]
    return result


def _resolve_one(
    raw: str,
    inner: str,
    *,
    strict: bool,
    warnings: list[TemplateWarning],
    table_index: int | None,
    row: int | None,
    column: int | None,
) -> str:
    parts = split_cells(inner, "|")
    name = _normalize_name(parts[0])

    positional: list[str] = []
    named: dict[str, str] = {}
    for part in parts[1:]:
        match = _NAMED_ARG_RE.match(part)
        if match:
            named[match.group(1).strip().lower()] = match.group(2).strip()
        else:
            positional.append(part.strip())

    handler = _REGISTRY.get(name)
    if handler is None:
        return _unknown(
            raw, name, "unrecognized template", strict, warnings, table_index, row, column
        )

    try:
        return handler(positional, named)
    except _UnknownTemplateShape as exc:
        return _unknown(raw, name, exc.reason, strict, warnings, table_index, row, column)


def _unknown(
    raw: str,
    name: str,
    reason: str,
    strict: bool,
    warnings: list[TemplateWarning],
    table_index: int | None,
    row: int | None,
    column: int | None,
) -> str:
    if strict:
        raise TemplateResolutionError(
            reason, raw=raw, table_index=table_index, row=row, column=column
        )
    warnings.append(
        TemplateWarning(
            kind="unknown_template",
            name=name,
            raw=raw,
            reason=reason,
            table_index=table_index,
            row=row,
            column=column,
        )
    )
    return ""


# -- {{convert}} / {{cvt}} ---------------------------------------------------
#
# Exact defined constants (spec 003 section 3.3.2). bhp is treated as
# mechanical hp: an approximation of intent (the two are used
# interchangeably on Wikipedia), not of arithmetic.

TO_KW = {
    "kW": 1.0,
    "W": 0.001,
    "PS": 0.73549875,  # 75 kgf.m/s, exact
    "hp-metric": 0.73549875,  # {{convert}}'s own alias for PS; seen in the wild
    "hp": 0.745699871582,  # mechanical horsepower, exact
    "bhp": 0.745699871582,  # treated as mechanical hp
    "cv": 0.73549875,  # metric, same as PS
    "ch": 0.73549875,
}
TO_NM = {
    "Nm": 1.0,
    "N.m": 1.0,
    "N*m": 1.0,
    "lbft": 1.3558179483314004,  # exact
    "lb.ft": 1.3558179483314004,
    "ftlb": 1.3558179483314004,
    "ft.lbf": 1.3558179483314004,
    "kgm": 9.80665,  # exact
    "kg.m": 9.80665,
}
TO_CC = {
    "cc": 1.0,
    "cm3": 1.0,
    "ccm": 1.0,
    "L": 1000.0,
    "l": 1000.0,
    "litre": 1000.0,
    "liter": 1000.0,
    "cuin": 16.387064,  # exact
    "cid": 16.387064,
    "mL": 1.0,
}

_CANONICAL_TABLES: tuple[tuple[str, dict[str, float]], ...] = (
    ("kW", TO_KW),
    ("Nm", TO_NM),
    ("cc", TO_CC),
)

# unit token (lowercased) -> (canonical unit, factor: 1 unit == `factor` canonical units)
_UNIT_INFO: dict[str, tuple[str, float]] = {
    unit.lower(): (canonical, factor)
    for canonical, table in _CANONICAL_TABLES
    for unit, factor in table.items()
}


def _parse_number(raw: str) -> float | None:
    cleaned = raw.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _round_half_away_from_zero(value: float, ndigits: int) -> float:
    if value == 0:
        return 0.0
    factor = 10**ndigits
    magnitude = math.floor(abs(value) * factor + 0.5) / factor
    return math.copysign(magnitude, value)


def _format_canonical_value(value: float) -> str:
    if abs(value) >= 10:
        return str(int(_round_half_away_from_zero(value, 0)))
    return f"{_round_half_away_from_zero(value, 1):.1f}"


#  A range can also be authored as one argument with an embedded hyphen or
#  en dash ({{cvt|133-136|PS|kW hp|0}}), as an alternative to two separate
#  positional arguments. Found in the wild during manual verification
#  (spec 007 section 6) -- without this, "133-136" fails the numeric check
#  on argument 1 and the whole cell is lost to an unknown_template warning.
_INLINE_RANGE_RE = re.compile(r"^\s*([\d,.]+)\s*[-–]\s*([\d,.]+)\s*$")


@_register("convert", "cvt")
def _h_convert(positional: list[str], _named: dict[str, str]) -> str:
    if not positional:
        raise _UnknownTemplateShape("missing value")

    inline_range = _INLINE_RANGE_RE.match(positional[0])
    if inline_range is not None:
        value1_raw, value2_raw = inline_range.group(1), inline_range.group(2)
        rest = positional[1:]
    else:
        value1_raw = positional[0]
        if _parse_number(value1_raw) is None:
            raise _UnknownTemplateShape("argument 1 is not numeric")
        rest = positional[1:]
        value2_raw = None
        if rest and _parse_number(rest[0]) is not None:
            value2_raw = rest[0]
            rest = rest[1:]

    value1_num = _parse_number(value1_raw)
    assert value1_num is not None

    if not rest:
        raise _UnknownTemplateShape("missing input unit")
    unit_raw = rest[0]

    canonical = _UNIT_INFO.get(unit_raw.strip().lower())
    is_canonical = canonical is not None and unit_raw.strip().lower() == canonical[0].lower()

    if value2_raw is None:
        authored = f"{value1_raw} {unit_raw}"
        if canonical is None or is_canonical:
            return authored
        canonical_unit, factor = canonical
        converted = _format_canonical_value(value1_num * factor)
        return f"{authored} ({converted} {canonical_unit})"

    authored = f"{value1_raw}–{value2_raw} {unit_raw}"
    if canonical is None or is_canonical:
        return authored
    canonical_unit, factor = canonical
    value2_num = _parse_number(value2_raw)
    assert value2_num is not None
    c1 = _format_canonical_value(value1_num * factor)
    c2 = _format_canonical_value(value2_num * factor)
    return f"{authored} ({c1}–{c2} {canonical_unit})"


# -- other templates worth a handler (spec 003 section 3.4) -----------------


@_register("nowrap")
def _h_nowrap(positional: list[str], _named: dict[str, str]) -> str:
    return positional[0] if positional else ""


@_register("nbsp", "spaces")
def _h_space(_positional: list[str], _named: dict[str, str]) -> str:
    return " "


@_register("ndash", "endash", "--")
def _h_ndash(_positional: list[str], _named: dict[str, str]) -> str:
    return "–"


@_register("mdash")
def _h_mdash(_positional: list[str], _named: dict[str, str]) -> str:
    return "—"


@_register("sfrac", "frac")
def _h_frac(positional: list[str], _named: dict[str, str]) -> str:
    if len(positional) < 2:
        return "/".join(positional)
    return f"{positional[0]}/{positional[1]}"


@_register("val")
def _h_val(positional: list[str], named: dict[str, str]) -> str:
    value = positional[0] if positional else ""
    unit = named.get("u", "")
    return f"{value} {unit}".strip()


@_register("small", "big", "nobold")
def _h_passthrough_first(positional: list[str], _named: dict[str, str]) -> str:
    return positional[0] if positional else ""


@_register("sortname")
def _h_sortname(positional: list[str], _named: dict[str, str]) -> str:
    return " ".join(p for p in positional[:2] if p)


@_register("sort")
def _h_sort(positional: list[str], _named: dict[str, str]) -> str:
    return positional[1] if len(positional) > 1 else ""


@_register("ubl", "plainlist")
def _h_list(positional: list[str], _named: dict[str, str]) -> str:
    return ", ".join(p for p in positional if p)


@_register("clear", "clarify", "citation needed", "cn", "efn", "refn", "rh")
def _h_empty(_positional: list[str], _named: dict[str, str]) -> str:
    # {{rh}} ("row header") is a styling-only template with no text output
    # of its own, commonly seen as colspan="N" {{rh}}|Label in real
    # engine-table divider rows -- see tokenizer.py's _ATTR_TOKEN.
    return ""


@_register("n/a")
def _h_na(_positional: list[str], _named: dict[str, str]) -> str:
    # Seen 17 times across the manual verification pass's 20 articles --
    # cheap and common enough to be worth its own handler (spec 003
    # section 3.4's bar), unlike the article-specific templates (rating,
    # co2, chem, ...) left as unknown_template warnings.
    return "N/A"


@_register("lang")
def _h_lang(positional: list[str], _named: dict[str, str]) -> str:
    if len(positional) > 1:
        return positional[1]
    return positional[0] if positional else ""
