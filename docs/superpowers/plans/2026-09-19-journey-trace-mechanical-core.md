# Journey Trace Mechanical Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given a `buildcg` call graph, an entry method and an outcome method, answer whether a bridge is needed at all and, if it is, produce the candidate backward roots with mechanical dismissals applied.

**Architecture:** A new `ancalagon.journey` package holding a functional core: a typed reader that turns `callgraph.json` into a `CallGraph` of `MethodRef` at the file boundary, forward reachability, graph inversion, backward roots, root dismissal, and the span verifier for a `Bridge`. No model calls and no Java toolchain — every input is a JSON file and every output is a value.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, uv. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-19-journey-trace-bridging-design.md`

## Scope

The spec covers more than one plan's worth of work. This plan implements the parts that need
neither a model nor an external process — spec sections **Search strategy** steps 1 and 2,
**Root ranking** (the dismissal half), and verifier 1 of **Verification**.

Deferred to later plans, each of which depends on this one:

- **Plan 2 — root classification and invoker search.** Spec steps 3 and 4. Needs source-level
  facts (annotations, supertypes, config files), so it depends on `symbol-types` and the J2EE
  extractors being callable.
- **Plan 3 — the search loop and model touch points.** Spec step 5, **Anchors**, **Ambiguity**,
  **Granularity**. Needs plan 2 and the `LLM` protocol.

## Global Constraints

Copied from `CLAUDE.md` and `docs/guidelines/`. Every task's requirements include these.

- Python `>=3.13`. All commands run under `uv run`.
- Pyright strict, zero errors. `Any` and `object` annotations are banned outright.
- Every generic is parameterised: `dict[str, int]`, never bare `dict`.
- No comments except a one-line header on a module or class stating its purpose. No docstrings.
- All Pydantic models `frozen=True`. All dataclasses `frozen=True`.
- One class per file. Fully qualified imports, no relative imports. No static methods.
- No `None` defaults, no `None` returns, no defensive `is not None` guards.
- `Sequence`/`Mapping` from `collections.abc` for parameters that are not mutated.
- Functional style: comprehensions over `for` loops with mutation. Early return.
- Black line length 100.
- Only `ancalagon/fs/real_file_system.py` may touch a file. Everything else takes a
  `FileSystem` and annotates paths as `pathlib.PurePath`.
- Tests live in `tests/unit/test_journey.py`, flat, matching the suite's existing layout. Few
  tests, each covering a whole behaviour, with concrete value assertions.
- Never name a real external codebase in a tracked artifact. Test data uses `com.example.*`.
- Verify with `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`.

## File Structure

| File | Responsibility |
|---|---|
| `ancalagon/contracts/method_ref.py` | `MethodRef` — one method, split into declaring class and subsignature |
| `ancalagon/contracts/call_graph_file.py` | `CallGraphFile` — the wire shape of `callgraph.json`, the single validated boundary |
| `ancalagon/contracts/call_graph.py` | `CallGraph` — the domain adjacency, keyed by `MethodRef` |
| `ancalagon/contracts/bridge.py` | `Bridge` — a claimed link with its evidence and rationale |
| `ancalagon/journey/parse_method_ref.py` | signature text to `MethodRef` |
| `ancalagon/journey/read_call_graph.py` | file to `CallGraph` |
| `ancalagon/journey/reachable_from.py` | transitive closure over a `CallGraph` |
| `ancalagon/journey/inverted.py` | a `CallGraph` with every edge reversed |
| `ancalagon/journey/backward_roots.py` | methods reaching an outcome that nothing in-project calls |
| `ancalagon/journey/on_a_journey.py` | mechanical dismissal of roots that cannot be on a journey |
| `ancalagon/journey/spans_hold.py` | verifier 1 — cited spans exist and contain the cited text |
| `tests/unit/test_journey.py` | the whole suite for this package |

---

### Task 1: MethodRef and its parser

**Files:**
- Create: `ancalagon/contracts/method_ref.py`
- Create: `ancalagon/journey/__init__.py`
- Create: `ancalagon/journey/parse_method_ref.py`
- Create: `tests/unit/test_journey.py`
- Modify: `pyproject.toml` — add `ancalagon.journey` to the layers contract

**Interfaces:**
- Consumes: nothing.
- Produces: `MethodRef(declaring_class: str, subsignature: str)` with `text() -> str`;
  `parse_method_ref(signature: str) -> MethodRef`.

`buildcg` writes every method as `<com.example.OrderService: void process(int)>`. The colon-space
separates the declaring class from the subsignature, and the class part contains no colon.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_journey.py`:

