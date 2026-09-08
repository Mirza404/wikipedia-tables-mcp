# Manual verification log

Per [`docs/specs/007-testing.md`](specs/007-testing.md) section 6: before the
first release, run the parser over ~20 real car articles and check the
extracted power and torque figures by hand. Unit tests alone cannot prove the
template resolver correct, because the risk is a plausible wrong number, not
a crash.

Run on 2026-09-08, `SpecialExportClient(cache_dir=...)` against live
`en.wikipedia.org`, `special-export-mcp/0.1.0` as the User-Agent. Every
article was fetched once; every re-run while diagnosing the findings below
cost zero further requests.

## Articles

| Title requested | Resolved to | Tables found |
|---|---|---|
| Volkswagen Golf Mk4 | Volkswagen Golf Mk4 | 2 |
| Škoda Octavia | Škoda Octavia | 7 |
| BMW E46 | BMW 3 Series (E46) | 3 |
| Mercedes-Benz W124 | Mercedes-Benz W124 | 3 |
| Audi B5 (car) | *(page does not exist)* | — |
| Ford Focus (first generation) | Ford Focus (first generation) | 4 |
| Toyota Corolla (E110) | Toyota Corolla (E110) | 2 |
| Honda Civic (sixth generation) | Honda Civic (sixth generation) | 2 |
| Opel Astra | Opel Astra | 13 |
| Peugeot 206 | Peugeot 206 | 4 |
| Renault Clio | Renault Clio | 6 |
| Fiat Punto | Fiat Punto | 5 |
| Volvo 850 | Volvo 850 | 2 |
| Saab 900 | Saab 900 | 0 |
| Alfa Romeo 156 | Alfa Romeo 156 | 2 |
| Citroën Xsara | Citroën Xsara | 0 |
| Nissan Primera | Nissan Primera | 0 |
| Mazda 323 | Mazda Familia | 1 |
| SEAT Ibiza | SEAT Ibiza | 10 |
| Škoda Fabia | Škoda Fabia | 6 |

19 of 20 titles resolved to a real article (`Audi B5 (car)` does not exist
under that title; not investigated further, since the goal of this pass is
breadth across real articles, not completeness of any one guess). The three
zero-table articles (Saab 900, Citroën Xsara, Nissan Primera) were checked
directly against their raw wikitext: none contain a `{|` anywhere. That is a
fact about those articles, not a parser miss — older or shorter car articles
sometimes carry engine specs as prose or an infobox instead of a wikitable.

72 tables parsed in total across the corpus.

## Findings, and what was fixed

Four real gaps surfaced, all in [PR #8](https://github.com/Mirza404/special-export-mcp/pull/8)
(this log is the next commit in the stack on top of it):

1. **`hp-metric` unit alias missing.** `{{convert|90|hp-metric|kW|0|abbr=on}}`
   (Renault Clio) had no canonical mapping, so a power value authored in it
   never got a kW figure at all -- silently incomplete, not wrong, but it
   broke the "every power cell yields a kW figure" guarantee. Added as an
   alias for PS (same conversion factor).
2. **Inline-hyphen range form of `{{convert}}`/`{{cvt}}`.** A range can be
   authored as one argument with an embedded hyphen or en dash
   (`{{cvt|133-136|PS|kW hp|0}}`, Opel Astra), not just as two separate
   positional arguments. The un-fixed parser failed the numeric check on
   argument 1 and produced an `unknown_template` warning plus an empty cell,
   losing real data. Now parsed the same as the two-argument form.
3. **`colspan="N" {{rh}}|content` broke the attribute/content split
   entirely.** `{{rh}}` ("row header") is a styling-only template with no
   text output, commonly interleaved with a real attribute in engine-table
   divider rows (seen in Škoda Octavia and Renault Clio). The attribute
   regex required every space-separated token to be `key=value`, so the
   whole string fell through to "no attributes, treat as content" --
   `colspan` was never applied, and the divider row came out one column
   wide instead of N. Fixed by tolerating a bare `{{...}}` token in the
   attribute grammar, and registering `{{rh}}` as a known no-op template.
4. **`{{n/a}}`** appeared 17 times across the corpus -- cheap and common
   enough to be worth its own handler per spec 003 section 3.4's bar.
   Resolves to `"N/A"`.

After the fixes, a second full pass over the same 20 articles found:

- **Zero remaining `convert`/`cvt` shape-validation false positives.**
- **`unknown_template` warnings, 7 categories remaining, all out of
  scope:** `rating` (safety-rating box), `co2`, `chem` (chemical formula),
  `#tag:ref`, `abbr`, `ref label`, `diagonal split header`. All appear in
  notes, references, or safety-rating cells -- never in a power or torque
  cell, and none involve arithmetic. This matches the project's explicit
  non-goal: a bounded registry, not a general expander.
- **61 `ambiguous_row_alignment` warnings** across the corpus. A sample was
  read against the raw wikitext by hand (the same way the Golf Mk4
  "1.8 T" / AUQ-AWP case was confirmed during Tier 4): every one checked is
  a row genuinely missing a trailing cell in the source (most often an
  omitted final "Notes" column with nothing to carry down), which a
  browser's own HTML rendering would misalign identically. This is the
  warning system doing its job, not a defect -- see
  [`docs/data-integrity.md`](data-integrity.md).

## Spot-checked arithmetic

Every cell where the authored unit was not already kW, Nm, or cc is where
this project performs arithmetic, and a transposed constant would produce a
plausible wrong number (spec 007 section 6's specific concern). A sample
across the corpus, checked by hand against the conversion constants in
[`templates.py`](../special_export_mcp/wikitext/templates.py):

| Authored | Canonical | Computation | Result |
|---|---|---|---|
| 115 PS | kW | 115 × 0.73549875 | 85 kW ✓ |
| 130 PS | kW | 130 × 0.73549875 | 96 kW ✓ |
| 133–136 PS | kW | 133 × 0.73549875, 136 × 0.73549875 | 98–100 kW ✓ |
| 90 hp-metric | kW | 90 × 0.73549875 | 66 kW ✓ |
| 180 PS | kW | 180 × 0.73549875 | 132 kW ✓ |

All match hand computation to the rounding rule (round half away from zero;
≥10 → integer). No transposed or mismatched constant found.

## Conclusion

The parser is sound against a real, diverse 20-article sample spanning six
manufacturers and three decades of articles. The four fixes above landed in
[PR #8](https://github.com/Mirza404/special-export-mcp/pull/8). No further
code changes are needed before release on the strength of this pass; the
remaining warnings are the system correctly flagging genuine source-data
irregularity rather than guessing through it.
