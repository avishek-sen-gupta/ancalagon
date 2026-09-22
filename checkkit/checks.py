# Deterministic criteria the agents in ancalagon.toml must satisfy.
import pathlib
import re

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.shell.shell_args import ShellArgs
from ancalagon.workspace.scope_error import ScopeError

CITED = re.compile(r"(?<![\w/.])/?(?:[\w.-]+/)*[\w-]+\.py\b")
SUBSYSTEMS = ("bus", "registry", "role")
GENERATED = ("runs", "output", "ws", "node_modules", "__pycache__")


def cites_a_file(answer: FreeText, ctx: ToolContext) -> Reviewed:
    if not CITED.search(answer.text):
        return Refused(
            reason=(
                "your answer cites no file. Name at least one Python file you actually "
                "read. A path relative to a read root, one relative to the repository, "
                "or an absolute one all count."
            )
        )
    return Accepted(value=answer)


def cited_files_exist(answer: FreeText, ctx: ToolContext) -> Reviewed:
    absent = sorted({cited for cited in CITED.findall(answer.text) if not _found(cited, ctx)})
    if absent:
        return Refused(
            reason=(
                f"these cited paths do not exist: {absent}. "
                "Cite only files you opened, and copy the path exactly as the tool "
                "reported it."
            )
        )
    return Accepted(value=answer)


def covers_every_subsystem(answer: FreeText, ctx: ToolContext) -> Reviewed:
    missing = [word for word in SUBSYSTEMS if word not in answer.text.lower()]
    if missing:
        return Refused(
            reason=(
                f"your answer never mentions {missing}. The goal asks for a section per "
                "subsystem, so each must appear with the files it lives in."
            )
        )
    return Accepted(value=answer)


def produced_output(args: ShellArgs, ran: ToolResult, ctx: ToolContext) -> Reviewed:
    if ran.ok and not ran.byte_count:
        return Refused(
            reason=(
                f"`{args.command}` produced no output, so it counted nothing. "
                "Check the directory and the pattern, then run it again."
            )
        )
    return Accepted(value=ran)


def _worth_walking(entry: pathlib.PurePath, ctx: ToolContext) -> bool:
    return (
        ctx.workspace.is_dir(entry)
        and not entry.name.startswith(".")
        and not any(entry.is_relative_to(root) for root in ctx.workspace.write_roots)
        and entry.name not in GENERATED
    )


def _python_under(root: pathlib.PurePath, ctx: ToolContext) -> tuple[pathlib.PurePath, ...]:
    entries = ctx.workspace.iterdir(root)
    return tuple(e for e in entries if e.name.endswith(".py")) + tuple(
        found for e in entries if _worth_walking(e, ctx) for found in _python_under(e, ctx)
    )


def _basenames(ctx: ToolContext) -> frozenset[str]:
    return frozenset(
        found.name for root in ctx.workspace.read_roots for found in _python_under(root, ctx)
    )


def _candidates(cited: str, ctx: ToolContext) -> tuple[pathlib.PurePath, ...]:
    given = pathlib.PurePath(cited)
    if given.is_absolute():
        return (given,)
    return tuple(base / given for root in ctx.workspace.read_roots for base in (root, root.parent))


def _is_file(candidate: pathlib.PurePath, ctx: ToolContext) -> bool:
    try:
        return ctx.workspace.is_file(candidate)
    except ScopeError:
        return False


def _found(cited: str, ctx: ToolContext) -> bool:
    if "/" not in cited:
        return cited in _basenames(ctx)
    return any(_is_file(candidate, ctx) for candidate in _candidates(cited, ctx))
