# Frozen configuration for a single ancalagon run, loaded from TOML.
import pathlib

import pydantic

from ancalagon.contracts.budget import Budget


class Config(pydantic.BaseModel, frozen=True):
    write_root: pathlib.Path
    read_roots: tuple[pathlib.Path, ...]
    model: str
    max_tokens: int
    num_retries: int
    request_timeout_s: int
    budget: Budget
    max_concurrent_agents: int
    agent_timeout_s: int
    max_depth: int
    tools: list[str]
    summary_chars: int
