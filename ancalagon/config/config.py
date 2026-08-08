# One run's configuration. Required fields are the three that cannot be guessed;
# the rest carry the same defaults ancalagon.example.toml ships with.
import pathlib

import pydantic

from ancalagon.contracts.budget import Budget

ROOT_BEHAVIOUR = (
    "You investigate a codebase or a set of artifacts to answer the goal you are given.\n"
    "Read before concluding, and prefer evidence from the files over recall.\n"
    "Delegate a focused subtask when a question is self-contained and you want it\n"
    "answered in a shape you can rely on.\n"
)


class Config(pydantic.BaseModel, frozen=True):
    write_root: pathlib.Path
    read_roots: tuple[pathlib.Path, ...]
    model: str
    root_behaviour: str = ROOT_BEHAVIOUR
    max_tokens: int = 8000
    num_retries: int = 3
    request_timeout_s: int = 300
    budget: Budget = Budget(turns=20, tool_calls=60)
    max_concurrent_agents: int = 4
    agent_timeout_s: int = 3600
    max_depth: int = 1
    tools: list[str] = []
    summary_chars: int = 1000
    compact_above_tokens: int = 60000
    keep_recent_messages: int = 8
