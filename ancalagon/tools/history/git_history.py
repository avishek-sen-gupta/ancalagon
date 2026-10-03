# Asks git why code looks the way it does, which no amount of reading the present tense answers.
import collections.abc
import pathlib

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.history.git_operation import GitOperation
from ancalagon.tools.history.history_args import HistoryArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError
from ancalagon.workspace.workspace import missing_hint


def _rev_fault(args: HistoryArgs) -> str:
    if args.operation is GitOperation.SHOW and not args.rev:
        return "show needs a rev"
    return ""


class GitHistory(Tool[HistoryArgs]):
    name = "git_history"
    description = (
        "Ask git why a file looks the way it does. log lists the commits that touched "
        "it, newest first; blame attributes every line to a commit; show displays one "
        "commit given rev. Commit messages often state intent that the code cannot."
    )
    cost = 1
    args_model = HistoryArgs

    def _command(self, args: HistoryArgs, path: str, repo: str) -> list[str]:
        if args.operation is GitOperation.LOG:
            return [
                "git",
                "-C",
                repo,
                "log",
                f"-n{args.limit}",
                "--date=short",
                "--pretty=format:%h %ad %an  %s",
                "--",
                path,
            ]
        if args.operation is GitOperation.BLAME:
            return ["git", "-C", repo, "blame", "--date=short", "-e", "--", path]
        return ["git", "-C", repo, "show", "--stat", "--date=short", args.rev]

    def run(self, args: HistoryArgs, ctx: ToolContext) -> ToolResult:
        if fault := _rev_fault(args):
            return ctx.failure(self.name, fault)
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        return self._at(args, path, ctx)

    def _at(self, args: HistoryArgs, path: pathlib.PurePath, ctx: ToolContext) -> ToolResult:
        if not ctx.workspace.exists(path):
            return ctx.failure(self.name, missing_hint(path))
        repo = str(path if ctx.workspace.is_dir(path) else path.parent)
        return self._asked(self._command(args, str(path), repo), ctx)

    def _asked(self, command: collections.abc.Sequence[str], ctx: ToolContext) -> ToolResult:
        code, out, err = run_command(command)
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
