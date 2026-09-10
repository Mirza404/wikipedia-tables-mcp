# 008 — Build order, milestones, open questions

## 1. Build order

Each milestone is a mergeable pull request. Each ends green on CI.

### M0 — Skeleton
`pyproject.toml`, package layout, `ruff`, `mypy`, `pytest`, GitHub Actions,
`LICENSE` (MIT), `README.md` stub, `errors.py` with the full exception tree.
No behaviour.

### M1 — Tier 1, fetch
`fetch.py`. Single-title path form, multi-title POST form, User-Agent, retry,
export-XML unwrapping, missing-page detection, redirect resolution.
Ships `get_wikitext(title)` as the only public call.
**Usable on its own**: `car-dealer` could already stop calling `action=parse`.

### M2 — Tier 2, tables
`tokenizer.py` and `tables.py`. Raw-wikitext cell values, no cleanup yet.
`rowspan`, `colspan`, attribute/content split, header-row detection, empty-row
drop, rectangularity, bounds, nested tables.

### M3 — Tier 3, inline markup
`inline.py`. Refs, comments, wikilinks, external links, formatting, entities.
No templates yet — a `{{...}}` passes through untouched at this point.

### M4 — Tier 3, templates
`templates.py`. Registry, argument parser, `convert`/`cvt` handler, the small
template table, and the `unknown_template` warning path.
**This is the highest-risk milestone.** Budget real fixture time here.

### M5 — Tier 4, sections
`sections.py`. Heading stack, breadcrumb, cleaned heading text.
Needs the Skoda Octavia fixture before it can be properly tested.

### M6 — Tier 5, client
`client.py`. Assembles M1-M5 into `SpecialExportClient` and the dict contract.
Caching, rate floor, logging.
**This is the milestone that makes M7 possible.**

### M7 — Tier 6, MCP server
`server.py`, the console script, the four tools, MCP-specific size caps.

### M8 — Hardening
The 20-article manual verification pass (Tier 7 §6), README with real examples,
`0.1.0` release.

Dependency note: M7 and M8 both depend only on M6, so they can run in parallel.
M7 is the deliverable — the server is the product — so if time is short, M8's
verification pass is the one that slips, not M7.

## 2. Decisions (answered 2026-09-05)

All questions are settled. Recorded here so a later reader can retrace a bad
decision to its reasoning.

**Q1 — return type. DECIDED: internal dataclasses, public plain dicts.**
Dict matches the handoff contract and the JSON the MCP layer must emit. The only
cost is no editor autocomplete on the result; there is no functional limitation.
Dataclasses internally so `mypy` guards the parser, where a silent bug produces
a wrong car specification. See 005 section 3.

**Q2 — `order=out` and unit conversion. DECIDED: kW is ground truth; convert.**
The original proposal avoided arithmetic to avoid a second source of error. That
objection does not hold: PS, hp, lbft and cuin conversions are exact defined
constants, not measurements. New rule — emit the authored value and unit always,
and append the canonical unit in parentheses when the authored unit is not
canonical (`"115 PS (85 kW)"`). Canonical units: power kW, torque Nm,
displacement cc. `order=out` needs no special case, because it changes only
Wikipedia's display order, never which value the author wrote. See 003 section
3.3.1.

**Q3 — lead-section tables. DECIDED: `section: ""`, `section_path: []`.**
An empty string cannot collide with a real heading.

**Q4 — nested tables. DECIDED: include `parent_table_index: int | None`.**

**Q5 — `list_page_sections` MCP tool. DECIDED: include in v1.**
About 20 lines over the existing heading stack, and it is what makes
`section_filter` usable without pulling a large payload first.

**Q6 — mid-table all-header rows. DECIDED: keep as data rows.**
Dropping loses data. Splitting the table surprises a consumer that expects one
table per `{|`.

**Q7 — caching. DECIDED: opt-in on-disk cache, off by default, no TTL.**
Reframed after the consumer's real usage profile was described: a loading phase
of ~50 models over the first weeks, decaying to near zero, with results stored
permanently in the consumer's own database. Each model is therefore fetched once
in its life whether or not a cache exists. Caching is **not** a production
feature here. It is kept, small and opt-in, for two narrower reasons: parser
development re-runs, and recovering a partly-complete loading phase without
refetching what already succeeded. Default `cache_dir=None`. See 001 section 7.1.

**Q8 — sync or async. RESOLVED: moot. Synchronous throughout.**
The question came from designing around a direct-import consumer. That framing
was wrong: this is a standalone MCP server, not a support library for one
application. The MCP SDK is async at the transport layer and wraps a blocking
fetch without difficulty at this request volume. No `AsyncSpecialExportClient`,
now or planned. No open risk.

**Q9 — languages. DECIDED: English only, likely permanently.**
The `language` constructor argument stays, because it costs nothing, but the
template registry is documented as English-only. `{{convert}}` does not exist on
the German or Serbo-Croatian Wikipedias. No work is done to support them.

**Q10 — naming and distribution. DECIDED.**
Repository `https://github.com/Mirza404/wikipedia-tables-mcp.git`. Import name
`wikipedia_tables_mcp`. **No PyPI publication.** `pyproject.toml` exists for
dependencies and tool configuration only. Consumers install from git or from a
local path:

```bash
pip install git+https://github.com/Mirza404/wikipedia-tables-mcp.git
```

The `[mcp]` extra still exists as an optional dependency group, so `car-dealer`
installs the client without the MCP SDK.

## 3. Risks

| Risk | Mitigation |
|---|---|
| `Special:Export` gets rate-limited too, later | Client-side interval floor, caching, and the fetch layer is one module — swapping to `action=raw` or to dumps is contained |
| A wrong number reaches `car-dealer` and looks valid | The authored value is never discarded, only supplemented (Q2); conversion constants are exact and unit-tested against Wikipedia's own rendering; structured warnings on any unrecognized shape; the M8 manual verification pass |
| A loading-phase burst trips a limit | Batch POST at 20 titles per request, client-side interval floor, and opt-in cache so a failed run does not refetch |
| Wikitable syntax is genuinely irregular across articles | Fixture-driven. Add a fixture per new failure shape rather than guessing at generality up front |
| Scope drift toward reimplementing MediaWiki | The non-goals in `000-overview.md` §7 are binding. A bounded template registry, never an expander |

## 4. Out of scope, confirmed

- No changes to `wikipedia-mcp` or its fork.
- No changes to `car-dealer`.
- No implementation before the user approves these specs.
- No PyPI publication. Install from git.
- No language other than English.
