import pydantic


class MessageRow(pydantic.BaseModel, frozen=True):
    id: int
    ts: str
    sender: int
    addressee: int
    kind: str
    summary: str
    ref_path: str
