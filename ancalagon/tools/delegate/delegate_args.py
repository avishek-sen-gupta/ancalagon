import pydantic

from ancalagon.contracts.contract_pair import ContractPair


class DelegateArgs(pydantic.BaseModel, frozen=True):
    task_id: str
    behaviour: str
    goal: str
    input_json: str
    contracts: ContractPair = pydantic.Field(
        default=ContractPair(),
        description=(
            'The shapes this subagent works to, as {"input": {"path": ..., '
            '"name": ...}, "answer": {...}}. Each path names a module you wrote '
            "with write_file that defines exactly one pydantic model, and each name is "
            "that model's class. Leave a side unset for prose, which is a single text "
            "field. The same module may serve both."
        ),
    )
    turns: int
    tool_calls: int
