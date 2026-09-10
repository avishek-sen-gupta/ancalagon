# Two web research tools

## The problem

An agent investigating a data structure sometimes needs something the workspace does not contain:
what a wire format means, what a library actually does, what an error string comes from. Today it
has no way to ask. Every tool in the harness reads the local filesystem, and the only process that
opens a socket is the LiteLLM adapter talking to the model endpoint.

The gap is narrow and the fix should be too. Two tools: one that searches, one that fetches a page
and writes its prose to disk.

## What this is not

**Not a research agent.** No role, no budget, no synthesis step, no report contract. Two tools that
a role may name in its `tools` list, and nothing else. If a research loop is wanted later it is
built the way every other loop here is built — out of a role and a delegation — not out of these.

**Not a general HTTP client.** `fetch_url` takes an `https` URL and returns the article text on that
page. It is not a way to call an API, post a form, or carry a header.

**Not a new output mechanism.** Every tool already writes its full output to
`<task_dir>/tools/NNNN-<tool>.txt` through `ToolContext.result` and returns the model a
`summary_chars` preview plus the path. Answers already arrive in files. These two tools inherit
that and add nothing.

## Where the answers already live

Worth stating plainly, because it removes a tool that would otherwise look necessary.

`run_dir` is `write_root/runs/r_<timestamp>` (`cli.py:51`), and `Workspace.from_config` appends
`write_root` to the read roots (`workspace/workspace.py:31`). So a tool's output file is inside the
agent's own read scope the moment it is written. Anything `fetch_url` puts on disk is immediately
reachable by `read_file` — which returns numbered lines from an offset — by `ripgrep`, and by
`convert_document`.

Pulling a named section out of a fetched page therefore needs no new tool. `ripgrep` finds the
heading, `read_file` reads from that offset. A parser tool for that job would be a third way to do
what two tools already do.

## Egress

The worker runs under `fence` (`sandbox/fence.py`), whose policy is written once per run in
`sandbox_of` (`cli.py:228`) and wraps every worker the run spawns. Its `allowedDomains` today holds
only the model endpoint. Web fetching cannot happen without widening it, and widening it is a
run-level act: every tool in that worker gains the same egress, `shell` included, in a process whose
read roots may contain a codebase under analysis.

Measured against the installed `fence`:

| policy | `example.com` | `en.wikipedia.org` |
|---|---|---|
| `["*"]` | 200 | reachable |
| `["example.com"]` | 200 | blocked |
| `["wikipedia.org"]` | — | blocked |
| `["*.wikipedia.org"]` | — | reachable |

Two things follow. `*` really does reach everything, so an allowlist is not a safety property unless
someone chooses to make it one. And matching is strict — a bare `wikipedia.org` does not cover
`en.wikipedia.org`, so a hand-written list needs `*.` prefixes to be usable at all.

**The decision: the operator writes the list.** A `[web]` table with `allowed_domains`, merged with
`[model].allowed_domains` into the fence policy. `["*"]` for open research, a named list for a
contained run. The config file is then the record of what a run could reach.

The rejected alternative was to have the code write `*` whenever a role names a web tool. It saves a
config field and costs the property that matters: a run's egress would be implied by a role's tool
list rather than stated, and `shell` in that worker would gain it silently.

Fetching from outside the fence — the worker posting a request the unfenced supervisor services —
was also considered. It preserves worker containment exactly. It was rejected as too much machinery
for the first version: a new supervisor responsibility and a round trip per page, to protect a
worker whose operator has already decided to let it read the web.

## Search

No account, no credential, no environment variable. `lite.duckduckgo.com` answers a POST with a plain
result table:

```html
<a rel="nofollow" href="https://pydantic.dev/..." class='result-link'>JSON | Pydantic Docs</a>
<td class='result-snippet'>JSON Json Parsing API ...</td>
```

The hrefs are direct — there is no `uddg=` redirect wrapper to unpick — so parsing is an xpath over
`result-link` and `result-snippet`. `lxml` arrives with trafilatura, so no regex is involved and no
dependency is added for it.

Brave and Tavily were rejected for requiring an account. Public SearXNG instances were rejected
because `format=json` is disabled on them, leaving HTML scraping with none of DuckDuckGo's
stability. The `ddgs` library was rejected for a subtler reason than its dependencies: it aggregates
several backends, so the domains a run reaches would change when it rotates a backend, without the
config changing. One hand-parsed endpoint keeps the allowlist honest and the breakage loud.

The cost accepted here is that DuckDuckGo may change its markup and the parse will break. It breaks
in one file, with a test that names it.

## Fetching

Measured on one real page (`en.wikipedia.org/wiki/Reverse_engineering`):

