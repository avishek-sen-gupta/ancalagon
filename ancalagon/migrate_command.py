# Migrates an existing run database to a schema version, as a deliberate offline step.
import pathlib
import sqlite3
import sys

import ancalagon.migrations


def migrate_command(path: pathlib.Path, to: int) -> int:
    if not path.is_file():
        raise ValueError(f"{path} does not exist")
    target = ancalagon.migrations.latest_version() if to < 0 else to
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 5000")
    before = ancalagon.migrations.user_version(conn)
    ancalagon.migrations.migrate(conn, target)
    sys.stdout.write(f"{path}: {before} -> {ancalagon.migrations.user_version(conn)}\n")
    return 0
