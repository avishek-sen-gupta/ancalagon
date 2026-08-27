# Loads a Config from a TOML file on disk.
import collections.abc
import pathlib
import re
import tomllib

from ancalagon.config.config import Config
from ancalagon.config.importable import importable
from ancalagon.config.raw_role import RawClassRef, RawRole
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.role import FREE_TEXT, Role
from ancalagon.contracts.run_contracts import run_contracts
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.fs.file_system import FileSystem
from ancalagon.sandbox.strategy import Strategy

ROLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# Every key is read by bracket, never .get(), so a config file must be complete:
# Config's defaults exist for callers building one in code, not to paper over a
# missing key in a file someone believed they had written correctly.
def _root(base: pathlib.PurePath, value: str, fs: FileSystem) -> pathlib.PurePath:
    given = fs.expanduser(pathlib.PurePath(value))
    return fs.resolve(given if given.is_absolute() else base / given)


def _optional_root(base: pathlib.PurePath, value: str, fs: FileSystem) -> str:
    return str(_root(base, value, fs)) if value else ""


def _run_settings(
    base: pathlib.PurePath, run: collections.abc.Mapping[str, str], fs: FileSystem
) -> RunSettings:
    return RunSettings(
        goal_file=_optional_root(base, run["goal_file"], fs),
        input_file=_optional_root(base, run["input_file"], fs),
        role=run["role"],
    )


def _class_ref(raw: RawClassRef) -> ClassRef:
    return ClassRef(module=raw.module, name=raw.name)


def _hooks(
    raw: collections.abc.Mapping[str, collections.abc.Sequence[RawClassRef]],
) -> dict[str, tuple[FunctionRef, ...]]:
    return {
        tool: tuple(FunctionRef(module=ref.module, name=ref.name) for ref in refs)
        for tool, refs in raw.items()
    }


def _contracts(name: str, raw: RawRole) -> tuple[FunctionRef, ClassRef, ClassRef]:
    if not raw.run.module:
        return (
            NO_RUN,
            _class_ref(raw.input) if raw.input.module else FREE_TEXT,
            _class_ref(raw.answer) if raw.answer.module else FREE_TEXT,
        )
    if raw.input.module or raw.answer.module:
        raise ValueError(
            f"[roles.{name}]: a role that declares run states its contracts in that "
            f"function's signature, so it must not also declare input or answer"
        )
    ref = FunctionRef(module=raw.run.module, name=raw.run.name)
    given, produced = run_contracts(ref)
    return ref, given, produced


def _role(name: str, raw: RawRole) -> Role:
    if not ROLE_NAME.match(name):
        raise ValueError(
            f"[roles.{name}]: a role name becomes the tool name delegate_{name}, "
            f"so it must match {ROLE_NAME.pattern}"
        )
    run, given, produced = _contracts(name, raw)
    return Role(
        behaviour=raw.behaviour,
        input=given,
        answer=produced,
        run=run,
        tools=tuple(raw.tools),
        budget=Budget(turns=raw.budget.turns, tool_calls=raw.budget.tool_calls),
        before=_hooks(raw.before),
        after=_hooks(raw.after),
    )


def load_config(path: pathlib.PurePath, fs: FileSystem) -> Config:
    base = fs.resolve(path).parent
    importable(base)
    raw = tomllib.loads(fs.read_text(path))
    workspace = raw["workspace"]
    model = raw["model"]
    limits = raw["limits"]
    return Config(
        write_root=_root(base, workspace["write_root"], fs),
        read_roots=tuple(_root(base, p, fs) for p in workspace["read_roots"]),
        roles={
            name: _role(name, RawRole.model_validate(table))
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
        run=_run_settings(base, raw["run"], fs),
        allowed_domains=tuple(model["allowed_domains"]),
        sandbox=Strategy(raw["sandbox"]["strategy"]),
    )
