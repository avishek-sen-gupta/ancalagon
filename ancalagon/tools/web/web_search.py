# Searches the web and writes the ranked results to the task directory.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.web.result import Result
from ancalagon.tools.web.results_in import results_in
from ancalagon.tools.web.search_args import SearchArgs
from ancalagon.web.web_client import WebClient

ENDPOINT = "https://lite.duckduckgo.com/lite/"


def _rendered(result: Result) -> str:
    return f"{result.rank}. {result.title}\n{result.url}\n{result.snippet}"


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
        page = self.client.post_form(ENDPOINT, {"q": args.query})
        if page.status != 200:
            return ctx.failure(self.name, f"{ENDPOINT} answered {page.status} for {args.query!r}")
        found = results_in(page.body, args.count)
        if not found:
            return ctx.failure(self.name, f"no results for {args.query!r}")
        return ctx.result(self.name, "\n\n".join(_rendered(r) for r in found))
