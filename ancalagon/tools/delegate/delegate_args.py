# The fields every delegate tool takes; create_model narrows `input` per role.
import pydantic


class DelegateArgs(pydantic.BaseModel, frozen=True):
    task_id: str
    goal: str
    input: pydantic.BaseModel
