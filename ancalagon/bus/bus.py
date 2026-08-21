# The task queue and append-only agent log. Claiming is atomic so two supervisors never overlap.
import pathlib
import sqlite3
from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite as sqlite_dialect

from ancalagon.attempt.attempt import Attempt, Queued
from ancalagon.attempt.attempt_of import attempt_of
from ancalagon.attempt.next_state import next_state
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.bus.agent_state import AgentState
from ancalagon.bus.connect import connect
from ancalagon.bus.schema import agent_events, agents, tasks
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_event import AgentEvent
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.harness_task import HarnessTask

DIALECT = sqlite_dialect.dialect(paramstyle="named")

BindValue = str | int

_A = agents.alias("a")
_T = tasks.alias("t")
_E = agent_events.alias("e")
_LATEST_E = agent_events.alias("le")

_LATEST_EVENT_ID = (
    sa.select(sa.func.max(_LATEST_E.c.id)).where(_LATEST_E.c.agent == _A.c.id).scalar_subquery()
)

_LATEST = sa.select(
    _A.c.id.label("agent"),
    _A.c.task.label("task"),
    _T.c.dir.label("dir"),
).select_from(_A.join(_T, _T.c.id == _A.c.task).join(_E, _E.c.id == _LATEST_EVENT_ID))

_DIR_OF = (
    sa.select(_T.c.dir)
    .select_from(_A.join(_T, _T.c.id == _A.c.task))
    .where(_A.c.id == sa.bindparam("agent"))
)

_INSERT_TASK = (
    sqlite_dialect.insert(tasks)
    .values(
        dir=sa.bindparam("dir"),
        parent_agent=sa.bindparam("parent_agent"),
        created=sa.bindparam("created"),
    )
    .on_conflict_do_update(index_elements=[tasks.c.dir], set_={"dir": tasks.c.dir})
    .returning(tasks.c.id)
)

_INSERT_AGENT = (
    sa.insert(agents)
    .values(task=sa.bindparam("task"), created=sa.bindparam("created"))
    .returning(agents.c.id)
)

_INSERT_EVENT = sa.insert(agent_events).values(
    agent=sa.bindparam("agent"),
    ts=sa.bindparam("ts"),
    status=sa.bindparam("status"),
    source=sa.bindparam("source"),
    pid=sa.bindparam("pid"),
    summary=sa.bindparam("summary"),
)

_ALL_TASKS = sa.select(tasks).order_by(tasks.c.id)

_ALL_AGENTS = sa.select(agents).order_by(agents.c.id)

_ALL_EVENTS = sa.select(agent_events).order_by(agent_events.c.id)

_HISTORY = (
    sa.select(agent_events)
    .where(agent_events.c.agent == sa.bindparam("agent"))
    .order_by(agent_events.c.id)
)

_TASK_BY_DIR = sa.select(tasks).where(tasks.c.dir == sa.bindparam("dir"))

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
    def open(cls, path: pathlib.Path, clock: Clock) -> "Bus":
        return cls(connect(path), clock)

    def _exec(
        self, stmt: sa.sql.ClauseElement, binds: Mapping[str, BindValue] = {}
    ) -> sqlite3.Cursor:
        return self.conn.execute(str(stmt.compile(dialect=DIALECT)), dict(binds))

    def _states(
        self,
        stmt: sa.sql.Select[tuple[int, int, str]],
        binds: Mapping[str, BindValue] = {},
    ) -> list[AgentState]:
        rows = self._exec(stmt, binds).fetchall()
        return [AgentState.model_validate(dict(r)) for r in rows]

    def _record(
        self,
        agent: int,
        status: AgentStatus,
        source: EventSource,
        pid: int = 0,
        summary: str = "",
    ) -> None:
        current = self.attempt(agent)
        next_state(current, status, source, pid)
        self._exec(
            _INSERT_EVENT,
            {
                "agent": agent,
                "ts": self._now(),
                "status": status.value,
                "source": source.value,
                "pid": pid,
                "summary": summary[:SUMMARY_LIMIT],
            },
        )

    def record(
        self,
        agent: int,
        status: AgentStatus,
        source: EventSource,
        pid: int = 0,
        summary: str = "",
    ) -> None:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._record(agent, status, source, pid, summary)
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def enqueue(self, dir: pathlib.Path, parent_agent: int) -> int:
        self.conn.execute("BEGIN IMMEDIATE")
        task = self._exec(
            _INSERT_TASK,
            {"dir": str(dir), "parent_agent": parent_agent, "created": self._now()},
        ).fetchone()
        agent = self._exec(
            _INSERT_AGENT, {"task": int(task["id"]), "created": self._now()}
        ).fetchone()
        agent_id = int(agent["id"])
        self._record(agent_id, AgentStatus.QUEUED, EventSource.SUPERVISOR)
        self.conn.execute("COMMIT")
        return agent_id

    def _queued(self) -> list[AgentState]:
        return [
            state
            for state in self._states(
                _LATEST.where(_E.c.status == sa.bindparam("status")).order_by(_A.c.id),
                {"status": AgentStatus.QUEUED.value},
            )
            if self.attempt(state.agent) == Queued()
        ]

    def claim(self, limit: int) -> list[AgentState]:
        self.conn.execute("BEGIN IMMEDIATE")
        waiting = self._queued()[:limit]
        for state in waiting:
            self._record(state.agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
        self.conn.execute("COMMIT")
        return waiting

    def dir_of(self, agent: int) -> str:
        match self._exec(_DIR_OF, {"agent": agent}).fetchone():
            case None:
                raise KeyError(f"no agent {agent}")
            case row:
                return str(row["dir"])

    def attempt(self, agent: int) -> Attempt:
        return attempt_of(self.history(agent))

    def queued_count(self) -> int:
        return len(self._queued())

    def history(self, agent: int) -> list[AgentEvent]:
        rows = self._exec(_HISTORY, {"agent": agent}).fetchall()
        return [AgentEvent.model_validate(dict(r)) for r in rows]

    def task(self, dir: pathlib.Path) -> HarnessTask:
        match self._exec(_TASK_BY_DIR, {"dir": str(dir)}).fetchone():
            case None:
                raise KeyError(f"no task at {dir}")
            case row:
                return HarnessTask.model_validate(dict(row))

    def snapshot(self) -> Snapshot:
        self.conn.execute("BEGIN")
        try:
            snap_tasks = tuple(
                HarnessTask.model_validate(dict(r)) for r in self._exec(_ALL_TASKS).fetchall()
            )
            agent_rows = [dict(r) for r in self._exec(_ALL_AGENTS).fetchall()]
            event_rows = [
                AgentEvent.model_validate(dict(r)) for r in self._exec(_ALL_EVENTS).fetchall()
            ]
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")
        agents_by_task = {
            task.id: tuple(int(r["id"]) for r in agent_rows if int(r["task"]) == task.id)
            for task in snap_tasks
        }
        task_by_agent = {int(r["id"]): int(r["task"]) for r in agent_rows}
        events = {
            int(r["id"]): tuple(e for e in event_rows if e.agent == int(r["id"]))
            for r in agent_rows
        }
        return Snapshot(
            tasks=snap_tasks,
            agents_by_task=agents_by_task,
            task_by_agent=task_by_agent,
            events=events,
            attempts={agent: attempt_of(found) for agent, found in events.items()},
        )
