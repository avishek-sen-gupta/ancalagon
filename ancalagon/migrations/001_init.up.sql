PRAGMA journal_mode = WAL;

CREATE TABLE tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    dir        TEXT    NOT NULL,
    parent     INTEGER NOT NULL DEFAULT 0,
    status     TEXT    NOT NULL CHECK (status IN
                   ('queued', 'running', 'completed', 'crashed', 'timeout', 'abandoned')),
    pid        INTEGER NOT NULL DEFAULT 0,
    exit_code  INTEGER NOT NULL DEFAULT 0,
    summary    TEXT    NOT NULL DEFAULT '' CHECK (length(summary) <= 1000),
    started    TEXT    NOT NULL DEFAULT '',
    finished   TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX tasks_status ON tasks (status);
CREATE INDEX tasks_dir    ON tasks (dir);
CREATE INDEX tasks_parent ON tasks (parent);

CREATE TABLE messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL,
    sender     INTEGER NOT NULL,
    addressee  INTEGER NOT NULL,
    kind       TEXT    NOT NULL,
    summary    TEXT    NOT NULL DEFAULT '' CHECK (length(summary) <= 1000),
    ref_path   TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX messages_inbox ON messages (addressee, id);

CREATE TABLE cursors (
    consumer      INTEGER PRIMARY KEY,
    last_seen_id  INTEGER NOT NULL DEFAULT 0
);

PRAGMA user_version = 1;
