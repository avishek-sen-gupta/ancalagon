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
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{next(self.counter):04d}-{tool_name}{suffix}"
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

    def failure(self, tool_name: str, error: str) -> ToolResult:
        path = self.write_output(tool_name, error, ".err.txt")
        return ToolResult(ok=False, summary=error[: self.summary_chars], path=path, error=error)
