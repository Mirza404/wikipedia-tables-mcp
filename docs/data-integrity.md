# Data integrity and recovery

Wikipedia tables are authored data. They can be internally inconsistent even
when the wikitext is valid. `wikipedia-tables-mcp` preserves what Wikipedia
actually contains and reports structural uncertainty; it never silently moves
values into columns that merely look more plausible.

## Warnings are part of the result contract

Every human, agent, and downstream importer **must inspect `warnings` before
persisting positional table data**. In particular,
`ambiguous_row_alignment` means that a row occupies fewer columns than the
table width after `rowspan` and `colspan` expansion. A missing cell is not
necessarily at the right edge, so any later value may have shifted columns.

The row remains in `rows` as evidence, padded to the table width, and the
warning includes its table index, row index, values, source-cell count, and
expected/occupied column counts. Keeping the evidence lets an interactive AI
investigate without making the parser guess.

## Required recovery policy

For an ambiguous row:

1. Do not persist its positionally assigned fields as trusted facts.
2. Import unaffected rows normally; quarantine only the ambiguous row.
3. An AI may inspect the returned row, adjacent rows, and the raw section using
   `get_wikitext`. It may also open the cited Wikipedia page when another view
   is useful. This is an exceptional fallback, not the bulk retrieval path.
4. Recover only facts whose meaning is explicit in the evidence, such as a
   value labelled `132 kW` being power or `235 Nm` being torque.
5. Leave any value that still requires a guess as `null` or pending review.
6. Record recovered values with their source revision, method, and confidence.

If this fallback becomes common, add a fixture and improve the deterministic
parser. Do not turn page scraping or AI inference into the normal import path.

## Known fixture example: Volkswagen Golf Mk4

The committed Golf Mk4 export contains two consecutive `|-` row separators in
the 1.8-litre engine group. The empty row consumes one row of a
`rowspan="3"`, leaving the final `1.8 T` / `AUQ/AWP` row one column short. A
browser follows the same table arithmetic.

The faithful rectangular grid therefore contains:

```json
{
  "Model": "1.8 T",
  "Year": "2001-2006",
  "Code": "AUQ/AWP",
  "Displ.": "132 kW at 5,500 rpm",
  "Power": "235 Nm at 1,950-4,700 rpm",
  "Torque": ""
}
```

Those positional assignments are not safe. Unit labels do support recovering
`Power = 132 kW` and `Torque = 235 Nm`; displacement should remain unknown
unless separately verified. The other `1.8 T` row is not affected.

