# Shared test helpers for the integration suite.
import collections.abc
import pathlib
import sys

import pytest


@pytest.fixture
def importable() -> collections.abc.Iterator[collections.abc.Callable[[pathlib.Path], None]]:
    path_before = list(sys.path)
    modules_before = set(sys.modules)
    yield lambda directory: sys.path.insert(0, str(directory))
    sys.path[:] = path_before
    for name in set(sys.modules) - modules_before:
        del sys.modules[name]
