# One run per work item

## Problem

`ancalagon run` is shaped for a person starting one investigation. A driver process that
wants a run per item across a large population cannot use it:

- the goal must fit in `argv` (`cli.py` `--goal`), and is duplicated into `spec.json`'s `input`
- the root task's output contract is fixed to `FreeText` (`cli.py` writes `FREE_TEXT_MODULE` and
  pins `contracts.py:FreeText`), so typed results are reachable only through `delegate`
- `_new_run_dir` always mints a fresh `r_NNNN`, so a caller can neither resume an interrupted
  item nor recognise a finished one
- every turn resends the system prompt and every tool schema at full price

Two changes. Nothing about the session loop, the supervisor or the bus changes.

## 1. Cache the static prefix

`LiteLLMClient.complete` sends the system prompt as a plain string. Anthropic renders `tools`,
then `system`, then `messages`, so one `cache_control` breakpoint on the system block also covers
the tool schemas — the only part of a request identical across turns and across items.

`WireMessage.content` becomes `str | tuple[WireTextBlock, ...]`, where `WireTextBlock` carries
`type`, `text` and an optional `cache_control`. Only the system message is ever built as blocks;
`to_wire` keeps returning strings.

Cache reads bill at 0.1x input, writes at 1.25x, so the second turn of any run pays it back. The
static prefix is estimated at a few thousand tokens against a 1,024-token minimum for the models
in use; the first run must confirm from `usage` that the breakpoint took effect rather than being
silently ignored for being too short.

Always on, no configuration knob: every model this harness targets is Anthropic-shaped, and a
knob nobody would turn off is a knob.

The growing transcript stays uncached. Covering it needs a breakpoint moved to the last message
each turn, which is a different change and out of scope until a measured run shows the remainder
dominating.

## 2. A `[run]` section in the config file

The three things a driver must vary per item are configuration, not invocation. They join the
TOML rather than becoming flags:

```toml
[run]
run_dir = ""    # where this run lives; empty means allocate the next write_root/runs/r_NNNN
goal_file = ""  # empty means the goal comes from --goal
contract = ""   # "path.py:ClassName"; empty means FreeText
```

Required section, all three entries present, empty string meaning absent. That is what `load.py`
already demands of every other setting, read by bracket and never `.get()`, so a file that omits
one fails loudly instead of silently taking a default. Existing config files need the block added,
and the resulting lookup failure says so.

**`run_dir`** — resolved against the config file like every other path, created if absent, and
used as the run directory verbatim. Empty falls back to today's behaviour: the next `r_NNNN` under
`write_root / "runs"`. `write_root` therefore governs only the fallback, and a config setting both
is stating a directory and an unused default, not a conflict.

Handing the driver the directory rather than a name under `runs/` keeps it ignorant of the layout:
it computes a path per item and checks that path. Naming the directory is what lets it do two
things:

- **recognise a completed item** — read `tasks/root/outcome.json` and check its kind. Presence
  alone is not enough; a failure, a timeout and an exhausted budget all leave a file there, and
  skipping on presence would cache a failure forever.
- **resume an interrupted one** — the worker already loads and repairs whatever
  `transcript.jsonl` it finds; this only makes that reachable

Neither involves polling. `run_until_idle` blocks until the run is over, so a driver invokes,
waits, and reads. Running items concurrently means several `ancalagon run` processes at once, each
with its own directory and its own `bus.db`; `max_concurrent_agents` governs agents inside one run
and does nothing for a population of one-agent runs.

Enqueuing an existing task directory already reuses the task row and adds an agent, so a second
invocation continues rather than collides.

Skip-if-finished stays with the driver. The harness has no content-addressed cache of model calls
and is not gaining one: only the driver knows whether an item's input changed.

**`goal_file`** — resolved against the config file like every other path. Exactly one of
`goal_file` and `--goal` must be given; both or neither exits non-zero. `--goal` survives because
inline text is the interactive case and editing a file to ask a question is worse.

**`contract`** — `path.py:ClassName`. The module is copied into the task directory as
`contracts.py` and `spec.json`'s `output` names the class. `contracts/resolve.py` already refuses
any path outside the task directory and runs against the copy, so no new escape surface.

A driver generates one config file per item from a template, so each item's run is a single
inspectable artifact and two items are diffable. The cost is that the run-wide block — model,
budget, limits — is duplicated across every generated file, making a model change a regeneration
rather than an edit. Accepted: these are derived artifacts. No config inheritance or include
mechanism.

## Tests

`fake_llm` covers the loop offline, so both changes are unit-testable without a credential.

- the system block carries `cache_control` and the tool schemas precede it — assert the payload
  handed to `litellm.completion`, not that a request succeeded
- `load_config` reads all three `[run]` entries; a config missing the section raises
- `run_dir` set puts the run at exactly that path; empty allocates `write_root/runs/r_NNNN`
- `goal_file` and `--goal` produce identical `spec.json`; supplying both, or neither, exits non-zero
- `contract` writes the named class into `spec.json` and copies the module; empty gives `FreeText`
- one integration test drives a real worker subprocess twice under the same `run_dir` and asserts
  the second invocation continues the first's transcript

## Out of scope

Per-turn transcript caching. Any content-addressed cache of model calls. Concurrency changes.
Anything in `session.py`, `supervisor/` or `bus/`.
