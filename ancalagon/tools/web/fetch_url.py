# Fetches a page and writes its article text to the task directory.
from ancalagon.contracts.any_tool import AnyTool
from ancalagon.contracts.tool_category import ToolCategory
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.web.fetch_args import FetchArgs
from ancalagon.web.extracted import extracted
from ancalagon.web.page import Page
from ancalagon.web.unreachable import Unreachable
from ancalagon.web.web_client import WebClient


def _fetched(page: Page, tool: AnyTool, ctx: ToolContext) -> ToolResult:
    if page.status != 200:
        return ctx.failure(tool, f"{page.url} answered {page.status}")
    text = extracted(page.body)
    if not text:
        return ctx.failure(
            tool, f"extracted no text from {page.url} ({page.status}, {page.content_type})"
        )
    return ctx.result(tool, text)


class FetchUrl(Tool[FetchArgs]):
    name = "fetch_url"
    description = (
        "Fetch an https page and return its article text, with navigation and markup removed. "
        "Fails on anything it cannot take prose from, such as a PDF or a JSON endpoint."
    )
    category = ToolCategory.WEB
    cost = 1
    args_model = FetchArgs

    def __init__(self, client: WebClient):
        self.client = client

    def run(self, args: FetchArgs, ctx: ToolContext) -> ToolResult:
        try:
            page = self.client.get(args.url)
        except Unreachable as exc:
            return ctx.failure(self, str(exc))
        return _fetched(page, self, ctx)
