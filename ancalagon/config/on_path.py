# Puts a config's import anchors on sys.path, so its dotted contract classes resolve.
import collections.abc
import pathlib
import sys


def on_path(paths: collections.abc.Sequence[pathlib.PurePath]) -> None:
    fresh = [str(p) for p in paths if str(p) not in sys.path]
    sys.path = [*sys.path, *fresh]
