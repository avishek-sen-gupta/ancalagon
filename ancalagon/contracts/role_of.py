# Turns a role as written into the role the core uses. Only the budget differs: a plain count
# becomes an allowance the session can spend down.
from ancalagon.contracts.allowance import Allowance
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.finite import Finite
from ancalagon.contracts.infinite import Infinite
from ancalagon.contracts.role import Role
from ancalagon.contracts.serialisable_role import SerialisableRole


def _allowance(given: int | str) -> Allowance:
    return Finite(value=given) if isinstance(given, int) else Infinite()


def role_of(written: SerialisableRole) -> Role:
    return Role(
        behaviour=written.behaviour,
        input=written.input,
        answer=written.answer,
        answer_file=written.answer_file,
        run=written.run,
        tools=written.tools,
        budget=Budget(
            turns=_allowance(written.budget.turns),
            tool_calls=_allowance(written.budget.tool_calls),
        ),
        before=written.before,
        after=written.after,
    )
