# RedDragon — Agent Instructions

#import .claude/core/project-context.md
#import .claude/core/workflow.md
#import .claude/core/implementation.md
#import .claude/core/tools-search.md
#import .claude/conditional/design-principles.md
#import .claude/conditional/testing-patterns.md

## Guardrails

These override defaults and are not negotiable.

**No gold plating.** Build what was asked for and nothing more. No abstraction layers, extension points, configuration knobs, or generality that no current caller needs. Simple enough that a human reading it understands it without explanation.

**No comments.** The only permitted comment is a one-line header on a class or module stating its purpose. A comment anywhere else means the code failed to explain itself — rewrite the code instead of annotating it. No docstrings on functions, no inline explanations, no section dividers, no TODOs.

**Fully typed, no `Any`.** Pyright runs in strict mode and must pass with zero errors. `Any` is banned outright — no `from typing import Any`, no `: Any`, no `dict[str, Any]`. If a type is hard to express, use a `Protocol`, a `TypeVar`, or a union; if it is genuinely unknown at a boundary, parse it into a Pydantic model at that boundary. `Any` in a signature means the contract was never worked out.

**No bare collection types.** Every generic must be parameterised: `dict[str, int]`, not `dict`; `list[Node]`, not `list`; `tuple[int, str]`, not `tuple`. This applies to `Sequence`, `Mapping`, `set`, `frozenset`, and `Iterable` equally. Pyright strict enforces it via `reportMissingTypeArgument`.

**No `object` annotations, and no JSON-blob types.** `object`, `JsonValue`, `JsonDict`, `JsonObject`, and any hand-rolled recursive JSON alias are all `Any` with extra steps — they defer the contract instead of stating it. There is no intermediate JSON representation in this codebase.

JSON exists only as text in files. The moment it enters Python it becomes a concrete Pydantic model via `model_validate_json`. Where the model class is generated at runtime, the containing type is **generic** (`AgentSpec[InT]`, `Completed[OutT]`) and the class is resolved by import before validation — the type is not unknown, only late-bound. If you reach for a JSON type, you have skipped resolving it.

**Few tests, each covering a whole behaviour.** Aggregate assertions logically into single tests. One test per coherent behaviour, asserting everything that behaviour implies — not one test per assertion. A module with eight behaviours gets eight tests, not eighty.
