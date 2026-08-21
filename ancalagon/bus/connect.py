# Opens the run database once, pragmas and schema check included, for every store to share.
import pathlib
import sqlite3

import ancalagon.migrations


def connect(path: pathlib.Path) -> sqlite3.Connection:
    if not path.exists():
        raise ValueError(f"{path} does not exist")
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    found = ancalagon.migrations.user_version(conn)
    latest = ancalagon.migrations.latest_version()
    if found != latest:
        raise ValueError(
            f"{path} is at schema version {found}, not {latest}; "
            f"run: ancalagon migrate --db {path}"
        )
    return conn
