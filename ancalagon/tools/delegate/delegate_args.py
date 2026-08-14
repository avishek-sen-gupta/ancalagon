import pydantic


class DelegateArgs(pydantic.BaseModel, frozen=True):
    task_id: str
    behaviour: str
    goal: str
    input_json: str
    input_schema: str = pydantic.Field(
        default="contracts.py:FreeText",
        pattern=r"^[^:]+\.py:[A-Za-z_][A-Za-z0-9_]*$",
        description=(
            "The shape input_json must match, as '<module>.py:<ClassName>'. Leave it "
            "unset to pass prose, in which case input_json carries a single text field. "
            "For structured input, define its model beside the answer's and name it here."
        ),
    )
    answer_schema: str = pydantic.Field(
        default="contracts.py:FreeText",
        pattern=r"^[^:]+\.py:[A-Za-z_][A-Za-z0-9_]*$",
        description=(
            "The shape the subagent must answer in, as '<module>.py:<ClassName>'. "
            "Leave it unset for prose. To require a structured answer, write a module "
            "defining a pydantic model with write_file, pass its path as contracts_path, "
            "and name the class here."
        ),
    )
    turns: int
    tool_calls: int
    contracts_path: str = ""
