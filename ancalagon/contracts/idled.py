# What idle returns: the attempt stops here and resumes when a child finishes.
from ancalagon.contracts.payload import Payload


class Idled(Payload, frozen=True):
    waiting_for: tuple[int, ...]

    def text_for_model(self) -> str:
        return f"idling until one of agents {list(self.waiting_for)} finishes"
