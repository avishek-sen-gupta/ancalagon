# Loads a transcript, giving interrupted tool calls synthetic results so the API accepts it.
import collections.abc
import pathlib

from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.fs.file_system import FileSystem

INTERRUPTED = "interrupted: agent terminated before this tool returned"


def load(fs: FileSystem, path: pathlib.PurePath) -> list[Message]:
    lines = [line for line in fs.read_text(path).splitlines() if line.strip()]
    return [Message.model_validate_json(line) for line in lines]


def repair(messages: collections.abc.Sequence[Message]) -> collections.abc.Sequence[Message]:
    if not messages:
        return messages
    last = messages[-1]
    if last.role is not MessageRole.ASSISTANT:
        return messages
    pending = [b for b in last.blocks if isinstance(b, ToolUse)]
    if not pending:
        return messages
    synthetic = Message(
        role=MessageRole.USER,
        blocks=[
            ToolResultBlock(tool_use_id=b.id, content=INTERRUPTED, is_error=True) for b in pending
        ],
        agent=last.agent,
        seq=last.seq + 1,
        ts=last.ts,
    )
    return [*messages, synthetic]
