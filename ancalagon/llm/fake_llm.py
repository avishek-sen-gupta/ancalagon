# Scripted replies, so the whole loop is testable without a network.
import collections.abc

from ancalagon.contracts.message import Message
from ancalagon.contracts.reply import Reply
from ancalagon.llm.tool_schema import ToolSchema


class FakeLLM:
    def __init__(self, replies: list[Reply]):
        self.replies = list(replies)
        self.seen: list[list[Message]] = []

    def complete(
        self,
        system: str,
        messages: collections.abc.Sequence[Message],
        tools: collections.abc.Sequence[ToolSchema],
    ) -> Reply:
        self.seen.append(list(messages))
        if not self.replies:
            raise RuntimeError("FakeLLM exhausted")
        return self.replies.pop(0)
