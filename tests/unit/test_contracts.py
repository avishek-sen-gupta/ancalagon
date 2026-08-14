import pathlib

import pydantic
import pytest

from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.message import Message
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
    assert budget.slice(turns=1, tool_calls=4) == Budget(turns=1, tool_calls=4)
    assert Budget(turns=0, tool_calls=5).turns_exhausted is True
    with pytest.raises(ValueError):
        budget.slice(turns=99, tool_calls=1)

    spec = AgentSpec[NodeSummary](
        task_id="node_7",
        behaviour="You summarise.",
        goal="Summarise this node.",
        input=NodeSummary(text="body", confidence=1),
        input_schema="contracts.py:NodeSummary",
        answer_schema="contracts.py:NodeSummary",
        budget=budget,
    )
    assert spec.tools == []
    assert AgentSpec[NodeSummary].model_validate_json(spec.model_dump_json()) == spec

    written = spec.model_dump_json()
    assert TaskSpec.model_validate_json(written).input_schema == "contracts.py:NodeSummary"
    assert AgentSpec[NodeSummary].model_validate_json(written).input.confidence == 1

    prose = spec.model_copy(update={"input": FreeText(text="body")}).model_dump_json()
    assert AgentSpec[FreeText].model_validate_json(prose).input.text == "body"
    with pytest.raises(pydantic.ValidationError):
        AgentSpec[NodeSummary].model_validate_json(prose)

    message = Message(
        role=Role.ASSISTANT,
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

    module = tmp_path / "contracts.py"
    module.write_text("import pydantic\n\n\nclass Verdict(pydantic.BaseModel):\n    ok: bool\n")
    resolved = resolve_class("contracts.py:Verdict", tmp_path)
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
