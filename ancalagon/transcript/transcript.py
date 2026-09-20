# Writes and flushes per message, so a killed agent still leaves a resumable history.
import pathlib

from ancalagon.contracts.message import Message
from ancalagon.contracts.message_line import MessageLine
from ancalagon.fs.file_system import FileSystem
from ancalagon.sink.no_sink import NO_SINK
from ancalagon.sink.sink import Sink


class Transcript:
    def __init__(
        self,
        fs: FileSystem,
        path: pathlib.PurePath,
        agent_id: int,
        sink: Sink = NO_SINK,
        task: str = "",
    ):
        self.path = path
        self.agent_id = agent_id
        self.sink = sink
        self.task = task
        fs.mkdir(path.parent, parents=True, exist_ok=True)
        self.handle = fs.open_append(path)

    def write(self, message: Message) -> None:
        self.handle.write(message.model_dump_json() + "\n")
        self.handle.flush()
        self.sink.publish(MessageLine(message=message), self.task)

    def close(self) -> None:
        self.handle.close()
