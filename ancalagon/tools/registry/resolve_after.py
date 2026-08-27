# Resolves a role's declared after hook, refusing one the tool cannot pass its arguments to.
import importlib

import pydantic

from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.tools.registry.accepts import accepts
from ancalagon.tools.registry.after import After

AFTER_ARITY = 3


def resolve_after(ref: FunctionRef, args_model: type[pydantic.BaseModel]) -> After:
    fault = accepts(ref, args_model, AFTER_ARITY)
    if fault:
        raise ValueError(f"{ref.name} in {ref.module} {fault}")
    found = getattr(importlib.import_module(ref.module), ref.name)
    if not isinstance(found, After):
        raise ValueError(f"{ref.name} in {ref.module} is not callable")
    return found
