import pathlib

import pydantic
import pytest

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.tools.registry.accepts import accepts
from ancalagon.tools.registry.resolve_after import resolve_after
from ancalagon.tools.registry.resolve_before import resolve_before
from ancalagon.tools.search.grep_args import GrepArgs
from ancalagon.tools.search.sed_args import SedArgs

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
