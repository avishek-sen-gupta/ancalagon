# The task queue and append-only agent log. Claiming is atomic so two supervisors never overlap.
import pathlib
import sqlite3
from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite as sqlite_dialect

import ancalagon.migrations
from ancalagon.attempt.attempt import (
    Attempt,
    Claimed,
    Closed,
    Collected,
    Lost,
    Queued,
    Running,
)
from ancalagon.attempt.attempt_of import attempt_of
from ancalagon.attempt.next_state import next_state
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.bus.agent_state import AgentState
from ancalagon.bus.schema import agent_events, agents, model_calls, tasks
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_event import AgentEvent
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.call_usage import CallUsage
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
    _T.c.parent_agent.label("parent_agent"),
    _E.c.status.label("status"),
    _E.c.pid.label("pid"),
    _E.c.summary.label("summary"),
).select_from(_A.join(_T, _T.c.id == _A.c.task).join(_E, _E.c.id == _LATEST_EVENT_ID))

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

_INSERT_CALL = sa.insert(model_calls).values(
    agent=sa.bindparam("agent"),
    ts=sa.bindparam("ts"),
    model=sa.bindparam("model"),
    prompt_tokens=sa.bindparam("prompt_tokens"),
    completion_tokens=sa.bindparam("completion_tokens"),
    cache_creation_tokens=sa.bindparam("cache_creation_tokens"),
    cache_read_tokens=sa.bindparam("cache_read_tokens"),
)

_NEWEST_AGENT = sa.select(sa.func.max(agents.c.id).label("agent")).where(
    agents.c.task == sa.bindparam("task")
)

_CHILD_TASKS = (
    sa.select(tasks)
    .where(
        tasks.c.parent_agent.in_(
            sa.select(agents.c.id).where(agents.c.task == sa.bindparam("task"))
        )
    )
    .order_by(tasks.c.id)
)

_ALL_TASKS = sa.select(tasks).order_by(tasks.c.id)

_ALL_AGENTS = sa.select(agents).order_by(agents.c.id)

_ALL_EVENTS = sa.select(agent_events).order_by(agent_events.c.id)

_LAST_IDLED_EVENT_ID = sa.select(sa.func.max(agent_events.c.id).label("id")).where(
    sa.and_(
        agent_events.c.agent == sa.bindparam("agent"),
        agent_events.c.status == sa.bindparam("status"),
    )
)

_NEWEST_EVENT_ID = sa.select(sa.func.max(agent_events.c.id).label("id")).where(
    agent_events.c.agent == sa.bindparam("agent")
)

_HISTORY = (
    sa.select(agent_events)
    .where(agent_events.c.agent == sa.bindparam("agent"))
    .order_by(agent_events.c.id)
)

_TASK_BY_DIR = sa.select(tasks).where(tasks.c.dir == sa.bindparam("dir"))

_CALLS = (
    sa.select(
        model_calls.c.model,
        model_calls.c.prompt_tokens,
        model_calls.c.completion_tokens,
        model_calls.c.cache_creation_tokens,
        model_calls.c.cache_read_tokens,
    )
    .where(model_calls.c.agent == sa.bindparam("agent"))
    .order_by(model_calls.c.id)
)

_TOKENS_BY_AGENT = (
    sa.select(
        model_calls.c.agent,
        sa.func.max(model_calls.c.model).label("model"),
        sa.func.sum(model_calls.c.prompt_tokens).label("prompt_tokens"),
        sa.func.sum(model_calls.c.completion_tokens).label("completion_tokens"),
        sa.func.sum(model_calls.c.cache_creation_tokens).label("cache_creation_tokens"),
        sa.func.sum(model_calls.c.cache_read_tokens).label("cache_read_tokens"),
    )
    .group_by(model_calls.c.agent)
    .order_by(model_calls.c.agent)
)

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

    def _exec(
        self, stmt: sa.sql.ClauseElement, binds: Mapping[str, BindValue] = {}
    ) -> sqlite3.Cursor:
        return self.conn.execute(str(stmt.compile(dialect=DIALECT)), dict(binds))

    def _states(
        self,
        stmt: sa.sql.Select[tuple[int, int, str, int, str, int, str]],
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

    def state(self, agent: int) -> AgentState:
        found = self._states(_LATEST.where(_A.c.id == sa.bindparam("agent")), {"agent": agent})
        if not found:
            raise KeyError(f"no agent {agent}")
        return found[0]

    def attempt(self, agent: int) -> Attempt:
        return attempt_of(self.history(agent))

    def unreaped(self) -> list[AgentState]:
        return [
            state
            for state in self._states(_LATEST.order_by(_A.c.id))
            if isinstance(self.attempt(state.agent), (Claimed, Running))
        ]

    def active_for(self, dir: pathlib.Path) -> list[AgentState]:
        return [
            state
            for state in self._states(
                _LATEST.where(_T.c.dir == sa.bindparam("dir")).order_by(_A.c.id),
                {"dir": str(dir)},
            )
            if isinstance(self.attempt(state.agent), (Queued, Claimed, Running))
        ]

    def newest_agent(self, task: int) -> int:
        return int(self._exec(_NEWEST_AGENT, {"task": task}).fetchone()["agent"])

    def child_tasks(self, task: int) -> list[HarnessTask]:
        rows = self._exec(_CHILD_TASKS, {"task": task}).fetchall()
        return [HarnessTask.model_validate(dict(r)) for r in rows]

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

    def _all_tasks(self) -> list[HarnessTask]:
        rows = self._exec(_ALL_TASKS).fetchall()
        return [HarnessTask.model_validate(dict(r)) for r in rows]

    def _last_idled_event_id(self, task: int) -> int:
        row = self._exec(
            _LAST_IDLED_EVENT_ID,
            {"agent": self.newest_agent(task), "status": AgentStatus.IDLING.value},
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
        return int(self._exec(_NEWEST_EVENT_ID, {"agent": agent}).fetchone()["id"])

    def wakeable(self) -> list[HarnessTask]:
        return [t for t in self._all_tasks() if self._has_news(t.id)]

    def live_children(self, agent: int) -> list[AgentState]:
        task = self.state(agent).task
        return [
            self.state(self.newest_agent(t.id))
            for t in self.child_tasks(task)
            if self.outstanding(t.id)
        ]

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

    def record_call(self, agent: int, usage: CallUsage) -> None:
        self._exec(
            _INSERT_CALL,
            {
                "agent": agent,
                "ts": self._now(),
                "model": usage.model,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cache_creation_tokens": usage.cache_creation_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
            },
        )

    def calls(self, agent: int) -> list[CallUsage]:
        rows = self._exec(_CALLS, {"agent": agent}).fetchall()
        return [CallUsage.model_validate(dict(r)) for r in rows]

    def tokens_by_agent(self) -> dict[int, CallUsage]:
        rows = self._exec(_TOKENS_BY_AGENT).fetchall()
        return {
            int(r["agent"]): CallUsage.model_validate(
                {k: v for k, v in dict(r).items() if k != "agent"}
            )
            for r in rows
        }

    def snapshot(self) -> Snapshot:
        snap_tasks = tuple(
            HarnessTask.model_validate(dict(r)) for r in self._exec(_ALL_TASKS).fetchall()
        )
        agent_rows = [dict(r) for r in self._exec(_ALL_AGENTS).fetchall()]
        event_rows = [
            AgentEvent.model_validate(dict(r)) for r in self._exec(_ALL_EVENTS).fetchall()
        ]
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
