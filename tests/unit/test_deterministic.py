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

from ancalagon.deterministic.run_context import RunContext


class Given(pydantic.BaseModel, frozen=True):
    path: str


class Produced(pydantic.BaseModel, frozen=True):
    seen: str


def echo(given: Given, ctx: RunContext) -> Produced:
    return Produced(seen=ctx.fs.read_text(ctx.task_dir / given.path))


def explodes(given: Given, ctx: RunContext) -> Produced:
    raise RuntimeError("the transform gave up")
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
    assert written["summary"] == '{"seen":"a claim appeared"}'
    assert written["spent"] == {"turns": 0, "tool_calls": 0}
    assert sorted(p.name for p in task_dir.iterdir()) == [
        "board.md",
        "outcome-4.json",
        "spec.json",
    ]


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
