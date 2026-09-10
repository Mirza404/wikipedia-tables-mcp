# 003 — Tier 3: inline markup and template resolution

Input: a raw wikitext cell value. Output: plain text a downstream regex can
read numbers out of.

Modules: `wikipedia_tables_mcp/wikitext/inline.py`, `.../templates.py`

## 1. Order of operations

Order matters. Apply in this sequence to one cell value:

1. Strip HTML comments `<!-- ... -->`, including multi-line.
2. Strip `<ref>...</ref>`, `<ref ... />`, and `<ref ...>...</ref>`.
3. Strip `<nowiki>` wrappers but keep their inner text literal — do not process
   markup inside them.
4. Resolve templates `{{...}}`, innermost first.
5. Resolve wikilinks `[[...]]`.
6. Resolve external links `[http://url text]` to `text`, or to the bare URL if
   there is no text.
7. Strip formatting: `'''bold'''`, `''italic''`, `<br>`, `<br/>`, `<small>`,
   `<sup>`, `<sub>`, `<span>`, and other bare HTML tags. `<br>` becomes a space.
8. Decode remaining HTML entities (`&nbsp;`, `&ndash;`, `&amp;`). `&nbsp;`
   becomes a normal space.
9. Strip leftover reference markers `[1]`, `[a]`, `[note 3]`, `[citation needed]`.
10. Collapse whitespace runs to one space. Strip ends.

## 2. Wikilinks

| Input | Output |
|---|---|
| `[[Straight-four engine\|I4]]` | `I4` |
| `[[VR6 engine]]` | `VR6 engine` |
| `[[List of ... engines#AGN\|AGN/BAF]]` | `AGN/BAF` |
| `[[Gasoline direct injection\|FSI]]` | `FSI` |
| `[[File:x.jpg\|thumb\|caption]]` | `""` — drop image links entirely |
| `[[Category:X]]` | `""` — drop |

Rule: take the text after the last `|`. With no `|`, take the whole target,
including any `#fragment`? **No** — with no pipe, drop the `#fragment` and keep
the page title only. `[[Foo#Bar]]` becomes `Foo`.

Drop links whose target namespace prefix is `File:`, `Image:`, `Category:`, or
`Media:` (case-insensitive).

## 3. Templates

### 3.1 The problem

Fixture counts: 61 `{{convert}}`, 12 `{{cvt}}` in one article. Real observed
shapes, all from the Golf Mk4 engine table:

```
{{convert|55|kW|PS hp|0|abbr=on}}
{{convert|128|Nm|lb.ft|abbr=on}}
{{convert|170|Nm|0|abbr=on}}
{{cvt|148|Nm|lbft|0}}
{{cvt|81|kW|PS hp|0}}
{{cvt|115|PS|kW PS hp|0|order=out}}
```

Note the variation: an output-unit list may be absent; a precision digit may be
absent; `order=out` inverts which unit is shown first.

### 3.2 Resolution strategy

Do **not** implement a general MediaWiki template expander. Implement a bounded
registry: `{template name (normalized) -> handler function}`.

Normalization of the name: strip, lowercase, collapse underscores to spaces.

Parse a template invocation into positional and named arguments, respecting
nesting: `{{`/`}}` and `[[`/`]]` depth, so a `|` inside a nested construct does
not split arguments.

### 3.3 `{{convert}}` and `{{cvt}}` handler

`{{cvt}}` is `{{convert}}` with `abbr=on` implied. One handler serves both.

Positional grammar, after named arguments are removed:

```
1 = value           (required, number, may be "1,234" or "5.5")
2 = input unit      (required, e.g. kW, Nm, PS, hp, mm, kg, L)
3 = second value OR output unit(s) OR precision
4 = output unit(s) OR precision
5 = precision
```

Ambiguity resolution, left to right:
- If argument 3 is numeric it is a **range end** (`{{convert|1|2|km}}`).
- Else if argument 3 matches a known unit token, or is a space-separated list of
  known unit tokens, it is the output unit list.
- Else if argument 3 is an integer 0-6 or `-1`..`-3`, it is precision.
- Remaining arguments follow the same test.

