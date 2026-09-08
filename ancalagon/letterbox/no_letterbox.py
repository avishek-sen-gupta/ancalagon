# The letterbox a session has when nobody can write to it, so that case is a choice.
from ancalagon.letterbox.letterbox import Letterbox


class NoLetterbox(Letterbox):
    def unread(self) -> tuple[str, ...]:
        return ()

    def mark(self, delivered: int) -> None:
        return None


NO_LETTERBOX = NoLetterbox()
