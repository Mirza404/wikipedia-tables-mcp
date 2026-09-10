# 001 — Tier 1: fetch layer

Input: one or more page titles. Output: raw wikitext per title.

Module: `wikipedia_tables_mcp/fetch.py`

## 1. Endpoint

Two request shapes exist. Both are supported.

### 1.1 Single title, path form

```
GET https://en.wikipedia.org/wiki/Special:Export/<Title_With_Underscores>
```

Verified working with a plain `curl`. Use this for one title.

### 1.2 Multiple titles, POST form

```
POST https://en.wikipedia.org/w/index.php?title=Special:Export&action=submit
Content-Type: application/x-www-form-urlencoded

pages=<Title1>%0A<Title2>%0A<Title3>&curonly=1&wpDownload=0
```

`pages` is a newline-separated list. `curonly=1` returns only the current
revision, not the full history. Use this for batches.

Batch size cap: **20 titles per POST**. Above 20, split into several POSTs.

This is a primary path, not an optimization. The peak load this project must
handle is a consumer's loading phase — roughly 50 titles in a short window. At
20 per request that is 3 requests instead of 50, which keeps a burst far below
any plausible limit rather than probing it.

## 2. Title normalization

- Replace spaces with underscores for the path form.
- Percent-encode the result with `urllib.parse.quote(title, safe='')` after
  underscore substitution, so `Škoda Octavia` and `AC/DC` survive.
- For the POST form send the title with spaces, not underscores. MediaWiki
  accepts both; spaces are the documented form for the `pages` field.
- Do not case-fold. MediaWiki capitalizes only the first letter itself.

## 3. User-Agent

Wikimedia policy requires an identifying User-Agent. Follow the same format
`wikipedia-mcp` uses:

```
wikipedia-tables-mcp/<version> (https://github.com/Mirza404/wikipedia-tables-mcp)
```

The contact segment is overridable through:

1. constructor argument `user_agent_contact`, then
2. environment variable `WIKIPEDIA_TABLES_CONTACT`, then
3. the repository URL above as default.

A caller may replace the whole string with `user_agent=`. If a caller passes an
empty User-Agent, raise `ConfigurationError`. Never send a blank or default
`python-requests/x.y` agent.

## 4. Redirects

`Special:Export` does not follow article redirects, and no request parameter
makes it. Corrected 2026-09-06: the original draft of this section claimed
`&redirects=1` resolves a redirect server-side. Verified live against
`https://en.wikipedia.org/wiki/Special:Export/UK` (a stable redirect to
`United Kingdom`): the response is byte-identical with and without that
parameter. A requested redirect page always comes back **as itself** --
`<title>UK</title>`, `<text>#REDIRECT [[United Kingdom]]</text>` -- never its
target's content. Do not add `&redirects=1` to a request; it does nothing.

Resolving a redirect is therefore a second real request. Detect
`#REDIRECT [[Target]]` (case-insensitive, optional leading colon) at the
start of the fetched wikitext, then fetch `Target`. Follow up to
`MAX_REDIRECT_HOPS` (5) times to bound a redirect chain; stop and return the
last fetched page as-is if the limit is hit. Record both the original and the
final title:

```python
{"requested_title": "Golf Mk4", "resolved_title": "Volkswagen Golf Mk4"}
```

This applies to both the single-title and the batch path. In a batch, a page
that comes back as a redirect stub gets its own follow-up single-title
request after the batch response is parsed.

## 5. Response parsing

The response is MediaWiki export XML, namespace
`http://www.mediawiki.org/xml/export-0.11/`.

Path to the wikitext:

```
mediawiki > page > revision > text
```

Verified in the fixture: one `<page>` per requested title, one `<text>` per
revision, whole article body inside it, XML-escaped (`&lt;ref`, `&lt;!--`).

Parse with `xml.etree.ElementTree`. It unescapes entities on read, so the
`.text` value is already real wikitext. Do not unescape a second time.

