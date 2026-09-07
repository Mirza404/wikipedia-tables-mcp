# Fixtures

Full, unmodified MediaWiki export XML. Committed so tests never hit the network.

| File | Source URL | Fetched |
|---|---|---|
| `volkswagen_golf_mk4.xml` | https://en.wikipedia.org/wiki/Special:Export/Volkswagen_Golf_Mk4 | 2026-09-05 |
| `skoda_octavia.xml` | https://en.wikipedia.org/wiki/Special:Export/%C5%A0koda_Octavia | 2026-09-06 |

`Skoda Octavia` (no diacritic) is itself a redirect stub to `Škoda Octavia`;
the fixture is fetched under the real, diacritic title directly. Tier 4's
main test: repeated `Engines` tables under different generation headings,
and generation headings that carry `<span class="anchor">` markup before
the visible title.

Refetch:

```bash
curl -s -A "special-export-mcp/0.1 (https://github.com/Mirza404/special-export-mcp)" \
  "https://en.wikipedia.org/wiki/Special:Export/Volkswagen_Golf_Mk4" \
  -o tests/fixtures/volkswagen_golf_mk4.xml

curl -s -A "special-export-mcp/0.1 (https://github.com/Mirza404/special-export-mcp)" \
  "https://en.wikipedia.org/wiki/Special:Export/%C5%A0koda_Octavia" \
  -o tests/fixtures/skoda_octavia.xml
```

Articles change. Assert on structural invariants, not byte-exact output.
See `docs/specs/007-testing.md`.
