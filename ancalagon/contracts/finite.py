# An allowance with a fixed amount left, spent down as an agent works.
import pydantic


class Finite(pydantic.BaseModel, frozen=True):
    value: int

    def permits(self, cost: int) -> bool:
        return self.value >= cost

    def spend(self, count: int) -> "Finite":
        return Finite(value=self.value - count)

    @property
    def exhausted(self) -> bool:
        return self.value <= 0

    def __str__(self) -> str:
        return str(self.value)

    @pydantic.model_serializer
    def _as_written(self) -> int:
        return self.value
