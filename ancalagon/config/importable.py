# Puts a config file's own directory on the import path, so the modules it names resolve.
import pathlib
import sys


def importable(base: pathlib.PurePath) -> None:
    entry = str(base)
    if entry not in sys.path:
        sys.path = [*sys.path, entry]
