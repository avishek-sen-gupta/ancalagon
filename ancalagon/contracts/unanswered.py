# Stands in for an answer that has not been submitted, so the slot never holds None.
import pydantic


class Unanswered(pydantic.BaseModel, frozen=True):
    pass
