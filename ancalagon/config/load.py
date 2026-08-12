# Loads a Config from a TOML file on disk.
import pathlib
import tomllib

from ancalagon.config.config import Config
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.run_settings import RunSettings


# Every key is read by bracket, never .get(), so a config file must be complete:
# Config's defaults exist for callers building one in code, not to paper over a
# missing key in a file someone believed they had written correctly.
def _root(base: pathlib.Path, value: str) -> pathlib.Path:
    given = pathlib.Path(value).expanduser()
    return given.resolve() if given.is_absolute() else (base / given).resolve()


def _optional_root(base: pathlib.Path, value: str) -> str:
    return str(_root(base, value)) if value else ""


def _run_settings(base: pathlib.Path, run: dict[str, str]) -> RunSettings:
    module, _, class_name = run["contract"].partition(":")
    if run["contract"] and not (module and class_name):
        raise ValueError(f'contract "{run["contract"]}" must be written path.py:ClassName')
    return RunSettings(
        run_dir=_optional_root(base, run["run_dir"]),
        goal_file=_optional_root(base, run["goal_file"]),
        contract_module=_optional_root(base, module),
        contract_class=class_name,
    )


def load_config(path: pathlib.Path) -> Config:
    base = path.resolve().parent
    raw = tomllib.loads(path.read_text())
    workspace = raw["workspace"]
    model = raw["model"]
    budget = raw["budget"]
    limits = raw["limits"]
    return Config(
        write_root=_root(base, workspace["write_root"]),
        read_roots=tuple(_root(base, p) for p in workspace["read_roots"]),
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
        compact_above_tokens=limits["compact_above_tokens"],
        keep_recent_messages=limits["keep_recent_messages"],
        run=_run_settings(base, raw["run"]),
    )
