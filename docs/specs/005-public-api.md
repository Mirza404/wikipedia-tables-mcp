# 005 — Tier 5: public Python API

Module: `wikipedia_tables_mcp/client.py`

This is the core the MCP server wraps. It is importable, but the MCP server in
Tier 6 is the supported surface. Synchronous throughout.

## 1. Class

```python
from wikipedia_tables_mcp import SpecialExportClient

client = SpecialExportClient(
    language="en",                  # -> https://en.wikipedia.org
    base_url=None,                  # overrides language entirely, for other wikis
    user_agent=None,                # full override
    user_agent_contact=None,        # contact segment only
    timeout=(5, 30),
    max_retries=3,
    min_request_interval=1.0,
    cache_dir=None,                 # off by default. Dev aid. See 001 section 7.1
    strict=False,                   # unknown templates raise instead of warn
    table_class=None,               # e.g. "wikitable" to filter
    limits=None,                    # Limits(max_tables=..., ...) from Tier 2 §4
)
```

The constructor makes no network call.

## 2. Methods

```python
client.get_page_tables(title: str) -> PageResult
client.get_pages_tables(titles: Sequence[str]) -> list[PageResult]
client.get_wikitext(title: str) -> str          # Tier 1 escape hatch
client.get_page_tables(title, refresh=True)     # bypass and overwrite cache
client.close() -> None                          # closes the requests.Session
```

`SpecialExportClient` is also a context manager.

## 3. Return shape

The handoff fixes the core contract. This spec keeps it exactly, and adds
optional keys only. Every added key is additive, so the consumer's existing
`result["exists"] / result["tables"] / result["error"]` code keeps working.

```python
{
  "exists": bool,
  "tables": [
    {
      "headers": ["Model", "Year", "Engine", "Code", "Displ.", "Power", "Torque"],
      "rows": [
        ["1.4", "1998–2004", "I4 16V", "AHW/AXP/BCA/...", "1390 cc",
         "55 kW at 5,500 rpm", "128 Nm at 3,300 rpm"],
        ...
      ],
      "section": "Engine choices > Golf and Jetta",
      # --- additive, all optional for the consumer ---
      "section_path": ["Engine choices", "Golf and Jetta"],
      "caption": None,
      "index": 0,
      "parent_table_index": None,
      "truncated": False,
      "warnings": [ ... ],
    },
  ],
  "error": None,          # str when exists is False
  # --- additive ---
  "requested_title": "Volkswagen Golf Mk4",
  "resolved_title": "Volkswagen Golf Mk4",
  "page_id": 1234,
  "revision_id": 5678,
  "revision_timestamp": "2026-08-30T11:22:33Z",
  "warnings": [ ... ],    # union of all table warnings
}
```

`warnings` are part of the data-integrity contract, not optional debugging
output. A consumer must not persist positionally mapped values from a row with
`kind="ambiguous_row_alignment"`. It may import the other rows and quarantine
only the warned one. See [`docs/data-integrity.md`](../data-integrity.md).

Decision to confirm (Tier 8, Q1): `dict` versus dataclass. Proposal: return
**plain dicts**, because the handoff's stated consumer contract is a dict and
the MCP layer must serialize to JSON anyway. Ship dataclasses internally and
convert at the boundary, so the internal code is typed and the public shape
stays a dict. If the user prefers dataclasses with a `.to_dict()`, that is a
small change — say so at review.

## 4. Errors

```
SpecialExportError                 (base)
├── ConfigurationError
├── FetchError
│   └── RateLimitError
├── ExportParseError
├── PageNotFoundError
├── WikitextParseError
└── TemplateResolutionError
```

Every error carries `.message`, and where relevant `.title`, `.status_code`,
`.raw`, `.table_index`, `.row`, `.column`.

**Policy at the client boundary:**

- A missing page is **not** an exception. `exists=False`,
  `error="Page not found: <title>"`, `tables=[]`.
- A network or HTTP failure **is** an exception (`FetchError`,
  `RateLimitError`). The caller must be able to tell "Wikipedia says this car
  does not exist" from "we could not reach Wikipedia". Collapsing both into
  `exists=False` would let `car-dealer` cache an outage as a fact.
- A parse failure on an existing page is **not** an exception in
  `strict=False`. It yields the tables that did parse, plus warnings.

In `get_pages_tables`, a per-title failure yields a `PageResult` with
`exists=False` and `error=<message>` for that title, so one bad title does not
sink the batch. A transport-level failure of the whole request still raises.

## 5. Logging

Standard `logging`, logger name `wikipedia_tables_mcp`. No handler configured by
the library. `INFO` for each fetch, `DEBUG` for URL and cache hits, `WARNING`
for retries and for template warnings.

## 6. Acceptance criteria

1. `SpecialExportClient().get_page_tables("Volkswagen Golf Mk4")` returns
   `exists=True` and at least one table whose `section` is
   `"Engine choices > Golf and Jetta"`.
2. A nonexistent title returns `exists=False` and a non-empty `error`, and does
   not raise.
3. A simulated HTTP 500 after retries raises `FetchError`, not `exists=False`.
4. `import wikipedia_tables_mcp` works with only `requests` installed — no `mcp`
   package needed.
5. With `cache_dir` set, two identical calls produce one HTTP request, and a
   third call in a fresh process also produces none.
