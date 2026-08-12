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
from ancalagon.llm.system_prompt import SystemPrompt
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
    reply = client.complete(SystemPrompt(static="sys"), [assistant, results], [])

    assert seen == {"num_retries": 4, "timeout": 99}
    assert chosen == ["auto"]

    client.complete(SystemPrompt(static="sys"), [assistant], [], force_tool="submit_answer")
    assert chosen[1] == {"type": "function", "function": {"name": "submit_answer"}}

    # litellm imports tenacity lazily, only when a retry actually fires, so a
    # missing dependency surfaces at the worst moment rather than at import.
    importlib.import_module("tenacity")
    assert reply.stop_reason == "stop"
    assert [b.text for b in reply.blocks if isinstance(b, Text)] == ["done"]
    assert (reply.cache_creation_input_tokens, reply.cache_read_input_tokens) == (0, 0)


def test_a_message_with_nothing_to_say_never_reaches_the_wire():
    blank = Message(role=Role.ASSISTANT, blocks=[], agent=1, seq=0, ts="")
    calls_only = Message(
        role=Role.ASSISTANT,
        blocks=[ToolUse(id="t1", name="rg", arguments="{}")],
        agent=1,
        seq=1,
        ts="",
    )

    assert to_wire(blank) == []
    assert to_wire(calls_only)[0].model_dump(exclude_defaults=True) == {
        "role": "assistant",
        "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "rg", "arguments": "{}"}}
        ],
    }


def test_only_the_static_system_half_is_cache_marked_and_usage_counters_reach_the_reply(
    monkeypatch: pytest.MonkeyPatch,
):
    seen: list[list[WireDict]] = []
    offered: list[list[dict[str, str]]] = []

    class FakeMessage:
        content = "done"
        tool_calls: list[str] = []

    class FakeChoice:
        message = FakeMessage()
        finish_reason = "stop"

    class FakeUsage:
        cache_creation_input_tokens = 2048
        cache_read_input_tokens = 1024

    class FakeResponse:
        choices = [FakeChoice()]
        usage = FakeUsage()

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
        offered.append(tools)
        return FakeResponse()

    fake = types.ModuleType("litellm")
    setattr(fake, "completion", fake_completion)
    setattr(fake, "ModelResponse", FakeResponse)
    monkeypatch.setitem(sys.modules, "litellm", fake)

    user = Message(role=Role.USER, blocks=[Text(text="the item")], agent=1, seq=0, ts="")
    client = LiteLLMClient(model="m", max_tokens=10, num_retries=1, request_timeout_s=9)
    reply = client.complete(
        SystemPrompt(static="behave", per_item="Goal: this one"),
        [user],
        [ToolSchema(name="rg", description="d", parameters_json='{"type": "object"}')],
    )

    assert seen[0][0] == {
        "role": "system",
        "content": [
            {"type": "text", "text": "behave", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Goal: this one"},
        ],
    }
    assert seen[0][1] == {"role": "user", "content": "the item"}
    assert offered[0] == [
        {
            "type": "function",
            "function": {"name": "rg", "description": "d", "parameters": {"type": "object"}},
        }
    ]
    assert (reply.cache_creation_input_tokens, reply.cache_read_input_tokens) == (2048, 1024)

    client.complete(SystemPrompt(static="behave"), [user], [])
    assert seen[1][0] == {
        "role": "system",
        "content": [{"type": "text", "text": "behave", "cache_control": {"type": "ephemeral"}}],
    }
