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
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.run_settings import RunSettings
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

    spec = AgentSpec[NodeSummary](
        task_id="node_7",
        behaviour="You summarise.",
        goal="Summarise this node.",
        input=NodeSummary(text="body", confidence=1),
        input_schema=ClassRef(module="node_summary.py", name="NodeSummary"),
        answer_schema=ClassRef(module="node_summary.py", name="NodeSummary"),
        budget=budget,
    )
    assert spec.tools == []
    assert AgentSpec[NodeSummary].model_validate_json(spec.model_dump_json()) == spec

    written = spec.model_dump_json()
    assert TaskSpec.model_validate_json(written).input_schema == ClassRef(
        module="node_summary.py", name="NodeSummary"
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

    module = tmp_path / "verdict.py"
    module.write_text("import pydantic\n\n\nclass Verdict(pydantic.BaseModel):\n    ok: bool\n")
    resolved = resolve_class(ClassRef(module=str(module), name="Verdict"))
    with pytest.raises(pydantic.ValidationError):
        ClassRef(module=str(module), name="not a class")
    assert resolved.__name__ == "Verdict"
    assert resolved.model_validate_json('{"ok": true}').model_dump() == {"ok": True}

    assert FreeText(text="plain").text == "plain"


def test_run_settings_require_a_contract_module_and_its_class_together():
    named = RunSettings(contract_module="shape.py", contract_class="Answer")
    assert (named.contract_module, named.contract_class) == ("shape.py", "Answer")
    assert (RunSettings().contract_module, RunSettings().contract_class) == ("", "")

    with pytest.raises(pydantic.ValidationError):
        RunSettings(contract_module="shape.py")
    with pytest.raises(pydantic.ValidationError):
        RunSettings(contract_class="Answer")


def test_a_role_defaults_to_prose_and_resolves_the_contracts_it_names(tmp_path: pathlib.Path):
    module = tmp_path / "shapes.py"
    module.write_text("import pydantic\n\n\nclass Component(pydantic.BaseModel):\n    name: str\n")

    prose = Role(
        behaviour="Investigate.", tools=("read_file",), budget=Budget(turns=4, tool_calls=8)
    )
    assert resolve_class(prose.input) is FreeText
    assert resolve_class(prose.answer) is FreeText

    named = Role(
        behaviour="Analyse.",
        answer=ClassRef(module=str(module), name="Component"),
        tools=("read_file",),
        budget=Budget(turns=4, tool_calls=8),
    )
    assert resolve_class(named.answer).model_fields.keys() == {"name"}
    assert resolve_class(named.input) is FreeText

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "shapes.py").write_text(
        "import pydantic\n\n\nclass Shape(pydantic.BaseModel):\n    width: int\n"
    )
    (dir_b / "shapes.py").write_text(
        "import pydantic\n\n\nclass Shape(pydantic.BaseModel):\n    height: int\n"
    )
    ref_a = ClassRef(module=str(dir_a / "shapes.py"), name="Shape")
    ref_b = ClassRef(module=str(dir_b / "shapes.py"), name="Shape")

    shape_a = resolve_class(ref_a)
    shape_b = resolve_class(ref_b)
    shape_a_again = resolve_class(ref_a)

    assert shape_a.model_fields.keys() == {"width"}
    assert shape_b.model_fields.keys() == {"height"}
    assert shape_a_again is shape_a

    with pytest.raises(AttributeError):
        resolve_class(ClassRef(module=str(module), name="Absent"))
