# The only place in the codebase that touches a file.
import pathlib
import typing

from ancalagon.fs.file_system import FileSystem


class RealFileSystem(FileSystem):
    def read_text(self, path: pathlib.PurePath) -> str:
        return pathlib.Path(path).read_text(encoding="utf-8")

    def write_text(self, path: pathlib.PurePath, text: str) -> None:
        pathlib.Path(path).write_text(text, encoding="utf-8")

    def read_bytes(self, path: pathlib.PurePath) -> bytes:
        return pathlib.Path(path).read_bytes()

    def mkdir(self, path: pathlib.PurePath, parents: bool = False, exist_ok: bool = False) -> None:
        pathlib.Path(path).mkdir(parents=parents, exist_ok=exist_ok)

    def unlink(self, path: pathlib.PurePath) -> None:
        pathlib.Path(path).unlink()

    def iterdir(self, path: pathlib.PurePath) -> tuple[pathlib.PurePath, ...]:
        return tuple(sorted(pathlib.Path(path).iterdir()))

    def glob(self, path: pathlib.PurePath, pattern: str) -> tuple[pathlib.PurePath, ...]:
        return tuple(sorted(pathlib.Path(path).glob(pattern)))

    # A file that is not there has never been modified, which is what a watcher wants to hear.
    def mtime(self, path: pathlib.PurePath) -> float:
        found = pathlib.Path(path)
        return found.stat().st_mtime if found.exists() else 0.0

    def exists(self, path: pathlib.PurePath) -> bool:
        return pathlib.Path(path).exists()

    def is_file(self, path: pathlib.PurePath) -> bool:
        return pathlib.Path(path).is_file()

    def is_dir(self, path: pathlib.PurePath) -> bool:
        return pathlib.Path(path).is_dir()

    def resolve(self, path: pathlib.PurePath) -> pathlib.PurePath:
        return pathlib.Path(path).resolve()

    def expanduser(self, path: pathlib.PurePath) -> pathlib.PurePath:
        return pathlib.Path(path).expanduser()

    def open_append(self, path: pathlib.PurePath) -> typing.TextIO:
        return pathlib.Path(path).open("a", encoding="utf-8")

    def open_write(self, path: pathlib.PurePath) -> typing.TextIO:
        return pathlib.Path(path).open("w", encoding="utf-8")
