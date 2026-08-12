# The single seam between the agent loop and any model provider.
import collections.abc
import typing

from ancalagon.contracts.message import Message
from ancalagon.contracts.reply import Reply
from ancalagon.llm.system_prompt import SystemPrompt
from ancalagon.llm.tool_schema import ToolSchema


class LLM(typing.Protocol):
    def complete(
        self,
        system: SystemPrompt,
        messages: collections.abc.Sequence[Message],
        tools: collections.abc.Sequence[ToolSchema],
        force_tool: str = "",
    ) -> Reply: ...
