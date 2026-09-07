# Refuses an answer whose citations do not resolve to those exact lines of a readable file.
import collections.abc
import pathlib

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.cited import Cited
from ancalagon.contracts.evidence import Evidence
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


def _stripped(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()]


def _mismatch(cited: Evidence, lines: collections.abc.Sequence[str]) -> str:
    shown = _stripped("\n".join(lines[cited.start_line - 1 : cited.end_line]))
    if _stripped(cited.quote) == shown:
        return ""
    return (
        f"{cited.path}: quote does not match lines {cited.start_line}-{cited.end_line}, "
        f"which read: " + " / ".join(shown)
    )


def _fault(cited: Evidence, ctx: ToolContext) -> str:
    try:
        text = ctx.workspace.read_text(pathlib.PurePath(cited.path))
    except (ScopeError, OSError) as error:
        return f"{cited.path}: not readable ({error})"
    if cited.end_line < cited.start_line:
        return f"{cited.path}: end_line {cited.end_line} is before start_line {cited.start_line}"
    lines = text.splitlines()
    if cited.end_line > len(lines):
        return (
            f"{cited.path}: lines {cited.start_line}-{cited.end_line} but the file has "
            f"{len(lines)}"
        )
    return _mismatch(cited, lines)


def evidence_resolves(answer: Cited, ctx: ToolContext) -> Reviewed:
    faults = [fault for cited in answer.citations() if (fault := _fault(cited, ctx))]
    if faults:
        return Refused(reason="these citations do not resolve: " + "; ".join(faults))
    return Accepted(value=answer)
