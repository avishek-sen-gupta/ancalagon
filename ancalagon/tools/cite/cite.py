# Records one span of one file and what the agent made of it, checking the quote is really there.
import pathlib

from ancalagon.clock.clock import Clock
from ancalagon.contracts.citation import Citation
from ancalagon.contracts.source_span import SourceSpan
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.cite.cite_args import CiteArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError
from ancalagon.workspace.workspace import missing_hint

CITATIONS = "citations.jsonl"


def _fault(args: CiteArgs, path: pathlib.PurePath, ctx: ToolContext) -> str:
    if not ctx.workspace.is_file(path):
        return missing_hint(path)
    lines = ctx.workspace.read_text(path).splitlines()
    cited = "\n".join(lines[args.start_line - 1 : args.end_line])
    if args.quote in cited:
        return ""
    return (
        f"lines {args.start_line}-{args.end_line} of {path} do not contain that quote. "
        f"They say:\n{cited}"
    )


class Cite(Tool[CiteArgs]):
    name = "cite"
    description = (
        f"Record what one span of one file says, so that a later turn can use it without "
        f"reading the file again. The quote must appear in the lines you cite, and the call "
        f"fails when it does not. Every citation is appended to {CITATIONS} in your task "
        f"directory; read that file when you are ready to answer."
    )
    cost = 1
    args_model = CiteArgs

    def __init__(self, clock: Clock):
        self.clock = clock

    def run(self, args: CiteArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_read(pathlib.PurePath(args.path))
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        fault = _fault(args, path, ctx)
        if fault:
            return ctx.failure(self.name, fault)
        citation = Citation(
            ts=self.clock.now().isoformat(),
            agent=ctx.agent_id,
            span=SourceSpan.model_validate(args.model_dump()),
            quote=args.quote,
            note=args.note,
        )
        ctx.workspace.append_line(ctx.task_dir / CITATIONS, citation.model_dump_json())
        return ctx.result(self.name, f"cited {path}:{args.start_line}-{args.end_line}")
