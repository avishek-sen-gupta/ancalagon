import pathlib
import socket
import tempfile

from ancalagon.clock.fake_clock import EPOCH, FakeClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.lifecycle_line import LifecycleLine
from ancalagon.contracts.log_event import LogEvent
from ancalagon.sink.socket_sink import SocketSink

# AF_UNIX paths are capped near 104 bytes, which pytest's tmp_path already exceeds.
SOCKET_ROOT = "/tmp"
RUN = "run-1"
TASK = "analyst"


def _path() -> str:
    return str(pathlib.Path(tempfile.mkdtemp(dir=SOCKET_ROOT)) / "q.sock")


def _listener(path: str) -> socket.socket:
    bound = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    bound.bind(path)
    bound.listen(8)
    return bound


def _read(listener: socket.socket) -> LogEvent:
    conn, _ = listener.accept()
    chunks: list[bytes] = []
    while not b"".join(chunks).endswith(b"\n"):
        chunks.append(conn.recv(4096))
    conn.close()
    return LogEvent.model_validate_json(b"".join(chunks).decode())


def _line(agent: int) -> LifecycleLine:
    return LifecycleLine(
        agent=agent,
        status=AgentStatus.RUNNING,
        source=EventSource.SUPERVISOR,
        pid=agent,
        summary="",
    )


def _expected(agent: int) -> LogEvent:
    return LogEvent(run=RUN, task=TASK, at=EPOCH.isoformat(), line=_line(agent))


def test_published_lines_reach_a_listener_intact():
    path = _path()
    listener = _listener(path)
    sink = SocketSink(path=path, run=RUN, clock=FakeClock())

    sink.publish(_line(1), TASK)
    sink.publish(_line(2), TASK)
    received = [_read(listener), _read(listener)]
    listener.close()

    assert received == [_expected(1), _expected(2)]


def test_publishing_without_a_listener_is_a_no_op_and_a_later_listener_still_receives():
    path = _path()
    sink = SocketSink(path=path, run=RUN, clock=FakeClock())

    sink.publish(_line(1), TASK)

    listener = _listener(path)
    sink.publish(_line(2), TASK)
    received = _read(listener)
    listener.close()

    assert received == _expected(2)
