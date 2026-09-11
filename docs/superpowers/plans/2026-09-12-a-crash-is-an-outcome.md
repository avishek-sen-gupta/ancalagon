# A Crash Is An Outcome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A session that crashes returns a `Failed` outcome carrying what it spent, instead of killing whatever called it — and every exception the harness swallows reaches a log with its stack.

**Architecture:** `Session.run` already returns `Failed` from three places. A fourth wraps the loop, so the provider dying is an outcome like any other. Logging is fixed where it is missing rather than sprinkled everywhere: one line in `ToolContext.failure` covers every tool refusal, and the worker gains the `basicConfig` it never had.

**Tech Stack:** Python 3.13, uv, pydantic, pytest, Pyright strict, import-linter, python-fp-lint.

**Spec:** none — settled in conversation. This plan is the record.

## Why this exists

`session_for` let a host run one agent in its own process. The first real run died like this:

```
litellm.exceptions.APIConnectionError: BedrockException - {"Message":"Bearer Token has expired"}
```

The traceback escaped `session.run()` and killed the script. A worker survives the same failure only because `worker.main:89` wraps the call in `except Exception`. Two things follow.

**The embedder has no such wrapper**, so the entry point this repo just shipped is the one path where a dead provider is fatal.

**The worker's own wrapper loses the spend.** `worker.py:93` writes `spent=NOTHING`, so an agent that burned eleven turns before the provider died reports zero. `Session` is the only thing that knows the true figure.

## Global Constraints

- Pyright strict, ZERO errors. `Any` is banned outright — no `typing.Any`, no `dict[str, Any]`, no `object` annotations.
- Every generic parameterised. All pydantic models `frozen=True`. Fully qualified imports, no relative imports.
- NO COMMENTS except a single one-line header at the top of a module or class. No docstrings, no inline explanations, no TODOs.
- No defensive programming and no `None` checks. The one deliberate exception is the broad `except Exception` this plan adds to `Session.run`; it is a boundary converting a crash into a domain value, which is what `worker.py:89` already does.
- python-fp-lint caps cyclomatic complexity at 3 and forbids `list.append`. `ancalagon/session.py` and `ancalagon/worker.py` are in `fp.json`'s exclude list; `ancalagon/tools/registry/tool_context.py` is NOT — mind it there.
- After editing imports run `uv run ruff check --select I --fix ancalagon/ tests/`.
- Assertions are sacred: do not weaken, change or delete an existing assertion. If one fails, that is a finding to report.
- No mocking. Use injected fakes.
- Do NOT use `python -c` with multiline strings. Write a script to the scratchpad and run `uv run python <path>`.
- Verification per task: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports`. Run the FULL integration suite every task.
- Talisman: APPEND a `.talismanrc` entry for a newly flagged file, REPLACE THE CHECKSUM IN PLACE for one already listed, never duplicate a filename. Verify every commit landed with `git log --oneline -1`.

## What the audit actually found

All 50 `except` sites were read. Most already keep the full exception, and this plan does not touch them:

| site | why no change |
|---|---|
| `bus/lifecycle_store.py:159,230` | `except Exception:` → ROLLBACK → **re-raise**. Nothing swallowed. |
| `web/real_web_client.py:30,37` | `raise Unreachable(...) from exc` — re-raised with the cause chained. |
| `supervisor/supervisor.py:65` | already calls `LOGGER.exception`. |
| `worker.py:89` | already calls `LOGGER.exception`. |

Two sites are **deliberately excluded**, and this is a stated assumption rather than an oversight — reverse it by adding the same one-line call if you disagree:

| site | why excluded |
|---|---|
| `text/decoded.py:5` | `UnicodeDecodeError` **is** the answer: "not UTF-8, so Latin-1". The module header says it cannot fail. Fires on every non-UTF-8 byte string a tool reads. |
| `supervisor/os_liveness.py:12,14` | `ProcessLookupError` / `PermissionError` **are** the liveness answer. Polled on every supervisor tick; a traceback per poll would bury the log. |

One consequence to know before Task 3: the CLI-level catches (`cli.py`, `check_contracts.py`, `run.py`) exist to turn a failure into a clean message for a human. `cli.py:51` calls `basicConfig(level=INFO)`, so adding `LOGGER.exception` there means **a config typo now prints a stack trace to the user's console** above the tidy message. That is the instruction as given and it is what this plan implements. It is one line per site to reverse.

---

### Task 1: A crash is an outcome

**Files:**
- Modify: `ancalagon/session.py` — wrap the `run` loop; upgrade one existing log call
- Test: `tests/unit/test_session_loop.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `Session.run` may now return `Failed` for any exception raised inside the loop. Its signature is unchanged — `Failed` is already a member of `Outcome`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_session_loop.py`. Read the file first for how a `Session` is built there and reuse that, rather than inventing a new fixture.

The fake must raise from `complete`, so write it beside the test:

```python
class ExplodingLLM(LLM):
    def complete(
        self,
        system: SystemPrompt,
        messages: collections.abc.Sequence[Message],
        tools: collections.abc.Sequence[ToolSchema],
        force_tool: str = "",
    ) -> Reply:
        raise RuntimeError("the provider hung up")
