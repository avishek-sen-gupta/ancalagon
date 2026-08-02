import importlib.util
import pathlib
import sys

import pydantic


def resolve_output_class(output: str, base: pathlib.Path) -> type[pydantic.BaseModel]:
    filename, _, class_name = output.partition(":")
    path = base / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    resolved = getattr(module, class_name)
    if not issubclass(resolved, pydantic.BaseModel):
        raise TypeError(f"{output} is not a pydantic model")
    return resolved
