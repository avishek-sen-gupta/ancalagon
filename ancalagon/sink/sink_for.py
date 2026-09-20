# Builds the sink a run writes to: the configured socket, or nothing at all.
from ancalagon.clock.clock import Clock
from ancalagon.sink.no_sink import NO_SINK
from ancalagon.sink.sink import Sink
from ancalagon.sink.socket_sink import SocketSink


def sink_for(log_socket: str, run: str, clock: Clock) -> Sink:
    if not log_socket:
        return NO_SINK
    return SocketSink(path=log_socket, run=run, clock=clock)
