# Loads a Config from a TOML file on disk.
import pathlib
import tomllib

from ancalagon.config.config import Config
from ancalagon.contracts.budget import Budget


def load_config(path: pathlib.Path) -> Config:
    raw = tomllib.loads(path.read_text())
    workspace = raw["workspace"]
    model = raw["model"]
    budget = raw["budget"]
    limits = raw["limits"]
    return Config(
        write_root=pathlib.Path(workspace["write_root"]),
        read_roots=tuple(pathlib.Path(p) for p in workspace["read_roots"]),
        model=model["name"],
        max_tokens=model["max_tokens"],
        budget=Budget(turns=budget["turns"], tool_calls=budget["tool_calls"]),
        max_concurrent_agents=limits["max_concurrent_agents"],
        agent_timeout_s=limits["agent_timeout_s"],
        max_depth=limits["max_depth"],
        tools=raw["tools"]["enabled"],
        summary_chars=limits["summary_chars"],
    )
