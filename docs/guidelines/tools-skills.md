## Workflow skills and agents

Use these at the point in the workflow where they belong, not as an afterthought.

| Skill / Agent | Trigger | What it is for |
|---|---|---|
| `superpowers:brainstorming` | Before any creative work | Mandatory first phase. Classifies the task, then questions and a design before code. |
| `superpowers:writing-plans` | A multi-step task, after the design is approved | Turns a spec into independently committable units |
| `superpowers:systematic-debugging` | A test failure or unexpected behaviour | Before proposing a fix, not after it fails |
| `superpowers:test-driven-development` | Implementing anything | The failing test comes first |
| `superpowers:verification-before-completion` | About to claim something works | Run the command and read the output before saying so |
| `/simplify` | After an implementation lands | Reuse, quality and efficiency of the changed code. Quality only — it does not hunt bugs |
| `/code-review` | Before merging, or on request | Correctness review at a chosen effort level |
| `audit-asserts` | Periodic test sweeps | Finds tests whose assertions do not match their names |
| `claude-mem:smart-explore` | Understanding unfamiliar structure | Tree-sitter outlines instead of reading whole files |
| `claude-mem:mem-search` | Resuming earlier work | Cross-session memory: "how did we do this last time?" |
| `code-review:*` agents | After a substantial feature | `security-auditor`, `contracts-reviewer`, `bug-hunter`, `test-coverage-reviewer`, dispatched via the Agent tool |

### Verifying this project

```bash
uv run python -m black .                       # formatting
uv run pyright                                 # strict, must be zero errors
uv run pytest tests/unit                       # no network
uv run pytest tests/integration                # real worker subprocesses
```

The pre-commit hook runs Talisman, Black, the `Any`/`object` ban, Pyright and the unit suite,
so a commit that passes has been through all of them. Two integration tests are gated and
skipped by default:

```bash
ANCALAGON_LIVE=1 uv run pytest tests/integration              # a funded model
ANCALAGON_LOCAL_MODEL=ollama_chat/qwen2.5:14b uv run pytest tests/integration
```

### Talisman

If Talisman flags a false positive, prefer rewording the flagged line when the wording is
incidental; suppress when it is not.

**Only the first `.talismanrc` entry per filename is honoured.** A second entry for a file
already listed is ignored, and the stale first one keeps failing the commit. So **append** an
entry for a newly flagged file, but **replace the checksum in place** for a file already listed
whose content has changed. Never remove an entry for a file that still needs suppressing.

Use the checksum Talisman reports, not one computed with `shasum` — it does not compute them the
same way.
