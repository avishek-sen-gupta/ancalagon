import datetime
import pathlib
import sqlite3

import ancalagon.migrations
from ancalagon.bus.message_row import MessageRow
from ancalagon.bus.task_row import TaskRow
from ancalagon.bus.task_status import TaskStatus


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


class Bus:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @classmethod
    def open(cls, path: pathlib.Path) -> "Bus":
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        ancalagon.migrations.migrate(conn, ancalagon.migrations.latest_version())
        return cls(conn)

    def enqueue(self, dir: pathlib.Path, parent: int) -> int:
        cursor = self.conn.execute(
            "INSERT INTO tasks (dir, parent, status, started) VALUES (?, ?, ?, ?) RETURNING id",
            (str(dir), parent, TaskStatus.QUEUED.value, ""),
        )
        row = cursor.fetchone()
        return int(row["id"])

    def claim(self, limit: int) -> list[TaskRow]:
        self.conn.execute("BEGIN IMMEDIATE")
        rows = self.conn.execute(
            "UPDATE tasks SET status = ?, started = ? WHERE id IN "
            "(SELECT id FROM tasks WHERE status = ? ORDER BY id LIMIT ?) RETURNING *",
            (TaskStatus.RUNNING.value, _now(), TaskStatus.QUEUED.value, limit),
        ).fetchall()
        self.conn.execute("COMMIT")
        return [TaskRow.model_validate({k: r[k] for k in r.keys()}) for r in rows]

    def mark_running(self, task_id: int, pid: int) -> None:
        self.conn.execute("UPDATE tasks SET pid = ? WHERE id = ?", (pid, task_id))

    def finish(self, task_id: int, status: TaskStatus, exit_code: int, summary: str) -> None:
        self.conn.execute(
            "UPDATE tasks SET status = ?, exit_code = ?, summary = ?, finished = ? WHERE id = ?",
            (status.value, exit_code, summary, _now(), task_id),
        )

    def get(self, task_id: int) -> TaskRow:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"no task {task_id}")
        return TaskRow.model_validate({k: row[k] for k in row.keys()})

    def running(self) -> list[TaskRow]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status = ? AND pid != 0 ORDER BY id",
            (TaskStatus.RUNNING.value,),
        ).fetchall()
        return [TaskRow.model_validate({k: r[k] for k in r.keys()}) for r in rows]

    def post(self, sender: int, addressee: int, kind: str, summary: str, ref_path: str) -> None:
        self.conn.execute(
            "INSERT INTO messages (ts, sender, addressee, kind, summary, ref_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), sender, addressee, kind, summary, ref_path),
        )

    def inbox(self, consumer: int) -> list[MessageRow]:
        seen = self.conn.execute(
            "SELECT last_seen_id FROM cursors WHERE consumer = ?", (consumer,)
        ).fetchone()
        last = int(seen["last_seen_id"]) if seen is not None else 0
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE addressee = ? AND id > ? ORDER BY id",
            (consumer, last),
        ).fetchall()
        if rows:
            self.conn.execute(
                "INSERT INTO cursors (consumer, last_seen_id) VALUES (?, ?) "
                "ON CONFLICT(consumer) DO UPDATE SET last_seen_id = excluded.last_seen_id",
                (consumer, int(rows[-1]["id"])),
            )
        return [MessageRow.model_validate({k: r[k] for k in r.keys()}) for r in rows]
