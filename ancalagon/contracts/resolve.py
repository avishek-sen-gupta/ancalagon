# Imports a contract module by the path its ClassRef names.
import importlib.util
import pathlib
import sys
import types

import pydantic

from ancalagon.contracts.class_ref import ClassRef


def _load_fresh(path: pathlib.Path) -> types.ModuleType:
    name = str(path)
    match importlib.util.spec_from_file_location(name, path):
        case None:
            raise ImportError(f"cannot load {path}")
        case spec:
            match spec.loader:
                case None:
                    raise ImportError(f"cannot load {path}")
                case loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[name] = module
                    loader.exec_module(module)
                    return module


def _load(path: pathlib.Path) -> types.ModuleType:
    matches = [m for m in sys.modules.values() if getattr(m, "__file__", None) == str(path)]
    match matches:
        case [module]:
            return module
        case _:
            return _load_fresh(path)


def resolve_class(ref: ClassRef) -> type[pydantic.BaseModel]:
    path = pathlib.Path(ref.module).resolve()
    module = _load(path)
    resolved = getattr(module, ref.name)
    if not issubclass(resolved, pydantic.BaseModel):
        raise TypeError(f"{ref.name} in {ref.module} is not a pydantic model")
    return resolved
