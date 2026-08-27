# Whether a hook can receive what the tool it is wired to will pass it.
import collections.abc
import inspect

import pydantic

from ancalagon.contracts.arity import arity_fault
from ancalagon.contracts.declared import annotation_fault
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.named_callable import named_callable


def _matches(declared: type[pydantic.BaseModel], args_model: type[pydantic.BaseModel]) -> str:
    if issubclass(args_model, declared):
        return ""
    return f"takes {declared.__name__}, but the tool passes {args_model.__name__}"


def _first_annotation_fault(
    found: collections.abc.Callable[..., object], args_model: type[pydantic.BaseModel]
) -> str:
    first = next(iter(inspect.signature(found).parameters.values())).name
    match annotation_fault(found, first, f"its first parameter, {first}"):
        case (None, fault):
            return fault
        case (declared, _):
            return _matches(declared, args_model)


def _receives(
    found: collections.abc.Callable[..., object],
    args_model: type[pydantic.BaseModel],
    arity: int,
) -> str:
    if fault := arity_fault(found, arity):
        return fault
    return _first_annotation_fault(found, args_model)


def accepts(ref: FunctionRef, args_model: type[pydantic.BaseModel], arity: int) -> str:
    match named_callable(ref):
        case (None, fault):
            return fault
        case (found, _):
            return _receives(found, args_model, arity)
