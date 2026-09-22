# Enforces read/write path scoping for agent tool access.
import pathlib
import typing

from ancalagon.fs.file_system import FileSystem
from ancalagon.workspace.scope_error import ScopeError

if typing.TYPE_CHECKING:
    from ancalagon.config.config import Config


def missing_hint(path: pathlib.PurePath) -> str:
    return f"no file or directory at {path}{_hint(path)}"


def _hint(path: pathlib.PurePath) -> str:
    if path.is_absolute():
        return ""
    return ". Relative paths resolve against the working directory; give an absolute path"


class Workspace:
    def __init__(
        self,
        fs: FileSystem,
        write_roots: tuple[pathlib.PurePath, ...],
        read_roots: tuple[pathlib.PurePath, ...],
    ):
        self.fs = fs
        self.write_roots = tuple(fs.resolve(fs.expanduser(r)) for r in write_roots)
        self.read_roots = tuple(fs.resolve(fs.expanduser(r)) for r in read_roots)

    @classmethod
    def from_config(cls, config: "Config", fs: FileSystem) -> "Workspace":
        return cls(
            fs,
            write_roots=(*config.write_roots, config.home),
            read_roots=(*config.read_roots, *config.write_roots, config.home),
        )

    def resolve_write(self, path: pathlib.PurePath) -> pathlib.PurePath:
        resolved = self.fs.resolve(self.fs.expanduser(path))
        if not any(resolved.is_relative_to(root) for root in self.write_roots):
            raise ScopeError(f"{path} is outside write_roots {self.write_roots}{_hint(path)}")
        return resolved

    def resolve_read(self, path: pathlib.PurePath) -> pathlib.PurePath:
        resolved = self.fs.resolve(self.fs.expanduser(path))
        if not any(resolved.is_relative_to(root) for root in self.read_roots):
            raise ScopeError(f"{path} is outside read_roots {self.read_roots}{_hint(path)}")
        return resolved

    def read_text(self, path: pathlib.PurePath) -> str:
        return self.fs.read_text(self.resolve_read(path))

    def read_bytes(self, path: pathlib.PurePath) -> bytes:
        return self.fs.read_bytes(self.resolve_read(path))

    def iterdir(self, path: pathlib.PurePath) -> tuple[pathlib.PurePath, ...]:
        return self.fs.iterdir(self.resolve_read(path))

    def changed_at(self, path: pathlib.PurePath) -> float:
        return self.fs.changed_at(self.resolve_read(path))

    def append_line(self, path: pathlib.PurePath, line: str) -> None:
        resolved = self.resolve_write(path)
        self.mkdir(resolved.parent, parents=True, exist_ok=True)
        handle = self.fs.open_append(resolved)
        handle.write(line + "\n")
        handle.close()

    def exists(self, path: pathlib.PurePath) -> bool:
        return self.fs.exists(self.resolve_read(path))

    def is_file(self, path: pathlib.PurePath) -> bool:
        return self.fs.is_file(self.resolve_read(path))

    def is_dir(self, path: pathlib.PurePath) -> bool:
        return self.fs.is_dir(self.resolve_read(path))

    def write_text(self, path: pathlib.PurePath, text: str) -> None:
        self.fs.write_text(self.resolve_write(path), text)

    def mkdir(self, path: pathlib.PurePath, parents: bool = False, exist_ok: bool = False) -> None:
        self.fs.mkdir(self.resolve_write(path), parents=parents, exist_ok=exist_ok)

    def unlink(self, path: pathlib.PurePath) -> None:
        self.fs.unlink(self.resolve_write(path))
