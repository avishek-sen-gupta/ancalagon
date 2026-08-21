# Answers a suspended agent's question, which queues a fresh attempt at the same task.
import pathlib

from ancalagon.attempt.snapshot import Snapshot
from ancalagon.bus.bus import Bus
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.text import Text
from ancalagon.schedule.active_for import active_for
from ancalagon.schedule.task_of import task_of
from ancalagon.transcript.transcript import Transcript


def _status(snapshot: Snapshot, agent: int) -> AgentStatus:
    return max(snapshot.events[agent], key=lambda event: event.id).status


def answer_task(
    run_dir: pathlib.Path,
    agent: int,
    answer: str,
    answered_by: int,
    clock: Clock,
) -> int:
    bus = Bus.open(run_dir / "bus.db", clock)
    snapshot = bus.snapshot()
    if not any(e.status is AgentStatus.NEEDS_INPUT for e in snapshot.events[agent]):
        raise ValueError(
            f"agent {agent} is {_status(snapshot, agent).value} and never asked a question"
        )
    task = task_of(snapshot, agent)
    task_dir = pathlib.Path(task.dir)
    active = active_for(snapshot, task.dir)
    if active:
        raise ValueError(
            f"agent {agent} was already answered; agent {active[0]} "
            f"is {_status(snapshot, active[0]).value} on the same task"
        )
    path = task_dir / "transcript.jsonl"
    log = Transcript(path=path, agent_id=answered_by)
    log.write(
        Message(
            role=MessageRole.USER,
            blocks=[Text(text=answer)],
            agent=answered_by,
            seq=len(path.read_text(encoding="utf-8").splitlines()),
            ts=clock.now().isoformat(),
        )
    )
    log.close()
    return bus.enqueue(task_dir, parent_agent=task.parent_agent)