```

Copy the exact signature from `ancalagon/llm/llm.py` — do not guess it, and inherit `LLM` as this codebase requires of Protocol implementers.

```python
def test_a_session_whose_provider_dies_returns_a_failure_carrying_what_it_spent(tmp_path):
    session = <built as the neighbouring tests build one, with ExplodingLLM()>

    outcome = session.run()

    assert isinstance(outcome, Failed)
    assert "RuntimeError" in outcome.error
    assert "the provider hung up" in outcome.error
    assert "Traceback (most recent call last)" in outcome.error
    assert outcome.summary == "the provider hung up"
    assert outcome.spent.turns == 1
```

The last assertion is the point of the whole task: the turn was spent before the provider was called, so a crash must report `1`, not `0`. Read `Spend` in `ancalagon/contracts/spend.py` for the real field name and fix the assertion to match — do NOT weaken it to something vaguer if the name differs.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run python -m pytest tests/unit/test_session_loop.py -k provider_dies -v`
Expected: FAIL with `RuntimeError: the provider hung up` escaping the test — not an assertion failure. That is the bug.

- [ ] **Step 3: Wrap the loop**

In `ancalagon/session.py`, `run` currently reads `def run(self): while True: ...`. Put the existing loop inside a `try`, leaving its body untouched, and add one handler:

```python
        except Exception as exc:
            LOGGER.exception("the session failed")
            return Failed(
                error=traceback.format_exc(),
                summary=str(exc)[: self.ctx.summary_chars],
                spent=self._spent(),
            )
```

`traceback` needs importing. `LOGGER` already exists at `session.py:47`. Catch `Exception`, never `BaseException` — `KeyboardInterrupt` and `SystemExit` must keep propagating.

The full traceback goes in `error` deliberately. Downstream, `collect_task._detail` hands `outcome.error` to `ctx.failure`, which writes the full text to a file and gives the model only `summary_chars` of it plus `[full output: <path>]` — so a parent agent gets a pointer, not a context flood. Do not shorten it.

- [ ] **Step 4: Make the existing ValidationError log carry its stack**

`session.py:201` reads:

```python
            except pydantic.ValidationError as exc:
                LOGGER.info("tool %s was called with bad arguments: %s", use.name, exc)
```

`LOGGER.info` records the message and no stack. Change to `LOGGER.exception("tool %s was called with bad arguments", use.name)` — `exception` implies `exc_info=True`, so the type, message and stack all land. Drop the now-duplicated `exc` argument. Leave the `result = ...` line alone.

- [ ] **Step 5: Log the unknown-tool KeyError**

`session.py:184` catches `KeyError` and tells the model, but logs nothing:

```python
            except KeyError as exc:
                blocks.append(ToolResultBlock(tool_use_id=use.id, content=str(exc), is_error=True))
```

Add `LOGGER.exception("the model called a tool that is not in the registry")` as the first line of the handler. Leave the `blocks.append` and the `continue` exactly as they are.

- [ ] **Step 6: Run the test**

Run: `uv run python -m pytest tests/unit/test_session_loop.py -v`
Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 7: Mutation-check**

Change `spent=self._spent()` to `spent=NOTHING` (import it from wherever `worker.py` gets it). The new test must fail on the spend assertion. Restore it. If it does not fail, the assertion is not doing its job — say so rather than moving on.

- [ ] **Step 8: Full verification, then commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add ancalagon/session.py tests/unit/test_session_loop.py
git commit -m "$(cat <<'EOF'
Return a failure instead of killing the caller

