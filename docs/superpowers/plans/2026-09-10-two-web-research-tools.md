# Two Web Research Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give an agent two tools — `web_search` and `fetch_url` — so it can search the web and read a page's article text, with both answers landing on disk like every other tool's.

**Architecture:** A new bottom-layer leaf package `ancalagon/web/` holds a `WebClient` protocol with a real `httpx` adapter and a scripted fake, plus `extracted()`, the single place trafilatura is called. Two tools in `ancalagon/tools/web/` receive the client by injection in `worker.py`, exactly as `ReadFile` receives a `Clock`. Egress is widened by an operator-written `[web] allowed_domains` merged into the fence policy.

**Tech Stack:** Python 3.13, pydantic, httpx (already a dependency), trafilatura (new), lxml (transitive, used in one file), pytest, Pyright strict, import-linter.

**Spec:** `docs/superpowers/specs/2026-09-10-two-web-research-tools-design.md`

## Global Constraints

- Pyright runs in strict mode and must report **zero** errors. `Any` is banned outright.
- Every generic is parameterised: `dict[str, int]`, never `dict`. No `object` annotations, no JSON-blob types.
- No comments except a **one-line header** on a module or class stating its purpose. No docstrings.
- All pydantic models are `frozen=True`. No mutation after construction.
- No `None` defaults, no `None` returns from non-`None` return types — use the null object pattern (`extracted()` returns `""`, never `None`).
- Fully qualified imports. One class per file. No static methods.
- No mocking. Use the injected fakes.
- Few tests, each covering a whole behaviour — not one test per assertion.
- Never put an identifier from a codebase under analysis into a tracked artifact. All fixtures use `example.com` / `example.org`.
- Verification per task: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit`. Before the **final** commit, also run the whole `uv run python -m pytest tests/integration` and `uv run lint-imports`.
- The pre-commit hook runs Black, the `Any`/`object` ban, import contracts, Pyright and the unit suite. A rejected commit means one of those failed.

---

### Task 1: The web port

**Files:**
- Create: `ancalagon/web/__init__.py`
- Create: `ancalagon/web/page.py`
- Create: `ancalagon/web/web_client.py`
- Create: `ancalagon/web/real_web_client.py`
- Create: `ancalagon/web/fake_web_client.py`
- Create: `ancalagon/web/extracted.py`
- Modify: `pyproject.toml` — add `trafilatura` to `dependencies`; add `ancalagon.web` to the layers contract and the independence contract
- Test: `tests/unit/test_web.py`

**Interfaces:**
- Consumes: `ancalagon.text.decoded.decoded` (existing: `decoded(raw: bytes) -> str`)
- Produces:
  - `Page(url: str, status: int, content_type: str, body: str)`, frozen
  - `WebClient` protocol: `get(self, url: str) -> Page` and `post_form(self, url: str, form: collections.abc.Mapping[str, str]) -> Page`
  - `RealWebClient()`, `FakeWebClient(pages: collections.abc.Mapping[str, Page])` with an `asked: list[tuple[str, dict[str, str]]]` record
  - `extracted(html: str) -> str` — returns `""` when nothing is extractable

- [ ] **Step 1: Add the dependency**

```bash
cd /Users/asgupta/code/ancalagon
uv add trafilatura
```

Confirm it landed in `[project].dependencies` in `pyproject.toml` alongside `httpx[socks]>=0.27`.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_web.py`:

```python
import pathlib

from ancalagon.web.extracted import extracted
from ancalagon.web.fake_web_client import FakeWebClient
from ancalagon.web.page import Page

ARTICLE = """
<html><head><title>A Title</title></head><body>
<nav><ul><li><a href="/edit">Edit this page</a></li><li><a href="/talk">Talk</a></li></ul></nav>
<article>
<h1>A Title</h1>
<p>The first paragraph explains the subject at enough length that an extractor treats it as the
main content of the page rather than as boilerplate around the edges of it.</p>
<p>The second paragraph continues that explanation, so the article carries more prose than the
navigation does, which is the signal the extractor decides on.</p>
</article>
<footer>Copyright notice belongs to nobody.</footer>
</body></html>
"""


def test_extraction_keeps_the_article_and_drops_the_navigation():
    text = extracted(ARTICLE)

    assert "The first paragraph explains the subject" in text
    assert "The second paragraph continues that explanation" in text
    assert "Edit this page" not in text
    assert "Copyright notice belongs to nobody." not in text


def test_extraction_of_a_page_with_no_prose_is_empty_rather_than_none():
    assert extracted("<html><body><div id='app'></div></body></html>") == ""


def test_the_fake_client_returns_scripted_pages_and_records_what_was_asked():
    page = Page(url="https://example.com/one", status=200, content_type="text/html", body="hi")
    client = FakeWebClient({"https://example.com/one": page})

    assert client.get("https://example.com/one") == page
    assert client.post_form("https://example.com/one", {"q": "a query"}) == page
    assert client.asked == [
        ("https://example.com/one", {}),
        ("https://example.com/one", {"q": "a query"}),
    ]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_web.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.web'`

