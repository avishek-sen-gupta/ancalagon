# An agent that answers by pointing at a file it wrote, rather than by passing the answer.
import typing

from ancalagon.contracts.any_tool import AnyTool
from ancalagon.profiles.answering import Answering
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile


class AnsweringAsFile(Answering):
    terminal_tool: typing.ClassVar[type[AnyTool]] = SubmitAnswerAsFile
