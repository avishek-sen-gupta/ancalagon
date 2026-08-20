import pathlib
import sqlite3

import pytest

from ancalagon.bus.bus import Bus
from ancalagon.clock.system_clock import SystemClock
from ancalagon.migrate_command import migrate_command
from ancalagon.migrations import latest_version, migrate, migrate_file, user_version


def test_migrations_round_trip_and_checks_reject_bad_rows(tmp_path: pathlib.Path):
    conn = sqlite3.connect(tmp_path / "bus.db")

    assert user_version(conn) == 0
    assert latest_version() == 1

    migrate(conn, latest_version())
    assert user_version(conn) == latest_version()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tasks", "agents", "agent_events", "model_calls"} <= tables
    assert not {"messages", "cursors"} & tables

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
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source) VALUES (1, 't', 'abandoned', 'supervisor')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source) "
            "VALUES (1, 't', 'exited', 'supervisor')"
        )

    conn.execute(
        "INSERT INTO agent_events (agent, ts, status, source) VALUES (1, 't', 'idling', 'worker')"
    )
    conn.execute(
        "INSERT INTO agent_events (agent, ts, status, source) "
        "VALUES (1, 't', 'collected', 'worker')"
    )
    conn.execute("INSERT INTO model_calls (agent, ts, prompt_tokens) VALUES (1, 't', 10)")

    migrate(conn, 0)
    assert user_version(conn) == 0
    remaining = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"tasks", "agents", "agent_events", "model_calls"} & remaining


def test_a_bus_never_migrates_itself_and_the_command_does_it_offline(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    db = tmp_path / "bus.db"
    with pytest.raises(ValueError, match="does not exist"):
        Bus.open(db, SystemClock())

    assert migrate_file(db, latest_version()) == (0, latest_version())
    Bus.open(db, SystemClock())

    stale = tmp_path / "stale.db"
    migrate(sqlite3.connect(stale), 0)
    with pytest.raises(ValueError, match="schema version 0, not 1"):
        Bus.open(stale, SystemClock())

    with pytest.raises(ValueError, match="does not exist"):
        migrate_command(tmp_path / "absent.db", -1)

    assert migrate_command(stale, -1) == 0
    assert capsys.readouterr().out.strip().endswith("0 -> 1")
    Bus.open(stale, SystemClock())

    assert migrate_command(stale, 0) == 0
    with pytest.raises(ValueError, match="schema version 0, not 1"):
        Bus.open(stale, SystemClock())
