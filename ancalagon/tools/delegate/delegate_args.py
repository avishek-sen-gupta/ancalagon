import pydantic


class DelegateArgs(pydantic.BaseModel, frozen=True):
    task_id: str
    behaviour: str
    goal: str
    input_json: str
    output: str
    turns: int
    tool_calls: int
    contracts_py: str = ""