- [ ] **Step 4: Write the port**

Create `ancalagon/web/__init__.py` (empty file).

Create `ancalagon/web/page.py`:

```python
# One HTTP response, as the harness sees it.
import pydantic


class Page(pydantic.BaseModel, frozen=True):
    url: str
    status: int
    content_type: str
    body: str
```

Create `ancalagon/web/web_client.py`:

```python
# Every HTTP request the harness makes, so that making one is an injected dependency.
import collections.abc
import typing

from ancalagon.web.page import Page


class WebClient(typing.Protocol):
    def get(self, url: str) -> Page: ...

    def post_form(self, url: str, form: collections.abc.Mapping[str, str]) -> Page: ...
```

Create `ancalagon/web/real_web_client.py`:

```python
# The only place httpx is called.
import collections.abc

import httpx

from ancalagon.text.decoded import decoded
from ancalagon.web.page import Page
from ancalagon.web.web_client import WebClient

TIMEOUT_S = 30.0
MAX_BYTES = 5_000_000
AGENT = "Mozilla/5.0 (compatible; ancalagon)"


def _page(response: httpx.Response) -> Page:
    return Page(
        url=str(response.url),
        status=response.status_code,
        content_type=response.headers.get("content-type", ""),
        body=decoded(response.content[:MAX_BYTES]),
    )


class RealWebClient(WebClient):
    def get(self, url: str) -> Page:
        with httpx.Client(follow_redirects=True, timeout=TIMEOUT_S) as client:
            return _page(client.get(url, headers={"User-Agent": AGENT}))

    def post_form(self, url: str, form: collections.abc.Mapping[str, str]) -> Page:
        with httpx.Client(follow_redirects=True, timeout=TIMEOUT_S) as client:
            return _page(client.post(url, data=dict(form), headers={"User-Agent": AGENT}))
```

Create `ancalagon/web/fake_web_client.py`:

```python
# Responses fixed at construction, so a test can say exactly what the web returned.
import collections.abc

from ancalagon.web.page import Page
from ancalagon.web.web_client import WebClient


class FakeWebClient(WebClient):
    def __init__(self, pages: collections.abc.Mapping[str, Page]):
        self.pages = dict(pages)
        self.asked: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str) -> Page:
        self.asked.append((url, {}))
        return self.pages[url]

    def post_form(self, url: str, form: collections.abc.Mapping[str, str]) -> Page:
        self.asked.append((url, dict(form)))
        return self.pages[url]
```

Create `ancalagon/web/extracted.py`:

```python
# The one place a page's HTML becomes the article's text.
import trafilatura


def extracted(html: str) -> str:
    return trafilatura.extract(html, include_links=False) or ""
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_web.py -v`
Expected: PASS, 3 tests.

If the first test fails on the exclusion assertions, print the actual output with `uv run python -c` is **not** allowed by the project guidelines — instead write a throwaway script into the scratchpad directory, run it with `uv run python <path>`, read the exact output, and **pin the exact expected string** in the test. Do not weaken the assertion to make it pass.

- [ ] **Step 6: Mutation-check the tests**

Break `extracted()` two ways and confirm a test fails each time:

1. Change it to `return html` — `test_extraction_keeps_the_article_and_drops_the_navigation` must fail on the `not in` assertions.
2. Change the `or ""` to a bare return — `test_extraction_of_a_page_with_no_prose_is_empty_rather_than_none` must fail.

Restore the correct implementation afterwards.

- [ ] **Step 7: Update the import contracts**

In `pyproject.toml`, in the `"Layers point downward"` contract, change the bottom entry:

```toml
    "ancalagon.env : ancalagon.fs : ancalagon.web",
```

and in the `"Sibling leaves are independent"` contract, add `ancalagon.web` to the modules list:

```toml
modules = [
    "ancalagon.contracts",
    "ancalagon.clock",
    "ancalagon.env",
    "ancalagon.fs",
    "ancalagon.web",
]
```

- [ ] **Step 8: Verify everything**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
```

Expected: Black clean, Pyright zero errors, unit suite green, all import contracts kept.

If Pyright reports unknown types from `trafilatura`, stop and report it — trafilatura ships `py.typed`, so it should not.

- [ ] **Step 9: Commit**

```bash
git add ancalagon/web tests/unit/test_web.py pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
Give the harness a way to reach the web

