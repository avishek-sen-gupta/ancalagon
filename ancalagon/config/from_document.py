# Turns a validated config document into the Config a run is given.
import collections.abc
import pathlib
import re
import typing

from ancalagon.config.config import Config
from ancalagon.config.document_from_config import DocumentFromConfig, RunFromConfig
from ancalagon.config.on_path import on_path
from ancalagon.config.role_from_config import ClassRefFromConfig, RoleFromConfig
from ancalagon.contracts.allowance import Allowance
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.finite import Finite
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.infinite import Infinite
from ancalagon.contracts.no_answer_file import NO_ANSWER_FILE
from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.role import FREE_TEXT, Role
from ancalagon.contracts.run_contracts import run_contracts
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.fs.file_system import FileSystem

ROLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _root(base: pathlib.PurePath, value: str, fs: FileSystem) -> pathlib.PurePath:
    given = fs.expanduser(pathlib.PurePath(value))
    return fs.resolve(given if given.is_absolute() else base / given)


def _optional_root(base: pathlib.PurePath, value: str, fs: FileSystem) -> str:
    return str(_root(base, value, fs)) if value else ""


def _run_settings(base: pathlib.PurePath, run: RunFromConfig, fs: FileSystem) -> RunSettings:
    return RunSettings(
        goal_file=_optional_root(base, run.goal_file, fs),
        input_file=_optional_root(base, run.input_file, fs),
        role=run.role,
    )


def _class_ref(raw: ClassRefFromConfig) -> ClassRef:
    return ClassRef(module=raw.module, name=raw.name)


def _hooks(
    raw: collections.abc.Mapping[str, collections.abc.Sequence[ClassRefFromConfig]],
) -> dict[str, tuple[FunctionRef, ...]]:
    return {
        tool: tuple(FunctionRef(module=ref.module, name=ref.name) for ref in refs)
        for tool, refs in raw.items()
    }


def _contracts(name: str, raw: RoleFromConfig) -> tuple[FunctionRef, ClassRef, ClassRef]:
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


def _allowance(given: int | typing.Literal["infinite"]) -> Allowance:
    if isinstance(given, int):
        return Finite(value=given)
    return Infinite()


def _role(name: str, raw: RoleFromConfig) -> Role:
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
        answer_file=_class_ref(raw.answer_file) if raw.answer_file.module else NO_ANSWER_FILE,
        run=run,
        tools=tuple(raw.tools),
        budget=Budget(
            turns=_allowance(raw.budget.turns),
            tool_calls=_allowance(raw.budget.tool_calls),
        ),
        before=_hooks(raw.before),
        after=_hooks(raw.after),
    )


def config_from(raw: DocumentFromConfig, base: pathlib.PurePath, fs: FileSystem) -> Config:
    on_path((base,))
    return Config(
        home=_root(base, raw.workspace.home, fs),
        write_roots=tuple(_root(base, p, fs) for p in raw.workspace.write_roots),
        read_roots=tuple(_root(base, p, fs) for p in raw.workspace.read_roots),
        roles={name: _role(name, table) for name, table in raw.roles.items()},
        model=raw.model.name,
        custom_llm_provider=raw.model.custom_llm_provider,
        max_tokens=raw.model.max_tokens,
        num_retries=raw.model.num_retries,
        request_timeout_s=raw.model.request_timeout_s,
        max_concurrent_agents=raw.limits.max_concurrent_agents,
        agent_timeout_s=raw.limits.agent_timeout_s,
        max_depth=raw.limits.max_depth,
        summary_chars=raw.limits.summary_chars,
        compact_above_tokens=raw.limits.compact_above_tokens,
        keep_recent_messages=raw.limits.keep_recent_messages,
        run=_run_settings(base, raw.run, fs),
        allowed_domains=tuple(raw.model.allowed_domains),
        web_domains=tuple(raw.web.allowed_domains),
        sandbox=raw.sandbox.strategy,
        log_socket=raw.log.socket,
        import_paths=(base,),
    )
