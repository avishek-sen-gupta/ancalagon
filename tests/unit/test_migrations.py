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
    assert {"tasks", "agents", "agent_events", "messages", "cursors"} <= tables

    conn.execute("INSERT INTO tasks (dir, created) VALUES ('ws/tasks/a', 't')")
    conn.execute("INSERT INTO agents (task, created) VALUES (1, 't')")
    conn.execute(
        "INSERT INTO agent_events (agent, ts, status, source) VALUES (1, 't', 'queued', 'supervisor')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tasks (dir, created) VALUES ('ws/tasks/a', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source) VALUES (1, 't', 'bogus', 'supervisor')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source) VALUES (1, 't', 'queued', 'nobody')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source, summary) "
            "VALUES (1, 't', 'queued', 'supervisor', ?)",
            ("x" * 1001,),
        )

    migrate(conn, 0)
    assert user_version(conn) == 0
    remaining = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"tasks", "agents", "agent_events"} & remaining
