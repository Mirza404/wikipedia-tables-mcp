# 002 — Tier 2: wikitable parsing

Input: raw wikitext. Output: a list of tables, each a header list plus a
rectangular row grid. Cell values at this tier are still raw wikitext.
Tier 3 cleans them.

Modules: `wikipedia_tables_mcp/wikitext/tokenizer.py`, `.../tables.py`

## 1. Wikitable syntax handled

```
{| class="wikitable" style="text-align:center;"
|+ optional caption
|-
! Header1 !! Header2 !! Header3
|-
| cell1 || cell2 || cell3
|-
| rowspan="2" | spanning cell || cell
|}
```

Line-level tokens:

| Token | Meaning |
|---|---|
| `{\|` | table open, rest of line is table attributes |
| `\|}` | table close |
| `\|-` | row separator, rest of line is row attributes |
| `\|+` | caption |
| `!` at line start | header cell(s), `!!` separates on one line |
| `\|` at line start | data cell(s), `\|\|` separates on one line |
| any other line | continuation of the previous cell's value |

## 2. Real complications, all observed in the fixture

Fixture: `tests/fixtures/volkswagen_golf_mk4.xml`, section `==Engine choices==`.

### 2.1 Cell attributes versus cell content

Inside one cell, a single `|` splits attributes from content:

```
| rowspan="2" | 1595 cc
```

Attributes are `rowspan="2"`, content is `1595 cc`.

The split is on the **first** `|` only, and only when the text before it looks
like an attribute list. A cell whose content itself contains `|`, for example a
piped wikilink or a template, must not be mis-split. Rule:

Take the text before the first `|` that is not inside `[[...]]`, `{{...}}`,
`<...>`, or a quoted attribute value. If that prefix matches
`^\s*[A-Za-z-]+\s*=\s*("[^"]*"|'[^']*'|\S+)(\s+...)*\s*$`, treat it as
attributes. Otherwise the whole cell is content and there are no attributes.

Observed spacing variants that must both parse:

```
| rowspan="2" | 1595 cc
| rowspan = "2" | 1598 cc
```

So: whitespace around `=` is allowed, and quotes may be `"`, `'`, or absent.

### 2.2 `rowspan`

`rowspan="N"` means the value occupies the same column in the next N-1 rows.
Carry it down. This is the wikitext form of the HTML-rowspan handling the
`wikipedia-mcp` fork already implements for rendered tables. Same idea, new
code, no shared source.

Algorithm: keep a pending-span map `{column_index: (value, rows_remaining)}`.
When starting a new row, first place every pending value into its column and
decrement its counter. Then consume the row's own cells into the remaining
columns, left to right.

### 2.3 `colspan`

`colspan="N"` repeats the value across N adjacent columns in the same row.
Present in the fixture (2 occurrences). Repeat the value; do not blank-fill.
`rowspan` and `colspan` can co-occur on one cell — the whole N-wide block
carries down.

### 2.4 Header-styled cells inside data rows

The fixture's engine table opens with a genuine header row of `!` cells. But
every data row *also* starts with a `!` cell:

```
|-
! 1.4
| 1998–2004 || [[Straight-four engine|I4]] 16V || ... 
```

`! 1.4` is a row label, not a table header. Rule:

- The **first** row of a table is the header row if all of its cells are `!`
  cells. Its values become `headers`.
- Any later row that mixes `!` and `|` cells is a **data** row. Its `!` cells
  are ordinary values in column order.
- A later row that is entirely `!` cells is a mid-table header. Decision to
  confirm: treat it as a data row whose values happen to be header text, and
  keep it in `rows`. Rationale: dropping it loses data; splitting the table
  into two is surprising for a consumer that expects one table per `{|`.

If the first row is not all-`!`, `headers` is an empty list and every row goes
into `rows`.

### 2.5 Empty and doubled row separators

The fixture contains:

```
|-
|-
! 1.8 [[Turbocharger|T]]
```

A `|-` that is immediately followed by another `|-` produces a row with zero
cells. Drop rows that have zero cells after rowspan carry-down. Do not drop a
row that has only carried-down values — that row is real.

### 2.6 Multi-line cell values

A cell value may continue on following lines until the next token line. Join
continuation lines with a single space and collapse runs of whitespace.

### 2.7 Nested tables

`{|` may appear inside a cell. Maintain a stack. Each `{|`/`|}` pair becomes its
own table in the output list, in the order its `|}` is seen — matching the
`wikipedia-mcp` fork's HTML behaviour. The nested table's own text is removed
from the parent cell's value, leaving the parent cell's other text.

Not present in the Golf Mk4 fixture. Needs a second fixture. See Tier 7.

### 2.8 Captions

`|+` gives the table a caption. Capture it as `caption: str | None`. It is not
a header row.

## 3. Rectangularity

The output grid must be rectangular. Let `width = max(len(headers), max row
length)`. Pad every short row on the right with `""`. Never truncate a row that
is longer than the header list — widen instead, and pad `headers` with `""`.

Rationale: a consumer indexing `row[3]` for "Power" must not hit `IndexError`
on a malformed article.

### 3.1 Ambiguous row alignment

Rectangular padding prevents an `IndexError`; it does not prove that authored
values occupy the correct semantic columns. When a data row occupies fewer
columns than the final table width after `rowspan` and `colspan` expansion,
append a structured `ambiguous_row_alignment` warning to the table.

The warning contains `table_index`, `row`, `expected_columns`,
`occupied_columns`, `source_cells`, and `values`. Its reason must state that a
missing cell is not necessarily trailing and positional values may therefore
be shifted. Keep the padded row in `rows` as evidence. Do not guess where the
missing cell belongs.

Consumers must quarantine a warned row before mapping cells to named fields.
An interactive AI may recover explicitly labelled facts from the evidence or
inspect raw wikitext, but uncertain fields remain missing. The binding recovery
policy and the Golf Mk4 example are in
[`docs/data-integrity.md`](../data-integrity.md).

## 4. Bounds

Copy the spirit of the `wikipedia-mcp` fork's limits, so one pathological
article cannot produce a gigantic payload:

| Bound | Default |
|---|---|
| `max_tables` | 50 |
| `max_rows_per_table` | 400 |
| `max_cells_per_row` | 60 |
| `max_cell_chars` | 2000 |

When a bound is hit, truncate and set a `truncated: true` flag on that table.
Do not raise.

## 5. Which tables are returned

Default: every `{| ... |}` in the page, regardless of `class`.

Optional filter `table_class="wikitable"` restricts to tables whose `class`
attribute contains that token. Default is no filter.

Rationale: infoboxes and navboxes are templates, not raw `{|`, so they mostly do
not appear anyway. Filtering by default would silently drop unclassed data
tables.

## 6. Acceptance criteria

Against `tests/fixtures/volkswagen_golf_mk4.xml`:

1. Exactly 2 tables are found (fixture has 2 `{|` and 2 `|}`).
2. The engine table's `headers` equal
   `["Model", "Year", "Engine", "Code", "Displ.", "Power", "Torque"]`.
3. Every row has exactly 7 cells.
4. The row `1.6 / 2000–2006 / I4 8V / AVU/BFQ` has `1595 cc` in the `Displ.`
   column, carried down by the `rowspan="2"` on the row above.
5. The row after `rowspan = "2" | 1598 cc` (spaces around `=`) carries `1598 cc`.
6. No row in the output has zero cells, despite the doubled `|-`.
7. The Golf Mk4 `AUQ/AWP` row carries an `ambiguous_row_alignment` warning
   identifying 6 occupied columns against the 7-column table width.
