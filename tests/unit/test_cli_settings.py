import collections.abc
import json
import pathlib

import pytest

from ancalagon import cli
from ancalagon.cli import created_run_dir, goal_of, root_spec, sandbox_of
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.config.config import Config
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.role import Role
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.sandbox.fence import Fence
from ancalagon.sandbox.strategy import Strategy
from ancalagon.sandbox.unsandboxed import Unsandboxed


def test_a_named_run_dir_is_created_verbatim_and_an_unnamed_one_is_stamped(
    tmp_path: pathlib.Path,
):
    write_root = tmp_path / "ws"
    named = tmp_path / "units" / "abc123"
    clock = FakeClock()

    assert created_run_dir(str(named), write_root, clock, RealFileSystem()) == named
    assert named.is_dir()
    assert created_run_dir(str(named), write_root, clock, RealFileSystem()) == named

    assert (
        created_run_dir("", write_root, clock, RealFileSystem())
        == write_root / "runs" / "r_20260101-000000"
    )
    clock.sleep(61)
    assert (
        created_run_dir("", write_root, clock, RealFileSystem())
        == write_root / "runs" / "r_20260101-000101"
    )

    clock.sleep(-61)
    with pytest.raises(FileExistsError):
        created_run_dir("", write_root, clock, RealFileSystem())


def test_an_allocated_run_dir_refuses_a_directory_another_run_already_took(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    write_root = tmp_path / "ws"
    taken = write_root / "runs" / "r_0001"
    taken.mkdir(parents=True)

    def race(_: pathlib.Path, __: FakeClock, ___: RealFileSystem) -> pathlib.Path:
        return taken

    monkeypatch.setattr(cli, "_allocated_run_dir", race)

    with pytest.raises(FileExistsError):
        created_run_dir("", write_root, FakeClock(), RealFileSystem())


def test_a_goal_comes_from_the_file_and_from_nowhere_else(tmp_path: pathlib.Path):
    goal_file = tmp_path / "goal.md"
    goal_file.write_text("describe the item")

    assert goal_of(RunSettings(goal_file=str(goal_file)), RealFileSystem()) == "describe the item"

    with pytest.raises(ValueError, match="no goal"):
        goal_of(RunSettings(), RealFileSystem())

    goal_file.write_text("   \n")
    with pytest.raises(ValueError, match="empty"):
        goal_of(RunSettings(goal_file=str(goal_file)), RealFileSystem())

    absent = tmp_path / "no-such-goal.md"
    with pytest.raises(ValueError, match="does not exist"):
        goal_of(RunSettings(goal_file=str(absent)), RealFileSystem())


def test_the_root_spec_comes_from_its_role_and_its_two_files(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "querykit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "shapes.py").write_text(
        "import pydantic\n\n\nclass Query(pydantic.BaseModel):\n    area: str\n"
    )
    importable(tmp_path)
    (tmp_path / "goal.md").write_text("map it")
    (tmp_path / "input.json").write_text('{"area": "bus"}')
    role = Role(
        behaviour="Analyse.",
        input=ClassRef(module="querykit.shapes", name="Query"),
        tools=("read_file", "submit_answer"),
        budget=Budget(turns=3, tool_calls=6),
    )
    config = Config(
        write_root=tmp_path,
        read_roots=(),
        model="anthropic/claude",
        roles={"analyst": role},
        run=RunSettings(
            goal_file=str(tmp_path / "goal.md"),
            input_file=str(tmp_path / "input.json"),
            role="analyst",
        ),
    )

    spec = root_spec(config, RealFileSystem())

    assert spec.task_id == "root"
    assert spec.role == role
    assert spec.goal == "map it"
    assert spec.input.model_dump() == {"area": "bus"}

    absent = config.model_copy(update={"run": config.run.model_copy(update={"role": "nobody"})})
    with pytest.raises(ValueError, match="no role named nobody"):
        root_spec(absent, RealFileSystem())


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

    assert isinstance(sandbox_of(defaulted, run_dir, RealFileSystem()), Fence)
    assert json.loads((run_dir / "fence.json").read_text()) == {
        "network": {"allowedDomains": ["bedrock-runtime.us-east-1.amazonaws.com"]},
        "filesystem": {"allowWrite": [str(write_root), str(run_dir)]},
    }

    unsandboxed = defaulted.model_copy(update={"sandbox": Strategy.NONE})
    assert isinstance(sandbox_of(unsandboxed, run_dir, RealFileSystem()), Unsandboxed)
