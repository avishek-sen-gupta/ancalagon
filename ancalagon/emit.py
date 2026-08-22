# Writes a command's output to a named file, or to stdout when none was named.
import pathlib
import sys

from ancalagon.fs.file_system import FileSystem


def emit(text: str, output: str, fs: FileSystem) -> None:
    if not output:
        sys.stdout.write(text + "\n")
        return
    fs.write_text(pathlib.PurePath(output), text + "\n")
