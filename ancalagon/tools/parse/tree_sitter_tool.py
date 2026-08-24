# Parses a source file to a flat list of AST nodes as JSON.
import pydantic
import tree_sitter

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.parse.ast_node import AstNode
from ancalagon.tools.parse.languages import GRAMMARS, language_of
from ancalagon.tools.parse.parse_args import ParseArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


def _node_of(node: tree_sitter.Node) -> AstNode:
    return AstNode(
        type=node.type,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        children=[c.type for c in node.children],
    )


def _walk(node: tree_sitter.Node) -> list[AstNode]:
    return [_node_of(node)] + [n for child in node.children for n in _walk(child)]


class TreeSitter(Tool[ParseArgs]):
    name = "treesitter"
    description = "Parse a source file and emit its AST nodes as JSON."
    cost = 1
    args_model = ParseArgs

    def run(self, args: ParseArgs, ctx: ToolContext) -> ToolResult:
        if args.language not in GRAMMARS:
            return ctx.failure(self.name, f"unsupported language {args.language}")
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        language = language_of(args.language)
        parser = tree_sitter.Parser(language)
        tree = parser.parse(ctx.workspace.read_bytes(path))
        nodes = pydantic.TypeAdapter(list[AstNode]).dump_json(_walk(tree.root_node), indent=2)
        return ctx.result(self.name, nodes.decode(), ".json")
