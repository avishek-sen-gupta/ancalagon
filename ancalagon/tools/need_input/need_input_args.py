import pydantic


class NeedInputArgs(pydantic.BaseModel, frozen=True):
    question: str
