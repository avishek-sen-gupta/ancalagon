# Asks git why code looks the way it does, which no amount of reading the present tense answers.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.history.git_operation import GitOperation
from ancalagon.tools.history.history_args import HistoryArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError
from ancalagon.workspace.workspace import missing_hint


class GitHistory(Tool):
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

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = HistoryArgs.model_validate_json(arguments)
        if args.operation is GitOperation.SHOW and not args.rev:
            return ctx.failure(self.name, "show needs a rev")
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        if not path.exists():
            return ctx.failure(self.name, missing_hint(path))
        repo = str(path if path.is_dir() else path.parent)
        code, out, err = run_command(self._command(args, str(path), repo))
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
