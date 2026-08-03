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
from ancalagon.llm.adapters.wire_tool_call import WireToolCall
from ancalagon.llm.tool_schema import ToolSchema


def _to_wire(message: Message) -> list[WireMessage]:
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
    return [WireMessage(role=message.role.value, content=text, tool_calls=calls)]


def _to_arguments(raw: str | collections.abc.Mapping[str, str]) -> str:
    return raw if isinstance(raw, str) else json.dumps(dict(raw))


class LiteLLMClient:
    def __init__(self, model: str, max_tokens: int):
        self.model = model
        self.max_tokens = max_tokens

    def complete(
        self,
        system: str,
        messages: collections.abc.Sequence[Message],
        tools: collections.abc.Sequence[ToolSchema],
    ) -> Reply:
        import litellm

        wire = [WireMessage(role="system", content=system)]
        for message in messages:
            wire.extend(_to_wire(message))
        payload = [m.model_dump(exclude_defaults=True) for m in wire]
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
        response = litellm.completion(
            model=self.model, messages=payload, tools=schemas, max_tokens=self.max_tokens
        )
        if not isinstance(response, litellm.ModelResponse):
            raise TypeError("litellm.completion returned a streaming response")
        choice = response.choices[0]
        blocks: list[Block] = []
        if choice.message.content:
            blocks.append(Text(text=choice.message.content))
        for call in choice.message.tool_calls or []:
            blocks.append(
                ToolUse.model_validate(
                    {
                        "id": call.id,
                        "name": call.function.name,
                        "arguments": _to_arguments(call.function.arguments),
                    }
                )
            )
        return Reply(blocks=blocks, stop_reason=choice.finish_reason)
