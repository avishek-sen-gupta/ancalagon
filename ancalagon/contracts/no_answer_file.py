# The class a role's answer file holds when the role submits no file: there is not one.
import pydantic

from ancalagon.contracts.class_ref import ClassRef


class NoAnswerFile(pydantic.BaseModel, frozen=True):
    pass


NO_ANSWER_FILE = ClassRef(module="ancalagon.contracts.no_answer_file", name="NoAnswerFile")
