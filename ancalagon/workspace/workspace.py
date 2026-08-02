# Enforces read/write path scoping for agent tool access.
import pathlib
import typing

from ancalagon.workspace.scope_error import ScopeError

if typing.TYPE_CHECKING:
    from ancalagon.config.config import Config


class Workspace:
    def __init__(self, write_root: pathlib.Path, read_roots: tuple[pathlib.Path, ...]):
        self.write_root = write_root.resolve()
        self.read_roots = tuple(r.resolve() for r in read_roots)

    @classmethod
    def from_config(cls, config: "Config") -> "Workspace":
        return cls(write_root=config.write_root, read_roots=(*config.read_roots, config.write_root))

    def resolve_write(self, path: pathlib.Path) -> pathlib.Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.write_root):
            raise ScopeError(f"{path} is outside write_root {self.write_root}")
        return resolved

    def resolve_read(self, path: pathlib.Path) -> pathlib.Path:
        resolved = path.resolve()
        if not any(resolved.is_relative_to(root) for root in self.read_roots):
            raise ScopeError(f"{path} is outside read_roots {self.read_roots}")
        return resolved
