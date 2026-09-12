from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.watching.rendered import rendered

CYAN = "[36m"
YELLOW = "[1;33m"
RED = "[31m"
OFF = "[0m"


def _message(role: MessageRole, blocks: list[Text | ToolUse | ToolResultBlock], agent: int = 3):
    return Message(role=role, blocks=blocks, agent=agent, seq=7, ts="2026-09-12T10:00:00Z")


def test_a_message_renders_a_header_and_one_line_per_block():
    message = _message(
        MessageRole.ASSISTANT,
        [
            Text(text="looking now"),
            ToolUse(id="tu_0", name="read_file", arguments='{"path": "/w/a.md"}'),
            ToolResultBlock(tool_use_id="tu_0", content="payload", is_error=False),
            ToolResultBlock(tool_use_id="tu_1", content="outside the read roots", is_error=True),
        ],
    )

    lines = rendered("r_1/root", message, 40).splitlines()

    assert lines[0] == f"{CYAN}[r_1/root/3]{OFF} A"
    assert lines[1] == "  looking now"
    assert lines[2] == f'  → {YELLOW}read_file{OFF} {{"path": "/w/a.md"}}'
    assert lines[3] == "  ← payload"
    assert lines[4] == f"  ← {RED}ERR{OFF} outside the read roots"
    assert len(lines) == 5


def test_a_message_indents_wrapped_text_and_truncates_every_block():
    message = _message(
        MessageRole.USER,
        [
            Text(text="first\nsecond"),
            Text(text="x" * 500),
            ToolUse(id="t", name="shell", arguments="y\ny" + "y" * 500),
            ToolResultBlock(tool_use_id="t", content="z\nz" + "z" * 500),
        ],
        agent=1,
    )

    lines = rendered("r_1/root", message, 10).splitlines()

    assert lines[0] == f"{CYAN}[r_1/root/1]{OFF} U"
    assert lines[1] == "  first"
    assert lines[2] == "  second"
    assert lines[3] == "  " + "x" * 40
    assert lines[4] == f"  → {YELLOW}shell{OFF} y y" + "y" * 7
    assert lines[5] == "  ← z z" + "z" * 7
