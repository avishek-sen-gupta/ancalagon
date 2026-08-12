# Migrates an existing run database to a schema version, without starting a run.
import pathlib
import sys

import ancalagon.migrations


def migrate_command(path: pathlib.Path, to: int) -> int:
    if not path.is_file():
        raise ValueError(f"{path} does not exist")
    target = ancalagon.migrations.latest_version() if to < 0 else to
    before, after = ancalagon.migrations.migrate_file(path, target)
    sys.stdout.write(f"{path}: {before} -> {after}\n")
    return 0
