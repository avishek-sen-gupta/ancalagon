import pathlib
import sqlite3

import pytest

from ancalagon.migrations import latest_version, migrate, user_version


def test_migrations_round_trip_and_checks_reject_bad_rows(tmp_path: pathlib.Path):
    conn = sqlite3.connect(tmp_path / "bus.db")

    assert user_version(conn) == 0
    assert latest_version() == 1

    migrate(conn, latest_version())
    assert user_version(conn) == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tasks", "messages", "cursors"} <= tables

    conn.execute("INSERT INTO tasks (dir, status) VALUES ('ws/tasks/a', 'queued')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tasks (dir, status) VALUES ('ws/tasks/b', 'bogus')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tasks (dir, status, summary) VALUES ('ws/tasks/c', 'queued', ?)",
            ("x" * 1001,),
        )

    migrate(conn, 0)
    assert user_version(conn) == 0
    remaining = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "tasks" not in remaining
