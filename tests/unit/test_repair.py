import pathlib

from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.transcript.history import load, repair
from ancalagon.transcript.transcript import Transcript


def test_transcript_persists_per_message_and_repairs_interrupted_tool_calls(
    tmp_path: pathlib.Path,
):
    path = tmp_path / "transcript.jsonl"
    log = Transcript(RealFileSystem(), path=path, agent_id=17)

    log.write(Message(role=MessageRole.USER, blocks=[Text(text="go")], agent=17, seq=0, ts="t0"))
    assert path.read_text().count("\n") == 1

    log.write(
        Message(
            role=MessageRole.ASSISTANT,
            blocks=[ToolUse(id="tu_1", name="ripgrep", arguments="{}")],
            agent=17,
            seq=1,
            ts="t1",
        )
    )
    log.close()

    loaded = load(RealFileSystem(), path)
    assert [m.seq for m in loaded] == [0, 1]
    assert loaded[0].agent == 17

    repaired = repair(loaded)
    assert len(repaired) == 3
    assert repaired[2].role is MessageRole.USER
    block = repaired[2].blocks[0]
    assert isinstance(block, ToolResultBlock)
    assert block.tool_use_id == "tu_1"
    assert block.is_error is True
    assert "interrupted" in block.content

    assert repair(repaired) == repaired
    assert repair([]) == []
