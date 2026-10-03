# Scripted replies, so the whole loop is testable without a network.
import collections.abc

from ancalagon.contracts.message import Message
from ancalagon.contracts.no_tool import NO_TOOL, NoTool
from ancalagon.contracts.reply import Reply
from ancalagon.contracts.tool_schema import ToolSchema
from ancalagon.llm.llm import LLM
from ancalagon.llm.system_prompt import SystemPrompt


class FakeLLM(LLM):
    def __init__(self, replies: collections.abc.Sequence[Reply]):
        self.replies = list(replies)
        self.systems: list[SystemPrompt] = []
        self.seen: list[list[Message]] = []
        self.forced: list[ToolSchema | NoTool] = []
        self.offered: list[list[ToolSchema]] = []

    def complete(
        self,
        system: SystemPrompt,
        messages: collections.abc.Sequence[Message],
        tools: collections.abc.Sequence[ToolSchema],
        force_tool: ToolSchema | NoTool = NO_TOOL,
    ) -> Reply:
        self.systems = [*self.systems, system]
        self.seen = [*self.seen, list(messages)]
        self.forced = [*self.forced, force_tool]
        self.offered = [*self.offered, list(tools)]
        if not self.replies:
            raise RuntimeError("FakeLLM exhausted")
        head, *rest = self.replies
        self.replies = rest
        return head
