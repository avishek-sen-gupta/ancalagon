# The input and answer contracts a run function states in its own signature.
import collections.abc
import inspect

import pydantic

from ancalagon.contracts.arity import arity_fault
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.declared import annotation_fault
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.named_callable import named_callable

RUN_ARITY = 2


def _ref_of(cls: type[pydantic.BaseModel]) -> ClassRef:
    return ClassRef(module=cls.__module__, name=cls.__name__)


def _must(
    found: collections.abc.Callable[..., object], key: str, label: str, ref: FunctionRef
) -> type[pydantic.BaseModel]:
    match annotation_fault(found, key, label):
        case (None, fault):
            raise ValueError(f"{ref.name} in {ref.module} {fault}")
        case (declared, _):
            return declared


def _found(ref: FunctionRef) -> collections.abc.Callable[..., object]:
    match named_callable(ref):
        case (None, fault):
            raise ValueError(f"{ref.name} in {ref.module} {fault}")
        case (found, _):
            return found


def run_contracts(ref: FunctionRef) -> tuple[ClassRef, ClassRef]:
    found = _found(ref)
    if fault := arity_fault(found, RUN_ARITY):
        raise ValueError(f"{ref.name} in {ref.module} {fault}")
    first = next(iter(inspect.signature(found).parameters.values())).name
    given = _must(found, first, f"its first parameter, {first}", ref)
    produced = _must(found, "return", "its return", ref)
    return _ref_of(given), _ref_of(produced)
