# Whether a hook can receive what the tool it is wired to will pass it.
import collections.abc
import importlib
import inspect
import typing

import pydantic

from ancalagon.contracts.declared import Declared, declared
from ancalagon.contracts.function_ref import FunctionRef

POSITIONAL = inspect.Parameter.POSITIONAL_OR_KEYWORD


def _annotation(found: collections.abc.Callable[..., object], arity: int) -> Declared:
    params = list(inspect.signature(found).parameters.values())
    if len(params) != arity or any(p.kind is not POSITIONAL for p in params):
        return None, f"must take {arity} positional parameters, not {[p.name for p in params]}"
    try:
        first = params[0].name
        return declared(typing.get_type_hints(found), first, f"its first parameter, {first}")
    except NameError as exc:
        return None, f"has an annotation that cannot be resolved: {exc}"


def _receives(
    found: collections.abc.Callable[..., object],
    args_model: type[pydantic.BaseModel],
    arity: int,
) -> str:
    match _annotation(found, arity):
        case (None, fault):
            return fault
        case (declared, _) if not issubclass(args_model, declared):
            return f"takes {declared.__name__}, but the tool passes {args_model.__name__}"
        case _:
            return ""


def accepts(ref: FunctionRef, args_model: type[pydantic.BaseModel], arity: int) -> str:
    module = importlib.import_module(ref.module)
    if not hasattr(module, ref.name):
        return f"is absent from {ref.module}"
    found = getattr(module, ref.name)
    if not callable(found):
        return "is not callable"
    return _receives(found, args_model, arity)
