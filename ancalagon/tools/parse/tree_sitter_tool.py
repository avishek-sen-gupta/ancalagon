# Parses a source file to a flat list of AST nodes as JSON.
import pydantic
import tree_sitter
import tree_sitter_python

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.parse.ast_node import AstNode
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.parse.parse_args import ParseArgs
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError

LANGUAGES = {"python": tree_sitter_python.language}


def _node_of(node: tree_sitter.Node) -> AstNode:
    return AstNode(
        type=node.type,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        children=[c.type for c in node.children],
    )


def _walk(node: tree_sitter.Node) -> list[AstNode]:
    return [_node_of(node)] + [n for child in node.children for n in _walk(child)]


class TreeSitter:
    name = "treesitter"
    description = "Parse a source file and emit its AST nodes as JSON."
    cost = 1

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, ParseArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = ParseArgs.model_validate_json(arguments)
        if args.language not in LANGUAGES:
            return ctx.failure(self.name, f"unsupported language {args.language}")
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        language = tree_sitter.Language(LANGUAGES[args.language]())
        parser = tree_sitter.Parser(language)
        tree = parser.parse(path.read_bytes())
        nodes = pydantic.TypeAdapter(list[AstNode]).dump_json(_walk(tree.root_node), indent=2)
        return ctx.result(self.name, nodes.decode(), ".json")
