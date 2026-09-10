"""Generic gates: what you were asked for exists, your own tests pass, and it imports."""

from __future__ import annotations

import pathlib

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.shell.run_shell import run_shell
from ancalagon.tools.shell.timed_out import TimedOut

SECONDS = 20


def _ran(command: str, ctx: ToolContext) -> tuple[int, str]:
    executed = run_shell(command, ctx.workspace.write_root, SECONDS)
    if isinstance(executed, TimedOut):
        return -1, f"`{command}` did not finish within {executed.seconds}s"
    return executed.exit_code, f"{executed.stdout}{executed.stderr}"[-1200:]


def _absent(names: tuple[str, ...], ctx: ToolContext) -> str:
    missing = [n for n in names if not ctx.workspace.is_file(ctx.workspace.write_root / n)]
    return f"you have not written {missing}" if missing else ""


def _tests_in(ctx: ToolContext) -> list[pathlib.PurePath]:
    found = ctx.workspace.iterdir(ctx.workspace.write_root)
    return sorted(p for p in found if p.name.startswith("test_") and p.name.endswith(".py"))


def _failure(command: str, ctx: ToolContext) -> str:
    code, output = _ran(command, ctx)
    if code == 0:
        return ""
    return f"`{command}` exited {code}, so it is not working yet.\n{output}"


def _failing(commands: tuple[str, ...], ctx: ToolContext) -> str:
    return next((found for found in (_failure(c, ctx) for c in commands) if found), "")


def _checked(
    answer: FreeText, wanted: tuple[str, ...], extra: tuple[str, ...], ctx: ToolContext
) -> Reviewed:
    absent = _absent(wanted, ctx)
    if absent:
        return Refused(reason=f"{absent}. You cannot answer until they are there.")
    tests = _tests_in(ctx)
    if not tests:
        return Refused(reason="you have written no tests, so nothing you claim can be checked")
    failed = _failing(tuple(f"python3 {t.name}" for t in tests) + extra, ctx)
    return Refused(reason=failed) if failed else Accepted(value=answer)


def your_tests_pass(answer: FreeText, ctx: ToolContext) -> Reviewed:
    return _checked(answer, ("engine.py",), (), ctx)


def it_runs_and_your_tests_pass(answer: FreeText, ctx: ToolContext) -> Reviewed:
    return _checked(answer, ("engine.py", "game.py"), ("python3 -c 'import game'",), ctx)