A WebClient protocol with an httpx adapter and a scripted fake, and
extracted() as the one place a page's HTML becomes prose. Nothing calls
it yet.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Operator-declared egress

**Files:**
- Modify: `ancalagon/config/config.py:28` — add `web_domains` beside `allowed_domains`
- Modify: `ancalagon/config/load.py:119` — read the optional `[web]` table
- Modify: `ancalagon/cli.py:228-236` — merge both lists into the fence policy
- Test: `tests/unit/test_config_load.py`, `tests/unit/test_sandbox.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `Config.web_domains: tuple[str, ...]`, defaulting to `()`. `sandbox_of` passes `config.allowed_domains + config.web_domains` to `Fence`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_config_load.py`, add:

```python
WEB = """
[web]
allowed_domains = ["*.example.com", "lite.duckduckgo.com"]
"""


def test_a_config_without_a_web_table_declares_no_web_domains(tmp_path: pathlib.Path):
    assert load_config(_written(tmp_path, ""), RealFileSystem()).web_domains == ()


def test_the_web_table_is_read_separately_from_the_model_endpoint(tmp_path: pathlib.Path):
    config = load_config(_written(tmp_path, WEB), RealFileSystem())

    assert config.allowed_domains == ("bedrock-runtime.us-east-1.amazonaws.com",)
    assert config.web_domains == ("*.example.com", "lite.duckduckgo.com")
```

`_written(tmp_path, block)` is the existing helper at `tests/unit/test_config_load.py:51`; it fills `TEMPLATE`'s `{block}` slot, which sits at the end of the template, so a `[web]` table dropped in there parses.

In `tests/unit/test_sandbox.py`, extend `test_fence_writes_its_policy_and_wraps_the_command` — do **not** add a new test file. Change the `Fence(...)` construction and the policy assertion to:

```python
    sandbox = Fence(
        write_root=write_root,
        allowed_domains=["bedrock-runtime.us-east-1.amazonaws.com", "*.example.com"],
        run_dir=run_dir,
        fs=RealFileSystem(),
    )

    policy = json.loads((run_dir / "fence.json").read_text())
    assert policy == {
        "network": {
            "allowedDomains": ["bedrock-runtime.us-east-1.amazonaws.com", "*.example.com"]
        },
        "filesystem": {"allowWrite": [str(write_root), str(run_dir)]},
    }
```

And add a test that `sandbox_of` is what merges them:

```python
def test_the_fence_policy_carries_the_model_endpoint_and_the_web_domains_together(
    tmp_path: pathlib.Path,
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = Config(
        write_root=tmp_path / "ws",
        read_roots=(tmp_path,),
        model="m",
        allowed_domains=("endpoint.example.net",),
        web_domains=("*.example.com",),
    )

    sandbox_of(config, run_dir, RealFileSystem())

    policy = json.loads((run_dir / "fence.json").read_text())
    assert policy["network"]["allowedDomains"] == ["endpoint.example.net", "*.example.com"]
```

with these imports added to `tests/unit/test_sandbox.py`:

```python
from ancalagon.cli import sandbox_of
from ancalagon.config.config import Config
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_config_load.py tests/unit/test_sandbox.py -v`
Expected: FAIL — pydantic rejects the unexpected `web_domains` keyword, and `load_config` returns a `Config` with no such attribute.

- [ ] **Step 3: Add the config field**

In `ancalagon/config/config.py`, immediately after `allowed_domains: tuple[str, ...] = ()`:

```python
    web_domains: tuple[str, ...] = ()
```

- [ ] **Step 4: Read the optional table**

In `ancalagon/config/load.py`, inside the `Config(...)` construction in `load_config`, immediately after the `allowed_domains=tuple(model["allowed_domains"]),` line:

```python
        web_domains=tuple(raw.get("web", {}).get("allowed_domains", [])),
```

The `[web]` table is optional, so this is `.get`, unlike the required tables above it which index directly.

- [ ] **Step 5: Merge into the fence policy**

In `ancalagon/cli.py`, in `sandbox_of`, change the `Fence` construction:

```python
    return Fence(
        write_root=config.write_root,
        allowed_domains=config.allowed_domains + config.web_domains,
        run_dir=run_dir,
        fs=fs,
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/unit/test_config_load.py tests/unit/test_sandbox.py -v`
Expected: PASS.

- [ ] **Step 7: Mutation-check**

Change the merge to `allowed_domains=config.allowed_domains` and confirm `test_the_fence_policy_carries_the_model_endpoint_and_the_web_domains_together` fails. Restore it.

