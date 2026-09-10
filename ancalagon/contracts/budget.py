# A turn and tool-call allowance, spent as an agent works and never overspent.
import pydantic

from ancalagon.contracts.allowance import Allowance


class Budget(pydantic.BaseModel, frozen=True):
    turns: Allowance
    tool_calls: Allowance

    @property
    def turns_exhausted(self) -> bool:
        return self.turns.exhausted

    def spend_turn(self) -> "Budget":
        return Budget(turns=self.turns.spend(1), tool_calls=self.tool_calls)

    def spend_tool_calls(self, count: int = 1) -> "Budget":
        return Budget(turns=self.turns, tool_calls=self.tool_calls.spend(count))
