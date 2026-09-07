# Compares two ranges of lines, in one file or two, and reports them aligned.
import collections.abc
import pathlib

from ancalagon.clock.clock import Clock
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.compare.alignment import align
from ancalagon.tools.compare.diff_args import DiffArgs
from ancalagon.tools.compare.region import Region
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError
from ancalagon.workspace.workspace import missing_hint


def _fault(path: pathlib.PurePath, region: Region, total: int) -> str:
    if region.end_line < region.start_line:
        return f"{path}: end_line {region.end_line} is before start_line {region.start_line}"
    if region.end_line > total:
        return f"{path}: lines {region.start_line}-{region.end_line} but the file has {total}"
    return ""


def _slice(lines: collections.abc.Sequence[str], region: Region) -> collections.abc.Sequence[str]:
    return lines[region.start_line - 1 : region.end_line]


class DiffRegions(Tool[DiffArgs]):
    name = "diff_regions"
    description = (
        "Compare two ranges of lines, in the same file or in two files, and get them aligned "
        "row by row: '= left:right text' for a line that matches, '- left:- text' for one only "
        "in the left range, '+ -:right text' for one only in the right. Both line numbers are "
        "the file's own, so a row can be cited as it stands. Trailing blanks are ignored, "
        "nothing else is. Use it to decide whether two declarations are the same instead of "
        "reading both and comparing them by eye."
    )
    cost = 2
    args_model = DiffArgs

    def __init__(self, clock: Clock):
        self.clock = clock

    def run(self, args: DiffArgs, ctx: ToolContext) -> ToolResult:
        try:
            left = ctx.workspace.resolve_read(args.left.path)
            right = ctx.workspace.resolve_read(args.right.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        absent = [missing_hint(path) for path in (left, right) if not ctx.workspace.is_file(path)]
        if absent:
            return ctx.failure(self.name, absent[0])
        ctx.record(left, self.clock)
        ctx.record(right, self.clock)
        left_lines = ctx.workspace.read_text(left).splitlines()
        right_lines = ctx.workspace.read_text(right).splitlines()
        faults = [
            fault
            for path, region, lines in (
                (left, args.left, left_lines),
                (right, args.right, right_lines),
            )
            if (fault := _fault(path, region, len(lines)))
        ]
        if faults:
            return ctx.failure(self.name, faults[0])
        aligned = align(
            _slice(left_lines, args.left),
            _slice(right_lines, args.right),
            args.left.start_line,
            args.right.start_line,
        )
        header = (
            f"== {left} {args.left.start_line}-{args.left.end_line}  vs  "
            f"{right} {args.right.start_line}-{args.right.end_line}"
        )
        footer = (
            f"{len(aligned.rows)} rows: {aligned.matching} matching, "
            f"{aligned.only_left} only left, {aligned.only_right} only right"
        )
        return ctx.result(self.name, "\n".join([header, *aligned.rows, footer]) + "\n")
