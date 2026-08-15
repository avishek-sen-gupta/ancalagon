# What submit_answer returns: the answer it validated, which ends the run.
import pydantic

from ancalagon.contracts.payload import Payload


class Submitted(Payload, frozen=True):
    answer: pydantic.BaseModel

    def text_for_model(self) -> str:
        return "answer accepted"
