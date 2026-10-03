# Turns a validated config document into the Config a run is given.
import pathlib
import re

from ancalagon.config.config import Config
from ancalagon.config.document_from_config import DocumentFromConfig, RunFromConfig
from ancalagon.config.on_path import on_path
from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.role import FREE_TEXT
from ancalagon.contracts.run_contracts import run_contracts
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.contracts.serialisable_role import SerialisableRole
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


def _derived(name: str, written: SerialisableRole) -> SerialisableRole:
    if written.run == NO_RUN:
        return written
    if written.input != FREE_TEXT or written.answer != FREE_TEXT:
        raise ValueError(
            f"[roles.{name}]: a role that declares run states its contracts in that "
            f"function's signature, so it must not also declare input or answer"
        )
    given, produced = run_contracts(written.run)
    return written.model_copy(update={"input": given, "answer": produced})


def _role(name: str, written: SerialisableRole) -> SerialisableRole:
    if not ROLE_NAME.match(name):
        raise ValueError(
            f"[roles.{name}]: a role name becomes the tool name delegate_{name}, "
            f"so it must match {ROLE_NAME.pattern}"
        )
    return _derived(name, written)


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
