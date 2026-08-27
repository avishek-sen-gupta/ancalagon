# The answer class a run function names by returning Outcome[X], and what to say otherwise.
import collections.abc
import typing

import pydantic

from ancalagon.contracts.declared import Declared
from ancalagon.contracts.outcome import Outcome


def _outcome_return(hints: collections.abc.Mapping[str, object]) -> Declared:
    ret = hints["return"]
    if typing.get_origin(ret) is not Outcome:
        return None, f"annotates return as {ret}, which is not Outcome[...]"
    match typing.get_args(ret):
        case (arg,) if isinstance(arg, type) and issubclass(arg, pydantic.BaseModel):
            return arg, ""
        case args:
            return None, f"parameterises Outcome with {args}, which is not one model class"


def outcome_arg(found: collections.abc.Callable[..., object]) -> Declared:
    try:
        hints = typing.get_type_hints(found)
    except NameError as exc:
        return None, f"has an annotation that cannot be resolved: {exc}"
    if "return" not in hints:
        return None, "does not annotate its return"
    return _outcome_return(hints)
