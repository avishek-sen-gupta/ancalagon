# An agent that is a function, not a conversation: it never builds a session, so it decides nothing.
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.profiles.profile import Profile

DETERMINISTIC = ClassRef(module="ancalagon.profiles.deterministic", name="Deterministic")


class Deterministic(Profile):
    pass
