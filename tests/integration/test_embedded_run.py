import collections.abc
import pathlib
import typing

import pydantic

from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.finite import Finite
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.role import Role
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.run import run
from ancalagon.sandbox.strategy import Strategy
from tests.integration.prepared_run import prepared_run_dir

KIT = """
import pydantic

from ancalagon.contracts.completed import Completed
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.nothing import NOTHING
from ancalagon.contracts.outcome import Outcome
from ancalagon.deterministic.run_context import RunContext


class Said(pydantic.BaseModel, frozen=True):
    text: str


def speaks(given: FreeText, ctx: RunContext) -> Outcome[Said]:
    return Completed(value=Said(text=given.text), summary="spoke", spent=NOTHING)
"""


class Said(pydantic.BaseModel, frozen=True):
    text: str


def test_a_run_hands_back_the_root_outcome_as_a_typed_value(
    tmp_path: pathlib.Path,
    importable: collections.abc.Callable[[pathlib.Path], None],
):
    fs = RealFileSystem()
    package = tmp_path / "speechkit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "speech.py").write_text(KIT)
    importable(tmp_path)
    (tmp_path / "goal.md").write_text("Say hello.")

    config = Config(
        write_root=pathlib.PurePath(tmp_path / "ws"),
        read_roots=(pathlib.PurePath(tmp_path / "ws"),),
        model="some-provider/no-model-is-called",
        roles={
            "root": Role(
                behaviour="Say it.",
                run=FunctionRef(module="speechkit.speech", name="speaks"),
                answer=ClassRef(module="speechkit.speech", name="Said"),
                tools=(),
                budget=Budget(turns=Finite(value=0), tool_calls=Finite(value=0)),
            )
        },
        run=RunSettings(goal_file=str(tmp_path / "goal.md"), role="root"),
        sandbox=Strategy.NONE,
        import_paths=(pathlib.PurePath(tmp_path),),
    )
    run_dir = prepared_run_dir(tmp_path / "ws" / "runs" / "embedded")

    produced = run(config, run_dir, SystemClock(), fs)

    assert isinstance(produced, Completed)
    value = typing.cast(Said, produced.value)
    assert value.text == "Say hello."
    assert list(pathlib.Path(run_dir).glob("*.toml")) == []
