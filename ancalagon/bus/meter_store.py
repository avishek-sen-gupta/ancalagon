# Token accounting: what each agent's model calls cost, on the run's shared connection.
import sqlite3
from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite as sqlite_dialect

from ancalagon.bus.schema import model_calls
from ancalagon.clock.clock import Clock
from ancalagon.contracts.call_usage import CallUsage

DIALECT = sqlite_dialect.dialect(paramstyle="named")

BindValue = str | int

_INSERT_CALL = sa.insert(model_calls).values(
    agent=sa.bindparam("agent"),
    ts=sa.bindparam("ts"),
    model=sa.bindparam("model"),
    prompt_tokens=sa.bindparam("prompt_tokens"),
    completion_tokens=sa.bindparam("completion_tokens"),
    cache_creation_tokens=sa.bindparam("cache_creation_tokens"),
    cache_read_tokens=sa.bindparam("cache_read_tokens"),
)

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


class MeterStore:
    def __init__(self, conn: sqlite3.Connection, clock: Clock):
        self.conn = conn
        self.clock = clock

    def _now(self) -> str:
        return self.clock.now().isoformat()

    def _exec(
        self, stmt: sa.sql.ClauseElement, binds: Mapping[str, BindValue] = {}
    ) -> sqlite3.Cursor:
        return self.conn.execute(str(stmt.compile(dialect=DIALECT)), dict(binds))

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
