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

PRAGMA user_version = 2;
