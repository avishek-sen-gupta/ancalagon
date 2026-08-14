import pydantic


class AnswerArgs(pydantic.BaseModel, frozen=True):
    task: int
    answer: str
