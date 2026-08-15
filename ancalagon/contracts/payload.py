# What a tool result carries, rendered to text only where the model reads it.
import pydantic


class Payload(pydantic.BaseModel, frozen=True):
    def text_for_model(self) -> str:
        raise NotImplementedError
