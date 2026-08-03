# Turn and tool-call allowances, sliced by a caller for its children and never overspent.
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

    def slice(self, turns: int, tool_calls: int) -> "Budget":
        if turns > self.turns or tool_calls > self.tool_calls:
            raise ValueError(
                f"cannot slice {turns}/{tool_calls} from {self.turns}/{self.tool_calls}"
            )
        return Budget(turns=turns, tool_calls=tool_calls)
