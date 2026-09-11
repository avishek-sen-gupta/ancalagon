# A worker is its own process, so it configures logging or its INFO lines go nowhere.
import collections.abc
import logging
import pathlib

import pytest

import ancalagon.deterministic.run
import ancalagon.worker


@pytest.mark.parametrize(
    "entry_point",
    [ancalagon.worker.main, ancalagon.deterministic.run.main],
)
def test_a_child_process_configures_logging_so_info_survives(
    tmp_path: pathlib.Path,
    entry_point: collections.abc.Callable[
        [pathlib.PurePath, pathlib.PurePath, int, pathlib.PurePath], int
    ],
):
    root = logging.getLogger()
    kept_handlers, kept_level = root.handlers, root.level
    try:
        root.handlers = []
        root.setLevel(logging.WARNING)
        with pytest.raises(OSError):
            entry_point(
                pathlib.PurePath(tmp_path / "runs"),
                pathlib.PurePath(tmp_path / "task"),
                1,
                pathlib.PurePath(tmp_path / "absent.json"),
            )
        assert root.level == logging.INFO
        assert len(root.handlers) == 1
    finally:
        root.handlers, root.level = kept_handlers, kept_level
