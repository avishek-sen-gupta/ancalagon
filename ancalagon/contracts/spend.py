# What an agent used, counted as it worked rather than derived from what it had left.
import pydantic


class Spend(pydantic.BaseModel, frozen=True):
    turns: int
    tool_calls: int

    def plus_turn(self) -> "Spend":
        return Spend(turns=self.turns + 1, tool_calls=self.tool_calls)

    def plus_tool_calls(self, count: int) -> "Spend":
        return Spend(turns=self.turns, tool_calls=self.tool_calls + count)
