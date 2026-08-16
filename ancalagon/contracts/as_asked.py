# The allowance that defers entirely to the parent's judgement, capping nothing.
from ancalagon.contracts.allowance import Allowance
from ancalagon.contracts.budget import Budget


class AsAsked(Allowance):
    def grant(self, parent: Budget, asked: Budget) -> Budget:
        return asked
