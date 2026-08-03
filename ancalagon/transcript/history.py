# Loads a transcript, giving interrupted tool calls synthetic results so the API accepts it.
import pathlib

from ancalagon.contracts.message import Message
from ancalagon.contracts.role import Role
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse

INTERRUPTED = "interrupted: agent terminated before this tool returned"


def load(path: pathlib.Path) -> list[Message]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [Message.model_validate_json(line) for line in lines]


def repair(messages: list[Message]) -> list[Message]:
    if not messages:
        return messages
    last = messages[-1]
    if last.role is not Role.ASSISTANT:
        return messages
    pending = [b for b in last.blocks if isinstance(b, ToolUse)]
    if not pending:
        return messages
    synthetic = Message(
        role=Role.USER,
        blocks=[
            ToolResultBlock(tool_use_id=b.id, content=INTERRUPTED, is_error=True) for b in pending
        ],
        agent=last.agent,
        seq=last.seq + 1,
        ts=last.ts,
    )
    return [*messages, synthetic]
