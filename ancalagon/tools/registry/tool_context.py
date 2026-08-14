# What a tool is given to do its work, and the writer that puts every output on disk.
import itertools
import pathlib

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.workspace.workspace import Workspace


class ToolContext:
    def __init__(
        self,
        workspace: Workspace,
        output_dir: pathlib.Path,
        summary_chars: int,
        agent_id: int,
    ):
        self.workspace = workspace
        self.output_dir = output_dir
        self.summary_chars = summary_chars
        self.agent_id = agent_id
        self.counter = itertools.count()

    def write_output(self, tool_name: str, text: str, suffix: str) -> pathlib.Path:
        path = self.workspace.resolve_write(
            self.output_dir / f"{next(self.counter):04d}-{tool_name}{suffix}"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def result(self, tool_name: str, text: str, suffix: str = ".txt") -> ToolResult:
        path = self.write_output(tool_name, text, suffix)
        return ToolResult(
            ok=True,
            summary=text[: self.summary_chars],
            path=path,
            byte_count=len(text.encode("utf-8")),
            truncated=len(text) > self.summary_chars,
        )

    def paged(self, tool_name: str, lines: list[str], offset: int, total: int) -> ToolResult:
        kept: list[str] = []
        used = 0
        for line in lines:
            if used + len(line) + 1 > self.summary_chars:
                if not kept:
                    kept.append(line[: self.summary_chars])
                break
            kept.append(line)
            used += len(line) + 1
        last = offset + len(kept)
        body = "\n".join(kept)
        note = f"[lines {offset}-{last} of {total}" + (
            f"; call again with offset={last} for more]" if last < total else "; end of file]"
        )
        path = self.write_output(tool_name, "\n".join(lines), ".txt")
        return ToolResult(
            ok=True,
            summary=f"{body}\n{note}",
            path=path,
            byte_count=len("\n".join(lines).encode("utf-8")),
            truncated=last < total,
        )

    def failure(self, tool_name: str, error: str) -> ToolResult:
        path = self.write_output(tool_name, error, ".err.txt")
        return ToolResult(ok=False, summary=error[: self.summary_chars], path=path, error=error)
