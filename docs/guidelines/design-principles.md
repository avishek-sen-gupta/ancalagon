## Design Principles

- **Prefer a generic mechanism to specialised infrastructure.** When a use case arrives, ask
  first which existing contract can express it, not which new table, status or subsystem it
  needs. The supervisor's whole contract with a child is `Spawner.spawn(task_dir, agent_id)` and
  an `outcome-<agent>.json` it reads as two fields — nothing in it says the child is an agent, so
  a file watcher, a deterministic transform or a human gate that honours the same contract costs
  the supervisor nothing. Widen what may sit behind an interface before adding another interface
  beside it. A table, a status or a scheduling rule added for one use case is a commitment every
  later one pays for, and the slightly worse fit of the generic route is usually the cheaper
  trade.
- **Use existing infrastructure before adding new abstractions.** Ask: "does the system already have something that solves this?" The answer is usually yes.
- **Start from the simplest possible mechanism.** Begin with minimal intervention. Add complexity only when proven insufficient.
- **No speculative code without tests.** Every code path must have a test that exercises it.
- **Stay consistent with established patterns.** When the codebase has a way of doing something, use it.
- **Never mask bugs with workaround guards.** Don't add `is not None` checks to make tests pass. Fix the root cause.
- **Pass decisions through data, don't re-derive downstream.** If a decision was made upstream, attach it to the data.
- **Do not encode information in string representations.** Use typed objects. Never use string prefixes, patterns, or regex to deduce what a value represents — use `isinstance`.

## Programming Patterns

### Code style

- Functional programming style. Avoid `for` loops with mutations — use comprehensions, `map`, `filter`, `reduce`.
- Prefer early return. Use `if` for exceptional cases, not the happy path.
- Small, composable functions. No massive functions.
- Fully qualified imports. No relative imports.
- One class per file (dataclass or otherwise).
- Logging, not `print` statements.
- Constants instead of magic strings and numbers. Wrap globals in classes.
- Enums for fixed string sets, not raw strings.

### Types and values

- Dataclasses must use `frozen=True`. No exceptions.
- No defensive programming. No `None` checks, no generic exception handling. If unsure, pause and ask.
- No `None` as a default parameter. Use empty structures (`{}`, `[]`, `()`).
- No `None` returns from non-None return types. Use null object pattern.
- No mutation after construction. Inject all dependencies at construction time.
- Domain-appropriate wrapping types for data crossing function boundaries. Wrap/unwrap at boundary layers only.
- Resolve enums into executable objects early in the call chain, then inject as dependencies.
- Use `Sequence` and `Mapping` from `collections.abc` for parameters that should not be mutated — never annotate a parameter as `list` or `dict` if the function doesn't need to mutate it.

### Architecture

- Ports-and-adapters. Functional core, imperative shell.
- Mutable state is permitted only in the imperative shell (file writes, subprocess spawning, SQLite, LLM calls). The functional core receives and returns immutable values.
- The shell is named, not assumed. `Session` is shell — its messages, remaining budget and sequence number advance a turn at a time, and threading them through the loop as parameters would move the mutation without removing it. `ToolContext`'s output counter is shell for the same reason: one instance per worker process, advanced only from a sequential loop. Everything else that holds values is a frozen model, and a class claiming to be shell needs the same argument these two have.
- Dependency injection for external systems (LLM clients, file I/O, clocks, GUIDs, subprocess spawning).
- No static methods.
