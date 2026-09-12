# Shell: what every agent in a workspace has said since the last time this was asked.
import pathlib

from ancalagon.clock.clock import Clock
from ancalagon.fs.file_system import FileSystem
from ancalagon.transcript.history import load
from ancalagon.watching.rendered import rendered

FRAME = 9
FLOOR = 20
TRANSCRIPTS = ("runs/*/tasks/*/transcript.jsonl", "*/tasks/*/transcript.jsonl")
UNREAD = -1


def _label(path: pathlib.PurePath) -> str:
    return f"{path.parts[-4]}/{path.parts[-2]}"


class Watch:
    def __init__(self, write_root: pathlib.PurePath, fs: FileSystem, clock: Clock, columns: int):
        self.write_root = write_root
        self.fs = fs
        self.clock = clock
        self.columns = columns
        self.read_through: dict[str, int] = {}
        self.changed_at: dict[str, float] = {}
        self._catch_up()

    def _transcripts(self) -> tuple[pathlib.PurePath, ...]:
        found = {p for shape in TRANSCRIPTS for p in self.fs.glob(self.write_root, shape)}
        return tuple(sorted(found))

    def _catch_up(self) -> None:
        for path in self._transcripts():
            self._new_since(path)

    def _new_since(self, path: pathlib.PurePath) -> str:
        where = str(path)
        stamp = self.fs.changed_at(path)
        if stamp <= self.changed_at.get(where, 0.0):
            return ""
        self.changed_at = {**self.changed_at, where: stamp}
        watermark = self.read_through.get(where, UNREAD)
        fresh = [m for m in load(self.fs, path) if m.seq > watermark]
        if not fresh:
            return ""
        self.read_through = {**self.read_through, where: fresh[-1].seq}
        label = _label(path)
        return "".join(rendered(label, m, self._width(label)) for m in fresh)

    def _width(self, label: str) -> int:
        return max(FLOOR, self.columns - len(label) - FRAME)

    def tick(self) -> str:
        return "".join(self._new_since(path) for path in self._transcripts())
