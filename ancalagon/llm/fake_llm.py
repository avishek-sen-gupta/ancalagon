# Scripted replies, so the whole loop is testable without a network.
import collections.abc

from ancalagon.contracts.message import Message
from ancalagon.contracts.reply import Reply
from ancalagon.llm.llm import LLM
from ancalagon.llm.system_prompt import SystemPrompt
from ancalagon.llm.tool_schema import ToolSchema


class FakeLLM(LLM):
    def __init__(self, replies: collections.abc.Sequence[Reply]):
        self.replies = list(replies)
        self.systems: list[SystemPrompt] = []
        self.seen: list[list[Message]] = []
        self.forced: list[str] = []

    def complete(
        self,
        system: SystemPrompt,
        messages: collections.abc.Sequence[Message],
        tools: collections.abc.Sequence[ToolSchema],
        force_tool: str = "",
    ) -> Reply:
        self.systems.append(system)
        self.seen.append(list(messages))
        self.forced.append(force_tool)
        if not self.replies:
            raise RuntimeError("FakeLLM exhausted")
        return self.replies.pop(0)
