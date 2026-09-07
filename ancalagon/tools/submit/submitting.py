# Which terminal submit tool a role named; the session offers and forces that one.
import collections.abc

from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile


def submitting(tools: collections.abc.Sequence[str]) -> str:
    return SubmitAnswerAsFile.name if SubmitAnswerAsFile.name in tools else SubmitAnswer.name
