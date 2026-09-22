import pathlib

import pytest

from ancalagon.clock.fake_clock import FakeClock
from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.fork import forked, orphaned
from ancalagon.fork_command import fork_run
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.transcript.history import INTERRUPTED

DELEGATES = frozenset({"delegate_engine"})

TEMPLATE = """
[workspace]
home = "./ws"
write_roots = []
read_roots = ["./artifacts"]

[model]
name = "some-provider/some-model"
num_retries = 2
request_timeout_s = 120
max_tokens = 4000
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "none"

[roles.engine]
behaviour = "You write the engine."
tools = ["read_file", "submit_answer"]
budget = { turns = 10, tool_calls = 20 }

[roles.root]
behaviour = "You delegate."
tools = ["delegate_engine", "submit_answer"]
budget = { turns = 10, tool_calls = 20 }

[run]
goal_file = "./goal.md"
input_file = ""
role = "root"
"""


def _said(seq: int, text: str) -> Message:
    return Message(
        role=MessageRole.ASSISTANT, blocks=[Text(text=text)], agent=1, seq=seq, ts=f"t{seq}"
    )


def _asked(seq: int, text: str) -> Message:
    return Message(role=MessageRole.USER, blocks=[Text(text=text)], agent=1, seq=seq, ts=f"t{seq}")


def _delegated(seq: int, task_id: str) -> Message:
    return Message(
        role=MessageRole.ASSISTANT,
        blocks=[
            ToolUse(
                id=f"tu_{seq}",
                name="delegate_engine",
                arguments=f'{{"task_id": "{task_id}", "goal": "g", "input": {{"text": "i"}}}}',
            )
        ],
        agent=1,
        seq=seq,
        ts=f"t{seq}",
    )


def _returned(seq: int, tool_use_id: str) -> Message:
    return Message(
        role=MessageRole.USER,
        blocks=[ToolResultBlock(tool_use_id=tool_use_id, content="queued", is_error=False)],
        agent=1,
        seq=seq,
        ts=f"t{seq}",
    )


def test_a_fork_of_a_history_without_delegates_is_the_history_up_to_the_cut():
    messages = [_asked(0, "go"), _said(1, "reading"), _asked(2, "result"), _said(3, "more")]

    cut = forked(messages, 2, DELEGATES, FakeClock())

    assert cut == messages[:2]
    assert orphaned(cut, DELEGATES) == ()
    assert forked(messages, 4, DELEGATES, FakeClock()) == messages


def test_a_cut_outside_the_history_is_refused():
    messages = [_asked(0, "go"), _said(1, "reading")]

    with pytest.raises(ValueError, match="--at 0"):
        forked(messages, 0, DELEGATES, FakeClock())
    with pytest.raises(ValueError, match="--at 9"):
        forked(messages, 9, DELEGATES, FakeClock())


def test_a_fork_past_a_delegate_answers_its_pending_call_and_names_the_orphaned_task():
    messages = [_asked(0, "go"), _delegated(1, "engine_fix_v2"), _returned(2, "tu_1")]

    cut = forked(messages, 2, DELEGATES, FakeClock())

    assert orphaned(cut, DELEGATES) == ("engine_fix_v2",)
    assert [m.seq for m in cut] == [0, 1, 2, 3, 4]
    interrupted = cut[2].blocks[0]
    assert isinstance(interrupted, ToolResultBlock)
    assert interrupted.tool_use_id == "tu_1"
    assert interrupted.content == INTERRUPTED
    assert cut[3].role is MessageRole.ASSISTANT
    notice = cut[4]
    assert notice.role is MessageRole.USER
    said = notice.blocks[0]
    assert isinstance(said, Text)
    assert "engine_fix_v2" in said.text
    assert notice.ts == FakeClock().now().isoformat()
    assert notice.agent == 1


def test_forking_writes_a_new_run_dir_holding_the_cut_transcript(tmp_path: pathlib.Path):
    fs = RealFileSystem()
    config_path = pathlib.PurePath(tmp_path / "anc.toml")
    fs.write_text(config_path, TEMPLATE)
    fs.write_text(pathlib.PurePath(tmp_path / "goal.md"), "build it")
    source = pathlib.PurePath(tmp_path / "ws" / "runs" / "r_source")
    history = [_asked(0, "go"), _delegated(1, "engine_fix_v2"), _returned(2, "tu_1")]
    fs.mkdir(source / "tasks" / "root", parents=True, exist_ok=True)
    fs.write_text(
        source / "tasks" / "root" / "transcript.jsonl",
        "".join(m.model_dump_json() + "\n" for m in history),
    )

    forked_dir, orphans = fork_run(config_path, source, 2, FakeClock(), fs)

    assert forked_dir.parent == pathlib.PurePath(tmp_path / "ws" / "runs")
    assert forked_dir != source
    assert orphans == ("engine_fix_v2",)
    written = [
        Message.model_validate_json(line)
        for line in fs.read_text(forked_dir / "tasks" / "root" / "transcript.jsonl").splitlines()
    ]
    assert written == list(forked(history, 2, DELEGATES, FakeClock()))
