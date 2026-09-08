# Where a session learns what a human left for it while it was working.
import typing


class Letterbox(typing.Protocol):
    def unread(self) -> tuple[str, ...]: ...

    def mark(self, delivered: int) -> None: ...
