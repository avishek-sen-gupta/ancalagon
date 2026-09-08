# A task's letterbox on disk: one file per note, named so that a sorted listing is chronological.
import pathlib

from ancalagon.fs.file_system import FileSystem
from ancalagon.letterbox.letterbox import Letterbox

NOTES = "notes"
SUFFIX = "*.txt"


class FileLetterbox(Letterbox):
    def __init__(self, fs: FileSystem, task_dir: pathlib.PurePath):
        self.fs = fs
        self.dir = task_dir / NOTES

    def _waiting(self) -> tuple[pathlib.PurePath, ...]:
        return self.fs.glob(self.dir, SUFFIX)

    def unread(self) -> tuple[str, ...]:
        return tuple(self.fs.read_text(path) for path in self._waiting())

    def mark(self, delivered: int) -> None:
        for path in self._waiting()[:delivered]:
            self.fs.unlink(path)
