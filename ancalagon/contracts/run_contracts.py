# The input and answer contracts a run function states in its own signature.
import collections.abc
import importlib
import inspect
import typing

import pydantic

from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.declared import declared
from ancalagon.contracts.function_ref import FunctionRef

RUN_ARITY = 2
POSITIONAL = inspect.Parameter.POSITIONAL_OR_KEYWORD


def _ref_of(cls: type[pydantic.BaseModel]) -> ClassRef:
    return ClassRef(module=cls.__module__, name=cls.__name__)


def _must(
    hints: collections.abc.Mapping[str, object], key: str, label: str, ref: FunctionRef
) -> type[pydantic.BaseModel]:
    match declared(hints, key, label):
        case (None, fault):
            raise ValueError(f"{ref.name} in {ref.module} {fault}")
        case (found, _):
            return found


def run_contracts(ref: FunctionRef) -> tuple[ClassRef, ClassRef]:
    found = getattr(importlib.import_module(ref.module), ref.name)
    if not callable(found):
        raise ValueError(f"{ref.name} in {ref.module} is not callable")
    params = list(inspect.signature(found).parameters.values())
    if len(params) != RUN_ARITY or any(p.kind is not POSITIONAL for p in params):
        raise ValueError(
            f"{ref.name} in {ref.module} must take {RUN_ARITY} positional parameters, "
            f"not {[p.name for p in params]}"
        )
    hints = typing.get_type_hints(found)
    first = params[0].name
    given = _must(hints, first, f"its first parameter, {first}", ref)
    produced = _must(hints, "return", "its return", ref)
    return _ref_of(given), _ref_of(produced)
