# Finds the callable a FunctionRef names, and what to say when it is not there.
import collections.abc
import importlib

from ancalagon.contracts.function_ref import FunctionRef

NamedCallable = tuple[collections.abc.Callable[..., object] | None, str]


def named_callable(ref: FunctionRef) -> NamedCallable:
    module = importlib.import_module(ref.module)
    if not hasattr(module, ref.name):
        return None, f"is absent from {ref.module}"
    found = getattr(module, ref.name)
    if not callable(found):
        return None, "is not callable"
    return found, ""
