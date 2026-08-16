# Answers a suspended agent's question, which queues a fresh attempt at the same task.
import pathlib

from ancalagon.bus.agent_status import AgentStatus
from ancalagon.clock.clock import Clock
from ancalagon.bus.bus import Bus
from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.text import Text
from ancalagon.transcript.transcript import Transcript


def answer_task(
    run_dir: pathlib.Path,
    agent: int,
    answer: str,
    answered_by: int,
    clock: Clock,
) -> int:
    bus = Bus.open(run_dir / "bus.db", clock)
    state = bus.state(agent)
    if not any(e.status is AgentStatus.NEEDS_INPUT for e in bus.history(agent)):
        raise ValueError(f"agent {agent} is {state.status.value} and never asked a question")
    task_dir = pathlib.Path(state.dir)
    active = bus.active_for(task_dir)
    if active:
        raise ValueError(
            f"agent {agent} was already answered; agent {active[0].agent} "
            f"is {active[0].status.value} on the same task"
        )
    path = task_dir / "transcript.jsonl"
    log = Transcript(path=path, agent_id=answered_by)
    log.append(
        Message(
            role=MessageRole.USER,
            blocks=[Text(text=answer)],
            agent=answered_by,
            seq=len(path.read_text(encoding="utf-8").splitlines()),
            ts=clock.now().isoformat(),
        )
    )
    log.close()
    return bus.enqueue(task_dir, parent_agent=state.parent_agent)
