PRAGMA journal_mode = WAL;

CREATE TABLE tasks (
    id           INTEGER PRIMARY KEY,
    dir          TEXT    NOT NULL UNIQUE,
    parent_agent INTEGER NOT NULL DEFAULT 0,
    created      TEXT    NOT NULL
);

CREATE TABLE agents (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task    INTEGER NOT NULL REFERENCES tasks (id),
    created TEXT    NOT NULL
);

CREATE INDEX agents_task ON agents (task);

CREATE TABLE agent_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    agent     INTEGER NOT NULL REFERENCES agents (id),
    ts        TEXT    NOT NULL,
    status    TEXT    NOT NULL CHECK (status IN
                  ('queued', 'claimed', 'running', 'completed', 'needs_input',
                   'exhausted', 'failed', 'crashed', 'timed_out',
                   'idling', 'collected')),
    source    TEXT    NOT NULL CHECK (source IN ('supervisor', 'worker')),
    pid       INTEGER NOT NULL DEFAULT 0,
    exit_code INTEGER NOT NULL DEFAULT 0,
    summary   TEXT    NOT NULL DEFAULT '' CHECK (length(summary) <= 1000)
);

CREATE INDEX agent_events_agent ON agent_events (agent, id);

CREATE TABLE model_calls (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    agent                 INTEGER NOT NULL REFERENCES agents (id),
    ts                    TEXT    NOT NULL,
    model                 TEXT    NOT NULL DEFAULT '',
    prompt_tokens         INTEGER NOT NULL DEFAULT 0,
    completion_tokens     INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX model_calls_agent ON model_calls (agent, id);

PRAGMA user_version = 1;
