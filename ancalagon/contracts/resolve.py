# Imports a task's contract module by name, refusing anything outside the task directory.
import importlib.util
import pathlib
import sys

import pydantic

from ancalagon.contracts.class_ref import ClassRef


def resolve_class(ref: ClassRef, base: pathlib.Path) -> type[pydantic.BaseModel]:
    path = (base / ref.module).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError(f"{ref.module} escapes the task directory {base}")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    resolved = getattr(module, ref.name)
    if not issubclass(resolved, pydantic.BaseModel):
        raise TypeError(f"{ref.name} in {ref.module} is not a pydantic model")
    return resolved
