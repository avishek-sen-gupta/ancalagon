# The two contracts a subagent works to: what it is given, and what it must answer in.
import pydantic

from ancalagon.contracts.contract_source import ContractSource


class ContractPair(pydantic.BaseModel, frozen=True):
    input: ContractSource = ContractSource()
    answer: ContractSource = ContractSource()
