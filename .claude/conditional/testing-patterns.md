## Testing Patterns

See the Guardrails in CLAUDE.md first — few tests, each covering a whole behaviour. These patterns govern how those tests are written, not how many there are.

- **TDD:** Write failing tests first. For every bug fix, extend an existing behaviour test so it fails without the fix, rather than adding a new test file.
- **Review assertions after writing tests.** Replace weak assertions (`assert x is not None`, `assert "name" in result`, `assert len(items) > 0`) with concrete value assertions (`assert result == 30`, `assert items == [1, 2, 3]`). If a concrete assertion isn't possible, say why.
- **Unit vs integration:** Unit tests (no I/O, no network) in `tests/unit/`. Integration tests (real LLM calls, real subprocesses end-to-end) in `tests/integration/`.
- **Fixtures:** Use `pytest` fixtures and `tmp_path` for filesystem tests.
- **No mocking:** Do not use `unittest.mock.patch`. Use dependency injection with fake objects — `FakeLLM` with scripted replies, injected clocks, injected spawners.
- **Assertions are sacred:** Do not modify test assertions unless certain the change is valid. Do not remove assertions without review.
- **No implementation hacks for tests:** Never add special behaviour just to make tests pass. Document hard-to-implement behaviour or ask for guidance.
