# An agent that answers by pointing at a file it wrote, rather than by passing the answer.
import typing

from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.any_tool import AnyTool
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.no_answer_file import NO_ANSWER_FILE
from ancalagon.contracts.serialisable_role import SerialisableRole
from ancalagon.profiles.answering import Answering, run_ref_fault
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile

ANSWERING_AS_FILE = ClassRef(module="ancalagon.profiles.answering_as_file", name="AnsweringAsFile")

ANSWER_FILE = ClassRef(module=AnswerFile.__module__, name=AnswerFile.__name__)


def _answer_fault(name: str, kind: str, role: SerialisableRole) -> str:
    if role.answer == ANSWER_FILE:
        return ""
    return (
        f"[roles.{name}] declares answer as {role.answer.name} in {role.answer.module}, "
        f"but {kind} answers with {ANSWER_FILE.name} in {ANSWER_FILE.module}"
    )


def _content_fault(name: str, kind: str, role: SerialisableRole) -> str:
    if role.answer_file != NO_ANSWER_FILE:
        return ""
    return (
        f"[roles.{name}] is {kind}, so it must declare answer_file: "
        "the class its answer file holds"
    )


class AnsweringAsFile(Answering):
    terminal_tool: typing.ClassVar[type[AnyTool]] = SubmitAnswerAsFile

    @classmethod
    def faults(cls, name: str, role: SerialisableRole, /) -> str:
        checks = (run_ref_fault, _answer_fault, _content_fault)
        return next((fault for check in checks if (fault := check(name, cls.__name__, role))), "")
