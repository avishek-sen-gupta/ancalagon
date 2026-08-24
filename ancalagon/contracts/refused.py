# A hook's verdict that a call may not proceed, carrying what the agent is told.
import pydantic


class Refused(pydantic.BaseModel, frozen=True):
    reason: str
