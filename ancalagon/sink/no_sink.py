# The sink a run has when no log queue is configured.
from ancalagon.contracts.line import Line
from ancalagon.sink.sink import Sink


class NoSink(Sink):
    def publish(self, line: Line) -> None:
        return None


NO_SINK = NoSink()
