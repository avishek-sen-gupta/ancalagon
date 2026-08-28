# The children a session has when it has none, so that case is a choice rather than a branch.
from ancalagon.children.children import Children


class NoChildren(Children):
    def outstanding(self) -> tuple[int, ...]:
        return ()

    def uncollected(self) -> tuple[int, ...]:
        return ()


NO_CHILDREN = NoChildren()
