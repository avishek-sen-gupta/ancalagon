# An agent that is a function, not a conversation: it never builds a session, so it decides nothing.
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.run_contracts import run_contracts
from ancalagon.contracts.serialisable_role import SerialisableRole
from ancalagon.profiles.profile import Profile

DETERMINISTIC = ClassRef(module="ancalagon.profiles.deterministic", name="Deterministic")


class Deterministic(Profile):
    @classmethod
    def faults(cls, name: str, role: SerialisableRole, /) -> str:
        if role.run == NO_RUN:
            return f"[roles.{name}] is {cls.__name__}, so it must name a run function"
        given, produced = run_contracts(role.run)
        disagreements = [
            (field, declared, derived)
            for field, declared, derived in (
                ("input", role.input, given),
                ("answer", role.answer, produced),
            )
            if declared != derived
        ]
        if not disagreements:
            return ""
        field, declared, derived = disagreements[0]
        return (
            f"[roles.{name}] declares {field} as {declared.name} in {declared.module}, but its "
            f"run function {role.run.name} in {role.run.module} states {field} as "
            f"{derived.name} in {derived.module}"
        )
