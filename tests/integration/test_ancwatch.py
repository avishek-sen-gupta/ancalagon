# The watcher's rendering is one jq program, run here against real transcript messages.
import pathlib
import subprocess

from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse

FILTER = pathlib.Path(__file__).parents[2] / "scripts" / "ancwatch.jq"
CYAN = "\x1b[36m"
YELLOW = "\x1b[1;33m"
RED = "\x1b[31m"
PLAIN = "\x1b[0m"


def render(message: Message, width: int) -> str:
    rendered = subprocess.run(
        [
            "jq",
            "-rj",
            "--arg",
            "n",
            "r_1/root",
            "--argjson",
            "width",
            str(width),
            "-f",
            str(FILTER),
        ],
        input=message.model_dump_json(),
        capture_output=True,
        text=True,
        check=True,
    )
    return rendered.stdout


def test_a_watched_line_cuts_prose_to_the_width_and_keeps_tool_arguments_whole():
    arguments = '{"path": "/a/long/enough/path/to/be/cut/BP13K800.txt", "offset": 774, "limit": 5}'
    spoken = Message(
        role=MessageRole.ASSISTANT,
        agent=3,
        seq=1,
        ts="2026-09-07T09:07:09",
        blocks=[
            Text(text="reading the copybook\nto find the field"),
            ToolUse(id="t1", name="read_file", arguments=arguments),
        ],
    )
    assert render(spoken, 26) == (
        f"{CYAN}[r_1/root/3]{PLAIN} A reading the copybook to fi"
        f" | → {YELLOW}read_file{PLAIN} {arguments}\n"
    )

    refused = Message(
        role=MessageRole.USER,
        agent=3,
        seq=2,
        ts="2026-09-07T09:07:10",
        blocks=[
            ToolResultBlock(
                tool_use_id="t1",
                content="these citations do not resolve: lines 2-9 but the file has 3",
                is_error=True,
            )
        ],
    )
    assert render(refused, 20) == (
        f"{CYAN}[r_1/root/3]{PLAIN} U ← {RED}ERR{PLAIN} these citations do n\n"
    )
