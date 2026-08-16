import json
import pathlib

from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.transcript.demote import for_wire


def _body(message: Message) -> str:
    block = message.blocks[0]
    assert isinstance(block, ToolResultBlock)
    return block.content


def _result(seq: int, size: int, is_error: bool = False, path: str = "/w/tools/0.txt") -> Message:
    return Message(
        role=MessageRole.USER,
        blocks=[
            ToolResultBlock(
                tool_use_id=f"tu_{seq}",
                content="x" * size,
                is_error=is_error,
                path=path,
                byte_count=size,
            )
        ],
        agent=1,
        seq=seq,
        ts="t",
    )


def test_demotion_shrinks_old_results_without_touching_structure_or_recent_turns():
    history = [
        Message(role=MessageRole.USER, blocks=[Text(text="go")], agent=1, seq=0, ts="t"),
        Message(
            role=MessageRole.ASSISTANT,
            blocks=[ToolUse(id="tu_1", name="read_file", arguments="{}")],
            agent=1,
            seq=1,
            ts="t",
        ),
        _result(2, 4000),
        _result(3, 4000, is_error=True),
        _result(4, 50),
        _result(5, 4000, path=""),
        _result(6, 4000),
    ]
    original = [m.model_dump_json() for m in history]

    assert for_wire(history, above_tokens=0, keep_recent=2) is history
    assert for_wire(history, above_tokens=10**9, keep_recent=2) is history

    wire = for_wire(history, above_tokens=1, keep_recent=2)

    assert len(wire) == len(history)
    assert [m.role for m in wire] == [m.role for m in history]
    assert [b.kind for m in wire for b in m.blocks] == [b.kind for m in history for b in m.blocks]
    assert [b.tool_use_id for m in wire for b in m.blocks if isinstance(b, ToolResultBlock)] == [
        "tu_2",
        "tu_3",
        "tu_4",
        "tu_5",
        "tu_6",
    ]

    assert _body(wire[2]) == "[4000 bytes at /w/tools/0.txt — read_file it if you need it]"
    assert _body(wire[3]) == "x" * 4000
    assert _body(wire[4]) == "x" * 50
    assert _body(wire[5]) == "x" * 4000
    assert _body(wire[6]) == "x" * 4000

    assert [m.model_dump_json() for m in history] == original


def test_a_demoted_result_still_names_a_file_that_exists(tmp_path: pathlib.Path):
    output = tmp_path / "0000-read_file.txt"
    output.write_text("y" * 4000)
    wire = for_wire([_result(0, 4000, path=str(output))], above_tokens=1, keep_recent=0)

    pointer = _body(wire[0])
    named = pointer.split(" at ", 1)[1].split(" — ", 1)[0]
    assert pathlib.Path(named).read_text() == "y" * 4000

    restored = json.loads(wire[0].model_dump_json())
    assert restored["blocks"][0]["path"] == str(output)
