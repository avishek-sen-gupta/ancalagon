# Resolves a role's declared before hook, refusing one the tool cannot pass its arguments to.
import importlib

import pydantic

from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.tools.registry.accepts import accepts
from ancalagon.tools.registry.before import Before

BEFORE_ARITY = 2


def resolve_before(ref: FunctionRef, args_model: type[pydantic.BaseModel]) -> Before:
    fault = accepts(ref, args_model, BEFORE_ARITY)
    if fault:
        raise ValueError(f"{ref.name} in {ref.module} {fault}")
    found = getattr(importlib.import_module(ref.module), ref.name)
    if not isinstance(found, Before):
        raise ValueError(f"{ref.name} in {ref.module} is not callable")
    return found