| form | size | content |
|---|---|---|
| raw HTML | 385 KB | everything |
| `pandoc -t markdown` | 490 KB | *larger than the input* — div fences and attributes |
| `pandoc -t plain` | 83 KB | prose plus nav menus, language lists, edit links |
| trafilatura | 50 KB | the article, starting at its title |

Markdown is disqualified by its own output size. The real choice was between reusing the `pandoc`
that `convert_document` already shells out to, and adding trafilatura. trafilatura wins on what the
agent reads, not on bytes: the pandoc output makes an agent walk through a list of Wikipedia
language links on every page before reaching a sentence of the article.

**`fetch_url` extracts and writes the article text.** The raw body is not kept.

When extraction yields nothing — a PDF, a JSON endpoint, an app shell with no server-rendered
content — the tool fails through `ctx.failure`, naming the URL, the status and the content-type.
Nothing is written. The two alternatives were both rejected for lying: writing the raw body reports
success for work the tool did not do, and falling back to pandoc leaves the agent unable to tell
which extractor produced what it is reading.

This makes the first version HTML-only, and non-HTML payloads never reach disk. That is a known
limit, not an oversight. If feeds or XML APIs turn out to matter, the fix is upstream of any parser
— write the body when the content-type is not HTML — plus a `query_xml` tool over `xmllint --xpath`
mirroring what `query_json` does with `jq`. `xmllint` is already on PATH. It is not built now because
no run has asked for it.

## The port

A new bottom-layer leaf package `ancalagon/web/`, beside `fs` and `env`:

- `web_client.py` — `WebClient` protocol, `get(url: str) -> Page`
- `page.py` — frozen `Page(url, status, content_type, body)`, where `url` is the final URL after
  redirects
- `real_web_client.py` — the only place `httpx` is called; timeout and size cap live here
- `fake_web_client.py` — responses scripted by URL, so unit tests are offline
- `extracted.py` — `extracted(html: str) -> str`, the only place trafilatura is called, in the shape
  of `text/decoded.py`

The tools receive a `WebClient` at construction in `worker.py:available_tools`, the way `ReadFile`
receives a `Clock`. They never import the real adapter.

Import-linter needs `ancalagon.web` added to the bottom layer alongside `env : fs`, and to the
"sibling leaves are independent" contract.

## The tools

`ancalagon/tools/web/`:

**`web_search`** — `SearchArgs(query: str, count: int = 10)`. Parses the result rows into a frozen
`Result(rank, title, url, snippet)` and writes them one per line as `rank. title`, the URL, then the
snippet. A non-200 is a failure naming the status.

Results are written as readable lines rather than JSONL. `ripgrep` offers a `structured` flag for
its JSON form; this does not, because the agent's next move after a search is always `fetch_url` on
one of the URLs, never a machine parse.

**`fetch_url`** — `FetchArgs(url: str)` with `pattern=r"^https://"` on the field. The constraint is
on the model's schema, so it is stated before the call rather than refused inside `run`.

Both return through `ctx.result`.

## Testing

No unit test touches the network. `FakeWebClient` is scripted by URL, in the shape `FakeFileSystem`
and `FakeEnvironment` already establish.

The DuckDuckGo fixture is a trimmed snapshot of the real markup, three results' worth, as a constant
in the test rather than a file — there is no `tests/fixtures/` directory today and one snapshot does
not justify creating one. Its query is a public library's API name, so no identifier from any
codebase under analysis enters a tracked artifact.

Five unit tests, one per behaviour:

- `extracted()` keeps the prose and drops the navigation
- `web_search` turns the fixture into ranked results on disk, with a truncated summary and a path
- `web_search` reports a non-200 as a failure naming the status
- `fetch_url` writes the article text on success, and fails naming url, status and content-type when
  extraction is empty
- `bind_tool` refuses a non-`https` URL — proving the schema constraint fires, rather than a check
  inside `run`

One gated integration test hits the real endpoint, skipped unless `ANCALAGON_WEB=1`, matching the
`ANCALAGON_LIVE` gate at `tests/integration/test_end_to_end.py:157`.

Each new test is mutation-checked before it is trusted, and verification runs the whole
`tests/integration`, not only the new file.

## Units of work

1. `ancalagon/web/` — port, `Page`, real and fake clients, `extracted()`; `trafilatura` added to
   `pyproject.toml`
2. `[web] allowed_domains` — config field, fence merge in `sandbox_of`, import-linter edits
3. `web_search` — tool, fixture, wiring in `available_tools`
4. `fetch_url` — tool, wiring
5. Docs — `ancalagon.example.toml` gains the `[web]` table, the README tool catalogue gains two rows
