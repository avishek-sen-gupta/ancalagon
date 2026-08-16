# A turn and tool-call allowance, spent as an agent works and never overspent.
import pydantic


class Budget(pydantic.BaseModel, frozen=True):
    turns: int
    tool_calls: int

    @property
    def turns_exhausted(self) -> bool:
        return self.turns <= 0

    def spend_turn(self) -> "Budget":
        return Budget(turns=self.turns - 1, tool_calls=self.tool_calls)

    def spend_tool_calls(self, count: int = 1) -> "Budget":
        return Budget(turns=self.turns, tool_calls=self.tool_calls - count)
