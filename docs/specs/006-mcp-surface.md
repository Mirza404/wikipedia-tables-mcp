# 006 — Tier 6: MCP server surface

Module: `special_export_mcp/server.py`. Optional extra: `pip install
special-export-mcp[mcp]`.

**This is the product.** Everything below Tier 6 exists to serve it.

The server is a thin adapter: no fetch logic, no parse logic. It constructs one
`SpecialExportClient` and calls it.

The MCP SDK is async at the transport layer. Tool handlers call the synchronous
client directly. At this request volume — a consumer's loading phase is roughly
50 titles spread over weeks — that is correct and needs no thread pool.

## 1. Transport

- `stdio` (default) and `sse`, matching the convention `wikipedia-mcp` uses, so
  an existing MCP host configuration needs no new concepts.
- Entry point: `special-export-mcp` console script.

```
special-export-mcp --transport stdio --language en --contact you@example.com
```

CLI flags map one to one onto `SpecialExportClient` constructor arguments.

## 2. Tools

### `get_page_tables`

```json
{
  "title": "Volkswagen Golf Mk4",
  "section_filter": null,
  "table_class": null,
  "max_tables": null
}
```

Returns the Tier 5 dict, JSON-serialized.

The tool description shown to the model must explicitly say that `warnings`
are data-quality controls. On `ambiguous_row_alignment`, the model must not
trust positional field assignments or silently repair the row. It may recover
only explicitly labelled facts from the returned evidence, call `get_wikitext`
for nearby raw source, or inspect the cited page as a bounded fallback. Anything
still inferred stays `null` or pending review, with recovery provenance. This
requirement is specified in [`docs/data-integrity.md`](../data-integrity.md).

`section_filter` is an optional case-insensitive substring matched against the
table's `section` breadcrumb. `"engines"` returns only engine tables from a
multi-generation article. This exists because a full car article can return many
tables and blow up an LLM context window.

### `get_pages_tables`

Same, with `"titles": ["A", "B"]`, capped at the Tier 1 batch limit of 20.

This is the tool a bulk loading phase uses. 50 models is 3 calls.

### `get_wikitext`

```json
{"title": "Volkswagen Golf Mk4", "section": null}
```

Returns raw wikitext. Optional `section` returns only the wikitext under a
heading whose breadcrumb matches. Truncated to a `max_chars` default of 100,000
with an explicit `truncated` flag.

Rationale for exposing raw wikitext at all: when the table parser fails on a new
article shape, an interactive session needs to see the source to diagnose it.

### `list_page_sections`

```json
{"title": "Volkswagen Golf Mk4"}
```

Returns the heading tree with each heading's breadcrumb and a count of tables
directly under it. Cheap, and it lets a host pick a `section_filter` before
pulling a large payload.

Decision to confirm (Tier 8, Q5): is `list_page_sections` wanted in v1, or is it
scope creep. Proposal: include it. It is ~20 lines over Tier 4's existing
heading stack and it is what makes `section_filter` usable.

### Language boundary — decided in this PR

**Decision by the project owner during the Tier 6 PR review:** MCP tools do not
accept a per-call `language` argument. The earlier JSON examples that included
`"language": "en"` were inconsistent with the project's settled scope and have
been corrected as part of this PR.

This decision was reached by deduction from the existing specifications:

1. Tier 0 defines English Wikipedia as the v1 boundary because the bounded
   template registry is English-specific.
2. Tier 8 Q9 records English-only support as decided, likely permanently.
3. Tier 6 constructs one `SpecialExportClient` and deliberately remains a thin
   adapter. Wikipedia language is therefore process configuration, not a value
   that changes independently on each tool call.

The CLI-level `--language` option remains because the underlying client already
supports constructing a process against another Wikipedia host, and retaining
that escape hatch costs nothing. It does **not** make non-English parsing a
supported MCP capability: other Wikipedias are not covered by the template
registry, fixtures, verification, or data-integrity guarantees. A deployment
that changes `--language` knowingly opts outside the supported v1 contract.

## 3. Response size

MCP responses go into an LLM context. Apply Tier 2's bounds, and additionally:

- Default `max_tables` for the MCP path is **10**, not 50. The library default
  stays 50. A host can raise it per call.
- Truncation is always reported, never silent.

## 4. What is deliberately not a tool

- No search. `wikipedia-mcp` does that. This server takes known titles.
- No summary or extract.
- No write operations.

## 5. Acceptance criteria

1. The server starts on stdio and lists exactly the tools above.
2. `get_page_tables` on the Golf Mk4 fixture returns the same dict the library
   returns, with no extra transformation.
3. Removing the `mcp` package breaks only `server.py`, never `client.py`. Proven
   by a test that imports the client with `mcp` absent from `sys.modules`.
