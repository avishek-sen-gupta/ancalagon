# What a config must satisfy before a run starts: every contract it names must resolve.
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.run_contracts import run_contracts
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.idle.idle import Idle
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile
from ancalagon.tools.submit.submitting import TERMINAL_TOOLS, submitting
from ancalagon.web.real_web_client import RealWebClient
from ancalagon.web.web_client import WebClient
from ancalagon.worker import build_registry


def _contract_fault(name: str, field: str, ref: ClassRef) -> str:
    try:
        resolve_class(ref)
        return ""
    except Exception as error:
        return (
            f"[roles.{name}] {field} names {ref.name} in {ref.module}, "
            f"which cannot be loaded: {type(error).__name__}: {error}"
        )


def _run_fault(name: str, role: Role) -> str:
    if role.run == NO_RUN:
        return ""
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


ANSWER_FILE = ClassRef(module=AnswerFile.__module__, name=AnswerFile.__name__)


def _submit_fault(name: str, role: Role) -> str:
    if role.run != NO_RUN or set(role.tools) & TERMINAL_TOOLS:
        return ""
    return (
        f"[roles.{name}] tools: a role that runs a session must name one of "
        f"{sorted(TERMINAL_TOOLS)}; named: {sorted(role.tools)}"
    )


def _answer_file_fault(name: str, role: Role) -> str:
    if SubmitAnswerAsFile.name not in role.tools or role.answer == ANSWER_FILE:
        return ""
    return (
        f"[roles.{name}] declares answer as {role.answer.name} in {role.answer.module}, but "
        f"{SubmitAnswerAsFile.name} submits {ANSWER_FILE.name} in {ANSWER_FILE.module}"
    )


def _hook_fault(name: str, role: Role, config: Config, fs: FileSystem, web: WebClient) -> str:
    named = set(role.before) | set(role.after)
    withheld = TERMINAL_TOOLS - {submitting(role.tools)}
    in_role_but_withheld = named & set(role.tools) & withheld
    not_in_role = named - set(role.tools) - {Idle.name}
    if in_role_but_withheld:
        tool = sorted(in_role_but_withheld)[0]
        chosen = submitting(role.tools)
        return (
            f"[roles.{name}] names a hook for {tool}, but that tool is not among its tools "
            f"because it named {chosen}"
        )
    if not_in_role:
        return f"[roles.{name}] names a hook for {sorted(not_in_role)[0]}, which it does not use"
    try:
        build_registry(
            config,
            TaskSpec(task_id=name, role=role, goal=""),
            config.write_root,
            parent=0,
            depth=0,
            output_class=resolve_class(role.answer),
            clock=SystemClock(),
            fs=fs,
            web=web,
        )
        return ""
    except Exception as error:
        return f"[roles.{name}] {error}"


def check_contracts(
    config: Config, fs: FileSystem = RealFileSystem(), web: WebClient = RealWebClient()
) -> None:
    faults = (
        [
            fault
            for name, role in config.roles.items()
            for field, ref in (("input", role.input), ("answer", role.answer))
            if (fault := _contract_fault(name, field, ref))
        ]
        or [fault for name, role in config.roles.items() if (fault := _run_fault(name, role))]
        or [fault for name, role in config.roles.items() if (fault := _submit_fault(name, role))]
        or [
            fault
            for name, role in config.roles.items()
            if (fault := _answer_file_fault(name, role))
        ]
        or [
            fault
            for name, role in config.roles.items()
            if (fault := _hook_fault(name, role, config, fs, web))
        ]
    )
    if faults:
        raise ValueError("\n".join(faults))
