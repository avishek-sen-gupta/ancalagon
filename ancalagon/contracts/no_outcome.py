# Raised when a run finishes without the root task ever writing an outcome file.
import pathlib


class NoOutcome(Exception):
    def __init__(self, task_dir: pathlib.PurePath):
        super().__init__(f"root task produced no outcome; see {task_dir}")
