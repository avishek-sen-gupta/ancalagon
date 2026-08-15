## Code Review

### Self-review checklist

Before every commit, scan the diff for these:

- **Workaround guards** — `is not None`, bare `try/except`, or a branch added to make a test pass
  without understanding why it failed.
- **Weak assertions** — `assert x is not None` or `assert "name" in result` where a concrete
  value is available: `assert result == 30`.
- **Mutation in loops** — accumulators inside `for` loops instead of comprehensions, `map`,
  `filter` or `reduce`.
- **Stale documentation** — `README.md` and `docs/architecture.md` are living documents. If the
  diff changes what a run does, what a tool accepts, or what a file on disk contains, they change
  in the same commit.
- **Missing tests** — a new code path with no test, and in particular a new *tool* with none:
  `collect_task` went untested long enough to accumulate a dead branch and a wrong field.
- **Data as strings** — a `*_json` field, a hand-built dict standing in for a record, a
  `json.dumps` outside an adapter or a file write. See the boundary rules in `CLAUDE.md`.
- **Constraints hidden inside `run`** — a check a tool performs on its arguments that the model
  never sees, when it could have been a `pattern` or a `default` on the args model.
- **Dead code** — unused imports, unreachable branches, values assigned and never read, and
  machinery with no caller. `AgentSpec`, `outcome_adapter` and the `messages` table were each
  written, bypassed, and left behind.
- **Subprocess arguments** — a model-supplied string reaching `argv` where the child could read it
  as an option.

### Guards that read state

A guard that asks about an agent's *latest* status is almost always wrong. Statuses are appended,
not replaced, and a worker records its terminal status before it finishes writing and exits — so
the last event says `exited` and the interesting one is further back. Ask whether the history
*contains* what you care about, and ask it inside the transaction that acts on the answer.

### Requested reviews

When asked to review, use the Design Principles, Programming Patterns and Guardrails as the
rubric. Order findings by severity:

1. **CRITICAL** — a sandbox escape, a data-loss risk, a secret in a tracked artifact
2. **HIGH** — a likely bug, a broken invariant
3. **MEDIUM** — code quality, a contract that defers rather than states
4. **LOW** — minor improvements

Report findings only; do not fix during a review. Distinguish what was read from the code from
what was reproduced, and say which is which — an unverified reading is a hypothesis, and calling
it a bug wastes the reader's trust.
