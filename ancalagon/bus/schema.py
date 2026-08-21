# The table definitions the bus compiles queries against; the schema itself still lives in 001_init.up.sql.
import sqlalchemy as sa

METADATA = sa.MetaData()

tasks = sa.Table(
    "tasks",
    METADATA,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("dir", sa.Text, nullable=False, unique=True),
    sa.Column("parent_agent", sa.Integer, nullable=False),
    sa.Column("created", sa.Text, nullable=False),
)

agents = sa.Table(
    "agents",
    METADATA,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("task", sa.Integer, nullable=False),
    sa.Column("created", sa.Text, nullable=False),
)

agent_events = sa.Table(
    "agent_events",
    METADATA,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("agent", sa.Integer, nullable=False),
    sa.Column("ts", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("pid", sa.Integer, nullable=False),
    sa.Column("summary", sa.Text, nullable=False),
)

model_calls = sa.Table(
    "model_calls",
    METADATA,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("agent", sa.Integer, nullable=False),
    sa.Column("ts", sa.Text, nullable=False),
    sa.Column("model", sa.Text, nullable=False),
    sa.Column("prompt_tokens", sa.Integer, nullable=False),
    sa.Column("completion_tokens", sa.Integer, nullable=False),
    sa.Column("cache_creation_tokens", sa.Integer, nullable=False),
    sa.Column("cache_read_tokens", sa.Integer, nullable=False),
)
