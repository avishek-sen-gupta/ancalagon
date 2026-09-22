# Cuts a root transcript at a chosen message, so that a new run carries on from there.
import collections.abc

from ancalagon.clock.clock import Clock
from ancalagon.contracts.delegated_task import DelegatedTask
from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.transcript.history import repair

ACKNOWLEDGED = "Understood."
NOTICE = (
    "This conversation was forked into a new run at message {at}. The tasks delegated "
    "earlier in it -- {tasks} -- belong to the run it was forked from and do not exist "
    "here, so do not check or collect them. Delegate again if you still need that work."
)


def orphaned(
    messages: collections.abc.Sequence[Message], delegates: collections.abc.Set[str]
) -> tuple[str, ...]:
    return tuple(
        DelegatedTask.model_validate_json(block.arguments).task_id
        for message in messages
        for block in message.blocks
        if isinstance(block, ToolUse) and block.name in delegates
    )


def _appended(role: MessageRole, text: str, after: Message, clock: Clock) -> Message:
    return Message(
        role=role,
        blocks=[Text(text=text)],
        agent=after.agent,
        seq=after.seq + 1,
        ts=clock.now().isoformat(),
    )


def forked(
    messages: collections.abc.Sequence[Message],
    at: int,
    delegates: collections.abc.Set[str],
    clock: Clock,
) -> collections.abc.Sequence[Message]:
    last = messages[-1].seq
    if at <= 0 or at > last + 1:
        raise ValueError(
            f"--at {at} names no message of this transcript, which runs 1 to {last + 1}"
        )
    kept = [message for message in messages if message.seq < at]
    tasks = orphaned(kept, delegates)
    if not tasks:
        return kept
    answered = list(repair(kept))
    bridged = (
        [*answered, _appended(MessageRole.ASSISTANT, ACKNOWLEDGED, answered[-1], clock)]
        if answered[-1].role is MessageRole.USER
        else answered
    )
    notice = NOTICE.format(at=at, tasks=", ".join(tasks))
    return [*bridged, _appended(MessageRole.USER, notice, bridged[-1], clock)]
