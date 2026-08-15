# Replaces an old tool result's body with a pointer to the file it was already written to.
import collections.abc
from ancalagon.contracts.block import Block
from ancalagon.contracts.message import Message
from ancalagon.contracts.tool_result_block import ToolResultBlock

# Below this a pointer would cost more than the content it replaces.
WORTH_DEMOTING = 200


def _demote_block(block: Block) -> Block:
    if not isinstance(block, ToolResultBlock):
        return block
    if block.is_error or not block.path or len(block.content) <= WORTH_DEMOTING:
        return block
    return block.model_copy(
        update={
            "content": (f"[{block.byte_count} bytes at {block.path} — read_file it if you need it]")
        }
    )


def demoted(message: Message) -> Message:
    blocks = [_demote_block(b) for b in message.blocks]
    if blocks == list(message.blocks):
        return message
    return message.model_copy(update={"blocks": blocks})


def for_wire(
    messages: collections.abc.Sequence[Message], above_tokens: int, keep_recent: int
) -> collections.abc.Sequence[Message]:
    if above_tokens <= 0:
        return messages
    if sum(len(m.model_dump_json()) for m in messages) // 4 < above_tokens:
        return messages
    cut = max(0, len(messages) - keep_recent)
    return [demoted(m) if i < cut else m for i, m in enumerate(messages)]