```python
import pytest

from ancalagon.journey.parse_method_ref import parse_method_ref


def test_parses_a_signature_into_class_and_subsignature_and_back():
    ref = parse_method_ref("<com.example.OrderService: void process(int,java.lang.String)>")

    assert ref.declaring_class == "com.example.OrderService"
    assert ref.subsignature == "void process(int,java.lang.String)"
    assert ref.text() == "<com.example.OrderService: void process(int,java.lang.String)>"

    with pytest.raises(ValueError):
        parse_method_ref("com.example.OrderService.process")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.journey'`

- [ ] **Step 3: Write minimal implementation**

Create `ancalagon/contracts/method_ref.py`:

```python
# One method as the call graph names it, split into its declaring class and its subsignature.
import pydantic


class MethodRef(pydantic.BaseModel, frozen=True):
    declaring_class: str = pydantic.Field(
        min_length=1, description="Fully qualified name of the class declaring the method."
    )
    subsignature: str = pydantic.Field(
        min_length=1, description="Return type, name and parameter types, as buildcg writes them."
    )

    def text(self) -> str:
        return f"<{self.declaring_class}: {self.subsignature}>"
```

Create `ancalagon/journey/__init__.py` as an empty file.

Create `ancalagon/journey/parse_method_ref.py`:

```python
# The one place a call graph's method signature stops being text.
import re

from ancalagon.contracts.method_ref import MethodRef


class Signature:
    PATTERN = re.compile(r"^<(?P<declaring_class>[^:]+): (?P<subsignature>.+)>$")


def parse_method_ref(signature: str) -> MethodRef:
    matched = Signature.PATTERN.match(signature)
    if not matched:
        raise ValueError(f"not a method signature: {signature}")
    return MethodRef(
        declaring_class=matched.group("declaring_class"),
        subsignature=matched.group("subsignature"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: PASS

- [ ] **Step 5: Add the package to the layers contract**

In `pyproject.toml`, in the `[[tool.importlinter.contracts]]` block named
`"Layers point downward"`, insert `"ancalagon.journey",` on its own line immediately after
`"ancalagon.attempt",`. This places the package above `llm`, `workspace`, `config`, `contracts`,
`fs` and `text`, all of which it may import, and below everything that might later import it.

- [ ] **Step 6: Verify and commit**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`
Expected: Black reformats nothing of substance, Pyright reports 0 errors, tests pass, all
import contracts kept.

```bash
git add ancalagon/contracts/method_ref.py ancalagon/journey tests/unit/test_journey.py pyproject.toml
git commit -m "Parse a call graph method signature into a typed reference"
```

---

### Task 2: Read a call graph into typed adjacency

**Files:**
- Create: `ancalagon/contracts/call_graph_file.py`
- Create: `ancalagon/contracts/call_graph.py`
- Create: `ancalagon/journey/read_call_graph.py`
- Modify: `tests/unit/test_journey.py`

**Interfaces:**
- Consumes: `MethodRef`, `parse_method_ref` from Task 1.
- Produces: `CallGraph(callees: dict[MethodRef, tuple[MethodRef, ...]])`;
  `read_call_graph(files: FileSystem, path: pathlib.PurePath) -> CallGraph`.

