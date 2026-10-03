# An agent that works and never answers: it idles when it has nothing left to do, and is
# started again with the conversation it already had.
from ancalagon.contracts.any_tool import AnyTool
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.no_answer_file import NO_ANSWER_FILE
from ancalagon.contracts.role import FREE_TEXT
from ancalagon.contracts.serialisable_role import SerialisableRole
from ancalagon.profiles.answering import run_ref_fault
from ancalagon.profiles.profile import Profile
from ancalagon.profiles.turn import Turn
from ancalagon.tools.idle.idle import Idle
from ancalagon.tools.idle.no_idle import NoIdle

STANDING = ClassRef(module="ancalagon.profiles.standing", name="Standing")

MECHANICS = (
    "You do not answer and you do not finish. You work, you write what you have to the files "
    "you own, and when there is nothing left to do you call idle. Idling ends this turn; you "
    "will be started again when something arrives for you, with this conversation intact."
)


def _answer_fault(name: str, kind: str, role: SerialisableRole) -> str:
    if role.answer == FREE_TEXT:
        return ""
    return (
        f"[roles.{name}] declares answer as {role.answer.name} in {role.answer.module}, but "
        f"{kind} never answers, so nothing would submit it"
    )


def _content_fault(name: str, kind: str, role: SerialisableRole) -> str:
    if role.answer_file == NO_ANSWER_FILE:
        return ""
    return (
        f"[roles.{name}] declares answer_file as {role.answer_file.name} in "
        f"{role.answer_file.module}, but {kind} never answers, so nothing would check it"
    )


class Standing(Profile):
    @classmethod
    def supplies(cls) -> tuple[tuple[type[AnyTool], ...], ...]:
        return ((Idle, NoIdle),)

    @classmethod
    def faults(cls, name: str, role: SerialisableRole, /) -> str:
        checks = (run_ref_fault, _answer_fault, _content_fault)
        return next((fault for check in checks if (fault := check(name, cls.__name__, role))), "")

    def mechanics(self, turn: Turn, /) -> str:
        return MECHANICS
