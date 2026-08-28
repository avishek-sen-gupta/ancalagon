ALTER TABLE agent_events ADD COLUMN seen_through INTEGER NOT NULL DEFAULT 0;

PRAGMA user_version = 2;