`callgraph.json` has three top-level fields — `callees`, `callsites`, `methodLines`. Only `callees`
is needed here, and Pydantic ignores the rest. `callsites` and `methodLines` are deliberately
left undeclared until a later plan needs them.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_journey.py`:

```python
import json
import pathlib

from ancalagon.contracts.method_ref import MethodRef
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.journey.read_call_graph import read_call_graph


def controller() -> MethodRef:
    return MethodRef(declaring_class="com.example.Controller", subsignature="void handle()")


def service() -> MethodRef:
    return MethodRef(declaring_class="com.example.Service", subsignature="void process()")


def repository() -> MethodRef:
    return MethodRef(declaring_class="com.example.Repository", subsignature="void save()")


def write_graph(tmp_path: pathlib.Path, edges: dict[str, list[str]]) -> pathlib.Path:
    path = tmp_path / "callgraph.json"
    path.write_text(
        json.dumps({"callees": edges, "callsites": {}, "methodLines": {}}), encoding="utf-8"
    )
    return path


def test_reads_callees_into_typed_adjacency_and_ignores_other_fields(tmp_path: pathlib.Path):
    path = write_graph(
        tmp_path,
        {controller().text(): [service().text()], service().text(): [repository().text()]},
    )

    graph = read_call_graph(RealFileSystem(), path)

    assert graph.callees == {
        controller(): (service(),),
        service(): (repository(),),
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.journey.read_call_graph'`

- [ ] **Step 3: Write minimal implementation**

Create `ancalagon/contracts/call_graph_file.py`:

```python
# The shape of callgraph.json on disk, and the single place its text is validated.
import pydantic


class CallGraphFile(pydantic.BaseModel, frozen=True):
    callees: dict[str, tuple[str, ...]]
```

Create `ancalagon/contracts/call_graph.py`:

```python
# Who calls whom, with every method a typed reference rather than a signature string.
import pydantic

from ancalagon.contracts.method_ref import MethodRef


class CallGraph(pydantic.BaseModel, frozen=True):
    callees: dict[MethodRef, tuple[MethodRef, ...]]
```

Create `ancalagon/journey/read_call_graph.py`:

```python
# The boundary where a call graph file becomes a value.
import pathlib

from ancalagon.contracts.call_graph import CallGraph
from ancalagon.contracts.call_graph_file import CallGraphFile
from ancalagon.fs.file_system import FileSystem
from ancalagon.journey.parse_method_ref import parse_method_ref


def read_call_graph(files: FileSystem, path: pathlib.PurePath) -> CallGraph:
    wire = CallGraphFile.model_validate_json(files.read_text(path))
    return CallGraph(
        callees={
            parse_method_ref(caller): tuple(parse_method_ref(target) for target in targets)
            for caller, targets in wire.callees.items()
        }
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: PASS

- [ ] **Step 5: Mutation-check the test**

Break the implementation in two ways and confirm the test fails each time, then restore it:

1. In `read_call_graph`, drop the `parse_method_ref` wrapping the caller so it reads `caller:`. Expected:
   Pyright error, or a `ValidationError` at `CallGraph` construction.
2. Declare `callsites` on `CallGraphFile` as a required field. Expected: still passes — which
   confirms the test does not depend on the ignored fields. Undo it.

- [ ] **Step 6: Verify and commit**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`
Expected: all pass.

```bash
git add ancalagon/contracts/call_graph_file.py ancalagon/contracts/call_graph.py ancalagon/journey/read_call_graph.py tests/unit/test_journey.py
git commit -m "Read a call graph file into typed adjacency"
```

---

### Task 3: Forward reachability and the bridge-needed test

**Files:**
- Create: `ancalagon/journey/reachable_from.py`
- Modify: `tests/unit/test_journey.py`

**Interfaces:**
- Consumes: `CallGraph`, `MethodRef` from Task 2.
- Produces: `reachable_from(graph: CallGraph, entry: MethodRef) -> frozenset[MethodRef]`.

This is spec step 1: expand callees forward from the entry once, then test membership of the
outcome. A cycle in the graph must terminate, which the `- seen` subtraction handles.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_journey.py`:

```python
from ancalagon.contracts.call_graph import CallGraph
from ancalagon.journey.reachable_from import reachable_from


def test_forward_reachability_is_transitive_includes_the_entry_and_survives_cycles():
    graph = CallGraph(
        callees={
            controller(): (service(),),
            service(): (repository(), controller()),
        }
    )

    assert reachable_from(graph, controller()) == frozenset(
        {controller(), service(), repository()}
    )
    assert reachable_from(graph, repository()) == frozenset({repository()})
    assert repository() in reachable_from(graph, controller())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.journey.reachable_from'`

- [ ] **Step 3: Write minimal implementation**

Create `ancalagon/journey/reachable_from.py`:

```python
# Everything a method transitively calls, itself included.
from ancalagon.contracts.call_graph import CallGraph
from ancalagon.contracts.method_ref import MethodRef


def reachable_from(graph: CallGraph, entry: MethodRef) -> frozenset[MethodRef]:
    return expanded(graph, frozenset({entry}), frozenset({entry}))


def expanded(
    graph: CallGraph, seen: frozenset[MethodRef], frontier: frozenset[MethodRef]
) -> frozenset[MethodRef]:
    if not frontier:
        return seen
    found = frozenset(
        target for method in frontier for target in graph.callees.get(method, ())
    )
    return expanded(graph, seen | found, found - seen)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: PASS

- [ ] **Step 5: Mutation-check the test**

Break the implementation in two ways and confirm the test fails each time, then restore it:

1. Change `expanded(graph, seen | found, found - seen)` to `expanded(graph, seen | found, found)`.
   Expected: `RecursionError` on the cyclic graph.
2. Change `reachable_from` to seed with `frozenset()` instead of `frozenset({entry})`.
   Expected: the `reachable_from(graph, repository())` assertion fails.

- [ ] **Step 6: Verify and commit**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`
Expected: all pass.

```bash
git add ancalagon/journey/reachable_from.py tests/unit/test_journey.py
git commit -m "Expand callees forward from an entry method"
```

---

### Task 4: Graph inversion and backward roots

**Files:**
- Create: `ancalagon/journey/inverted.py`
- Create: `ancalagon/journey/backward_roots.py`
- Modify: `tests/unit/test_journey.py`

**Interfaces:**
- Consumes: `CallGraph`, `MethodRef`, `reachable_from` from Tasks 2 and 3.
- Produces: `inverted(graph: CallGraph) -> CallGraph`;
  `backward_roots(graph: CallGraph, outcome: MethodRef) -> frozenset[MethodRef]`.

This is spec step 2. Backward expansion is the forward expansion run over the inverted graph, so
`reachable_from` is reused rather than mirrored. A root is a method in that backward set with no
entry in the inverted adjacency — nothing in-project calls it. The outcome is its own root when
nothing calls it.

`inverted` is quadratic in the number of edges. That is knowingly accepted: it is called once per
round of the search, and correctness is what this task is for. If it becomes the bottleneck, fix
it then, with a benchmark.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_journey.py`:

```python
from ancalagon.journey.backward_roots import backward_roots
from ancalagon.journey.inverted import inverted


def listener() -> MethodRef:
    return MethodRef(declaring_class="com.example.Listener", subsignature="void onMessage()")


def test_inversion_reverses_every_edge_and_roots_are_the_uncalled_callers():
    graph = CallGraph(
        callees={
            controller(): (service(),),
            listener(): (service(),),
            service(): (repository(),),
        }
    )

    assert inverted(graph).callees == {
        service(): (controller(), listener()),
        repository(): (service(),),
    }
    assert backward_roots(graph, repository()) == frozenset({controller(), listener()})
    assert backward_roots(graph, controller()) == frozenset({controller()})
```

Note: `inverted` must produce callers in the order their callers appear in `graph.callees`, which
for a dict literal is insertion order, so `(controller(), listener())` is deterministic.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.journey.backward_roots'`

- [ ] **Step 3: Write minimal implementation**

Create `ancalagon/journey/inverted.py`:

```python
# The same call graph with every edge reversed, so callers can be walked like callees.
from ancalagon.contracts.call_graph import CallGraph
from ancalagon.contracts.method_ref import MethodRef


def inverted(graph: CallGraph) -> CallGraph:
    targets = frozenset(
        target for targets in graph.callees.values() for target in targets
    )
    return CallGraph(
        callees={target: callers_of(graph, target) for target in targets}
    )


def callers_of(graph: CallGraph, target: MethodRef) -> tuple[MethodRef, ...]:
    return tuple(caller for caller, targets in graph.callees.items() if target in targets)
```

Create `ancalagon/journey/backward_roots.py`:

```python
# Methods that reach an outcome but that nothing in the project calls.
from ancalagon.contracts.call_graph import CallGraph
from ancalagon.contracts.method_ref import MethodRef
from ancalagon.journey.inverted import inverted
from ancalagon.journey.reachable_from import reachable_from


def backward_roots(graph: CallGraph, outcome: MethodRef) -> frozenset[MethodRef]:
    backward = inverted(graph)
    return frozenset(
        method
        for method in reachable_from(backward, outcome)
        if not backward.callees.get(method, ())
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: PASS

- [ ] **Step 5: Mutation-check the test**

Break the implementation in two ways and confirm the test fails each time, then restore it:

1. In `backward_roots`, drop the `if not backward.callees.get(method, ())` filter. Expected: the
   root assertion fails because `service()` and `repository()` are included.
2. In `inverted`, swap `caller` and `target` in the `callers_of` comprehension. Expected: the
   inversion assertion fails.

- [ ] **Step 6: Verify and commit**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`
Expected: all pass.

```bash
git add ancalagon/journey/inverted.py ancalagon/journey/backward_roots.py tests/unit/test_journey.py
git commit -m "Find the backward roots that reach an outcome"
```

---

### Task 5: Dismiss roots that cannot be on a journey

**Files:**
- Create: `ancalagon/journey/on_a_journey.py`
- Modify: `tests/unit/test_journey.py`

**Interfaces:**
- Consumes: `MethodRef` from Task 1.
- Produces: `on_a_journey(root: MethodRef) -> bool`.

This is the mechanical half of spec **Root ranking**. Only the dismissals the call graph alone
supports belong here: a program entry point and a static initialiser are never on a user journey.
The annotation- and path-based dismissals in the spec — `@Scheduled`, lifecycle callbacks, the
test source tree — need source facts and belong to Plan 2, not here. Do not stub them.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_journey.py`:

```python
from ancalagon.journey.on_a_journey import on_a_journey


def test_program_entry_points_and_static_initialisers_are_dismissed():
    main = MethodRef(
        declaring_class="com.example.App", subsignature="void main(java.lang.String[])"
    )
    initialiser = MethodRef(declaring_class="com.example.App", subsignature="void <clinit>()")

    assert not on_a_journey(main)
    assert not on_a_journey(initialiser)
    assert on_a_journey(controller())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.journey.on_a_journey'`

- [ ] **Step 3: Write minimal implementation**

Create `ancalagon/journey/on_a_journey.py`:

```python
# Whether a backward root could be on a user journey at all, judged from its signature alone.
from ancalagon.contracts.method_ref import MethodRef


class NeverOnAJourney:
    SUBSIGNATURES = frozenset({"void main(java.lang.String[])", "void <clinit>()"})


def on_a_journey(root: MethodRef) -> bool:
    return root.subsignature not in NeverOnAJourney.SUBSIGNATURES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: PASS

- [ ] **Step 5: Verify and commit**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`
Expected: all pass.

```bash
git add ancalagon/journey/on_a_journey.py tests/unit/test_journey.py
git commit -m "Dismiss roots that no user journey can pass through"
```

---

### Task 6: The Bridge record and its span verifier

**Files:**
- Create: `ancalagon/contracts/bridge.py`
- Create: `ancalagon/journey/spans_hold.py`
- Modify: `tests/unit/test_journey.py`

**Interfaces:**
- Consumes: `MethodRef` from Task 1; the existing `Evidence` from
  `ancalagon/contracts/evidence.py`.
- Produces: `Bridge(invoker: MethodRef, root: MethodRef, evidence: tuple[Evidence, ...],
  rationale: str)`; `spans_hold(files: FileSystem, bridge: Bridge) -> bool`.

This is verifier 1 of spec **Verification**: the cited spans exist and contain the cited text.
`Evidence` already carries an absolute path, a one-based inclusive line range and the quoted
lines, so it is reused rather than reinvented.

A cited range that runs past the end of the file returns `False`. That is the verifier reporting
its verdict, not a defensive guard — reject it in review if it is written as a `try`/`except`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_journey.py`:

```python
from ancalagon.contracts.bridge import Bridge
from ancalagon.contracts.evidence import Evidence
from ancalagon.journey.spans_hold import spans_hold


def bridge_citing(path: pathlib.Path, start: int, end: int, quote: str) -> Bridge:
    return Bridge(
        invoker=controller(),
        root=service(),
        evidence=(Evidence(path=str(path), start_line=start, end_line=end, quote=quote),),
        rationale="the registry entry names the implementation",
    )


def test_a_span_holds_only_when_the_file_really_says_what_was_quoted(tmp_path: pathlib.Path):
    path = tmp_path / "registry.properties"
    path.write_text("alpha=one\nbeta=two\ngamma=three\n", encoding="utf-8")
    files = RealFileSystem()

    assert spans_hold(files, bridge_citing(path, 2, 2, "beta=two"))
    assert spans_hold(files, bridge_citing(path, 1, 2, "alpha=one\nbeta=two"))
    assert not spans_hold(files, bridge_citing(path, 2, 2, "beta=three"))
    assert not spans_hold(files, bridge_citing(path, 3, 9, "gamma=three"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.contracts.bridge'`

- [ ] **Step 3: Write minimal implementation**

Create `ancalagon/contracts/bridge.py`:

```python
# A claimed link across a break in the call graph, with what backs it and why it was chosen.
import pydantic

from ancalagon.contracts.evidence import Evidence
from ancalagon.contracts.method_ref import MethodRef


class Bridge(pydantic.BaseModel, frozen=True):
    invoker: MethodRef = pydantic.Field(
        description="The method on the forward side that reaches the root."
    )
    root: MethodRef = pydantic.Field(
        description="The backward root the invoker is claimed to reach."
    )
    evidence: tuple[Evidence, ...] = pydantic.Field(
        min_length=1, description="The spans that back the claim, at least one."
    )
    rationale: str = pydantic.Field(
        min_length=1,
        description="Why this candidate was selected over the others, never why the link exists.",
    )
```

Create `ancalagon/journey/spans_hold.py`:

```python
# Verifier one: every span a bridge cites exists and contains the text it quoted.
import pathlib

from ancalagon.contracts.bridge import Bridge
from ancalagon.contracts.evidence import Evidence
from ancalagon.fs.file_system import FileSystem


def spans_hold(files: FileSystem, bridge: Bridge) -> bool:
    return all(span_holds(files, cited) for cited in bridge.evidence)


def span_holds(files: FileSystem, cited: Evidence) -> bool:
    lines = files.read_text(pathlib.PurePath(cited.path)).splitlines()
    if cited.end_line > len(lines) or cited.end_line < cited.start_line:
        return False
    return "\n".join(lines[cited.start_line - 1 : cited.end_line]) == cited.quote.rstrip("\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_journey.py -v`
Expected: PASS

- [ ] **Step 5: Mutation-check the test**

Break the implementation in two ways and confirm the test fails each time, then restore it:

1. Change the slice to `lines[cited.start_line : cited.end_line]`. Expected: the
   `spans_hold(files, bridge_citing(path, 2, 2, "beta=two"))` assertion fails.
2. Drop the `cited.end_line > len(lines)` check. Expected: the last assertion fails, because the
   out-of-range slice silently truncates to `"gamma=three"` and compares equal.

- [ ] **Step 6: Verify and commit**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`
Expected: all pass.

```bash
git add ancalagon/contracts/bridge.py ancalagon/journey/spans_hold.py tests/unit/test_journey.py
git commit -m "Verify that a bridge's cited spans say what it quoted"
```

---

### Task 7: Document the package

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: nothing in code.

`docs/guidelines/code-review.md` makes `README.md` and `docs/architecture.md` part of the commit
that changes behaviour, not a follow-up. This plan adds a package, so both change once, here, at
the end, when the package's shape is settled.

- [ ] **Step 1: Read what is there**

Run: `grep -n "^## \|^### " README.md docs/architecture.md`

Find the section each file uses to list packages or subsystems. Follow that file's existing
heading depth and prose style — do not invent a new section shape.

- [ ] **Step 2: Add the package to `docs/architecture.md`**

Write a short subsection for `ancalagon.journey`, matching the surrounding entries in length and
tone, stating: it is a functional core with no I/O of its own beyond an injected `FileSystem`; it
answers whether a bridge is needed between an entry and an outcome in a `buildcg` call graph, and
produces the candidate backward roots when one is; and it implements spec steps 1 and 2 of
`docs/superpowers/specs/2026-09-19-journey-trace-bridging-design.md`, with classification, the
search loop and the remaining verifiers still to come.

- [ ] **Step 3: Add the package to `README.md`**

Add one line in the same place and format the README already uses to name packages.

- [ ] **Step 4: Verify and commit**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`
Expected: all pass.

```bash
git add README.md docs/architecture.md
git commit -m "Document the journey package"
```

---

## Self-Review

**Spec coverage.**

| Spec section | Task | Status |
|---|---|---|
| Search strategy, step 1 | 3 | covered — `reachable_from` plus a membership test |
| Search strategy, step 2 | 4 | covered — `inverted`, `backward_roots` |
| Search strategy, steps 3–5 | — | deferred to Plans 2 and 3, declared in Scope |
| Verification, verifier 1 | 6 | covered — `spans_hold` |
| Verification, verifiers 2–4 | — | deferred to Plan 2, declared in Scope |
| Anchors | — | deferred to Plan 3, declared in Scope |
| Artifact (the segment graph) | 6 | partial — `Bridge` exists; the graph that holds bridges is Plan 3 |
| Ambiguity | — | deferred to Plan 3, declared in Scope |
| Granularity (CFG refinement) | — | deferred to Plan 3, declared in Scope |
| Root ranking, dismissal | 5 | partial by design — only the signature-based dismissals |
| Root ranking, ordering | — | deferred to Plan 3, declared in Scope |
| Division of labour | — | no model touch point in this plan, by scope |

**Type consistency.** `MethodRef` is constructed identically in every task. `CallGraph.callees`
is `dict[MethodRef, tuple[MethodRef, ...]]` in Tasks 2, 3 and 4. `reachable_from` returns
`frozenset[MethodRef]` and is consumed as one in Task 4. `Evidence` field names match
`ancalagon/contracts/evidence.py` as it exists: `path`, `start_line`, `end_line`, `quote`.

**Placeholders.** None. Every step carries the code or the exact command it asks for; Task 7 is
prose-only and says why, and names what to read before writing.

**Known gap carried from the spec.** Separating dead code and test fixtures from genuine
reflective targets is unsolved, and Task 5 deliberately implements only the two dismissals that
a signature alone justifies. Plan 2 inherits the problem.
