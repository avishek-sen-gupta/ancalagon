# Imports a generated contracts module by path, refusing anything outside the task directory.
import importlib.util
import pathlib
import sys

import pydantic


def resolve_class(reference: str, base: pathlib.Path) -> type[pydantic.BaseModel]:
    filename, _, class_name = reference.partition(":")
    path = (base / filename).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError(f"{reference} escapes the task directory {base}")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    resolved = getattr(module, class_name)
    if not issubclass(resolved, pydantic.BaseModel):
        raise TypeError(f"{reference} is not a pydantic model")
    return resolved
