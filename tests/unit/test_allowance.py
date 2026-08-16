import json
import pathlib

import pytest

from ancalagon.contracts.allowance import Allowance
from ancalagon.contracts.as_asked import AsAsked
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.within_parent import WithinParent
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.tools.delegate.delegate import Delegate
from ancalagon.tools.delegate.delegate_args import DelegateArgs
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.workspace import Workspace


class Clamped(Allowance):
    def grant(self, parent: Budget, asked: Budget) -> Budget:
        return Budget(
            turns=min(asked.turns, parent.turns),
            tool_calls=min(asked.tool_calls, parent.tool_calls),
        )


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    return ToolContext(
        workspace=Workspace(write_root=write_root, read_roots=(write_root,)),
        output_dir=write_root / "tools",
        summary_chars=200,
        agent_id=1,
    )


def test_a_child_is_granted_no_more_than_its_parent_unless_the_allowance_says_otherwise(
    tmp_path: pathlib.Path,
):
    parent = Budget(turns=10, tool_calls=30)
    assert WithinParent().grant(parent, Budget(turns=4, tool_calls=9)) == Budget(
        turns=4, tool_calls=9
    )
    with pytest.raises(ValueError, match="cannot slice"):
        WithinParent().grant(parent, Budget(turns=20, tool_calls=9))
    assert AsAsked().grant(parent, Budget(turns=20, tool_calls=99)) == Budget(
        turns=20, tool_calls=99
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    migrate_file(run_dir / "bus.db", latest_version())
    ctx = _ctx(tmp_path)
    asked = DelegateArgs(
        task_id="child",
        behaviour="b",
        goal="g",
        input_json='{"text": "go"}',
        turns=40,
        tool_calls=99,
    )

    capped = Delegate(run_dir=run_dir, parent=1, budget=parent)
    refused = capped.run(asked, ctx)
    assert refused.ok is False
    assert "cannot slice 40/99 from 10/30" in refused.error
    assert not (run_dir / "tasks" / "child" / "spec.json").exists()

    fitted = asked.model_copy(update={"turns": 6, "tool_calls": 20})
    assert capped.run(fitted, ctx).ok is True
    granted = TaskSpec.model_validate_json((run_dir / "tasks" / "child" / "spec.json").read_text())
    assert granted.budget == Budget(turns=6, tool_calls=20)

    clamped = Delegate(run_dir=run_dir, parent=1, budget=parent, allowance=Clamped())
    assert clamped.run(asked.model_copy(update={"task_id": "clamped"}), ctx).ok is True
    cut = TaskSpec.model_validate_json((run_dir / "tasks" / "clamped" / "spec.json").read_text())
    assert cut.budget == Budget(turns=10, tool_calls=30)

    free = Delegate(run_dir=run_dir, parent=1, budget=parent, allowance=AsAsked())
    assert free.run(asked.model_copy(update={"task_id": "free"}), ctx).ok is True
    unbounded = json.loads((run_dir / "tasks" / "free" / "spec.json").read_text())
    assert unbounded["budget"] == {"turns": 40, "tool_calls": 99}
