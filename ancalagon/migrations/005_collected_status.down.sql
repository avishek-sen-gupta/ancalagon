DELETE FROM agent_events WHERE status = 'collected';

ALTER TABLE agent_events RENAME TO agent_events_old;
DROP INDEX agent_events_agent;

CREATE TABLE agent_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    agent     INTEGER NOT NULL REFERENCES agents (id),
    ts        TEXT    NOT NULL,
    status    TEXT    NOT NULL CHECK (status IN
                  ('queued', 'claimed', 'running', 'completed', 'needs_input',
                   'exhausted', 'failed', 'crashed', 'timed_out', 'abandoned', 'exited', 'idling')),
    source    TEXT    NOT NULL CHECK (source IN ('supervisor', 'worker')),
    pid       INTEGER NOT NULL DEFAULT 0,
    exit_code INTEGER NOT NULL DEFAULT 0,
    summary   TEXT    NOT NULL DEFAULT '' CHECK (length(summary) <= 1000)
);

CREATE INDEX agent_events_agent ON agent_events (agent, id);

INSERT INTO agent_events SELECT * FROM agent_events_old;
DROP TABLE agent_events_old;

PRAGMA user_version = 4;