- [ ] **Step 8: Verify**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit
```

- [ ] **Step 9: Commit**

```bash
git add ancalagon/config ancalagon/cli.py tests/unit/test_config_load.py tests/unit/test_sandbox.py
git commit -m "$(cat <<'EOF'
Let an operator say where a run may reach

A [web] allowed_domains table, merged with the model endpoint into the
fence policy. The config file is then the record of what a run could
reach, rather than a role's tool list implying it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `web_search`

**Files:**
- Create: `ancalagon/tools/web/__init__.py`
- Create: `ancalagon/tools/web/result.py`
- Create: `ancalagon/tools/web/search_args.py`
- Create: `ancalagon/tools/web/results_in.py`
- Create: `ancalagon/tools/web/web_search.py`
- Modify: `ancalagon/worker.py:77-116` — `available_tools` gains a `web: WebClient` parameter and one `bound_for` line
- Modify: `ancalagon/worker.py:125-158` — `build_registry` gains the same parameter and passes it through
- Modify: `ancalagon/worker.py:167` — `main` constructs a `RealWebClient()` and passes it to `build_registry`
- Modify: `tests/unit/test_answer_file.py:54`, `tests/unit/test_watch.py:209`, `tests/unit/test_hooks.py:200`, `tests/unit/test_tools.py:345,355,369` — each `build_registry(...)` call gains `web=FakeWebClient({})`
- Modify (only if Step 7 requires it): `pyrightconfig.json`
- Test: `tests/unit/test_web_tools.py`

**Interfaces:**
- Consumes: `WebClient`, `FakeWebClient`, `Page` from Task 1. `ToolContext`, `Tool`, `bound_for`, `bind_tool` (existing).
- Produces:
  - `Result(rank: int, title: str, url: str, snippet: str)`, frozen
  - `SearchArgs(query: str, count: int = 10)`, frozen
  - `results_in(html: str, count: int) -> tuple[Result, ...]`
  - `WebSearch(client: WebClient)` with `name = "web_search"`
  - `available_tools(...)` and `build_registry(...)` both take a keyword-only-in-practice `web: WebClient`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_web_tools.py`:

```python
import pathlib

from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.web.search_args import SearchArgs
from ancalagon.tools.web.web_search import ENDPOINT, WebSearch
from ancalagon.web.fake_web_client import FakeWebClient
from ancalagon.web.page import Page
from ancalagon.workspace.workspace import Workspace

DDG_PAGE = """
<html><body><table>
<tr><td valign="top">1.&nbsp;</td>
    <td><a rel="nofollow" href="https://example.com/one" class='result-link'>First Result</a></td>
</tr>
<tr><td>&nbsp;</td><td class='result-snippet'>The first snippet.</td></tr>
<tr><td valign="top">2.&nbsp;</td>
    <td><a rel="nofollow" href="https://example.org/two" class='result-link'>Second Result</a></td>
</tr>
<tr><td>&nbsp;</td><td class='result-snippet'>The second <b>snippet</b>.</td></tr>
</table></body></html>
"""


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(exist_ok=True)
    return ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root,
        summary_chars=50,
        agent_id=17,
    )


def _answered(body: str, status: int = 200) -> FakeWebClient:
    return FakeWebClient(
        {ENDPOINT: Page(url=ENDPOINT, status=status, content_type="text/html", body=body)}
    )