Match elements by local name, ignoring the namespace prefix, so an export
schema bump from 0.11 to 0.12 does not break the parser.

Also capture, per page, for the client result and for debugging:

- `<title>`
- `<id>` (page id)
- `<revision><id>` (revision id)
- `<revision><timestamp>`

### 5.1 Missing pages

A title that does not exist produces **no** `<page>` element for it. There is no
error element. Detect a missing page by requested-title absence in the parsed
set, matched case-insensitively and with underscores normalized to spaces.

Result for that title: `exists=False`, `error="Page not found: <title>"`.

## 6. HTTP behaviour

- Timeout: connect 5 s, read 30 s. Both overridable.
- Retry: at most 3 attempts, on HTTP 429, 500, 502, 503, 504, and on connection
  or read timeouts. Exponential backoff 1 s, 2 s, 4 s, with full jitter.
- Honour a `Retry-After` header when present. It overrides the backoff.
- Never retry on 400, 403, 404. Those are caller or policy errors.
- `gzip` accepted (`requests` does this by default).

## 7. Politeness and caching

- Client-side minimum interval between requests, default 1.0 s, configurable
  through `min_request_interval`. This is a self-imposed floor, not a server
  rule. It keeps burst behaviour well under any limit.

### 7.1 On-disk cache: a development and burst safety net

Scope, stated plainly: **caching is not a production feature.** A consumer
fetches a given model once in its life and stores the result in its own
database. Over the lifetime of a deployment the cache saves close to nothing.

It earns its place for two narrower reasons:

1. **Parser development.** Re-running the parser over the same fixture articles
   hundreds of times is exactly the request pattern that got `action=parse`
   locked out for hours. With a cache directory set, that cost is paid once.
2. **Burst-phase recovery.** A consumer's loading phase pulls ~50 models. If the
   parser has a bug and 30 are already fetched, a re-run must not refetch those
   30.

Design, kept deliberately small:

- Constructor argument `cache_dir: str | Path | None`. `None` disables it.
  **Default is `None`.**
- No TTL and no expiry. The cached wikitext of a discontinued car does not go
  stale in any way this project cares about.
- Layout: one file per page, `<cache_dir>/<sha256(resolved_title)[:16]>.json`,
  holding the wikitext plus `requested_title`, `resolved_title`, `page_id`,
  `revision_id`, `revision_timestamp`, and `fetched_at`.
- A cache hit skips the HTTP request and the `min_request_interval` wait.
- `refresh=True` on a call forces a refetch and overwrites the entry.
- Plain JSON. Readable, hand-editable, safe to delete at any time.

No in-process cache. One cache layer is enough, and a second is another place
for a stale value to hide.

## 8. Errors raised by this layer

All inherit `SpecialExportError`. See `errors.py`, Tier 5 section 4.

| Error | Cause |
|---|---|
| `ConfigurationError` | Empty or invalid User-Agent, bad base URL |
| `FetchError` | Network failure, or non-retryable HTTP status |
| `RateLimitError` | HTTP 429 after retries are exhausted |
| `ExportParseError` | Response is not valid export XML, or has no `<text>` |
| `PageNotFoundError` | Title absent from the response |

`PageNotFoundError` is **not** raised by the high-level client. There it becomes
`exists=False` plus `error`. It exists so the fetch layer can be used directly.

## 9. Acceptance criteria

1. `fetch_wikitext("Volkswagen Golf Mk4")` returns a string containing
   `==Engine choices==` and `{| class="wikitable"`.
2. `fetch_many(["Volkswagen Golf Mk4", "Skoda Octavia"])` issues one POST and
   returns two entries.
3. A nonexistent title returns a missing-page marker, not an exception, from
   `fetch_many`.
4. Every outgoing request carries the compliant User-Agent. Asserted in tests
   against a mocked transport.
5. No test in CI makes a live network call.
6. With `cache_dir` set, a second call for the same title makes zero HTTP
   requests, proven against a mocked transport that fails on any second call.
