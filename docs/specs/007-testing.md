# 007 — Tier 7: fixtures, tests, CI

## 1. No live network in tests

Every test runs against committed fixture XML. CI makes zero requests to
Wikimedia. Reasons: determinism, and not adding load to a service whose rate
limits already caused this project to exist.

A separate, opt-in marker `@pytest.mark.live` covers a small set of live smoke
tests. They run only with `pytest -m live`, never in CI by default.

## 2. Fixtures

Committed under `tests/fixtures/`. Each is the full, unmodified export XML, plus
a `.source` sidecar file recording the URL and the fetch date.

| Fixture | Why | Status |
|---|---|---|
| `volkswagen_golf_mk4.xml` | `rowspan`, `rowspan = "2"` spacing variant, doubled `\|-`, `!` row-label cells, 61 `{{convert}}`, 12 `{{cvt}}`, `order=out`, `colspan`, 20 `<ref>`, 2 HTML comments, 2-level heading ancestry | **already saved** (fetched 2026-09-05, 45,758 bytes) |
| `skoda_octavia.xml` | Multi-generation: repeated `Engines` tables under different generation headings. Tier 4's main test. | to fetch |
| `mercedes_benz_glc.xml` | Second multi-generation case, different author conventions | to fetch |
| `nested_table.xml` | A page with a `{\|` inside a cell. Needs finding. | to find and fetch |
| `missing_page.xml` | Export response for a nonexistent title — no `<page>` element | to fetch |
| `redirect.xml` | `Golf Mk4` with `redirects=1`, resolved title differs from requested | to fetch |

Refetch command, recorded in `tests/fixtures/README.md`:

```bash
curl -s -A "wikipedia-tables-mcp/0.1 (https://github.com/Mirza404/wikipedia-tables-mcp)" \
  "https://en.wikipedia.org/wiki/Special:Export/Volkswagen_Golf_Mk4" \
  -o tests/fixtures/volkswagen_golf_mk4.xml
```

Fixtures are snapshots. Articles change. Golden-output tests must assert on
**structural invariants** (row count is consistent, `1595 cc` carried down,
breadcrumb has 2 parts), not on a full byte-for-byte expected dict, so a
harmless article edit after a refetch does not produce a wall of red.

## 3. Test layers

| Layer | Scope |
|---|---|
| `test_inline.py` | Tier 3 string-in / string-out. Fast, many cases. |
| `test_templates.py` | Template argument parsing, every observed `convert`/`cvt` shape, and the unknown-shape warning path |
| `test_tables.py` | Tier 2 against hand-written minimal wikitext snippets, one complication per test |
| `test_sections.py` | Tier 4 heading stack, including a heading-shaped line inside a table |
| `test_fetch.py` | Tier 1 with `requests` mocked. User-Agent asserted. Retry and `Retry-After` asserted. |
| `test_client.py` | Tier 5 end to end, fixture XML fed through a mocked transport |
| `test_server.py` | Tier 6 tool registration and passthrough |
| `test_fixtures.py` | The Tier 2/3/4 acceptance criteria, run against real fixtures |

## 4. Property tests

Optional, `hypothesis`. Two properties worth it:

1. Every parsed table is rectangular. No row length differs from the width.
2. The inline cleaner never emits `[[`, `]]`, `{{`, `}}`, `<ref`, or `<!--`.
3. Unit conversion round-trips: converting X to canonical and back lands within
   the stated rounding tolerance.

## 5. CI

GitHub Actions, on push and pull request:

- Python 3.10, 3.11, 3.12, 3.13 matrix.
- `ruff check`, `ruff format --check`.
- `mypy wikipedia_tables_mcp`.
- `pytest -m "not live"` with coverage.

Coverage floor: 85% on `wikipedia_tables_mcp/wikitext/`. That package is the part
where a silent bug produces a wrong car specification.

## 6. Manual verification against reality

Before the first release, run the parser over ~20 real car articles and diff the
extracted power and torque figures against the rendered Wikipedia pages by hand.
The template resolver's correctness cannot be proven by unit tests alone,
because the risk is a plausible wrong number, not a crash.

Run this pass with `cache_dir` set, so the 20 articles are fetched once and every
re-run of the parser during diagnosis costs zero requests.

Pay specific attention to every cell where the authored unit was not kW, Nm, or
cc. Those are the cells where this project now performs arithmetic, and a
transposed constant would produce a plausible wrong number.

Record the result in `docs/verification-log.md`.