def test_search_writes_ranked_results_to_the_task_directory(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    client = _answered(DDG_PAGE)

    found = WebSearch(client).run(SearchArgs(query="a query"), ctx)

    assert found.ok is True
    assert client.asked == [(ENDPOINT, {"q": "a query"})]
    assert pathlib.Path(found.path).read_text() == (
        "1. First Result\n"
        "https://example.com/one\n"
        "The first snippet.\n"
        "\n"
        "2. Second Result\n"
        "https://example.org/two\n"
        "The second snippet."
    )
    assert found.summary.text == "1. First Result\nhttps://example.com/one\nThe first snip"
    assert found.truncated is True


def test_search_honours_the_count_it_was_given(tmp_path: pathlib.Path):
    found = WebSearch(_answered(DDG_PAGE)).run(SearchArgs(query="a query", count=1), _ctx(tmp_path))

    assert pathlib.Path(found.path).read_text() == (
        "1. First Result\nhttps://example.com/one\nThe first snippet."
    )


def test_search_reports_a_bad_status_as_a_failure_naming_it(tmp_path: pathlib.Path):
    found = WebSearch(_answered("", status=503)).run(SearchArgs(query="a query"), _ctx(tmp_path))

    assert found.ok is False
    assert found.error == f"{ENDPOINT} answered 503 for 'a query'"


def test_search_reports_an_empty_result_table_as_a_failure(tmp_path: pathlib.Path):
    empty = "<html><body><table></table></body></html>"
    found = WebSearch(_answered(empty)).run(SearchArgs(query="a query"), _ctx(tmp_path))

    assert found.ok is False
    assert found.error == "no results for 'a query'"
```

The `summary.text` assertion above depends on `summary_chars=50`. Count the characters exactly rather than guessing; if it is off, correct the expected string, not the `summary_chars`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_web_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.tools.web'`

- [ ] **Step 3: Write the models and the parse**

Create `ancalagon/tools/web/__init__.py` (empty file).

Create `ancalagon/tools/web/result.py`:

```python
# One result from a web search.
import pydantic


class Result(pydantic.BaseModel, frozen=True):
    rank: int
    title: str
    url: str
    snippet: str
```

Create `ancalagon/tools/web/search_args.py`:

```python
# Arguments for a web search.
import pydantic


class SearchArgs(pydantic.BaseModel, frozen=True):
    query: str
    count: int = pydantic.Field(default=10, ge=1, le=25)
```

Create `ancalagon/tools/web/results_in.py` — this is the **only** file in the codebase that touches lxml, deliberately, so that any Pyright exemption it needs is scoped to it alone:

```python
# The one place a search engine's result table becomes results.
import lxml.html

from ancalagon.tools.web.result import Result

LINKS = "//a[@class='result-link']"
SNIPPET = "ancestor::tr[1]/following-sibling::tr[1]/td[@class='result-snippet']"


def _text(element: lxml.html.HtmlElement) -> str:
    return " ".join(element.text_content().split())


def _snippet(link: lxml.html.HtmlElement) -> str:
    found = link.xpath(SNIPPET)
    return _text(found[0]) if found else ""


def results_in(html: str, count: int) -> tuple[Result, ...]:
    tree = lxml.html.fromstring(html)
    return tuple(
        Result(rank=rank, title=_text(link), url=link.get("href"), snippet=_snippet(link))
        for rank, link in enumerate(tree.xpath(LINKS)[:count], start=1)
    )
```

`_snippet` returning `""` when there is no snippet row is not a defensive guard: DuckDuckGo genuinely omits the abstract row for some results, and the source markup says so.

- [ ] **Step 4: Write the tool**

Create `ancalagon/tools/web/web_search.py`:

```python
# Searches the web and writes the ranked results to the task directory.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.web.result import Result
from ancalagon.tools.web.results_in import results_in
from ancalagon.tools.web.search_args import SearchArgs
from ancalagon.web.web_client import WebClient

ENDPOINT = "https://lite.duckduckgo.com/lite/"


def _rendered(result: Result) -> str:
    return f"{result.rank}. {result.title}\n{result.url}\n{result.snippet}"


class WebSearch(Tool[SearchArgs]):
    name = "web_search"
    description = (
        "Search the web. Returns ranked results, each a title, a URL and a snippet. Follow a "
        "result with fetch_url to read the page itself; the snippet alone is not evidence."
    )
    cost = 1
    args_model = SearchArgs

    def __init__(self, client: WebClient):
        self.client = client

    def run(self, args: SearchArgs, ctx: ToolContext) -> ToolResult:
        page = self.client.post_form(ENDPOINT, {"q": args.query})
        if page.status != 200:
            return ctx.failure(self.name, f"{ENDPOINT} answered {page.status} for {args.query!r}")
        found = results_in(page.body, args.count)
        if not found:
            return ctx.failure(self.name, f"no results for {args.query!r}")
        return ctx.result(self.name, "\n\n".join(_rendered(r) for r in found))
```

- [ ] **Step 5: Wire it into the worker**

In `ancalagon/worker.py`, add these imports in the correct alphabetical positions among the existing ones:

```python
from ancalagon.tools.web.web_search import WebSearch
from ancalagon.web.real_web_client import RealWebClient
from ancalagon.web.web_client import WebClient
```

Change the `available_tools` signature to take the client — add it after `clock: Clock,`:

```python
def available_tools(
    role: Role,
    roles: collections.abc.Mapping[str, Role],
    run_dir: pathlib.PurePath,
    parent: int,
    output_class: type[pydantic.BaseModel],
    clock: Clock,
    fs: FileSystem,
    web: WebClient,
) -> list[BoundTool]:
```

Add one line to the returned list, immediately after `bound_for(Shell(), role),`:

```python
        bound_for(WebSearch(web), role),
```

Change the `build_registry` signature the same way — add `web: WebClient,` after `fs: FileSystem,` — and pass it through at the `available_tools(...)` call:

```python
    available = available_tools(
        spec.role, spawnable, run_dir, parent, output_class, clock, fs, web
    ) + [
```

In `main`, immediately after `fs = RealFileSystem()`, add:

```python
    web = RealWebClient()
```

and add `web=web,` to the `build_registry(...)` call.

- [ ] **Step 6: Update the six existing `build_registry` call sites**

Every one of these already uses keyword arguments, so each gains one line, `web=FakeWebClient({}),`, and the import `from ancalagon.web.fake_web_client import FakeWebClient`:

- `tests/unit/test_answer_file.py:54`
- `tests/unit/test_watch.py:209`
- `tests/unit/test_hooks.py:200`
- `tests/unit/test_tools.py:345`, `:355`, `:369`

Find them all rather than trusting these line numbers, which drift:

```bash
grep -rn "build_registry(" tests/
```

- [ ] **Step 7: Run the tests and Pyright**

```bash
uv run python -m pytest tests/unit/test_web_tools.py -v
uv run pyright
```

Expected: tests PASS; Pyright zero errors.

**If and only if Pyright reports unknown types from `lxml`**, add this entry to the `executionEnvironments` array in `pyrightconfig.json`, and nothing broader:

```json
    {
      "root": "ancalagon/tools/web/results_in.py",
      "reportUnknownMemberType": "none",
      "reportUnknownVariableType": "none",
      "reportUnknownArgumentType": "none",
      "reportMissingTypeStubs": "none"
    }
```

Include only the rules Pyright actually named. Then re-run `uv run pyright` and confirm zero errors. If it is already clean, add nothing — the exemption is not spent on a prediction.

- [ ] **Step 8: Mutation-check the tests**

Break the code two ways and confirm a test fails each time:

1. In `results_in`, drop the `[:count]` slice — `test_search_honours_the_count_it_was_given` must fail.
2. In `WebSearch.run`, change the status check to `!= 999` — `test_search_reports_a_bad_status_as_a_failure_naming_it` must fail.

Restore both.

- [ ] **Step 9: Verify**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
```

- [ ] **Step 10: Commit**

```bash
git add ancalagon/tools/web ancalagon/worker.py tests/ pyrightconfig.json
git commit -m "$(cat <<'EOF'
Let an agent search the web

One keyless endpoint, parsed in a single file so its markup dependency
is contained, written to the task directory as ranked lines. A role gets
it by naming web_search in its tools.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `fetch_url`

**Files:**
- Create: `ancalagon/tools/web/fetch_args.py`
- Create: `ancalagon/tools/web/fetch_url.py`
- Modify: `ancalagon/worker.py` — one `bound_for` line in `available_tools`
- Test: `tests/unit/test_web_tools.py` (extend, do not create a new file)

**Interfaces:**
- Consumes: `WebClient`, `FakeWebClient`, `Page`, `extracted` from Task 1; the `_ctx` helper and `ARTICLE`-style fixtures from Task 3's test file.
- Produces: `FetchArgs(url: str)`, frozen, with `pattern=r"^https://"`; `FetchUrl(client: WebClient)` with `name = "fetch_url"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_web_tools.py`, and add the imports it needs at the top of that file:

```python
import pydantic
import pytest

from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.web.fetch_args import FetchArgs
from ancalagon.tools.web.fetch_url import FetchUrl

PAGE = """
<html><head><title>A Title</title></head><body>
<nav><ul><li><a href="/edit">Edit this page</a></li></ul></nav>
<article>
<h1>A Title</h1>
<p>The first paragraph explains the subject at enough length that an extractor treats it as the
main content of the page rather than as boilerplate around the edges of it.</p>
<p>The second paragraph continues that explanation, so the article carries more prose than the
navigation does, which is the signal the extractor decides on.</p>
</article>
<footer>Copyright notice belongs to nobody.</footer>
</body></html>
"""

TARGET = "https://example.com/article"


def _serving(body: str, status: int = 200, content_type: str = "text/html") -> FakeWebClient:
    return FakeWebClient(
        {TARGET: Page(url=TARGET, status=status, content_type=content_type, body=body)}
    )


def test_fetch_writes_the_article_text_without_the_navigation(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    client = _serving(PAGE)

    got = FetchUrl(client).run(FetchArgs(url=TARGET), ctx)

    assert got.ok is True
    assert client.asked == [(TARGET, {})]
    written = pathlib.Path(got.path).read_text()
    assert "The first paragraph explains the subject" in written
    assert "The second paragraph continues that explanation" in written
    assert "Edit this page" not in written
    assert "Copyright notice belongs to nobody." not in written
    assert got.byte_count == len(written.encode("utf-8"))


def test_fetch_fails_naming_the_url_status_and_type_when_nothing_can_be_extracted(
    tmp_path: pathlib.Path,
):
    client = _serving("%PDF-1.4 binary rubbish", content_type="application/pdf")

    got = FetchUrl(client).run(FetchArgs(url=TARGET), _ctx(tmp_path))

    assert got.ok is False
    assert got.error == f"extracted no text from {TARGET} (200, application/pdf)"


def test_fetch_reports_a_bad_status_as_a_failure(tmp_path: pathlib.Path):
    got = FetchUrl(_serving("", status=404)).run(FetchArgs(url=TARGET), _ctx(tmp_path))

    assert got.ok is False
    assert got.error == f"{TARGET} answered 404"


def test_a_non_https_url_is_refused_by_the_schema_not_by_the_tool(tmp_path: pathlib.Path):
    with pytest.raises(pydantic.ValidationError):
        FetchArgs(url="http://example.com/article")

    bound = bind_tool(FetchUrl(_serving(PAGE)))
    refused = bound.invoke('{"url": "ftp://example.com/article"}', _ctx(tmp_path))

    assert refused.ok is False
    assert "url" in refused.error
```

`BoundTool.invoke` is a field of type `collections.abc.Callable[[str, ToolContext], ToolResult]` (`ancalagon/tools/registry/bound_tool.py:14`), so `bound.invoke(json_text, ctx)` is the call. The point of that test is that the refusal comes from parsing the arguments, not from a check inside `run`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_web_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.tools.web.fetch_args'`

- [ ] **Step 3: Write the args model**

Create `ancalagon/tools/web/fetch_args.py`:

```python
# Arguments for fetching one page.
import pydantic


class FetchArgs(pydantic.BaseModel, frozen=True):
    url: str = pydantic.Field(
        pattern=r"^https://", description="An https URL. Plain http is refused."
    )
```

The constraint lives on the field so the model is told it by the tool's schema before it calls, rather than being refused inside `run`.

- [ ] **Step 4: Write the tool**

Create `ancalagon/tools/web/fetch_url.py`:

```python
# Fetches a page and writes its article text to the task directory.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.web.fetch_args import FetchArgs
from ancalagon.web.extracted import extracted
from ancalagon.web.web_client import WebClient


class FetchUrl(Tool[FetchArgs]):
    name = "fetch_url"
    description = (
        "Fetch an https page and return its article text, with navigation and markup removed. "
        "Fails on anything it cannot take prose from, such as a PDF or a JSON endpoint."
    )
    cost = 1
    args_model = FetchArgs

    def __init__(self, client: WebClient):
        self.client = client

    def run(self, args: FetchArgs, ctx: ToolContext) -> ToolResult:
        page = self.client.get(args.url)
        if page.status != 200:
            return ctx.failure(self.name, f"{args.url} answered {page.status}")
        text = extracted(page.body)
        if not text:
            return ctx.failure(
                self.name,
                f"extracted no text from {page.url} ({page.status}, {page.content_type})",
            )
        return ctx.result(self.name, text)
```

- [ ] **Step 5: Wire it into the worker**

In `ancalagon/worker.py`, add the import in its alphabetical position:

```python
from ancalagon.tools.web.fetch_url import FetchUrl
```

and add one line to `available_tools`, immediately after `bound_for(WebSearch(web), role),`:

```python
        bound_for(FetchUrl(web), role),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/unit/test_web_tools.py -v`
Expected: PASS.

- [ ] **Step 7: Mutation-check**

1. Delete the `if not text:` branch so an empty extraction returns `ctx.result` — `test_fetch_fails_naming_the_url_status_and_type_when_nothing_can_be_extracted` must fail.
2. Remove `pattern=r"^https://"` from `FetchArgs` — `test_a_non_https_url_is_refused_by_the_schema_not_by_the_tool` must fail.

Restore both.

- [ ] **Step 8: Verify**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
```

- [ ] **Step 9: Commit**

```bash
git add ancalagon/tools/web ancalagon/worker.py tests/unit/test_web_tools.py
git commit -m "$(cat <<'EOF'
Let an agent read a page

fetch_url writes the article's prose and nothing else, and fails loudly
naming the url, status and content type when there is no prose to take.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The gated live test and the docs

**Files:**
- Create: `tests/integration/test_web.py`
- Modify: `ancalagon.example.toml` — add the `[web]` table
- Modify: `README.md:236` — two rows in the tool catalogue
- Modify: `.talismanrc` — only if Talisman flags a changed file

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: nothing other tasks rely on.

- [ ] **Step 1: Write the gated integration test**

Create `tests/integration/test_web.py`:

```python
import os
import pathlib

import pytest

from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.web.fetch_args import FetchArgs
from ancalagon.tools.web.fetch_url import FetchUrl
from ancalagon.tools.web.search_args import SearchArgs
from ancalagon.tools.web.web_search import WebSearch
from ancalagon.web.real_web_client import RealWebClient
from ancalagon.workspace.workspace import Workspace

pytestmark = pytest.mark.skipif(
    os.environ.get("ANCALAGON_WEB") != "1",
    reason="reaches the live web; set ANCALAGON_WEB=1 to run",
)


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(exist_ok=True)
    return ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root,
        summary_chars=1000,
        agent_id=1,
    )


def test_a_search_and_a_fetch_against_the_live_web(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    client = RealWebClient()

    found = WebSearch(client).run(SearchArgs(query="pydantic model_validate_json", count=5), ctx)
    assert found.ok is True
    urls = [
        line
        for line in pathlib.Path(found.path).read_text().splitlines()
        if line.startswith("https://")
    ]
    assert len(urls) == 5

    got = FetchUrl(client).run(FetchArgs(url="https://en.wikipedia.org/wiki/Reverse_engineering"), ctx)
    assert got.ok is True
    assert "reverse engineering" in pathlib.Path(got.path).read_text().lower()
```

- [ ] **Step 2: Run it, gated and ungated**

```bash
uv run python -m pytest tests/integration/test_web.py -v
```
Expected: 1 skipped.

```bash
ANCALAGON_WEB=1 uv run python -m pytest tests/integration/test_web.py -v
```
Expected: PASS. If the search returns fewer than five results, the assertion is telling you something real about the endpoint — investigate before changing the number.

- [ ] **Step 3: Document the config**

In `ancalagon.example.toml`, add after the `[sandbox]` table:

```toml
[web]
allowed_domains = []
```

with no surrounding comment — the README carries the explanation.

- [ ] **Step 4: Document the tools**

In `README.md`, add a new two-row group to the tool catalogue (which starts at the `### The tools` heading), placed immediately after the `| Searching | |` table:

```markdown
| Reaching the web | |
|---|---|
| `web_search` | ranked results for a query: title, URL and snippet |
| `fetch_url` | one https page's article text, with navigation and markup removed |
```

Then, in the same file, document the egress requirement wherever the sandbox is described. Find that place first:

```bash
grep -n "fence\|sandbox\|allowed_domains" README.md
```

Add, in that section, a paragraph saying: the worker runs under a fence policy built from `[model].allowed_domains` and `[web].allowed_domains` together; `web_search` and `fetch_url` reach nothing unless the operator lists the domains, `["*"]` opens the run to the whole web, and matching is strict — `example.com` does not cover `www.example.com`, which needs `*.example.com`.

- [ ] **Step 5: Full verification**

This is the last commit, so run everything, including the whole integration suite:

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
```

Expected: Black clean, Pyright zero errors, both suites green (with the gated web and live-model tests skipped), all import contracts kept. `tests/integration` takes about forty seconds — do not narrow it to the file you expect to break.

- [ ] **Step 6: Grep for anything left behind**

```bash
grep -rn "web_search\|fetch_url\|web_domains" --include="*.py" --include="*.toml" --include="*.md" . | grep -v ".venv"
```

Confirm every hit is intentional and that no half-renamed string literal survives.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_web.py ancalagon.example.toml README.md
git commit -m "$(cat <<'EOF'
Document the web tools and prove them against the live web

A gated integration test that actually searches and fetches, plus the
catalogue rows and the egress paragraph an operator needs before turning
either tool on.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

If Talisman flags a file, reword the flagged line when the wording is incidental. If it must be suppressed, **append** a `.talismanrc` entry for a newly flagged file but **replace the checksum in place** for a file already listed — only the first entry per filename is honoured. Use the checksum Talisman reports, never one computed with `shasum`.

---

## Notes for the executor

- The spec is `docs/superpowers/specs/2026-09-10-two-web-research-tools-design.md`. Read it before Task 1. It records why several obvious-looking alternatives were rejected, so you do not re-propose them.
- Non-HTML payloads are deliberately out of scope. `fetch_url` fails on them and writes nothing. Do not add a content-type branch, and do not add an XML tool. The spec says what that would look like if it is ever wanted.
- Do not add a `structured=true` flag to `web_search`. The rendering is readable lines on purpose.
- If any step needs more than one corrective patch, stop and raise it rather than stacking a second fix on the first.
