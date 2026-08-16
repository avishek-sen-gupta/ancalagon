# The default allowance: a child may ask for anything up to what its parent was given.
from ancalagon.contracts.allowance import Allowance
from ancalagon.contracts.budget import Budget


class WithinParent(Allowance):
    def grant(self, parent: Budget, asked: Budget) -> Budget:
        return parent.slice(asked.turns, asked.tool_calls)
