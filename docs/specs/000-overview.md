# 000 — Overview and architecture

Status: DRAFT — awaiting user review. No implementation until approved.

## 1. Purpose

`wikipedia-tables-mcp` is a standalone MCP server. It fetches
Wikipedia page **wikitext** through `Special:Export` and parses wikitables out
of it into structured rows.

It is a new project. It is not a fork of, an addition to, or a dependency of
`wikipedia-mcp` (upstream `Rudra-ravi/wikipedia-mcp`, fork `Mirza404/wikipedia-mcp`).
No code is shared. No file in those repos is touched.

Repository: https://github.com/Mirza404/wikipedia-tables-mcp

## 2. Why a separate fetch path

`wikipedia-mcp` reads pages through `action=parse`, the live HTML rendering API.

Observed problems with `action=parse`:

- Anonymous rate limit is 10 requests per minute
  (mediawiki.org/wiki/Wikimedia_APIs/Rate_limits). A policy-compliant
  User-Agent should raise this to 200/min. That raise was never confirmed in
  practice.
- During real use the endpoint entered an undocumented lockout. The lockout
  lasted many hours. It did not clear when the request came from a different
  real IP address.

Verified on 2026-09-05:

- `https://en.wikipedia.org/wiki/Special:Export/Volkswagen_Golf_Mk4` returns
  HTTP 200 and 45,758 bytes of MediaWiki export XML to a plain `curl`.
- `Special:Export` was not affected by the block that held `action=parse`.
- Wikimedia documentation (Help:Export, dumps.wikimedia.org) recommends
  export-style access over the live rendering API for bulk access to known
  titles. That is exactly this use case.

`Special:Export` is therefore the foundation of this project.

## 3. What this is, and what it is not

This is a **standalone MCP server**. It is not a support library for any one
consumer, and it is not designed around any one consumer's runtime.

`car-dealer` (an OLX bargain-car finder) is the first *user* of the server, not
a partner project. Its usage profile shapes the performance requirements, and
nothing else:

- A loading phase over the first weeks, feeding in roughly 50 car models.
- Usage then decays toward zero as models accumulate.
- Extracted specifications land in `car-dealer`'s own **database**, permanently.
  This project does not persist anything on a consumer's behalf.
- Once loaded, this server leaves the hot path. Real-time data for that
  application comes from OLX, which is entirely out of scope here.

Two consequences, and only two:

1. **Bursts matter more than steady throughput.** Fetching 50 titles in a short
   window is the peak load this project must handle politely. The batch POST
   form is a primary path, not an optimization. See 001 section 1.2.
2. **Nothing needs long-term storage here.** The consumer's database is the
   permanent record. This project holds no durable state of its own.

That repository is out of scope for this task. Nothing in it is modified here.

## 4. Structure: thin MCP adapter over a plain core

The MCP server is the product. `SpecialExportClient` is the core it wraps:

1. `SpecialExportClient` — a plain, synchronous Python class holding all fetch,
   parse, and error logic. No MCP dependency on its import path.
2. `server.py` — MCP tool definitions. Schema and serialization only.

Rationale: `wikipedia-mcp` proves this split with its `WikipediaClient`. Keeping
the core free of protocol concerns is what makes it unit-testable without a
running server. The class stays importable because that costs nothing, but the
server is the supported surface, and the design does not bend to accommodate a
direct-import consumer.

**Runtime: synchronous throughout.** The MCP SDK is async at the transport
layer. It wraps a blocking fetch without difficulty at this request volume. No
async client, now or planned.

Consequence: the MCP server is an optional extra. The core install has
`requests` only. Not published to PyPI — install from git:

```bash
pip install git+https://github.com/Mirza404/wikipedia-tables-mcp.git
```

## 5. Module layout (proposed)

```
wikipedia_tables_mcp/
  __init__.py            # version, public exports
  client.py              # SpecialExportClient — fetch + orchestrate + return
  fetch.py               # HTTP, User-Agent, retry, export XML unwrapping
  wikitext/
    tokenizer.py         # line classification of wikitext
    tables.py            # {| ... |} to headers/rows, rowspan/colspan
    sections.py          # heading stack, breadcrumb ancestry
    inline.py            # wikilinks, refs, comments, formatting, entities
    templates.py         # {{convert}} / {{cvt}} resolver + registry
  errors.py              # structured error types
  server.py              # MCP tool definitions (optional extra)
tests/
  fixtures/              # saved export XML, committed, never live-fetched in CI
```

## 6. Tiers

Each tier is a separate spec file. Each tier is independently testable and
independently useful. Build them in order.

| Tier | Spec | Delivers |
|---|---|---|
| 1 | [001-fetch.md](001-fetch.md) | Title to raw wikitext string |
| 2 | [002-table-parsing.md](002-table-parsing.md) | Wikitext to headers/rows grid |
| 3 | [003-inline-and-templates.md](003-inline-and-templates.md) | Clean cell text |
| 4 | [004-section-ancestry.md](004-section-ancestry.md) | Breadcrumb per table |
| 5 | [005-public-api.md](005-public-api.md) | `SpecialExportClient` contract |
| 6 | [006-mcp-surface.md](006-mcp-surface.md) | MCP tools |
| 7 | [007-testing.md](007-testing.md) | Fixtures, test strategy, CI |
| 8 | [008-milestones.md](008-milestones.md) | Build order, open questions |

## 7. Non-goals

- No rendering of wikitext to HTML.
- No general template expansion engine. Only a bounded registry (Tier 3).
- No full-text search, no summaries, no related-topic discovery. Those exist in
  `wikipedia-mcp`. This project fetches known titles.
- No write access to Wikipedia. Read only.
- No async API. Synchronous `requests`. The MCP SDK handles transport-level
  concurrency; nothing here needs to.
- English Wikipedia only. The `language` argument exists and costs nothing, but
  the template registry is English-only and stays that way.
- No PyPI publication.
- No support for non-Wikipedia MediaWiki wikis in v1, but the base URL is a
  constructor parameter so it is not designed out.

## 8. Language and runtime

- Python 3.10 or newer.
- Runtime dependency: `requests`.
- Optional extra `mcp`: the `mcp` SDK, for `server.py` only.
- No PyPI release. `pyproject.toml` is for dependencies and tool config only.
- Dev: `pytest`, `ruff`, `mypy`.
