# Migrates an existing run database to a schema version, without starting a run.
import pathlib
import sys

import ancalagon.migrations
from ancalagon.fs.file_system import FileSystem


def migrate_command(path: pathlib.PurePath, to: int, fs: FileSystem) -> int:
    if not fs.is_dir(path.parent):
        raise ValueError(f"{path.parent} does not exist")
    target = ancalagon.migrations.latest_version(fs) if to < 0 else to
    before, after = ancalagon.migrations.migrate_file(path, target, fs)
    sys.stdout.write(f"{path}: {before} -> {after}\n")
    return 0
