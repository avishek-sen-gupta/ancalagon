# Loads a transcript, giving interrupted tool calls synthetic results so the API accepts it.
import collections.abc
import pathlib

from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use_from_model import ToolUseFromModel
from ancalagon.fs.file_system import FileSystem

INTERRUPTED = "interrupted: agent terminated before this tool returned"


def load(fs: FileSystem, path: pathlib.PurePath) -> list[Message]:
    lines = [line for line in fs.read_text(path).splitlines() if line.strip()]
    return [Message.model_validate_json(line) for line in lines]


def _unanswered(last: Message) -> list[ToolUseFromModel]:
    if last.role is not MessageRole.ASSISTANT:
        return []
    return [b for b in last.blocks if isinstance(b, ToolUseFromModel)]


def _synthetic(last: Message, pending: collections.abc.Sequence[ToolUseFromModel]) -> Message:
    return Message(
        role=MessageRole.USER,
        blocks=[
            ToolResultBlock(tool_use_id=b.id, content=INTERRUPTED, is_error=True) for b in pending
        ],
        agent=last.agent,
        seq=last.seq + 1,
        ts=last.ts,
    )


def repair(messages: collections.abc.Sequence[Message]) -> collections.abc.Sequence[Message]:
    if not messages:
        return messages
    pending = _unanswered(messages[-1])
    if not pending:
        return messages
    return [*messages, _synthetic(messages[-1], pending)]
