# What a tool is given to do its work, and the writer that puts every output on disk.
import collections.abc
import itertools
import pathlib

import pydantic

from ancalagon.clock.clock import Clock
from ancalagon.contracts.access import Access
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.text_answer import TextAnswer
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.workspace.workspace import Workspace

# A role whose input contract is FreeText and whose run named no input file still has one.
NO_INPUT = FreeText(text="")


class ToolContext:
    def __init__(
        self,
        workspace: Workspace,
        task_dir: pathlib.PurePath,
        summary_chars: int,
        agent_id: int,
        input: pydantic.BaseModel = NO_INPUT,
    ):
        self.workspace = workspace
        self.task_dir = task_dir
        self.output_dir = task_dir / "tools"
        self.summary_chars = summary_chars
        self.agent_id = agent_id
        self.input = input
        self.counter = itertools.count()

    def record(self, path: pathlib.PurePath, clock: Clock) -> None:
        seen = Access(
            ts=clock.now().isoformat(),
            agent=self.agent_id,
            path=str(path),
            mtime=self.workspace.mtime(path),
        )
        self.workspace.append_line(self.task_dir / "access.jsonl", seen.model_dump_json())

    def write_output(self, tool_name: str, text: str, suffix: str) -> pathlib.PurePath:
        path = self.workspace.resolve_write(
            self.output_dir / f"{next(self.counter):04d}-{tool_name}{suffix}"
        )
        self.workspace.mkdir(path.parent, parents=True, exist_ok=True)
        self.workspace.write_text(path, text)
        return path

    def result(self, tool_name: str, text: str, suffix: str = ".txt") -> ToolResult:
        path = self.write_output(tool_name, text, suffix)
        return ToolResult(
            ok=True,
            summary=TextAnswer(text=text[: self.summary_chars]),
            path=path,
            byte_count=len(text.encode("utf-8")),
            truncated=len(text) > self.summary_chars,
        )

    def full_result(self, tool_name: str, text: str, suffix: str = ".txt") -> ToolResult:
        path = self.write_output(tool_name, text, suffix)
        return ToolResult(
            ok=True,
            summary=TextAnswer(text=text),
            path=path,
            byte_count=len(text.encode("utf-8")),
            truncated=False,
        )

    def paged(
        self,
        tool_name: str,
        lines: collections.abc.Sequence[str],
        offset: int,
        total: int,
    ) -> ToolResult:
        totals = itertools.accumulate(len(line) + 1 for line in lines)
        fitting = [
            line for line, total in zip(lines, totals, strict=True) if total <= self.summary_chars
        ]
        kept = fitting if fitting or not lines else [lines[0][: self.summary_chars]]
        last = offset + len(kept)
        body = "\n".join(kept)
        note = f"[lines {offset}-{last} of {total}" + (
            f"; call again with offset={last} for more]" if last < total else "; end of file]"
        )
        path = self.write_output(tool_name, "\n".join(lines), ".txt")
        return ToolResult(
            ok=True,
            summary=TextAnswer(text=f"{body}\n{note}"),
            path=path,
            byte_count=len("\n".join(lines).encode("utf-8")),
            truncated=last < total,
        )

    def failure(self, tool_name: str, error: str) -> ToolResult:
        path = self.write_output(tool_name, error, ".err.txt")
        return ToolResult(
            ok=False,
            summary=TextAnswer(text=error[: self.summary_chars]),
            path=path,
            error=error,
        )
