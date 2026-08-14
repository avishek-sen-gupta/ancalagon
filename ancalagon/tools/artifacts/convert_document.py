# Converts a document into a readable or structured form with pandoc.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.artifacts.convert_args import ConvertArgs
from ancalagon.tools.artifacts.document_format import DocumentFormat
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError

SUFFIX = {
    DocumentFormat.MARKDOWN: ".md",
    DocumentFormat.PLAIN: ".txt",
    DocumentFormat.JSON: ".json",
    DocumentFormat.HTML: ".html",
}


class ConvertDocument(Tool[ConvertArgs]):
    name = "convert_document"
    description = (
        "Convert a document -- docx, odt, epub, rtf, latex, html and others -- into "
        "markdown, plain text, html, or pandoc's JSON abstract syntax tree. Use json "
        "when you need the document's structure rather than its prose."
    )
    cost = 1
    args_model = ConvertArgs

    def run(self, args: ConvertArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = run_command(["pandoc", "-t", args.to.value, str(path)])
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out, SUFFIX[args.to])
