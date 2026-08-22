# Enforces read/write path scoping for agent tool access.
import pathlib
import typing

from ancalagon.fs.file_system import FileSystem
from ancalagon.workspace.scope_error import ScopeError

if typing.TYPE_CHECKING:
    from ancalagon.config.config import Config


def missing_hint(path: pathlib.Path) -> str:
    return f"no file or directory at {path}{_hint(path)}"


def _hint(path: pathlib.Path) -> str:
    if path.is_absolute():
        return ""
    return ". Relative paths resolve against the working directory; give an absolute path"


class Workspace:
    def __init__(
        self, fs: FileSystem, write_root: pathlib.Path, read_roots: tuple[pathlib.Path, ...]
    ):
        self.fs = fs
        self.write_root = write_root.expanduser().resolve()
        self.read_roots = tuple(r.expanduser().resolve() for r in read_roots)

    @classmethod
    def from_config(cls, config: "Config", fs: FileSystem) -> "Workspace":
        return cls(
            fs, write_root=config.write_root, read_roots=(*config.read_roots, config.write_root)
        )

    def resolve_write(self, path: pathlib.Path) -> pathlib.Path:
        resolved = path.expanduser().resolve()
        if not resolved.is_relative_to(self.write_root):
            raise ScopeError(f"{path} is outside write_root {self.write_root}{_hint(path)}")
        return resolved

    def resolve_read(self, path: pathlib.Path) -> pathlib.Path:
        resolved = path.expanduser().resolve()
        if not any(resolved.is_relative_to(root) for root in self.read_roots):
            raise ScopeError(f"{path} is outside read_roots {self.read_roots}{_hint(path)}")
        return resolved

    def read_text(self, path: pathlib.Path) -> str:
        return self.fs.read_text(self.resolve_read(path))

    def read_bytes(self, path: pathlib.Path) -> bytes:
        return self.fs.read_bytes(self.resolve_read(path))

    def iterdir(self, path: pathlib.Path) -> tuple[pathlib.Path, ...]:
        return self.fs.iterdir(self.resolve_read(path))

    def exists(self, path: pathlib.Path) -> bool:
        return self.fs.exists(self.resolve_read(path))

    def is_file(self, path: pathlib.Path) -> bool:
        return self.fs.is_file(self.resolve_read(path))

    def is_dir(self, path: pathlib.Path) -> bool:
        return self.fs.is_dir(self.resolve_read(path))

    def write_text(self, path: pathlib.Path, text: str) -> None:
        self.fs.write_text(self.resolve_write(path), text)

    def mkdir(self, path: pathlib.Path, parents: bool = False, exist_ok: bool = False) -> None:
        self.fs.mkdir(self.resolve_write(path), parents=parents, exist_ok=exist_ok)

    def unlink(self, path: pathlib.Path) -> None:
        self.fs.unlink(self.resolve_write(path))
