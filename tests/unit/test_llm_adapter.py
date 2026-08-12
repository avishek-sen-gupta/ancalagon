import importlib
import sys
import types

import pytest

from ancalagon.contracts.message import Message
from ancalagon.contracts.role import Role
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.llm.adapters.litellm_client import LiteLLMClient, to_wire
from ancalagon.llm.tool_schema import ToolSchema

WireDict = dict[str, str | list[dict[str, str | dict[str, str]]]]


def test_wire_format_preserves_tool_calls_and_passes_retry_settings(
    monkeypatch: pytest.MonkeyPatch,
):
    assistant = Message(
        role=Role.ASSISTANT,
        blocks=[Text(text="thinking"), ToolUse(id="t1", name="rg", arguments='{"p":1}')],
        agent=1,
        seq=0,
        ts="",
    )
    results = Message(
        role=Role.USER,
        blocks=[ToolResultBlock(tool_use_id="t1", content="hit")],
        agent=1,
        seq=1,
        ts="",
    )

    sent = to_wire(assistant)[0].model_dump(exclude_defaults=True)
    assert sent["content"] == "thinking"
    assert sent["tool_calls"] == [
        {"id": "t1", "type": "function", "function": {"name": "rg", "arguments": '{"p":1}'}}
    ]
    assert to_wire(results)[0].model_dump(exclude_defaults=True) == {
        "role": "tool",
        "content": "hit",
        "tool_call_id": "t1",
    }

    seen: dict[str, int] = {}
    chosen: list[str | dict[str, str | dict[str, str]]] = []

    class FakeMessage:
        content = "done"
        tool_calls: list[str] = []

    class FakeChoice:
        message = FakeMessage()
        finish_reason = "stop"

    class FakeResponse:
        choices = [FakeChoice()]

    def fake_completion(
        model: str,
        messages: list[WireDict],
        tools: list[dict[str, str]],
        max_tokens: int,
        num_retries: int,
        timeout: int,
        tool_choice: str | dict[str, str | dict[str, str]],
    ) -> FakeResponse:
        seen["num_retries"] = num_retries
        seen["timeout"] = timeout
        chosen.append(tool_choice)
        return FakeResponse()

    fake = types.ModuleType("litellm")
    setattr(fake, "completion", fake_completion)
    setattr(fake, "ModelResponse", FakeResponse)
    monkeypatch.setitem(sys.modules, "litellm", fake)

    client = LiteLLMClient(model="m", max_tokens=10, num_retries=4, request_timeout_s=99)
    reply = client.complete("sys", [assistant, results], [])

    assert seen == {"num_retries": 4, "timeout": 99}
    assert chosen == ["auto"]

    client.complete("sys", [assistant], [], force_tool="submit_answer")
    assert chosen[1] == {"type": "function", "function": {"name": "submit_answer"}}

    # litellm imports tenacity lazily, only when a retry actually fires, so a
    # missing dependency surfaces at the worst moment rather than at import.
    importlib.import_module("tenacity")
    assert reply.stop_reason == "stop"
    assert [b.text for b in reply.blocks if isinstance(b, Text)] == ["done"]


def test_the_system_prompt_is_sent_as_one_cache_marked_block(
    monkeypatch: pytest.MonkeyPatch,
):
    seen: list[list[WireDict]] = []

    class FakeMessage:
        content = "done"
        tool_calls: list[str] = []

    class FakeChoice:
        message = FakeMessage()
        finish_reason = "stop"

    class FakeResponse:
        choices = [FakeChoice()]

    def fake_completion(
        model: str,
        messages: list[WireDict],
        tools: list[dict[str, str]],
        max_tokens: int,
        num_retries: int,
        timeout: int,
        tool_choice: str | dict[str, str | dict[str, str]],
    ) -> FakeResponse:
        seen.append(messages)
        return FakeResponse()

    fake = types.ModuleType("litellm")
    setattr(fake, "completion", fake_completion)
    setattr(fake, "ModelResponse", FakeResponse)
    monkeypatch.setitem(sys.modules, "litellm", fake)

    user = Message(role=Role.USER, blocks=[Text(text="the item")], agent=1, seq=0, ts="")
    client = LiteLLMClient(model="m", max_tokens=10, num_retries=1, request_timeout_s=9)
    client.complete(
        "behave", [user], [ToolSchema(name="rg", description="d", parameters_json="{}")]
    )

    assert seen[0][0] == {
        "role": "system",
        "content": [{"type": "text", "text": "behave", "cache_control": {"type": "ephemeral"}}],
    }
    assert seen[0][1] == {"role": "user", "content": "the item"}
