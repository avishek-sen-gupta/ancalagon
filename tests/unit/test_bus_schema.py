# The migrated database columns must match the schema.py Table definitions the bus queries against.
import pathlib
import sqlite3

from ancalagon.bus import schema
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.migrations import latest_version, migrate_file


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def test_schema_py_tables_match_the_migrated_database_columns(tmp_path: pathlib.Path):
    db = tmp_path / "bus.db"
    migrate_file(db, latest_version(RealFileSystem()), RealFileSystem())
    conn = sqlite3.connect(db)

    assert _columns(conn, "tasks") == ["id", "dir", "parent_agent", "created"]
    assert [c.name for c in schema.tasks.columns] == ["id", "dir", "parent_agent", "created"]

    assert _columns(conn, "agents") == ["id", "task", "created"]
    assert [c.name for c in schema.agents.columns] == ["id", "task", "created"]

    assert _columns(conn, "agent_events") == [
        "id",
        "agent",
        "ts",
        "status",
        "source",
        "pid",
        "summary",
    ]
    assert [c.name for c in schema.agent_events.columns] == [
        "id",
        "agent",
        "ts",
        "status",
        "source",
        "pid",
        "summary",
    ]

    assert _columns(conn, "model_calls") == [
        "id",
        "agent",
        "ts",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cache_creation_tokens",
        "cache_read_tokens",
    ]
    assert [c.name for c in schema.model_calls.columns] == [
        "id",
        "agent",
        "ts",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cache_creation_tokens",
        "cache_read_tokens",
    ]
