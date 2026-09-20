# Sends each line to a Unix socket, one connection per line so writers never interleave.
# Nothing listening is the configured no-op: the line is dropped and the run carries on.
import socket

from ancalagon.clock.clock import Clock
from ancalagon.contracts.line import Line
from ancalagon.contracts.log_event import LogEvent
from ancalagon.sink.sink import Sink

TIMEOUT_S = 0.25


class SocketSink(Sink):
    def __init__(self, path: str, run: str, clock: Clock):
        self.path = path
        self.run = run
        self.clock = clock

    def publish(self, line: Line) -> None:
        event = LogEvent(run=self.run, at=self.clock.now().isoformat(), line=line)
        payload = (event.model_dump_json() + "\n").encode()
        wire = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        wire.settimeout(TIMEOUT_S)
        try:
            wire.connect(self.path)
            wire.sendall(payload)
        except OSError:
            return None
        finally:
            wire.close()
