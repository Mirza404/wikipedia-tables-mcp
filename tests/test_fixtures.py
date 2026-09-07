"""Tier 2/3/4 acceptance criteria, run against real committed fixtures.

See docs/specs/007-testing.md section 2. Assertions are structural
(counts, specific carried-down values), not full byte-exact dicts, so a
harmless article edit after a refetch does not produce a wall of red.
"""

from __future__ import annotations

import re
from pathlib import Path

import defusedxml.ElementTree as ET

from special_export_mcp.wikitext.inline import clean_cell
from special_export_mcp.wikitext.tables import parse_tables

FIXTURES = Path(__file__).parent / "fixtures"


def _wikitext_from_export_xml(path: Path) -> str:
    root = ET.parse(path).getroot()
    assert root is not None
    for page in root:
        for child in page:
            if child.tag.rsplit("}", 1)[-1] != "revision":
                continue
            for rev_child in child:
                if rev_child.tag.rsplit("}", 1)[-1] == "text":
                    assert rev_child.text is not None
                    return rev_child.text
    raise AssertionError(f"no revision text found in {path}")


def test_golf_mk4_has_exactly_two_tables() -> None:
    wikitext = _wikitext_from_export_xml(FIXTURES / "volkswagen_golf_mk4.xml")
    tables = parse_tables(wikitext)
    assert len(tables) == 2


def test_golf_mk4_engine_table_headers() -> None:
    wikitext = _wikitext_from_export_xml(FIXTURES / "volkswagen_golf_mk4.xml")
    tables = parse_tables(wikitext)
    assert tables[0].headers == ["Model", "Year", "Engine", "Code", "Displ.", "Power", "Torque"]


def test_golf_mk4_every_row_has_seven_cells() -> None:
    wikitext = _wikitext_from_export_xml(FIXTURES / "volkswagen_golf_mk4.xml")
    tables = parse_tables(wikitext)
    for row in tables[0].rows:
        assert len(row) == 7


def test_golf_mk4_rowspan_carries_1595cc_down() -> None:
    wikitext = _wikitext_from_export_xml(FIXTURES / "volkswagen_golf_mk4.xml")
    tables = parse_tables(wikitext)
    matches = [row for row in tables[0].rows if "AVU/BFQ" in row[3]]
    assert len(matches) == 1
    assert matches[0][4] == "1595 cc"


def test_golf_mk4_rowspan_with_spaces_around_equals_carries_1598cc() -> None:
    wikitext = _wikitext_from_export_xml(FIXTURES / "volkswagen_golf_mk4.xml")
    tables = parse_tables(wikitext)
    matches = [row for row in tables[0].rows if "Gasoline direct injection" in row[0]]
    assert len(matches) == 1
    assert matches[0][4] == "1598 cc"


def test_golf_mk4_no_row_has_zero_cells() -> None:
    wikitext = _wikitext_from_export_xml(FIXTURES / "volkswagen_golf_mk4.xml")
    tables = parse_tables(wikitext)
    for table in tables:
        for row in table.rows:
            assert len(row) > 0


# Rows whose Power cell is not expected to yield a kW figure because they
# contain no engine data. See docs/specs/002-table-parsing.md section 2.5.
_KNOWN_NON_POWER_ROWS = {
    # A doubled |- with a pending rowspan produces a row that carries only
    # the spanned Displ. value; there is no power data in that row at all.
    ("", "", "", "", "1781 cc", "", ""),
    # `|colspan="7"|` with empty content: a genuine blank spacer row.
    ("", "", "", "", "", "", ""),
}


def test_golf_mk4_auq_awp_row_has_a_machine_readable_alignment_warning() -> None:
    # The doubled |- at the start of this 1.8-litre group consumes one row of
    # the source's rowspan="3". The final AUQ/AWP row consequently has six
    # occupied columns for seven headers. The parser stays faithful to that
    # broken source, but must make the ambiguity impossible to miss.
    wikitext = _wikitext_from_export_xml(FIXTURES / "volkswagen_golf_mk4.xml")
    engine_table = parse_tables(wikitext)[0]
    row_index = next(i for i, row in enumerate(engine_table.rows) if "AUQ/AWP" in row[3])

    warning = next(
        warning
        for warning in engine_table.warnings
        if warning.kind == "ambiguous_row_alignment" and warning.row == row_index
    )
    assert warning.table_index == 0
    assert warning.expected_columns == 7
    assert warning.occupied_columns == 6
    assert warning.source_cells == 6
    assert warning.values == engine_table.rows[row_index]


