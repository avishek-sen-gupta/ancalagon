# The task queue and append-only agent log. Claiming is atomic so two supervisors never overlap.
import datetime
import pathlib
import sqlite3

import ancalagon.migrations
from ancalagon.bus.agent_event import AgentEvent
from ancalagon.bus.agent_state import AgentState
from ancalagon.bus.agent_status import TERMINAL, AgentStatus
from ancalagon.bus.event_source import EventSource
from ancalagon.bus.message_row import MessageRow
from ancalagon.bus.task_row import TaskRow
from ancalagon.contracts.call_usage import CallUsage

LATEST = """
SELECT a.id AS agent, a.task AS task, t.dir AS dir, t.parent_agent AS parent_agent,
       e.status AS status, e.pid AS pid, e.exit_code AS exit_code, e.summary AS summary
FROM agents a
JOIN tasks t ON t.id = a.task
JOIN agent_events e ON e.id = (SELECT MAX(id) FROM agent_events WHERE agent = a.id)
"""

TERMINAL_MARKS = ", ".join("?" for _ in TERMINAL)
TERMINAL_VALUES = tuple(s.value for s in TERMINAL)


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

    def _states(self, where: str, params: tuple[str | int, ...]) -> list[AgentState]:
        rows = self.conn.execute(LATEST + where, params).fetchall()
        return [AgentState.model_validate({k: r[k] for k in r.keys()}) for r in rows]

    def record(
        self,
        agent: int,
        status: AgentStatus,
        source: EventSource,
        pid: int = 0,
        exit_code: int = 0,
        summary: str = "",
    ) -> None:
        self.conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source, pid, exit_code, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (agent, _now(), status.value, source.value, pid, exit_code, summary[:1000]),
        )

    def enqueue(self, dir: pathlib.Path, parent_agent: int) -> int:
        self.conn.execute("BEGIN IMMEDIATE")
        task = self.conn.execute("SELECT id FROM tasks WHERE dir = ?", (str(dir),)).fetchone()
        if task is None:
            task = self.conn.execute(
                "INSERT INTO tasks (dir, parent_agent, created) VALUES (?, ?, ?) RETURNING id",
                (str(dir), parent_agent, _now()),
            ).fetchone()
        agent = self.conn.execute(
            "INSERT INTO agents (task, created) VALUES (?, ?) RETURNING id",
            (int(task["id"]), _now()),
        ).fetchone()
        agent_id = int(agent["id"])
        self.record(agent_id, AgentStatus.QUEUED, EventSource.SUPERVISOR)
        self.conn.execute("COMMIT")
        return agent_id

    def claim(self, limit: int) -> list[AgentState]:
        self.conn.execute("BEGIN IMMEDIATE")
        waiting = self._states(
            "WHERE e.status = ? ORDER BY a.id LIMIT ?", (AgentStatus.QUEUED.value, limit)
        )
        for state in waiting:
            self.record(state.agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
        self.conn.execute("COMMIT")
        return waiting

    def state(self, agent: int) -> AgentState:
        found = self._states("WHERE a.id = ?", (agent,))
        if not found:
            raise KeyError(f"no agent {agent}")
        return found[0]

    def live(self) -> list[AgentState]:
        return self._states(
            f"WHERE e.status NOT IN ({TERMINAL_MARKS}) ORDER BY a.id", TERMINAL_VALUES
        )

    def in_flight(self) -> list[AgentState]:
        return self._states(
            "WHERE e.status IN (?, ?) ORDER BY a.id",
            (AgentStatus.CLAIMED.value, AgentStatus.RUNNING.value),
        )

    def active_for(self, dir: pathlib.Path) -> list[AgentState]:
        return self._states(
            f"WHERE t.dir = ? AND e.status NOT IN ({TERMINAL_MARKS}) ORDER BY a.id",
            (str(dir), *TERMINAL_VALUES),
        )

    def queued_count(self) -> int:
        return len(self._states("WHERE e.status = ?", (AgentStatus.QUEUED.value,)))

    def history(self, agent: int) -> list[AgentEvent]:
        rows = self.conn.execute(
            "SELECT * FROM agent_events WHERE agent = ? ORDER BY id", (agent,)
        ).fetchall()
        return [AgentEvent.model_validate({k: r[k] for k in r.keys()}) for r in rows]

    def task(self, dir: pathlib.Path) -> TaskRow:
        row = self.conn.execute("SELECT * FROM tasks WHERE dir = ?", (str(dir),)).fetchone()
        if row is None:
            raise KeyError(f"no task at {dir}")
        return TaskRow.model_validate({k: row[k] for k in row.keys()})

    def record_call(self, agent: int, usage: CallUsage) -> None:
        self.conn.execute(
            "INSERT INTO model_calls (agent, ts, model, prompt_tokens, completion_tokens, "
            "cache_creation_tokens, cache_read_tokens) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                agent,
                _now(),
                usage.model,
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.cache_creation_tokens,
                usage.cache_read_tokens,
            ),
        )

    def calls(self, agent: int) -> list[CallUsage]:
        rows = self.conn.execute(
            "SELECT model, prompt_tokens, completion_tokens, cache_creation_tokens, "
            "cache_read_tokens FROM model_calls WHERE agent = ? ORDER BY id",
            (agent,),
        ).fetchall()
        return [CallUsage.model_validate({k: r[k] for k in r.keys()}) for r in rows]

    def tokens_by_agent(self) -> dict[int, CallUsage]:
        rows = self.conn.execute(
            "SELECT agent, MAX(model) AS model, SUM(prompt_tokens) AS prompt_tokens, "
            "SUM(completion_tokens) AS completion_tokens, "
            "SUM(cache_creation_tokens) AS cache_creation_tokens, "
            "SUM(cache_read_tokens) AS cache_read_tokens "
            "FROM model_calls GROUP BY agent ORDER BY agent"
        ).fetchall()
        return {
            int(r["agent"]): CallUsage.model_validate({k: r[k] for k in r.keys() if k != "agent"})
            for r in rows
        }

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
