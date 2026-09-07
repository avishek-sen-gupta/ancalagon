# Edits a JSON file in place with jq, so a large structure is built across many small calls.
import collections.abc

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.artifacts.json_edit_args import JsonEditArgs
from ancalagon.tools.artifacts.json_op import JsonOp
from ancalagon.tools.artifacts.json_path import path_of
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError

PROGRAMS: collections.abc.Mapping[JsonOp, str] = {
    JsonOp.SET: "setpath($p; $v)",
    JsonOp.APPEND: "setpath($p; getpath($p) + [$v])",
    JsonOp.REMOVE: "delpaths([$p])",
}


class EditJson(Tool[JsonEditArgs]):
    name = "edit_json"
    description = (
        "Change one place in a JSON file inside the write root, leaving the rest alone. "
        "Use this to build a large answer across many small calls instead of writing the "
        "whole file each time. set replaces what is at the pointer, append adds to the "
        "array there, remove deletes the key. The file must already exist; write_file with "
        "{} creates it."
    )
    cost = 1
    args_model = JsonEditArgs

    def run(self, args: JsonEditArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        value = [] if args.op is JsonOp.REMOVE else ["--argjson", "v", args.value]
        code, out, err = run_command(
            [
                "jq",
                "--argjson",
                "p",
                path_of(args.pointer).model_dump_json(),
                *value,
                PROGRAMS[args.op],
                str(path),
            ]
        )
        if code != 0:
            return ctx.failure(self.name, err)
        ctx.workspace.write_text(path, out)
        return ctx.result(self.name, f"{args.op} at {args.pointer or '/'} in {path}")
