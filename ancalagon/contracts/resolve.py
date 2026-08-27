# Imports a contract module by the dotted name its ClassRef gives.
import importlib

import pydantic

from ancalagon.contracts.class_ref import ClassRef


def resolve_class(ref: ClassRef) -> type[pydantic.BaseModel]:
    resolved = getattr(importlib.import_module(ref.module), ref.name)
    if not issubclass(resolved, pydantic.BaseModel):
        raise TypeError(f"{ref.name} in {ref.module} is not a pydantic model")
    return resolved
