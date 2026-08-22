# Writes and flushes per message, so a killed agent still leaves a resumable history.
import pathlib

from ancalagon.contracts.message import Message
from ancalagon.fs.file_system import FileSystem


class Transcript:
    def __init__(self, fs: FileSystem, path: pathlib.Path, agent_id: int):
        self.path = path
        self.agent_id = agent_id
        fs.mkdir(path.parent, parents=True, exist_ok=True)
        self.handle = fs.open_append(path)

    def write(self, message: Message) -> None:
        self.handle.write(message.model_dump_json() + "\n")
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()
