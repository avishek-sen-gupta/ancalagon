# Decides what budget a parent may grant a child, so a tree cannot outgrow its root by accident.
import typing

from ancalagon.contracts.budget import Budget


class Allowance(typing.Protocol):
    def grant(self, parent: Budget, asked: Budget) -> Budget: ...
