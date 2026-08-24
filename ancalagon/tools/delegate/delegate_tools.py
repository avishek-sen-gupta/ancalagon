# One delegate tool per declared role, so the role a parent picks is the tool it calls.
import collections.abc
import pathlib

from ancalagon.clock.clock import Clock
from ancalagon.contracts.role import Role
from ancalagon.fs.file_system import FileSystem
from ancalagon.tools.delegate.delegate_to import DelegateTo
from ancalagon.tools.registry.bound_for import bound_for
from ancalagon.tools.registry.bound_tool import BoundTool


def delegate_tools(
    roles: collections.abc.Mapping[str, Role],
    caller: Role,
    run_dir: pathlib.PurePath,
    parent: int,
    clock: Clock,
    fs: FileSystem,
) -> list[BoundTool]:
    return [
        bound_for(DelegateTo(name, role, run_dir, parent, clock, fs), caller)
        for name, role in roles.items()
    ]
