# The only place in the codebase that touches a file.
import pathlib
import typing

from ancalagon.fs.file_system import FileSystem


class RealFileSystem(FileSystem):
    def read_text(self, path: pathlib.Path) -> str:
        return path.read_text(encoding="utf-8")

    def write_text(self, path: pathlib.Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")

    def read_bytes(self, path: pathlib.Path) -> bytes:
        return path.read_bytes()

    def mkdir(self, path: pathlib.Path, parents: bool = False, exist_ok: bool = False) -> None:
        path.mkdir(parents=parents, exist_ok=exist_ok)

    def unlink(self, path: pathlib.Path) -> None:
        path.unlink()

    def iterdir(self, path: pathlib.Path) -> tuple[pathlib.Path, ...]:
        return tuple(sorted(path.iterdir()))

    def glob(self, path: pathlib.Path, pattern: str) -> tuple[pathlib.Path, ...]:
        return tuple(sorted(path.glob(pattern)))

    def exists(self, path: pathlib.Path) -> bool:
        return path.exists()

    def is_file(self, path: pathlib.Path) -> bool:
        return path.is_file()

    def is_dir(self, path: pathlib.Path) -> bool:
        return path.is_dir()

    def open_append(self, path: pathlib.Path) -> typing.TextIO:
        return path.open("a", encoding="utf-8")

    def open_write(self, path: pathlib.Path) -> typing.TextIO:
        return path.open("w", encoding="utf-8")
