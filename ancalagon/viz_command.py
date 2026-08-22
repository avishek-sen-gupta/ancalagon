# The viz subcommand: turns a trace's JSON into a Mermaid sequence diagram.
import pathlib
import sys

from ancalagon.emit import emit
from ancalagon.fs.file_system import FileSystem
from ancalagon.trace.trace import Trace
from ancalagon.viz.mermaid import mermaid


def _read(source: str, fs: FileSystem) -> str:
    if not source:
        return sys.stdin.read()
    return fs.read_text(pathlib.PurePath(source))


def viz_command(source: str, output: str, fs: FileSystem) -> int:
    emit(mermaid(Trace.model_validate_json(_read(source, fs))), output, fs)
    return 0
