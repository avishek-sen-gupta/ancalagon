# Translates between our contracts and litellm's OpenAI-shaped wire format.
import collections.abc
import json

from ancalagon.contracts.block import Block
from ancalagon.contracts.message import Message
from ancalagon.contracts.reply import Reply
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.llm.adapters.wire_function import WireFunction
from ancalagon.llm.adapters.wire_message import WireMessage
from ancalagon.llm.adapters.wire_text_block import WireTextBlock
from ancalagon.llm.adapters.wire_tool_call import WireToolCall
from ancalagon.llm.adapters.wire_usage import WireUsage
from ancalagon.llm.system_prompt import SystemPrompt
from ancalagon.llm.tool_schema import ToolSchema


def _system_blocks(system: SystemPrompt) -> tuple[WireTextBlock, ...]:
    static = WireTextBlock(type="text", text=system.static, cache_control={"type": "ephemeral"})
    if not system.per_item:
        return (static,)
    return (static, WireTextBlock(type="text", text=system.per_item))


def to_wire(message: Message) -> list[WireMessage]:
    results = [b for b in message.blocks if isinstance(b, ToolResultBlock)]
    if results:
        return [
            WireMessage(role="tool", tool_call_id=b.tool_use_id, content=b.content) for b in results
        ]
    text = "".join(b.text for b in message.blocks if isinstance(b, Text))
    calls = [
        WireToolCall(
            id=b.id,
            type="function",
            function=WireFunction(name=b.name, arguments=b.arguments),
        )
        for b in message.blocks
        if isinstance(b, ToolUse)
    ]
    if not text and not calls:
        return []
    return [WireMessage(role=message.role.value, content=text, tool_calls=calls)]


def _to_arguments(raw: str | collections.abc.Mapping[str, str]) -> str:
    return raw if isinstance(raw, str) else json.dumps(dict(raw))


class LiteLLMClient:
    def __init__(self, model: str, max_tokens: int, num_retries: int, request_timeout_s: int):
        self.model = model
        self.max_tokens = max_tokens
        self.num_retries = num_retries
        self.request_timeout_s = request_timeout_s

    def complete(
        self,
        system: SystemPrompt,
        messages: collections.abc.Sequence[Message],
        tools: collections.abc.Sequence[ToolSchema],
        force_tool: str = "",
    ) -> Reply:
        import litellm

        wire = [WireMessage(role="system", content=_system_blocks(system))]
        for message in messages:
            wire.extend(to_wire(message))
        payload = [m.model_dump(mode="json", exclude_defaults=True) for m in wire]
        schemas = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": json.loads(t.parameters_json),
                },
            }
            for t in tools
        ]
        wanted: str | dict[str, str | dict[str, str]] = (
            {"type": "function", "function": {"name": force_tool}} if force_tool else "auto"
        )
        response = litellm.completion(
            model=self.model,
            messages=payload,
            tools=schemas,
            max_tokens=self.max_tokens,
            num_retries=self.num_retries,
            timeout=self.request_timeout_s,
            tool_choice=wanted,
        )
        if not isinstance(response, litellm.ModelResponse):
            raise TypeError("litellm.completion returned a streaming response")
        first = response.choices[0]
        blocks: list[Block] = []
        if first.message.content:
            blocks.append(Text(text=first.message.content))
        for call in first.message.tool_calls or []:
            blocks.append(
                ToolUse.model_validate(
                    {
                        "id": call.id,
                        "name": call.function.name,
                        "arguments": _to_arguments(call.function.arguments),
                    }
                )
            )
        usage = WireUsage.model_validate(getattr(response, "usage", WireUsage()))
        return Reply(
            blocks=blocks,
            stop_reason=first.finish_reason,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
        )
