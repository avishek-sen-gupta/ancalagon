import collections.abc
import pathlib

import pydantic
import pytest

from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.outcome import outcome_adapter
from ancalagon.contracts.outcome_header import OutcomeHeader
from ancalagon.contracts.outcome_kind import OutcomeKind
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_use import ToolUse


class NodeSummary(pydantic.BaseModel):
    text: str
    confidence: int


def test_contracts_round_trip_and_budget_arithmetic(tmp_path: pathlib.Path):
    budget = Budget(turns=3, tool_calls=10)
    assert budget.spend_turn() == Budget(turns=2, tool_calls=10)
    assert budget.spend_tool_calls() == Budget(turns=3, tool_calls=9)
    assert budget.spend_tool_calls(4) == Budget(turns=3, tool_calls=6)
    assert budget.spend_tool_calls(0) == budget
    assert Budget(turns=0, tool_calls=5).turns_exhausted is True

    role = Role(
        behaviour="You summarise.",
        input=ClassRef(module="node_summary", name="NodeSummary"),
        answer=ClassRef(module="node_summary", name="NodeSummary"),
        tools=(),
        budget=budget,
    )
    spec = AgentSpec[NodeSummary](
        task_id="node_7",
        role=role,
        goal="Summarise this node.",
        input=NodeSummary(text="body", confidence=1),
    )
    assert spec.role.tools == ()
    assert AgentSpec[NodeSummary].model_validate_json(spec.model_dump_json()) == spec

    written = spec.model_dump_json()
    assert TaskSpec.model_validate_json(written).role.input == ClassRef(
        module="node_summary", name="NodeSummary"
    )
    assert AgentSpec[NodeSummary].model_validate_json(written).input.confidence == 1

    prose = spec.model_copy(update={"input": FreeText(text="body")}).model_dump_json()
    assert AgentSpec[FreeText].model_validate_json(prose).input.text == "body"
    with pytest.raises(pydantic.ValidationError):
        AgentSpec[NodeSummary].model_validate_json(prose)

    message = Message(
        role=MessageRole.ASSISTANT,
        blocks=[Text(text="hi"), ToolUse(id="tu_1", name="ripgrep", arguments='{"pattern":"x"}')],
        agent=17,
        seq=0,
        ts="2026-08-03T00:00:00Z",
    )
    restored = Message.model_validate_json(message.model_dump_json())
    assert restored == message
    assert isinstance(restored.blocks[1], ToolUse)
    assert restored.blocks[1].arguments == '{"pattern":"x"}'

    adapter = outcome_adapter(NodeSummary)
    completed = Completed[NodeSummary](
        value=NodeSummary(text="done", confidence=2),
        summary="finished",
        spent=Budget(turns=1, tool_calls=2),
    )
    assert adapter.validate_json(completed.model_dump_json()) == completed
    failed = Failed(error="boom", summary="died", spent=Budget(turns=0, tool_calls=0))
    assert adapter.validate_json(failed.model_dump_json()) == failed

    assert FreeText(text="plain").text == "plain"


def test_run_settings_default_to_empty_and_carry_a_role_name():
    named = RunSettings(input_file="input.json", role="analyst")
    assert (named.input_file, named.role) == ("input.json", "analyst")
    assert (RunSettings().input_file, RunSettings().role) == ("", "")


def test_a_role_defaults_to_prose_and_resolves_the_contracts_it_names(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "shapekit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "shapes.py").write_text(
        "import pydantic\n\n\nclass Component(pydantic.BaseModel):\n    name: str\n"
    )
    importable(tmp_path)

    prose = Role(
        behaviour="Investigate.", tools=("read_file",), budget=Budget(turns=4, tool_calls=8)
    )
    assert resolve_class(prose.input) is FreeText
    assert resolve_class(prose.answer) is FreeText

    named = Role(
        behaviour="Analyse.",
        answer=ClassRef(module="shapekit.shapes", name="Component"),
        tools=("read_file",),
        budget=Budget(turns=4, tool_calls=8),
    )
    component = resolve_class(named.answer)
    fields = set(component.model_fields)
    assert fields == {"name"}
    assert resolve_class(named.answer) is component
    assert resolve_class(named.input) is FreeText

    with pytest.raises(pydantic.ValidationError):
        ClassRef(module="shapekit.shapes", name="not a class")
    with pytest.raises(pydantic.ValidationError):
        ClassRef(module="./shapekit/shapes.py", name="Component")
    with pytest.raises(pydantic.ValidationError):
        ClassRef(module=str(tmp_path / "shapekit" / "shapes.py"), name="Component")

    with pytest.raises(AttributeError):
        resolve_class(ClassRef(module="shapekit.shapes", name="Absent"))
    with pytest.raises(ModuleNotFoundError):
        resolve_class(ClassRef(module="shapekit.absent", name="Component"))


def test_an_outcome_header_reads_the_kind_from_any_outcome():
    completed = Completed[FreeText](
        value=FreeText(text="done"), summary="done", spent=Budget(turns=1, tool_calls=2)
    )
    completed_header = OutcomeHeader.model_validate_json(completed.model_dump_json())
    assert completed_header.kind == OutcomeKind.COMPLETED
    assert completed_header.summary == "done"

    failed = Failed(error="boom", summary="boom", spent=Budget(turns=0, tool_calls=0))
    failed_header = OutcomeHeader.model_validate_json(failed.model_dump_json())
    assert failed_header.kind == OutcomeKind.FAILED
    assert failed_header.summary == "boom"