**The authored value is always positional argument 1, with its unit in argument
2.** The named argument `order=out` changes only which unit Wikipedia *displays*
first. It does not change what the author wrote. Therefore `order=out` needs no
special handling at all — see §3.3.2.

#### 3.3.1 Output policy: canonical units

Decided (Q2). kW is the ground truth the consumer needs. The conversions between
these units are exact defined constants, not estimates, so computing them adds
no measurement error.

Canonical unit per quantity:

| Quantity | Canonical |
|---|---|
| Power | `kW` |
| Torque | `Nm` |
| Displacement | `cc` |

Rule:

1. Emit the authored value and authored unit verbatim, always.
2. If the authored unit is **not** the canonical unit for its quantity, append
   the converted canonical value in parentheses.
3. If the authored unit **is** canonical, or has no canonical mapping, emit it
   alone.

```
{{convert|55|kW|PS hp|0|abbr=on}}          ->  "55 kW"
{{convert|128|Nm|lb.ft|abbr=on}}           ->  "128 Nm"
{{cvt|115|PS|kW PS hp|0|order=out}}        ->  "115 PS (85 kW)"
{{convert|150|hp|kW}}                      ->  "150 hp (112 kW)"
{{convert|200|lbft|Nm}}                    ->  "200 lbft (271 Nm)"
{{convert|2.0|L|cc}}                       ->  "2.0 L (2000 cc)"
```

The authored figure is never discarded. A consumer regex for `kW`, `Nm`, or `cc`
always finds a value.

> **Note for consumers — leading-digit parsing.**
> When the authored unit is not canonical, the cell holds two numbers and the
> **authored** one comes first: `"115 PS (85 kW)"`. A consumer that anchors on
> the unit (`(\d+)\s*kW`) reads 85 and is correct. A consumer that takes the
> first number in the cell reads 115, which is the PS figure, not kW.
>
> This is a documentation and consumer-side concern, not a parser defect — both
> figures are correct and correctly labelled. If it proves awkward in practice,
> the fix is small and local to this handler. Options, in order of preference:
> put the canonical value first (`"85 kW (115 PS)"`), or add a parallel
> structured field per cell carrying `{value, unit}` alongside the display text.
> Neither changes any other tier. Revisit at M4 once a real consumer exists.

#### 3.3.2 Conversion constants

Exact by definition. Hard-code these; do not pull in a units library.

```python
TO_KW = {
    "kW": 1.0,
    "W": 0.001,
    "PS": 0.73549875,            # 75 kgf.m/s, exact
    "hp": 0.745699871582,        # mechanical horsepower, exact
    "bhp": 0.745699871582,       # treated as mechanical hp
    "cv": 0.73549875,            # metric, same as PS
    "ch": 0.73549875,
}
TO_NM = {
    "Nm": 1.0, "N.m": 1.0, "N*m": 1.0,
    "lbft": 1.3558179483314004,  # exact
    "lb.ft": 1.3558179483314004,
    "ftlb": 1.3558179483314004,
    "ft.lbf": 1.3558179483314004,
    "kgm": 9.80665,              # exact
    "kg.m": 9.80665,
}
TO_CC = {
    "cc": 1.0, "cm3": 1.0, "ccm": 1.0,
    "L": 1000.0, "l": 1000.0, "litre": 1000.0, "liter": 1000.0,
    "cuin": 16.387064,           # exact
    "cid": 16.387064,
    "mL": 1.0,
}
```

`bhp` is treated as mechanical `hp`. That is an approximation of intent, not of
arithmetic — the two are used interchangeably on Wikipedia. Note it in the
README.

**Rounding.** Round half away from zero. Result >= 10 -> integer. Result < 10 ->
one decimal place. This matches Wikipedia's own default precision for these
quantities and makes the output diffable against the rendered page.

#### 3.3.3 Ranges

`{{convert|1950|4700|rpm}}` emits `"1950-4700 rpm"` with an en dash. When the
unit is convertible, both ends convert: `{{convert|100|120|hp|kW}}` emits
`"100-120 hp (75-89 kW)"`.

### 3.4 Other templates worth a handler

