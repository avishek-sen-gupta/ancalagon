# Loads a Config from a TOML file on disk.
import pathlib
import re
import tomllib

from ancalagon.config.config import Config
from ancalagon.config.raw_role import RawClassRef, RawRole
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.role import FREE_TEXT, Role
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.sandbox.strategy import Strategy

ROLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# Every key is read by bracket, never .get(), so a config file must be complete:
# Config's defaults exist for callers building one in code, not to paper over a
# missing key in a file someone believed they had written correctly.
def _root(base: pathlib.Path, value: str) -> pathlib.Path:
    given = pathlib.Path(value).expanduser()
    return given.resolve() if given.is_absolute() else (base / given).resolve()


def _optional_root(base: pathlib.Path, value: str) -> str:
    return str(_root(base, value)) if value else ""


def _run_settings(base: pathlib.Path, run: dict[str, str]) -> RunSettings:
    return RunSettings(
        run_dir=_optional_root(base, run["run_dir"]),
        goal_file=_optional_root(base, run["goal_file"]),
        input_file=_optional_root(base, run["input_file"]),
        role=run["role"],
    )


def _class_ref(base: pathlib.Path, raw: RawClassRef) -> ClassRef:
    return ClassRef(module=str(_root(base, raw.module)), name=raw.name)


def _role(base: pathlib.Path, name: str, raw: RawRole) -> Role:
    if not ROLE_NAME.match(name):
        raise ValueError(
            f"[roles.{name}]: a role name becomes the tool name delegate_{name}, "
            f"so it must match {ROLE_NAME.pattern}"
        )
    return Role(
        behaviour=raw.behaviour,
        input=_class_ref(base, raw.input) if raw.input.module else FREE_TEXT,
        answer=_class_ref(base, raw.answer) if raw.answer.module else FREE_TEXT,
        tools=tuple(raw.tools),
        budget=Budget(turns=raw.budget.turns, tool_calls=raw.budget.tool_calls),
    )


def load_config(path: pathlib.Path) -> Config:
    base = path.resolve().parent
    raw = tomllib.loads(path.read_text())
    workspace = raw["workspace"]
    model = raw["model"]
    limits = raw["limits"]
    return Config(
        write_root=_root(base, workspace["write_root"]),
        read_roots=tuple(_root(base, p) for p in workspace["read_roots"]),
        roles={
            name: _role(base, name, RawRole.model_validate(table))
            for name, table in raw.get("roles", {}).items()
        },
        model=model["name"],
        max_tokens=model["max_tokens"],
        num_retries=model["num_retries"],
        request_timeout_s=model["request_timeout_s"],
        max_concurrent_agents=limits["max_concurrent_agents"],
        agent_timeout_s=limits["agent_timeout_s"],
        max_depth=limits["max_depth"],
        summary_chars=limits["summary_chars"],
        compact_above_tokens=limits["compact_above_tokens"],
        keep_recent_messages=limits["keep_recent_messages"],
        run=_run_settings(base, raw["run"]),
        allowed_domains=tuple(model["allowed_domains"]),
        sandbox=Strategy(raw["sandbox"]["strategy"]),
    )