def test_golf_mk4_every_power_cell_yields_a_kw_figure() -> None:
    # Acceptance criteria 9 and 12 in docs/specs/003-inline-and-templates.md:
    # a (\d+)\s*kW regex matches every non-ambiguous power cell, whether
    # authored in kW or in PS. Structurally ambiguous rows are selected from
    # machine-readable parser warnings, never from a hard-coded model name.
    wikitext = _wikitext_from_export_xml(FIXTURES / "volkswagen_golf_mk4.xml")
    tables = parse_tables(wikitext)
    engine_table = tables[0]
    power_idx = engine_table.headers.index("Power")
    ambiguous_rows = {
        warning.row
        for warning in engine_table.warnings
        if warning.kind == "ambiguous_row_alignment"
    }

    misses = []
    for row_index, row in enumerate(engine_table.rows):
        if tuple(row) in _KNOWN_NON_POWER_ROWS:
            continue
        if row_index in ambiguous_rows:
            continue
        cleaned, _ = clean_cell(row[power_idx])
        if not re.search(r"(\d+)\s*kW", cleaned):
            misses.append(row)

    assert misses == []


def test_golf_mk4_engine_table_section_ancestry() -> None:
    # Acceptance criteria 1-2 in docs/specs/004-section-ancestry.md.
    wikitext = _wikitext_from_export_xml(FIXTURES / "volkswagen_golf_mk4.xml")
    tables = parse_tables(wikitext)
    assert tables[0].section == "Engine choices > Golf and Jetta"
    assert len(tables[0].section_path) == 2


def test_golf_mk4_section_breadcrumbs_are_cleaned() -> None:
    # Criterion 3: no [[, no ''', no <ref> in any breadcrumb.
    wikitext = _wikitext_from_export_xml(FIXTURES / "volkswagen_golf_mk4.xml")
    tables = parse_tables(wikitext)
    for table in tables:
        for part in table.section_path:
            assert "[[" not in part
            assert "'''" not in part
            assert "<ref" not in part


def test_skoda_octavia_generations_share_the_trailing_engines_element() -> None:
    # Criterion 4: several tables share "Engines" but differ in the
    # leading generation element.
    wikitext = _wikitext_from_export_xml(FIXTURES / "skoda_octavia.xml")
    tables = parse_tables(wikitext)
    engine_tables = [t for t in tables if t.section_path[-1:] == ["Engines"]]
    assert len(engine_tables) >= 4

    leading_elements = {t.section_path[0] for t in engine_tables}
    assert len(leading_elements) >= 3


def test_skoda_octavia_duplicate_sections_are_genuine() -> None:
    # Criterion 5: no two tables share an identical section unless the
    # article genuinely has two tables under one heading. The third- and
    # fourth-generation "Engines" sections each really do have two tables
    # (front-wheel-drive and all-wheel-drive "Combi 4x4" variants) with no
    # subheading between them -- confirmed by reading the raw wikitext.
    wikitext = _wikitext_from_export_xml(FIXTURES / "skoda_octavia.xml")
    tables = parse_tables(wikitext)

    sections = [t.section for t in tables if t.section]
    duplicates = {s for s in sections if sections.count(s) > 1}
    assert duplicates == {
        "Third generation (Typ 5E; 2012) > Engines",
        "Fourth generation (Typ NX; 2020) > Engines",
    }
    for section in duplicates:
        assert sections.count(section) == 2


def test_skoda_octavia_heading_anchors_are_stripped() -> None:
    # The real article's generation headings carry <span class="anchor">
    # markup before the visible title; the breadcrumb must be plain text.
    wikitext = _wikitext_from_export_xml(FIXTURES / "skoda_octavia.xml")
    tables = parse_tables(wikitext)
    assert any(t.section_path[:1] == ["First generation (Typ 1U; 1996)"] for t in tables)
    for table in tables:
        for part in table.section_path:
            assert "<span" not in part
            assert "anchor" not in part
