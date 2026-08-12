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

PRAGMA user_version = 2;
