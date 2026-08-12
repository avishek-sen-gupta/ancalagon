import pathlib

import pytest

from ancalagon.cli import contract_source, goal_of, output_of, run_dir_of
from ancalagon.contracts.free_text_module import FREE_TEXT_MODULE
from ancalagon.contracts.run_settings import RunSettings


def test_a_named_run_dir_is_used_verbatim_and_an_unnamed_one_is_allocated(
    tmp_path: pathlib.Path,
):
    write_root = tmp_path / "ws"
    named = tmp_path / "units" / "abc123"

    assert run_dir_of(RunSettings(run_dir=str(named)), write_root) == named
    assert named.is_dir()
    assert run_dir_of(RunSettings(run_dir=str(named)), write_root) == named

    assert run_dir_of(RunSettings(), write_root) == write_root / "runs" / "r_0001"
    assert run_dir_of(RunSettings(), write_root) == write_root / "runs" / "r_0002"


def test_a_goal_comes_from_exactly_one_of_the_file_and_the_argument(
    tmp_path: pathlib.Path,
):
    goal_file = tmp_path / "goal.md"
    goal_file.write_text("describe the item")

    assert goal_of(RunSettings(goal_file=str(goal_file)), "") == "describe the item"
    assert goal_of(RunSettings(), "inline") == "inline"

    with pytest.raises(ValueError):
        goal_of(RunSettings(goal_file=str(goal_file)), "inline")
    with pytest.raises(ValueError):
        goal_of(RunSettings(), "")


def test_a_named_contract_replaces_free_text(tmp_path: pathlib.Path):
    module = tmp_path / "shape.py"
    module.write_text(
        "import pydantic\n\n\nclass Answer(pydantic.BaseModel):\n    verdict: str\n"
    )

    assert output_of(RunSettings()) == "contracts.py:FreeText"
    assert contract_source(RunSettings()) == FREE_TEXT_MODULE

    named = RunSettings(contract_module=str(module), contract_class="Answer")
    assert output_of(named) == "contracts.py:Answer"
    assert "class Answer" in contract_source(named)
