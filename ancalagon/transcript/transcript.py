# Writes and flushes per message, so a killed agent still leaves a resumable history.
import pathlib

from ancalagon.contracts.message import Message


class Transcript:
    def __init__(self, path: pathlib.Path, agent_id: int):
        self.path = path
        self.agent_id = agent_id
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a", encoding="utf-8")

    def write(self, message: Message) -> None:
        self.handle.write(message.model_dump_json() + "\n")
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()