Session.run already returned Failed for a refused tool and for a reply
that called nothing. A dead provider was the one crash that escaped,
which mattered only to the worker until a host could embed a session.

The worker caught it and wrote spent=NOTHING, so an agent that burned
eleven turns before the provider died reported zero. Session is the only
thing that knows the real figure, so the outcome now carries it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: One line covers every tool refusal

**Files:**
- Modify: `ancalagon/tools/registry/tool_context.py` — `failure` logs before it returns
- Test: `tests/unit/test_tools.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks rely on. `ToolContext.failure`'s signature and return value are unchanged.

Thirty-seven tool sites read `except <Error> as exc: return ctx.failure(self.name, str(exc))`. Logging in `failure` covers all of them from one place, and also covers refusals that never raised.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_tools.py`, using pytest's `caplog` fixture:

```python
def test_a_tool_failure_is_logged_with_its_stack(tmp_path, caplog):
    ctx = <a ToolContext built as the neighbouring tests build one>
    with caplog.at_level(logging.ERROR):
        try:
            raise ScopeError("outside the read roots")
        except ScopeError as exc:
            result = ctx.failure("read_file", str(exc))

    assert result.ok is False
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is not None
    assert "ScopeError" in caplog.text
    assert "outside the read roots" in caplog.text
```

`caplog.records[0].exc_info is not None` is the assertion that matters — it is what distinguishes a logged stack from a logged string. Everything else could pass without the traceback.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run python -m pytest tests/unit/test_tools.py -k failure_is_logged -v`
Expected: FAIL on `len(caplog.records) == 1` — nothing is logged today.

- [ ] **Step 3: Log it**

In `ancalagon/tools/registry/tool_context.py`, add a module-level `LOGGER = logging.getLogger(__name__)` (the file has no logger today) and make `failure` log before it writes:

```python
    def failure(self, tool_name: str, error: str) -> ToolResult:
        LOGGER.error("%s failed: %s", tool_name, error, exc_info=True)
        path = self.write_output(tool_name, error, ".err.txt")
```

`LOGGER.error(..., exc_info=True)` rather than `LOGGER.exception(...)` on purpose: `failure` is also called where nothing was raised, and `exc_info=True` outside a handler simply records no stack rather than failing. Leave the rest of the method untouched.

This file is NOT in `fp.json`'s exclude list, so python-fp-lint inspects it. If it objects, report the rule rather than restructuring.

- [ ] **Step 4: Run the test, then the whole suite**

Run: `uv run python -m pytest tests/unit/test_tools.py -v`
Expected: PASS. Then run the full unit suite — other tests capture logs and a new ERROR record can surprise them. If a pre-existing test fails, report it; do not silence it by weakening its assertion.

- [ ] **Step 5: Full verification, then commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add ancalagon/tools/registry/tool_context.py tests/unit/test_tools.py
git commit -m "$(cat <<'EOF'
Log a tool failure where every tool failure already goes

Thirty-seven catch sites all end in ctx.failure, so the one place they
share is the honest place to log. A refusal that never raised is logged
too, without its stack, which is the truth about it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The log a worker never had

**Files:**
- Modify: `ancalagon/worker.py` — configure logging in `cli`
- Modify: `ancalagon/deterministic/run.py` — configure logging in `cli`; log the crash it swallows
- Modify: `ancalagon/contracts/declared.py`, `ancalagon/check_contracts.py`, `ancalagon/cli.py`, `ancalagon/run.py`, `ancalagon/tools/shell/run_shell.py` — log what they catch
- Test: `tests/unit/test_worker_logging.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

Nothing outside `cli.py:51` calls `basicConfig`. A worker is a separate process, so every `LOGGER.info` it makes is dropped — logging's last-resort handler is WARNING-level. `session.py`'s "the reply called no tool, asking again" has never appeared in any log.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_worker_logging.py`:

```python
def test_a_worker_process_configures_logging_so_info_survives():
    root = logging.getLogger()
    before = root.level
    try:
        root.handlers = []
        root.level = logging.WARNING
        configure_logging()
        assert root.level == logging.INFO
        assert len(root.handlers) == 1
    finally:
        root.handlers = []
        root.level = before
