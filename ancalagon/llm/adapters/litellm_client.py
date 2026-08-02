import collections.abc
import json

from ancalagon.contracts.block import Block
from ancalagon.contracts.message import Message
from ancalagon.contracts.reply import Reply
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.llm.tool_schema import ToolSchema


def _to_wire(message: Message) -> list[dict[str, str]]:
    results = [b for b in message.blocks if isinstance(b, ToolResultBlock)]
    if results:
        return [
            {"role": "tool", "tool_call_id": b.tool_use_id, "content": b.content} for b in results
        ]
    text = "".join(b.text for b in message.blocks if isinstance(b, Text))
    return [{"role": message.role.value, "content": text}]


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

        wire = [{"role": "system", "content": system}]
        for message in messages:
            wire.extend(_to_wire(message))
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
            model=self.model, messages=wire, tools=schemas, max_tokens=self.max_tokens
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
