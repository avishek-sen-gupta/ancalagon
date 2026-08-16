# Imports a contract module by the path its ClassRef names.
import importlib.util
import pathlib
import sys
import types

import pydantic

from ancalagon.contracts.class_ref import ClassRef


def _already_loaded(path: pathlib.Path) -> types.ModuleType | None:
    matches = [m for m in sys.modules.values() if getattr(m, "__file__", None) == str(path)]
    match matches:
        case [module]:
            return module
        case _:
            return None


def _load_fresh(path: pathlib.Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    match spec:
        case None:
            raise ImportError(f"cannot load {path}")
        case _ if spec.loader is None:
            raise ImportError(f"cannot load {path}")
        case _:
            module = importlib.util.module_from_spec(spec)
            sys.modules[path.stem] = module
            spec.loader.exec_module(module)
            return module


def resolve_class(ref: ClassRef) -> type[pydantic.BaseModel]:
    path = pathlib.Path(ref.module).resolve()
    module = _already_loaded(path) or _load_fresh(path)
    resolved = getattr(module, ref.name)
    if not issubclass(resolved, pydantic.BaseModel):
        raise TypeError(f"{ref.name} in {ref.module} is not a pydantic model")
    return resolved
