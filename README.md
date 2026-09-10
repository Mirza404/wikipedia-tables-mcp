# wikipedia-tables-mcp

Standalone MCP server. Fetches Wikipedia page wikitext through
`Special:Export` and parses wikitables out of it into structured rows, with
section ancestry, unit conversion, and machine-readable data-integrity
warnings.

See [docs/specs](docs/specs/README.md) for the full design, and
[docs/verification-log.md](docs/verification-log.md) for the manual
verification pass run against 20 real car articles before release.

## Install

Not published to PyPI. Install from git:

```bash
pip install git+https://github.com/Mirza404/wikipedia-tables-mcp.git
```

With the MCP server extra:

```bash
pip install "wikipedia-tables-mcp[mcp] @ git+https://github.com/Mirza404/wikipedia-tables-mcp.git"
```

## Usage: as an MCP server

```bash
wikipedia-tables-mcp --transport stdio --contact you@example.com
```

Add it to an MCP host's config the same way as any stdio server, for
example Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "special-export": {
      "command": "wikipedia-tables-mcp",
      "args": ["--contact", "you@example.com"]
    }
  }
}
```

Four tools: `get_page_tables`, `get_pages_tables` (up to 20 titles),
`get_wikitext` (raw source, optionally scoped to one section),
`list_page_sections` (the heading tree with a table count per heading, to
pick a `section_filter` before pulling a large payload). See
[docs/specs/006-mcp-surface.md](docs/specs/006-mcp-surface.md) for the full
tool schemas.

## Usage: as a Python library

```python
from wikipedia_tables_mcp import SpecialExportClient

with SpecialExportClient(user_agent_contact="you@example.com") as client:
    result = client.get_page_tables("Volkswagen Golf Mk4")
```

`result["tables"][0]` for that real article's engine table looks like:

```python
{
    "headers": ["Model", "Year", "Engine", "Code", "Displ.", "Power", "Torque"],
    "rows": [
        ["1.4", "1998–2004", "I4 16V", "AHW/AXP/BCA/AKQ/APE/AUA",
         "1390 cc", "55 kW at 5,500 rpm", "128 Nm at 3,300 rpm"],
        # ... every unit is authored-verbatim; a non-canonical one gets its
        # kW/Nm/cc equivalent appended, e.g. "115 PS (85 kW) at 5,200 rpm"
        ...
    ],
    "section": "Engine choices > Golf and Jetta",
    "section_path": ["Engine choices", "Golf and Jetta"],
    "caption": None,
    "index": 0,
    "parent_table_index": None,
    "truncated": False,
    "warnings": [],
}
```

## Data integrity

Wikipedia can contain structurally broken tables. Results therefore carry
machine-readable `warnings`; consumers and AI agents must inspect them before
persisting positional row data. Ambiguous rows are returned as evidence but
must be quarantined rather than silently corrected. See
[Data integrity and recovery](docs/data-integrity.md) for the required
fallback policy and a real example found in the Golf Mk4 article itself.

## Why

`action=parse` (the live rendering API used by `wikipedia-mcp`) has a low
anonymous rate limit and was observed to enter an hours-long undocumented
lockout. `Special:Export` is a documented, export-style alternative that
was unaffected. See
[docs/specs/000-overview.md](docs/specs/000-overview.md) for the full
rationale.

## Scope

English Wikipedia only (see [docs/specs/000-overview.md](docs/specs/000-overview.md)
section 7 and [docs/specs/008-milestones.md](docs/specs/008-milestones.md) Q9):
the bounded `{{convert}}`/`{{cvt}}` template registry that does the unit
conversion is English-specific. `bhp` is treated as mechanical `hp` -- an
approximation of editorial intent, not of arithmetic, since the two are used
interchangeably on Wikipedia.

## License

MIT
