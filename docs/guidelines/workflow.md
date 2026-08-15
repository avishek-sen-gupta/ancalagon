## Workflow

### Phases (mandatory, in order)

Every non-trivial task goes through these phases. Do not skip. Do not start implementing before completing brainstorm.

1. **Brainstorm** — **Always invoke the `superpowers:brainstorming` skill first.** Read the relevant code. Check how the existing system handles similar cases. Identify at least two approaches and their trade-offs. Ask: "does the system already have infrastructure for this?" Consider whether an open-source project already solves the problem.
2. **Plan** — Choose an approach. For features spanning multiple modules, identify independently-committable units and their order. Use the `superpowers:writing-plans` skill for multi-step tasks.
3. **Test first** — Write failing tests that define the expected behaviour. No implementation code until at least one test exists.
4. **Implement** — Write the minimum code to make the tests pass.
5. **Self-review** — Before verifying, review your own diff. Check against the Guardrails in CLAUDE.md and the Design Principles. Look for: comments that shouldn't exist, workaround guards, mutation in loops, weak assertions, speculative abstractions.
6. **Verify** — `uv run python -m black . && uv run pyright && uv run python -m pytest tests/`. All checks must pass. The pre-commit hook runs these too, so a rejected commit means one of them failed rather than something new.
7. **Commit** — One logical unit per commit.

When asked to audit or show issues, only report findings — do not fix unless explicitly asked.

### Complexity classification

Classify before starting. This determines how much ceremony is needed.

- **Light** (< 50 lines, single file, no new abstractions) — brief brainstorm.
- **Standard** (50–300 lines, 2–5 files, follows existing patterns) — brainstorm identifies the pattern being followed.
- **Heavy** (300+ lines, new abstractions, multiple subsystems) — brainstorm must produce a written design with trade-offs before any code. Break into independently-committable units. Do not attempt in a single pass. Re-read actual code before each phase — design documents can anchor you to a flawed model.

### Commits and state

- One logical unit per commit. Each commit must have its own tests.
- Update README and other living docs if the diff changes public behaviour, adds features, or modifies architecture. This is part of the commit, not a follow-up.
- Leave the working directory clean. No uncommitted files.
- Prefer a committed partial result over an uncommitted complete attempt.

### Data security

- **NEVER reference external codebases under analysis** (names, APIs, domains, packages, class names, organisation names) in any tracked artifact: commit messages, specs, plans, docs, test names, screenshots.
- Use generic examples (`com.example.utils`, `class Foo`) instead of real names from codebases being analysed.
- Keep external-codebase-specific context in untracked experiment directories only.
- The consequences of leaking proprietary identifiers into public git history are catastrophic.

This matters more here than in most projects: the harness exists to analyse other people's code, and its workspace, transcripts, and task bus will be full of it.

### Documentation

- Never modify files in `docs/superpowers/specs/` or `docs/superpowers/plans/`.
- Update living documentation (README, design docs) instead.
