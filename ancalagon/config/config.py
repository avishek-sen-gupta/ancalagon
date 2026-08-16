# One run's configuration. Required fields are the three that cannot be guessed;
# the rest carry the same defaults ancalagon.example.toml ships with.
import collections.abc
import pathlib

import pydantic

from ancalagon.contracts.role import Role
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.sandbox.strategy import Strategy


class Config(pydantic.BaseModel, frozen=True):
    write_root: pathlib.Path
    read_roots: tuple[pathlib.Path, ...]
    model: str
    roles: collections.abc.Mapping[str, Role] = {}
    max_tokens: int = 8000
    num_retries: int = 3
    request_timeout_s: int = 300
    max_concurrent_agents: int = 4
    agent_timeout_s: int = 3600
    max_depth: int = 1
    summary_chars: int = 1000
    compact_above_tokens: int = 60000
    keep_recent_messages: int = 8
    run: RunSettings = RunSettings()
    allowed_domains: tuple[str, ...] = ()
    sandbox: Strategy = Strategy.FENCE
