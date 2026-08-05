# Loads a Config from a TOML file on disk.
import pathlib
import tomllib

from ancalagon.config.config import Config
from ancalagon.contracts.budget import Budget


def load_config(path: pathlib.Path) -> Config:
    base = path.resolve().parent
    raw = tomllib.loads(path.read_text())
    workspace = raw["workspace"]
    model = raw["model"]
    budget = raw["budget"]
    limits = raw["limits"]
    return Config(
        write_root=(base / workspace["write_root"]).resolve(),
        read_roots=tuple((base / p).resolve() for p in workspace["read_roots"]),
        root_behaviour=raw["agent"]["root_behaviour"],
        model=model["name"],
        max_tokens=model["max_tokens"],
        num_retries=model["num_retries"],
        request_timeout_s=model["request_timeout_s"],
        budget=Budget(turns=budget["turns"], tool_calls=budget["tool_calls"]),
        max_concurrent_agents=limits["max_concurrent_agents"],
        agent_timeout_s=limits["agent_timeout_s"],
        max_depth=limits["max_depth"],
        tools=raw["tools"]["enabled"],
        summary_chars=limits["summary_chars"],
    )
