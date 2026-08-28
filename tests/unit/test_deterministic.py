import collections.abc
import importlib
import json
import pathlib

import pydantic

from ancalagon.config.load import load_config
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.deterministic.run import main
from ancalagon.fs.real_file_system import RealFileSystem

RUNNERS = """
import pydantic

from ancalagon.contracts.completed import Completed
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.no_watermark import NO_WATERMARK
from ancalagon.contracts.nothing import NOTHING
from ancalagon.contracts.outcome import Outcome
from ancalagon.deterministic.run_context import RunContext


class Given(pydantic.BaseModel, frozen=True):
    path: str


class Produced(pydantic.BaseModel, frozen=True):
    seen: str


def echo(given: Given, ctx: RunContext) -> Outcome[Produced]:
    seen = ctx.fs.read_text(ctx.task_dir / given.path)
    return Completed(value=Produced(seen=seen), summary=f"read {given.path}", spent=NOTHING)


def waits(given: Given, ctx: RunContext) -> Outcome[Produced]:
    return Idling(summary="waiting for a child", spent=NOTHING, seen_through=NO_WATERMARK)


def explodes(given: Given, ctx: RunContext) -> Outcome[Produced]:
    raise RuntimeError("the transform gave up")


def reports_its_agent(given: Given, ctx: RunContext) -> Outcome[Produced]:
    return Completed(
        value=Produced(seen=str(ctx.agent_id)), summary=f"agent {ctx.agent_id}", spent=NOTHING
    )
"""

CONFIG = """
[workspace]
write_root = "./ws"
read_roots = ["./ws"]

[model]
name = "some-provider/some-model"
num_retries = 2
request_timeout_s = 120
max_tokens = 4000
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "fence"

[run]
goal_file = ""
input_file = ""
role = "transformer"

[roles.transformer]
behaviour = "Read the file you are given."
run = { module = "runkit.runners", name = "%s" }
tools = []
budget = { turns = 0, tool_calls = 0 }
"""


def _prepared(
    tmp_path: pathlib.Path,
    importable: collections.abc.Callable[[pathlib.Path], None],
    function: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    package = tmp_path / "runkit"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("")
    (package / "runners.py").write_text(RUNNERS)
    importable(tmp_path)
    config_path = tmp_path / f"{function}.toml"
    config_path.write_text(CONFIG % function)
    task_dir = tmp_path / "tasks" / function
    task_dir.mkdir(parents=True)
    role = load_config(config_path, RealFileSystem()).roles["transformer"]
    given_class: type[pydantic.BaseModel] = importlib.import_module("runkit.runners").Given
    given = given_class(path="board.md")
    spec = AgentSpec[given_class](task_id=function, role=role, goal="Read it.", input=given)
    (task_dir / "spec.json").write_text(spec.model_dump_json())
    return config_path, task_dir


def test_a_run_function_produces_the_outcome_a_supervisor_reads(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    config_path, task_dir = _prepared(tmp_path, importable, "echo")
    (task_dir / "board.md").write_text("a claim appeared")

    assert main(tmp_path, task_dir, 4, config_path) == 0

    written = json.loads((task_dir / "outcome-4.json").read_text())
    assert written["kind"] == "completed"
    assert written["value"] == {"seen": "a claim appeared"}
    assert written["summary"] == "read board.md"
    assert written["spent"] == {"turns": 0, "tool_calls": 0}
    assert sorted(p.name for p in task_dir.iterdir()) == [
        "board.md",
        "outcome-4.json",
        "spec.json",
    ]


def test_a_run_function_may_idle_instead_of_completing(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    config_path, task_dir = _prepared(tmp_path, importable, "waits")

    assert main(tmp_path, task_dir, 7, config_path) == 0

    written = json.loads((task_dir / "outcome-7.json").read_text())
    assert written["kind"] == "idling"
    assert written["summary"] == "waiting for a child"
    assert written["spent"] == {"turns": 0, "tool_calls": 0}
    assert "value" not in written


def test_a_run_function_that_raises_records_a_failure_the_way_a_worker_does(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    config_path, task_dir = _prepared(tmp_path, importable, "explodes")

    assert main(tmp_path, task_dir, 9, config_path) == 1

    written = json.loads((task_dir / "outcome-9.json").read_text())
    assert written["kind"] == "failed"
    assert written["summary"] == "the transform gave up"
    assert "RuntimeError: the transform gave up" in written["error"]
    assert written["spent"] == {"turns": 0, "tool_calls": 0}


def test_a_run_function_is_told_which_agent_it_is(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    config_path, task_dir = _prepared(tmp_path, importable, "reports_its_agent")

    assert main(tmp_path, task_dir, 12, config_path) == 0

    written = json.loads((task_dir / "outcome-12.json").read_text())
    assert written["value"] == {"seen": "12"}
    assert written["summary"] == "agent 12"
