# What a delegate tool declares to the model, shared by the real one and the one with no bus.
import pydantic

from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.tools.delegate.delegate_args import DelegateArgs


def delegate_name(role_name: str) -> str:
    return f"delegate_{role_name}"


def delegate_description(role_name: str, role: Role) -> str:
    return (
        f"Queue a {role_name} task. Returns its task id immediately without waiting. "
        f"That agent is told: {role.behaviour} "
        "Reusing a task_id after that task has finished retries it, and the new agent "
        "inherits the previous one's transcript. Use a new task_id for a clean start."
    )


def delegate_args(role_name: str, role: Role) -> type[DelegateArgs]:
    return pydantic.create_model(
        f"DelegateTo{role_name.title().replace('_', '')}Args",
        __base__=DelegateArgs,
        input=(resolve_class(role.input), ...),
    )