Cheap, common, and likely in car articles:

| Template | Result |
|---|---|
| `{{nowrap\|X}}`, `{{noWrap\|X}}` | `X` |
| `{{nbsp}}`, `{{spaces}}` | one space |
| `{{ndash}}`, `{{endash}}`, `{{--}}` | `–` |
| `{{mdash}}` | `—` |
| `{{sfrac\|a\|b}}`, `{{frac\|a\|b}}` | `a/b` |
| `{{val\|N\|u=X}}` | `N X` |
| `{{small\|X}}`, `{{big\|X}}`, `{{nobold\|X}}` | `X` |
| `{{sortname\|A\|B}}` | `A B` |
| `{{sort\|key\|X}}` | `X` |
| `{{ubl\|a\|b\|c}}`, `{{plainlist\|...}}` | `a, b, c` |
| `{{clear}}`, `{{clarify}}`, `{{citation needed}}`, `{{cn}}`, `{{efn}}`, `{{refn}}` | `""` |
| `{{lang\|xx\|text}}` | `text` |

### 3.5 Unknown templates — must not fail silently

An unrecognized template shape must produce a clear, structured signal. Never a
silently wrong value.

Behaviour, in `strict=False` mode (the default):

- The template renders as `""` in the cell text.
- A structured entry is appended to the table's `warnings` list:

```python
{
  "kind": "unknown_template",
  "name": "convert",
  "raw": "{{convert|foo|bar|baz}}",
  "reason": "argument 1 is not numeric",
  "table_index": 0,
  "row": 4,
  "column": 5,
}
```

- The client result carries `warnings` up to the top level.

In `strict=True` mode the same condition raises `TemplateResolutionError`
carrying the same fields.

A **known** template whose arguments do not match its grammar is the same case:
a warning, not a guess. Specifically, `{{convert}}` with a non-numeric first
argument is `unknown_template` with `reason`, not `"" `and silence.

Rationale: the handoff requires this. A wrong engine power number is worse for
`car-dealer` than a missing one, because it looks valid.

### 3.6 Unit token list

Keep an explicit set of recognized unit tokens so argument disambiguation works:
`kW W PS hp bhp mph km/h Nm N.m lbft lb.ft ft.lbf cc cm3 L l cuin in mm cm m km
kg lb t s rpm`. Case-sensitive where MediaWiki is (`kW` not `kw`), but accept a
case-insensitive match and emit the canonical spelling.

An unrecognized token in the output-unit position is not an error — it just is
not treated as a unit for disambiguation.

## 4. Acceptance criteria

Cell-level unit tests against real fixture strings:

1. `{{convert|55|kW|PS hp|0|abbr=on}} at 5,500 rpm` -> `55 kW at 5,500 rpm`
2. `{{cvt|235|Nm|lbft|0}} at 1,950–4,700 rpm` -> `235 Nm at 1,950–4,700 rpm`
3. `[[Straight-four engine|I4]] 16V` -> `I4 16V`
4. `[[VR5 engine|VR5]] 10V` -> `VR5 10V`
5. `[[List of discontinued Volkswagen Group petrol engines#AGN|AGN/BAF]]` -> `AGN/BAF`
6. `1.8 [[Turbocharger|T]]` -> `1.8 T`
7. A cell containing `<ref>...</ref>` loses the whole ref, keeps the rest.
8. `{{convert|abc|kW}}` produces one `unknown_template` warning and `""`.
9. Regex `(\d+)\s*kW` matches every non-empty, structurally unambiguous power
   cell in the fixture's engine table.
10. `{{cvt|115|PS|kW PS hp|0|order=out}}` -> `115 PS (85 kW)`. Cross-checked
    against Wikipedia's own rendering of that template, "85 kW (115 PS; 113 hp)".
11. `{{convert|150|hp|kW}}` -> `150 hp (112 kW)`.
12. Every structurally unambiguous power cell in the fixture's engine table
    yields a kW figure, whether authored in kW or in PS. The known `AUQ/AWP`
    source defect is selected through Tier 2's machine-readable alignment
    warning, never through a hard-coded article/model exception.
