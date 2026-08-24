# A hook's verdict that a call may proceed, carrying the value it proceeds with.
import pydantic


class Accepted(pydantic.BaseModel, frozen=True):
    value: pydantic.BaseModel
