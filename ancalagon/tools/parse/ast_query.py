# Runs a tree-sitter query over a tree and reports every capture of every match.
import collections.abc
import pathlib

import pydantic
import tree_sitter

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.parse.ast_query_args import AstQueryArgs
from ancalagon.tools.parse.capture import Capture
from ancalagon.tools.parse.languages import GRAMMARS, language_of
from ancalagon.tools.parse.query_match import QueryMatch
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.searchable_files import searchable_files
from ancalagon.workspace.scope_error import ScopeError

MATCHES = pydantic.TypeAdapter(list[QueryMatch])


def _capture_of(node: tree_sitter.Node) -> Capture:
    return Capture(
        type=node.type,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        start_point=(node.start_point.row, node.start_point.column),
        end_point=(node.end_point.row, node.end_point.column),
        text=bytes(node.text or b"").decode("utf-8", errors="replace"),
    )


def _in_file(
    parser: tree_sitter.Parser, query: tree_sitter.Query, path: str, ctx: ToolContext
) -> list[QueryMatch]:
    tree = parser.parse(ctx.workspace.read_bytes(pathlib.PurePath(path)))
    return [
        QueryMatch(
            file=path,
            pattern=pattern,
            captures={name: [_capture_of(n) for n in nodes] for name, nodes in bound.items()},
        )
        for pattern, bound in tree_sitter.QueryCursor(query).matches(tree.root_node)
    ]


class AstQuery(Tool[AstQueryArgs]):
    name = "ast_query"
    description = (
        "Run a tree-sitter query over source files and return every match, with each named "
        "capture's node type, byte range, row and column, and its text. Use this rather than "
        "ast_grep when the parts of a match need naming, or their exact locations are wanted."
    )
    cost = 1
    args_model = AstQueryArgs

    def run(self, args: AstQueryArgs, ctx: ToolContext) -> ToolResult:
        if args.language not in GRAMMARS:
            return ctx.failure(self.name, f"unsupported language {args.language}")
        try:
            roots = [str(ctx.workspace.resolve_read(r)) for r in args.roots]
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        return self._over(roots, args, ctx)

    def _over(
        self, roots: collections.abc.Sequence[str], args: AstQueryArgs, ctx: ToolContext
    ) -> ToolResult:
        listed, files, err = searchable_files(roots, args.globs)
        if listed not in (0, 1):
            return ctx.failure(self.name, err)
        if not files:
            return ctx.result(self.name, "[]", ".json")
        return self._matched(files, args, ctx)

    def _matched(
        self, files: collections.abc.Sequence[str], args: AstQueryArgs, ctx: ToolContext
    ) -> ToolResult:
        language = language_of(args.language)
        try:
            query = tree_sitter.Query(language, args.query)
        except tree_sitter.QueryError as exc:
            return ctx.failure(self.name, str(exc))
        parser = tree_sitter.Parser(language)
        found = [match for path in files for match in _in_file(parser, query, path, ctx)]
        return ctx.result(self.name, MATCHES.dump_json(found, indent=2).decode(), ".json")