```

Name whatever you add `configure_logging` and put it where both `worker.cli` and `deterministic.run.cli` can import it without breaking the import-linter layers — check `pyproject.toml`'s "Layers point downward" contract before choosing the module. If no module below both exists, calling `logging.basicConfig(level=logging.INFO)` directly in each `cli` is acceptable; then drop this test and assert the behaviour in Step 3 instead. Say in your report which you chose and why.

- [ ] **Step 2: Run it and watch it fail**

Expected: FAIL — `configure_logging` does not exist.

- [ ] **Step 3: Configure logging in both process entry points**

`worker.py`'s `cli()` and `deterministic/run.py`'s `cli()` each gain the same call `ancalagon/cli.py:51` already makes, before they parse arguments. Match `cli.py`'s call exactly so all three processes log alike.

- [ ] **Step 4: Log the deterministic crash**

`deterministic/run.py:76` writes a `Failed` with a full traceback but logs nothing — `worker.py:89`'s twin, missing its log line. It has no `LOGGER` today. Add `LOGGER = logging.getLogger(__name__)` and, as the handler's first line:

```python
        LOGGER.exception("the deterministic run failed")
```

Leave the `Failed` construction and the `return 1` exactly as they are.

- [ ] **Step 5: Log the five remaining swallows**

Each gains `LOGGER.exception(<a short message naming what was being attempted>)` as the first line of its handler, and a module-level `LOGGER` where the file has none. Change nothing else in these handlers — every returned value and message stays identical.

- `ancalagon/contracts/declared.py:24` — `NameError`
- `ancalagon/check_contracts.py:26` — a contract class that cannot be loaded
- `ancalagon/check_contracts.py:104` — a role that fails to build
- `ancalagon/cli.py:56` — `NoOutcome`
- `ancalagon/cli.py:104` — `ValueError`
- `ancalagon/run.py:50` — `pydantic.ValidationError`
- `ancalagon/tools/shell/run_shell.py:20` — `subprocess.TimeoutExpired`

Do NOT touch `text/decoded.py` or `supervisor/os_liveness.py`. The plan section above says why.

Note `check_contracts.py` and `cli.py` are in `fp.json`'s exclude list; `declared.py`, `run.py` and `run_shell.py` are not.

- [ ] **Step 6: Full verification, then commit**

The CLI now prints a stack trace above its tidy message for a bad config. That is intended. Check that `uv run python -m pytest tests/unit` still passes — a CLI test asserting exact stderr may now fail, which is a finding to report rather than to fix by weakening it.

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add ancalagon tests
git commit -m "$(cat <<'EOF'
Give the worker the logging configuration it never had

Only ancalagon/cli.py ever called basicConfig, and a worker is a separate
process, so its INFO lines went to a last-resort handler that drops
anything below WARNING. The reply-called-no-tool line has never appeared
in any log.

The deterministic runner wrote a traceback into its outcome file and told
no one, which is worker.py's handler missing its one log call.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Say so in the README

**Files:**
- Modify: `README.md` — the "Running one agent in your process" section
- Modify: `.talismanrc` — only if Talisman flags it

**Interfaces:** consumes Task 1's behaviour; produces nothing.

- [ ] **Step 1: Document what `run()` now returns**

The section added last week tells a host what fails later than it would like. It should now also say what does *not* fail. Add to it, matching the surrounding register — plain declarative sentences, lowercase identifiers in backticks:

```markdown
`session.run()` does not raise. A provider that dies, a tool that throws, anything the loop does
not expect: each comes back as a `Failed` outcome carrying the traceback in `error` and the turns
and tool calls actually spent. A host switches on the outcome rather than wrapping the call.
```

Verify that claim against `ancalagon/session.py` before committing it — two specs in this repo have shipped a claim labelled "measured" that was false, and a third was caught in review last week.

- [ ] **Step 2: Full verification, then commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add README.md .talismanrc
git commit -m "$(cat <<'EOF'
Tell a host that a session does not raise

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Notes for the executor

- Task 1 is the behaviour change; Tasks 2 and 3 are the logging sweep; Task 4 is documentation. They are independent after Task 1.
- Do NOT add `LOGGER.exception` to `text/decoded.py` or `supervisor/os_liveness.py`, and do not touch `bus/lifecycle_store.py`, `web/real_web_client.py` or `supervisor/supervisor.py:65` — the table above says why for each.
- The full traceback belongs in `Failed.error`. Do not shorten it: `ctx.failure` already truncates for the model and writes the full text to a file.
- If any step needs more than one corrective patch, stop and raise it rather than stacking a second fix on the first.
