import pathlib

from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.lifecycle_line import LifecycleLine
from ancalagon.contracts.line import Line
from ancalagon.contracts.message import Message
from ancalagon.contracts.message_line import MessageLine
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.text import Text
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.sink.sink import Sink
from ancalagon.transcript.transcript import Transcript


class FakeSink(Sink):
    def __init__(self) -> None:
        self.lines: list[tuple[str, Line]] = []

    def publish(self, line: Line, task: str) -> None:
        self.lines.append((task, line))


def _lifecycle(agent: int, status: AgentStatus, pid: int = 0) -> LifecycleLine:
    return LifecycleLine(
        agent=agent,
        status=status,
        source=EventSource.SUPERVISOR,
        pid=pid,
        summary="",
    )


def test_every_transcript_message_and_lifecycle_event_reaches_the_sink(tmp_path: pathlib.Path):
    sink = FakeSink()
    fs = RealFileSystem()
    written = Message(
        role=MessageRole.ASSISTANT,
        blocks=[Text(text="hello")],
        agent=1,
        seq=0,
        ts="2026-01-01T00:00:00+00:00",
    )
    log = Transcript(
        fs,
        path=pathlib.PurePath(tmp_path) / "t.jsonl",
        agent_id=1,
        sink=sink,
        task="root",
    )
    log.write(written)
    log.close()

    db = pathlib.PurePath(tmp_path) / "bus.db"
    migrate_file(db, latest_version(fs), fs)
    bus = LifecycleStore.open(db, FakeClock(), fs, sink=sink)
    agent = bus.enqueue(pathlib.PurePath(tmp_path) / "tasks" / "root", parent_agent=0).id
    bus.claim(limit=1)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=7)

    assert sink.lines == [
        ("root", MessageLine(message=written)),
        ("root", _lifecycle(agent, AgentStatus.QUEUED)),
        ("root", _lifecycle(agent, AgentStatus.CLAIMED)),
        ("root", _lifecycle(agent, AgentStatus.RUNNING, pid=7)),
    ]
