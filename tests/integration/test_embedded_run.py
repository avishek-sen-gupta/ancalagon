import collections.abc
import pathlib
import typing

import pydantic

from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.load import load_config
from ancalagon.contracts.completed import Completed
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.run import run
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

CONFIG = """
[workspace]
write_root = "./ws"
read_roots = ["./ws"]

[model]
name = "some-provider/no-model-is-called"
num_retries = 1
request_timeout_s = 60
max_tokens = 1000
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 120
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "none"

[roles.root]
behaviour = "Say it."
run = { module = "speechkit.speech", name = "speaks" }
tools = []
budget = { turns = 0, tool_calls = 0 }

[run]
goal_file = "./goal.md"
input_file = ""
role = "root"
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
    config_path = tmp_path / "anc.toml"
    config_path.write_text(CONFIG)
    config = load_config(pathlib.PurePath(config_path), fs)
    run_dir = prepared_run_dir(tmp_path / "ws" / "runs" / "embedded")

    produced = run(config, run_dir, pathlib.PurePath(config_path), SystemClock(), fs)

    assert isinstance(produced, Completed)
    value = typing.cast(Said, produced.value)
    assert value.text == "Say hello."
