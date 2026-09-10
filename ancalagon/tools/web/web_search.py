# Searches the web and writes the ranked results to the task directory.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.web.result import Result
from ancalagon.tools.web.results_in import results_in
from ancalagon.tools.web.search_args import SearchArgs
from ancalagon.web.page import Page
from ancalagon.web.unreachable import Unreachable
from ancalagon.web.web_client import WebClient

ENDPOINT = "https://lite.duckduckgo.com/lite/"


def _rendered(result: Result) -> str:
    return f"{result.rank}. {result.title}\n{result.url}\n{result.snippet}"


def _searched(page: Page, args: SearchArgs, name: str, ctx: ToolContext) -> ToolResult:
    if page.status != 200:
        return ctx.failure(name, f"{ENDPOINT} answered {page.status} for {args.query!r}")
    found = results_in(page.body, args.count)
    if not found:
        return ctx.failure(name, f"no results for {args.query!r}")
    return ctx.result(name, "\n\n".join(_rendered(r) for r in found))


class WebSearch(Tool[SearchArgs]):
    name = "web_search"
    description = (
        "Search the web. Returns ranked results, each a title, a URL and a snippet. Follow a "
        "result with fetch_url to read the page itself; the snippet alone is not evidence."
    )
    cost = 1
    args_model = SearchArgs

    def __init__(self, client: WebClient):
        self.client = client

    def run(self, args: SearchArgs, ctx: ToolContext) -> ToolResult:
        try:
            page = self.client.post_form(ENDPOINT, {"q": args.query})
        except Unreachable as exc:
            return ctx.failure(self.name, str(exc))
        return _searched(page, args, self.name, ctx)
