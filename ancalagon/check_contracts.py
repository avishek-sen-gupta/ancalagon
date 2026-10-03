# What a config must satisfy before a run starts: every contract it names must resolve.
from ancalagon.bus.no_bus import NO_BUS
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.role_of import role_of
from ancalagon.contracts.serialisable_role import SerialisableRole
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.profiles.resolve_profile import resolve_profile
from ancalagon.session_for import assemble
from ancalagon.tools.idle.idle import Idle
from ancalagon.tools.submit.submitting import TERMINAL_TOOLS
from ancalagon.web.real_web_client import RealWebClient
from ancalagon.web.web_client import WebClient


def _contract_fault(name: str, field: str, ref: ClassRef) -> str:
    try:
        resolve_class(ref)
        return ""
    except Exception as error:
        return (
            f"[roles.{name}] {field} names {ref.name} in {ref.module}, "
            f"which cannot be loaded: {type(error).__name__}: {error}"
        )


def _profile_fault(name: str, written: SerialisableRole) -> str:
    try:
        kind = resolve_profile(written.profile)
    except Exception as error:
        return f"[roles.{name}] profile: {error}"
    return kind.faults(name, written)


def _submit_fault(name: str, role: Role) -> str:
    if role.run != NO_RUN:
        return ""
    terminal = set(role.tools) & TERMINAL_TOOLS
    if len(terminal) == 1:
        return ""
    if not terminal:
        return (
            f"[roles.{name}] tools: a role that runs a session must name one of "
            f"{sorted(TERMINAL_TOOLS)}; named: {sorted(role.tools)}"
        )
    return (
        f"[roles.{name}] tools: a role that runs a session must name only one of "
        f"{sorted(TERMINAL_TOOLS)}; named: {sorted(terminal)}"
    )


def _hook_fault(
    name: str, written: SerialisableRole, config: Config, fs: FileSystem, web: WebClient
) -> str:
    role = role_of(written)
    named = set(role.before) | set(role.after)
    not_in_role = named - set(role.tools) - {Idle.name}
    if not_in_role:
        return f"[roles.{name}] names a hook for {sorted(not_in_role)[0]}, which it does not use"
    try:
        assemble(
            config,
            TaskSpec(task_id=name, role=written, goal=""),
            config.home,
            parent=0,
            depth=0,
            output_class=resolve_class(role.answer),
            answer_file_class=resolve_class(role.answer_file),
            clock=SystemClock(),
            fs=fs,
            web=web,
            bus=NO_BUS,
        )
        return ""
    except Exception as error:
        return f"[roles.{name}] {error}"


def check_contracts(
    config: Config, fs: FileSystem = RealFileSystem(), web: WebClient = RealWebClient()
) -> None:
    resolved = {name: role_of(written) for name, written in config.roles.items()}
    faults = (
        [
            fault
            for name, role in resolved.items()
            for field, ref in (
                ("input", role.input),
                ("answer", role.answer),
                ("answer_file", role.answer_file),
            )
            if (fault := _contract_fault(name, field, ref))
        ]
        or [
            fault
            for name, written in config.roles.items()
            if (fault := _profile_fault(name, written))
        ]
        or [fault for name, role in resolved.items() if (fault := _submit_fault(name, role))]
        or [
            fault
            for name, written in config.roles.items()
            if (fault := _hook_fault(name, written, config, fs, web))
        ]
    )
    if faults:
        raise ValueError("\n".join(faults))
