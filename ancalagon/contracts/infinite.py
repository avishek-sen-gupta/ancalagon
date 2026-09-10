# An allowance that is never spent down, for a run that ends only when the agent answers.
import pydantic


class Infinite(pydantic.BaseModel, frozen=True):
    def permits(self, cost: int) -> bool:
        return True

    def spend(self, count: int) -> "Infinite":
        return self

    @property
    def exhausted(self) -> bool:
        return False

    def __str__(self) -> str:
        return "unlimited"
