# An unrestricted shell command, scoped by the directory it runs in and bounded by a timeout.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.shell.execution import Execution
from ancalagon.tools.shell.run_shell import run_shell
from ancalagon.tools.shell.shell_args import ShellArgs
from ancalagon.tools.shell.timed_out import TimedOut
from ancalagon.workspace.scope_error import ScopeError

TIMEOUT_S = 120


class Shell(Tool[ShellArgs]):
    name = "shell"
    description = (
        "Run a shell command line in a directory and capture its output. "
        f"Killed after {TIMEOUT_S} seconds."
    )
    cost = 1
    args_model = ShellArgs

    def __init__(self, timeout_s: int = TIMEOUT_S):
        self.timeout_s = timeout_s

    def run(self, args: ShellArgs, ctx: ToolContext) -> ToolResult:
        try:
            cwd = ctx.workspace.resolve_read(args.cwd)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        return self._reported(run_shell(args.command, cwd, self.timeout_s), args.command, ctx)

    def _reported(
        self, executed: Execution | TimedOut, command: str, ctx: ToolContext
    ) -> ToolResult:
        if isinstance(executed, TimedOut):
            return ctx.failure(
                self.name, f"{self.name} timed out after {executed.seconds}s: {command}"
            )
        if executed.exit_code != 0:
            return ctx.failure(
                self.name, f"exit {executed.exit_code}\n{executed.stdout}{executed.stderr}"
            )
        return ctx.result(self.name, executed.stdout)
