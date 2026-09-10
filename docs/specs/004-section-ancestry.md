# 004 — Tier 4: section heading ancestry

Every returned table carries a breadcrumb naming the full chain of headings
above it.

Module: `wikipedia_tables_mcp/wikitext/sections.py`

## 1. Why

Car articles cover several generations in one page. Skoda Octavia and
Mercedes-Benz GLC each repeat the same kind of engine table once per
generation, nested under headings:

```
== Fourth generation (2019-present) ==
=== Engines ===
{| class="wikitable"
...
```

Without ancestry, a consumer receives several near-identical tables and cannot
tell which generation each belongs to. The nearest heading alone (`Engines`) is
not enough — it is the same for all of them.

The `wikipedia-mcp` fork solved this for rendered HTML tables on branch
`fix/multi-header-tables`, commit "Give table sections full heading ancestry
(breadcrumb)". This is the same feature, implemented independently against
wikitext. No code is copied.

## 2. Wikitext headings

```
== Level 2 ==
=== Level 3 ===
```

Grammar: a line whose stripped form matches `^(={2,6})\s*(.+?)\s*\1$`.

Observed spacing variants in the fixture, both must parse:

```
==Engine choices==
=== Golf and Jetta ===
```

`=` at level 1 (`= X =`) is reserved for the page title and is rare in article
bodies. Accept levels 1 to 6. Treat level 1 the same as any other.

Heading text is itself wikitext. Run it through the Tier 3 inline cleaner:
`=== [[Volkswagen Bora|Bora]]/Jetta Mk4 ===` becomes `Bora/Jetta Mk4`.

A `=`-looking line inside a `<nowiki>`, `<pre>`, or a `{| ... |}` table body is
not a heading. Neither are heading- or table-looking lines inside an HTML
comment. Track these contexts before classifying table or heading syntax.
Self-closing tags such as `<nowiki />` do not enter literal mode, and tags
inside HTML comments do not change literal state.

Tier 3's warning policy also applies to heading text. If cleaning a heading
encounters an unknown or malformed template, attach that structured warning to
every table whose ancestry includes the heading. In strict mode, raise the same
`TemplateResolutionError` that the template would raise inside a cell. Never
turn an unsupported heading template into an empty breadcrumb silently.

## 3. The heading stack

Maintain a stack of `(level, text)`.

On a heading of level L: pop every entry with level >= L, then push `(L, text)`.

When a table opens, snapshot the current stack. That snapshot is the table's
ancestry — snapshot at `{|`, not at `|}`, so a table that spans a heading
boundary is attributed to where it starts.

## 4. Output shape

Each table carries both a joined string and the parts:

```python
{
  "section": "Fourth generation (2019-present) > Engines",
  "section_path": ["Fourth generation (2019-present)", "Engines"],
  ...
}
```

Separator: `" > "`.

A table before any heading, in the article lead, gets:

```python
{"section": "", "section_path": []}
```

Decision to confirm (Tier 8, Q3): `""` versus `"(lead)"`. Proposal: `""`, and
let the consumer decide how to display it. An empty string cannot collide with a
real heading named "(lead)".

## 5. Interaction with nested tables

A table nested inside another table's cell has the same heading ancestry as its
parent. The heading stack does not change inside a table body.

Decision to confirm (Tier 8, Q4): whether a nested table should additionally
carry a pointer to its parent, for example `parent_table_index: int | None`.
Proposal: yes, cheap and harmless.

## 6. Acceptance criteria

Against `tests/fixtures/volkswagen_golf_mk4.xml`:

1. The engine table's `section` equals `"Engine choices > Golf and Jetta"`.
2. Its `section_path` has exactly 2 elements.
3. Heading text is cleaned: no `[[`, no `'''`, no `<ref>` in any breadcrumb.

Against a multi-generation fixture (Skoda Octavia, see Tier 7):

4. Several tables share the trailing element `"Engines"` but differ in the
   leading generation element.
5. No two tables in that fixture have an identical `section` unless the article
   genuinely has two tables under one heading.
