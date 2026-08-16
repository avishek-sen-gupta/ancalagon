import json
import pathlib

import pytest

from ancalagon import cli
from ancalagon.cli import (
    answer_schema_of,
    contract_source,
    goal_of,
    install_contracts,
    run_dir_of,
    sandbox_of,
)
from ancalagon.config.config import Config
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.free_text_module import FREE_TEXT_MODULE
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.sandbox.fence import Fence
from ancalagon.sandbox.strategy import Strategy
from ancalagon.sandbox.unsandboxed import Unsandboxed


def test_a_named_run_dir_is_used_verbatim_and_an_unnamed_one_is_allocated(
    tmp_path: pathlib.Path,
):
    write_root = tmp_path / "ws"
    named = tmp_path / "units" / "abc123"

    assert run_dir_of(RunSettings(run_dir=str(named)), write_root) == named
    assert named.is_dir()
    assert run_dir_of(RunSettings(run_dir=str(named)), write_root) == named

    (write_root / "runs").mkdir(parents=True)
    (write_root / "runs" / "unrelated").mkdir()
    (write_root / "runs" / "r_abc").mkdir()
    (write_root / "runs" / "r_001x").mkdir()

    assert run_dir_of(RunSettings(), write_root) == write_root / "runs" / "r_0001"
    assert run_dir_of(RunSettings(), write_root) == write_root / "runs" / "r_0002"


def test_an_allocated_run_dir_refuses_a_directory_another_run_already_took(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    write_root = tmp_path / "ws"
    taken = write_root / "runs" / "r_0001"
    taken.mkdir(parents=True)

    def race(_: pathlib.Path) -> pathlib.Path:
        return taken

    monkeypatch.setattr(cli, "_allocated_run_dir", race)

    with pytest.raises(FileExistsError):
        run_dir_of(RunSettings(), write_root)


def test_a_goal_comes_from_the_file_and_from_nowhere_else(tmp_path: pathlib.Path):
    goal_file = tmp_path / "goal.md"
    goal_file.write_text("describe the item")

    assert goal_of(RunSettings(goal_file=str(goal_file))) == "describe the item"

    with pytest.raises(ValueError, match="no goal"):
        goal_of(RunSettings())

    goal_file.write_text("   \n")
    with pytest.raises(ValueError, match="empty"):
        goal_of(RunSettings(goal_file=str(goal_file)))

    absent = tmp_path / "no-such-goal.md"
    with pytest.raises(ValueError, match="does not exist"):
        goal_of(RunSettings(goal_file=str(absent)))


def test_a_named_contract_replaces_free_text(tmp_path: pathlib.Path):
    module = tmp_path / "shape.py"
    module.write_text("import pydantic\n\n\nclass Answer(pydantic.BaseModel):\n    verdict: str\n")

    assert answer_schema_of(RunSettings()) == ClassRef(module="free_text.py", name="FreeText")
    assert contract_source(RunSettings()) == FREE_TEXT_MODULE

    named = RunSettings(contract_module=str(module), contract_class="Answer")
    assert answer_schema_of(named) == ClassRef(module="shape.py", name="Answer")
    assert "class Answer" in contract_source(named)


def test_the_root_task_dir_carries_both_contracts_the_worker_resolves(tmp_path: pathlib.Path):
    module = tmp_path / "shape.py"
    module.write_text("import pydantic\n\n\nclass Answer(pydantic.BaseModel):\n    verdict: str\n")

    default_dir = tmp_path / "default"
    default_dir.mkdir()
    assert install_contracts(RunSettings(), default_dir) == ClassRef(
        module=str(default_dir / "free_text.py"), name="FreeText"
    )
    assert sorted(p.name for p in default_dir.iterdir()) == ["free_text.py"]

    named_dir = tmp_path / "named"
    named_dir.mkdir()
    named = RunSettings(contract_module=str(module), contract_class="Answer")

    assert install_contracts(named, named_dir) == ClassRef(
        module=str(named_dir / "shape.py"), name="Answer"
    )
    assert sorted(p.name for p in named_dir.iterdir()) == ["free_text.py", "shape.py"]
    assert (
        resolve_class(ClassRef(module=str(named_dir / "free_text.py"), name="FreeText")).__name__
        == "FreeText"
    )
    assert (
        resolve_class(ClassRef(module=str(named_dir / "shape.py"), name="Answer")).__name__
        == "Answer"
    )


def test_sandbox_of_resolves_each_strategy_and_fence_is_the_unstated_default(
    tmp_path: pathlib.Path,
):
    write_root = tmp_path / "ws"
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    defaulted = Config(
        write_root=write_root,
        read_roots=(),
        model="anthropic/claude",
        allowed_domains=("bedrock-runtime.us-east-1.amazonaws.com",),
    )
    assert defaulted.sandbox is Strategy.FENCE

    assert isinstance(sandbox_of(defaulted, run_dir), Fence)
    assert json.loads((run_dir / "fence.json").read_text()) == {
        "network": {"allowedDomains": ["bedrock-runtime.us-east-1.amazonaws.com"]},
        "filesystem": {"allowWrite": [str(write_root), str(run_dir)]},
    }

    unsandboxed = defaulted.model_copy(update={"sandbox": Strategy.NONE})
    assert isinstance(sandbox_of(unsandboxed, run_dir), Unsandboxed)
