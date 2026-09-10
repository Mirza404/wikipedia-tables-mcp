"""Tier 2 tests: hand-written wikitext snippets, one complication per test."""

from __future__ import annotations

from wikipedia_tables_mcp.wikitext.tables import Limits, parse_tables
from wikipedia_tables_mcp.wikitext.templates import TemplateWarning


def test_basic_table_headers_and_rows() -> None:
    wikitext = """
{| class="wikitable"
|-
! A
! B
|-
| 1
| 2
|-
| 3
| 4
|}
"""
    tables = parse_tables(wikitext)
    assert len(tables) == 1
    assert tables[0].headers == ["A", "B"]
    assert tables[0].rows == [["1", "2"], ["3", "4"]]


def test_no_header_row_when_first_row_mixes_bar_and_bang() -> None:
    wikitext = """
{|
|-
! 1.4
| 1998
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].headers == []
    assert tables[0].rows == [["1.4", "1998"]]


def test_attribute_content_split_with_normal_spacing() -> None:
    wikitext = """
{|
|-
! A
! B
|-
| rowspan="2" | 1595 cc
| x
|-
| y
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows[0] == ["1595 cc", "x"]
    assert tables[0].rows[1] == ["1595 cc", "y"]


def test_attribute_content_split_with_spaces_around_equals() -> None:
    wikitext = """
{|
|-
! A
! B
|-
| rowspan = "2" | 1598 cc
| x
|-
| y
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows[0] == ["1598 cc", "x"]
    assert tables[0].rows[1] == ["1598 cc", "y"]


def test_piped_wikilink_is_not_mistaken_for_an_attribute() -> None:
    wikitext = """
{|
|-
! A
|-
| [[Straight-four engine|I4]] 16V
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows == [["[[Straight-four engine|I4]] 16V"]]


def test_literal_double_pipe_inside_a_template_does_not_split_the_cell() -> None:
    # {{...}} is opaque at this tier: its own internal '|' arguments are
    # never cell separators, so a template that happens to carry a
    # literal '||' argument must not be split into two cells here.
    wikitext = """
{|
|-
! A
|-
| {{tlx|a||b}} tail
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows == [["{{tlx|a||b}} tail"]]


def test_colspan_survives_a_styling_template_before_the_attribute_pipe() -> None:
    # colspan="N" {{rh}}|content is a real idiom in car-article engine
    # tables (a row-header styling template with no args, interleaved
    # with a real attribute). Found during the manual verification pass
    # against live articles (Skoda Octavia, Renault Clio): without this,
    # the whole string fails the attribute-list match and falls through
    # to content, so colspan is never applied at all.
    wikitext = """
{|
|-
! A !! B !! C
|-
|colspan="3" {{rh}}|[[Petrol engine]]s
|-
| x || y || z
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows == [
        ["[[Petrol engine]]s", "[[Petrol engine]]s", "[[Petrol engine]]s"],
        ["x", "y", "z"],
    ]
    assert tables[0].warnings == []


def test_colspan_repeats_the_value() -> None:
    wikitext = """
{|
|-
! A
! B
! C
|-
| colspan="2" | wide
| narrow
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows == [["wide", "wide", "narrow"]]


def test_rowspan_and_colspan_combine() -> None:
    wikitext = """
{|
|-
! A
! B
! C
|-
| rowspan="2" colspan="2" | block
| x
|-
| y
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows[0] == ["block", "block", "x"]
    assert tables[0].rows[1] == ["block", "block", "y"]


def test_header_styled_cell_inside_a_data_row_is_a_row_label() -> None:
    wikitext = """
{|
|-
! Model
! Year
|-
! 1.4
| 1998
|-
! 1.6
| 2000
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].headers == ["Model", "Year"]
    assert tables[0].rows == [["1.4", "1998"], ["1.6", "2000"]]


def test_mid_table_all_header_row_is_kept_as_data() -> None:
    wikitext = """
{|
|-
! Model
! Year
|-
| 1.4
| 1998
|-
! 1.6
! 2000
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].headers == ["Model", "Year"]
    assert tables[0].rows == [["1.4", "1998"], ["1.6", "2000"]]


def test_doubled_row_separator_drops_the_empty_row() -> None:
    wikitext = """
{|
|-
! A
|-
| x
|-
|-
| y
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows == [["x"], ["y"]]


def test_row_with_only_carried_down_values_is_kept() -> None:
    # A doubled |- with no cells between produces a row of its own. If a
    # rowspan is still pending at that point, that row is not empty -- it
    # carries the pending value and must not be dropped (spec 002 section
    # 2.5). This is the exact shape in the Golf Mk4 fixture around "1.8".
    wikitext = """
{|
|-
! A
! B
|-
| rowspan="2" | carried
| x
|-
|-
| y
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows == [["carried", "x"], ["carried", ""], ["y", ""]]


def test_multiline_cell_value_is_joined_with_a_single_space() -> None:
    wikitext = """
{|
|-
! A
|-
| first line
second line
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows == [["first line second line"]]


def test_caption_is_captured() -> None:
    wikitext = """
{|
|+ My caption
|-
! A
|-
| x
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].caption == "My caption"


def test_table_with_no_caption_has_none() -> None:
    wikitext = """
{|
|-
! A
|-
| x
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].caption is None


def test_short_rows_are_padded_to_the_header_width() -> None:
    wikitext = """
{|
|-
! A
! B
! C
|-
| 1
| 2
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].rows == [["1", "2", ""]]
    assert len(tables[0].warnings) == 1
    assert tables[0].warnings[0].to_dict() == {
        "kind": "ambiguous_row_alignment",
        "reason": (
            "row occupies 2 of 3 columns after rowspan/colspan expansion; "
            "missing cells are not necessarily trailing, so positional values may be shifted"
        ),
        "table_index": 0,
        "row": 0,
        "expected_columns": 3,
        "occupied_columns": 2,
        "source_cells": 2,
        "values": ["1", "2", ""],
    }


def test_valid_rowspan_does_not_warn_about_row_alignment() -> None:
    wikitext = """
{|
|-
! A
! B
! C
|-
| rowspan="2" | carried
| first
| row
|-
| second
| row
|}
"""
    table = parse_tables(wikitext)[0]
    assert table.rows == [
        ["carried", "first", "row"],
        ["carried", "second", "row"],
    ]
    assert not any(warning.kind == "ambiguous_row_alignment" for warning in table.warnings)


def test_a_row_longer_than_the_header_widens_the_header() -> None:
    wikitext = """
{|
|-
! A
|-
| 1
| 2
| 3
|}
"""
    tables = parse_tables(wikitext)
    assert tables[0].headers == ["A", "", ""]
    assert tables[0].rows == [["1", "2", "3"]]


def test_max_cell_chars_truncates_and_flags_truncated() -> None:
    wikitext = "{|\n|-\n! A\n|-\n| " + ("x" * 50) + "\n|}\n"
    tables = parse_tables(wikitext, limits=Limits(max_cell_chars=10))
    assert tables[0].truncated is True
    assert tables[0].rows[0][0] == "x" * 10


def test_max_rows_per_table_truncates_and_flags_truncated() -> None:
    lines = ["{|", "|-", "! A"]
    for i in range(5):
        lines += ["|-", f"| {i}"]
    lines.append("|}")
    wikitext = "\n".join(lines)

    tables = parse_tables(wikitext, limits=Limits(max_rows_per_table=2))
    assert tables[0].truncated is True
    assert len(tables[0].rows) == 2


def test_max_cells_per_row_bounds_a_header_colspan() -> None:
    # A header cell's colspan is attacker/author controlled (e.g.
    # colspan="999999999") and must be bounded the same way a data row's
    # colspan already is, or one malformed header line can blow past
    # every size limit before a single data row is even read.
    wikitext = '{|\n|-\n! colspan="1000" | A\n|-\n| x\n|}'
    tables = parse_tables(wikitext, limits=Limits(max_cells_per_row=5))
    assert len(tables[0].headers) == 5
    assert tables[0].truncated is True


def test_max_tables_caps_the_number_returned() -> None:
    wikitext = "\n".join("{|\n|-\n! A\n|-\n| x\n|}" for _ in range(3))
    tables = parse_tables(wikitext, limits=Limits(max_tables=2))
    assert len(tables) == 2


def test_table_class_filter_keeps_only_matching_tables() -> None:
    wikitext = """
{| class="wikitable sortable"
|-
! A
|-
| kept
|}
{| class="navbox"
|-
! A
|-
| dropped
|}
"""
    tables = parse_tables(wikitext, table_class="wikitable")
    assert len(tables) == 1
    assert tables[0].rows == [["kept"]]


def test_nested_table_is_its_own_entry_with_parent_index() -> None:
    wikitext = """
{|
|-
! Outer
|-
| before
{|
|-
! Inner
|-
| nested value
|}
after
|}
"""
    tables = parse_tables(wikitext)
    assert len(tables) == 2
    # the inner table's closing |} is seen first
    inner, outer = tables[0], tables[1]
    assert inner.headers == ["Inner"]
    assert inner.rows == [["nested value"]]
    assert inner.parent_table_index == 1

    assert outer.headers == ["Outer"]
    assert outer.parent_table_index is None
    # the nested table's own text is removed from the parent cell's value
    assert outer.rows == [["before after"]]


def test_self_closing_nowiki_does_not_hide_later_heading() -> None:
    wikitext = """
== Before ==
<nowiki />
== Engines ==
{|
|-
! Model
|-
| Real data
|}
"""
    table = parse_tables(wikitext)[0]
    assert table.section == "Engines"


def test_heading_inside_html_comment_does_not_change_ancestry() -> None:
    wikitext = """
== Real section ==
<!--
== Editorial note ==
-->
{|
|-
! Model
|-
| Real data
|}
"""
    table = parse_tables(wikitext)[0]
    assert table.section == "Real section"


def test_literal_table_examples_are_not_returned() -> None:
    real_table = """{|
|-
! Model
|-
| Real data
|}
"""
    for tag in ("nowiki", "pre"):
        example = f"""<{tag}>
{{|
|-
! Example
|-
| Not data
|}}
</{tag}>
"""
        tables = parse_tables(example + real_table)
        assert len(tables) == 1
        assert tables[0].rows == [["Real data"]]


def test_heading_template_warning_is_attached_to_each_table_snapshot() -> None:
    wikitext = """
== Generation {{unsupported_heading|Mk1}} ==
{|
|-
! A
|-
| first
|}
{|
|-
! A
|-
| second
|}
"""
    tables = parse_tables(wikitext)

    assert [table.section for table in tables] == ["Generation", "Generation"]
    for index, table in enumerate(tables):
        warning = next(w for w in table.warnings if w.kind == "unknown_template")
        assert isinstance(warning, TemplateWarning)
        assert warning.table_index == index
        assert warning.row is None
        assert warning.column is None
