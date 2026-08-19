# The task queue and append-only agent log. Claiming is atomic so two supervisors never overlap.
import pathlib
import sqlite3

import ancalagon.migrations
from ancalagon.attempt.attempt import (
    Attempt,
    Claimed,
    Closed,
    Collected,
    Lost,
    Queued,
    Reported,
    Running,
)
from ancalagon.attempt.attempt_of import attempt_of
from ancalagon.attempt.next_state import next_state
from ancalagon.bus.agent_state import AgentState
from ancalagon.bus.task_row import TaskRow
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_event import AgentEvent
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.call_usage import CallUsage
from ancalagon.contracts.event_source import EventSource

LATEST = """
SELECT a.id AS agent, a.task AS task, t.dir AS dir, t.parent_agent AS parent_agent,
       e.status AS status, e.pid AS pid, e.exit_code AS exit_code, e.summary AS summary
FROM agents a
JOIN tasks t ON t.id = a.task
JOIN agent_events e ON e.id = (SELECT MAX(id) FROM agent_events WHERE agent = a.id)
"""

# Agent ids start at 1, so 0 is the person who started the run rather than any agent.
HUMAN = 0

# The schema's CHECK constraint on agent_events.summary; longer text is truncated.
SUMMARY_LIMIT = 1000


class Bus:
    def __init__(self, conn: sqlite3.Connection, clock: Clock):
        self.conn = conn
        self.clock = clock

    def _now(self) -> str:
        return self.clock.now().isoformat()

    @classmethod
    def _connect(cls, path: pathlib.Path) -> sqlite3.Connection:
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @classmethod
    def open(cls, path: pathlib.Path, clock: Clock) -> "Bus":
        if not path.exists():
            raise ValueError(f"{path} does not exist")
        conn = cls._connect(path)
        found = ancalagon.migrations.user_version(conn)
        latest = ancalagon.migrations.latest_version()
        if found != latest:
            raise ValueError(
                f"{path} is at schema version {found}, not {latest}; "
                f"run: ancalagon migrate --db {path}"
            )
        return cls(conn, clock)

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
        owns_transaction = not self.conn.in_transaction
        if owns_transaction:
            self.conn.execute("BEGIN IMMEDIATE")
        try:
            current = self.attempt(agent)
            event = AgentEvent(
                id=0,
                agent=agent,
                ts=self._now(),
                status=status,
                source=source,
                pid=pid,
                exit_code=exit_code,
                summary=summary[:SUMMARY_LIMIT],
            )
            next_state(current, event)
            self.conn.execute(
                "INSERT INTO agent_events (agent, ts, status, source, pid, exit_code, summary) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event.agent,
                    event.ts,
                    event.status.value,
                    event.source.value,
                    event.pid,
                    event.exit_code,
                    event.summary,
                ),
            )
        except Exception:
            if owns_transaction:
                self.conn.execute("ROLLBACK")
            raise
        if owns_transaction:
            self.conn.execute("COMMIT")

    def enqueue(self, dir: pathlib.Path, parent_agent: int) -> int:
        self.conn.execute("BEGIN IMMEDIATE")
        task = self.conn.execute("SELECT id FROM tasks WHERE dir = ?", (str(dir),)).fetchone()
        if task is None:
            task = self.conn.execute(
                "INSERT INTO tasks (dir, parent_agent, created) VALUES (?, ?, ?) RETURNING id",
                (str(dir), parent_agent, self._now()),
            ).fetchone()
        agent = self.conn.execute(
            "INSERT INTO agents (task, created) VALUES (?, ?) RETURNING id",
            (int(task["id"]), self._now()),
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

    def attempt(self, agent: int) -> Attempt:
        return attempt_of(self.history(agent))

    def unreaped(self) -> list[AgentState]:
        return [
            state
            for state in self._states("ORDER BY a.id", ())
            if isinstance(self.attempt(state.agent), (Claimed, Running, Reported))
        ]

    def _reaped(self, agent: int) -> bool:
        return isinstance(self.attempt(agent), (Closed, Lost, Collected))

    def active_for(self, dir: pathlib.Path) -> list[AgentState]:
        return [
            state
            for state in self._states("WHERE t.dir = ? ORDER BY a.id", (str(dir),))
            if isinstance(self.attempt(state.agent), (Queued, Claimed, Running, Reported))
        ]

    def newest_agent(self, task: int) -> int:
        return int(
            self.conn.execute(
                "SELECT MAX(id) AS agent FROM agents WHERE task = ?", (task,)
            ).fetchone()["agent"]
        )

    def child_tasks(self, task: int) -> list[TaskRow]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE parent_agent IN "
            "(SELECT id FROM agents WHERE task = ?) ORDER BY id",
            (task,),
        ).fetchall()
        return [TaskRow.model_validate({k: r[k] for k in r.keys()}) for r in rows]

    def outstanding(self, task: int) -> bool:
        match self.attempt(self.newest_agent(task)):
            case Closed(verdict=closed_verdict):
                return closed_verdict is AgentStatus.IDLING
            case Collected(verdict=collected_verdict):
                return collected_verdict is AgentStatus.IDLING
            case Lost():
                return False
            case _:
                return True

    def uncollected(self, task: int) -> list[int]:
        return [
            self.newest_agent(t.id)
            for t in self.child_tasks(task)
            if isinstance(self.attempt(self.newest_agent(t.id)), (Closed, Lost))
        ]

    def _all_tasks(self) -> list[TaskRow]:
        rows = self.conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        return [TaskRow.model_validate({k: r[k] for k in r.keys()}) for r in rows]

    def _last_idled_event_id(self, task: int) -> int:
        row = self.conn.execute(
            "SELECT MAX(id) AS id FROM agent_events WHERE agent = ? AND status = ?",
            (self.newest_agent(task), AgentStatus.IDLING.value),
        ).fetchone()
        return int(row["id"] or 0)

    def _is_news(self, agent: int) -> bool:
        match self.attempt(agent):
            case Closed(verdict=verdict):
                return verdict is not AgentStatus.IDLING
            case Lost():
                return True
            case _:
                return False

    def _has_news(self, task: int) -> bool:
        idled_at = self._last_idled_event_id(task)
        if idled_at == 0:
            return False
        return any(
            self._is_news(self.newest_agent(child.id))
            and self._newest_event_id(self.newest_agent(child.id)) > idled_at
            for child in self.child_tasks(task)
        )

    def _newest_event_id(self, agent: int) -> int:
        return int(
            self.conn.execute(
                "SELECT MAX(id) AS id FROM agent_events WHERE agent = ?", (agent,)
            ).fetchone()["id"]
        )

    def wakeable(self) -> list[TaskRow]:
        return [t for t in self._all_tasks() if self._has_news(t.id)]

    def live_children(self, agent: int) -> list[AgentState]:
        task = self.state(agent).task
        return [
            self.state(self.newest_agent(t.id))
            for t in self.child_tasks(task)
            if self.outstanding(t.id)
        ]

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
                self._now(),
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
