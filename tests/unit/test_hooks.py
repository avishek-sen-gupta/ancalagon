import pathlib

import pydantic
import pytest

from ancalagon.cli import check_contracts
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.load import load_config
from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.registry.accepts import accepts
from ancalagon.tools.registry.resolve_after import resolve_after
from ancalagon.tools.registry.resolve_before import resolve_before
from ancalagon.tools.search.grep_args import GrepArgs
from ancalagon.tools.search.sed_args import SedArgs
from ancalagon.worker import build_registry

MODULE = """
from __future__ import annotations

import pydantic

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.grep_args import GrepArgs
from ancalagon.tools.search.sed_args import SedArgs


def narrow(query: GrepArgs, ctx: ToolContext) -> Reviewed:
    return Accepted(value=query)


def general(anything: pydantic.BaseModel, ctx: ToolContext) -> Reviewed:
    return Accepted(value=anything)


def other_tool(edit: SedArgs, ctx: ToolContext) -> Reviewed:
    return Accepted(value=edit)


def bare(query, ctx) -> Reviewed:
    return Accepted(value=query)


def unresolvable(query: NoSuchClass, ctx: ToolContext) -> Reviewed:
    return Accepted(value=query)


def not_a_model(query: int, ctx: ToolContext) -> Reviewed:
    return Accepted(value=GrepArgs(pattern="x", roots=[]))


def starred(*args, **kwargs) -> Reviewed:
    return Accepted(value=GrepArgs(pattern="x", roots=[]))


def reviewing(query: GrepArgs, ran: ToolResult, ctx: ToolContext) -> Reviewed:
    return Accepted(value=ran)


not_a_function = 3
"""


@pytest.fixture
def hooks(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "hooks.py"
    path.write_text(MODULE)
    return path


def test_a_hook_is_accepted_only_when_it_can_receive_what_the_tool_will_pass(
    hooks: pathlib.Path,
):
    def fault(name: str, args_model: type[pydantic.BaseModel], arity: int = 2) -> str:
        return accepts(FunctionRef(module=str(hooks), name=name), args_model, arity)

    assert fault("narrow", GrepArgs) == ""
    assert fault("general", GrepArgs) == ""
    assert fault("general", SedArgs) == ""
    assert fault("reviewing", GrepArgs, arity=3) == ""

    assert fault("other_tool", GrepArgs) == "takes SedArgs, but the tool passes GrepArgs"
    assert fault("bare", GrepArgs) == "does not annotate its first parameter, query"
    assert fault("not_a_model", GrepArgs) == (
        "annotates query as <class 'int'>, which is not a model class"
    )
    assert fault("starred", GrepArgs) == (
        "must take 2 positional parameters, not ['args', 'kwargs']"
    )
    assert fault("reviewing", GrepArgs) == (
        "must take 2 positional parameters, not ['query', 'ran', 'ctx']"
    )
    assert "NoSuchClass" in fault("unresolvable", GrepArgs)
    assert fault("not_a_function", GrepArgs) == "is not callable"
    assert "absent" in fault("absent", GrepArgs)


def test_resolvers_return_a_usable_hook_and_refuse_one_of_the_wrong_shape(
    hooks: pathlib.Path,
):
    given = GrepArgs(pattern="x", roots=[])
    before = resolve_before(FunctionRef(module=str(hooks), name="narrow"), GrepArgs)
    assert before(given, None) == Accepted(value=given)  # pyright: ignore[reportArgumentType]

    after = resolve_after(FunctionRef(module=str(hooks), name="reviewing"), GrepArgs)
    assert isinstance(after, object)

    with pytest.raises(ValueError, match="takes SedArgs, but the tool passes GrepArgs"):
        resolve_before(FunctionRef(module=str(hooks), name="other_tool"), GrepArgs)

    with pytest.raises(ValueError, match="must take 3 positional parameters"):
        resolve_after(FunctionRef(module=str(hooks), name="narrow"), GrepArgs)


CONFIG = """
[workspace]
write_root = "./ws"
read_roots = ["."]

[model]
name = "m"
num_retries = 0
request_timeout_s = 10
max_tokens = 100
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 10
max_depth = 1
compact_above_tokens = 0
keep_recent_messages = 8
summary_chars = 100

[sandbox]
strategy = "none"

[roles.root]
behaviour = "Look."
tools = ["ripgrep"]
budget = { turns = 2, tool_calls = 4 }

[roles.root.before]
ripgrep = { module = "./hooks.py", name = "narrow" }

[roles.root.after]
ripgrep = { module = "./hooks.py", name = "reviewing" }

[run]
goal_file = "./goal.md"
input_file = ""
role = "root"
"""


def test_a_role_declares_its_hooks_and_they_are_resolved_against_the_tools_it_names(
    tmp_path: pathlib.Path, hooks: pathlib.Path
):
    fs = RealFileSystem()
    (tmp_path / "goal.md").write_text("go")
    (tmp_path / "ancalagon.toml").write_text(CONFIG)
    config = load_config(tmp_path / "ancalagon.toml", fs)

    role = config.roles["root"]
    assert role.before == {"ripgrep": FunctionRef(module=str(hooks), name="narrow")}
    assert role.after == {"ripgrep": FunctionRef(module=str(hooks), name="reviewing")}
    check_contracts(config)

    registry = build_registry(
        config,
        TaskSpec(task_id="root", role=role, goal="g"),
        tmp_path,
        parent=1,
        depth=0,
        output_class=FreeText,
        clock=SystemClock(),
        fs=fs,
    )
    assert sorted(registry.names()) == ["idle", "ripgrep", "submit_answer"]

    mismatched = role.model_copy(
        update={"before": {"ripgrep": FunctionRef(module=str(hooks), name="other_tool")}}
    )
    with pytest.raises(ValueError, match="takes SedArgs, but the tool passes GrepArgs"):
        check_contracts(config.model_copy(update={"roles": {"root": mismatched}}))

    unknown = role.model_copy(
        update={"before": {"sed": FunctionRef(module=str(hooks), name="narrow")}}
    )
    with pytest.raises(ValueError, match="names a hook for sed, which it does not use"):
        check_contracts(config.model_copy(update={"roles": {"root": unknown}}))
