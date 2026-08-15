# The ordinary tool result: text the model reads exactly as the tool wrote it.
from ancalagon.contracts.payload import Payload


class TextAnswer(Payload, frozen=True):
    text: str

    def text_for_model(self) -> str:
        return self.text
