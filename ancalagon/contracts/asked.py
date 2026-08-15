# What need_input returns: the question it recorded, which ends the run.
from ancalagon.contracts.payload import Payload


class Asked(Payload, frozen=True):
    question: str

    def text_for_model(self) -> str:
        return f"question recorded: {self.question}"
