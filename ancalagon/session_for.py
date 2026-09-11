# How one agent is assembled: the tools it may call, and the session that calls them.
import collections.abc
import pathlib

import pydantic

from ancalagon.bus.bus import Bus
from ancalagon.bus.no_bus import NO_BUS
from ancalagon.children.children import Children
from ancalagon.children.no_children import NO_CHILDREN
from ancalagon.clock.clock import Clock
from ancalagon.config.config import Config
from ancalagon.contracts.message import Message
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.file_system import FileSystem
from ancalagon.letterbox.letterbox import Letterbox
from ancalagon.letterbox.no_letterbox import NO_LETTERBOX
from ancalagon.llm.llm import LLM
from ancalagon.llm.meter import Meter
from ancalagon.llm.unmetered import UNMETERED
from ancalagon.session import Session
from ancalagon.tools.artifacts.convert_document import ConvertDocument
from ancalagon.tools.artifacts.edit_json import EditJson
from ancalagon.tools.artifacts.extract_strings import ExtractStrings
from ancalagon.tools.artifacts.file_type import FileType
from ancalagon.tools.artifacts.query_json import QueryJson
from ancalagon.tools.compare.diff_regions import DiffRegions
from ancalagon.tools.delegate.answer_task import AnswerTask
from ancalagon.tools.delegate.check_task import CheckTask
from ancalagon.tools.delegate.collect_task import CollectTask
from ancalagon.tools.delegate.delegate_tools import delegate_tools
from ancalagon.tools.files.append_file import AppendFile
from ancalagon.tools.files.delete_file import DeleteFile
from ancalagon.tools.files.edit_file import EditFile
from ancalagon.tools.files.list_dir import ListDir
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.files.write_file import WriteFile
from ancalagon.tools.history.git_history import GitHistory
from ancalagon.tools.idle.idle import Idle
from ancalagon.tools.idle.idle_args import IdleArgs
from ancalagon.tools.idle.no_idle import NoIdle
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.parse.ast_query import AstQuery
from ancalagon.tools.parse.tree_sitter_tool import TreeSitter
from ancalagon.tools.registry.bound_for import bound_for
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.ast_grep import AstGrep
from ancalagon.tools.search.find_symbol import FindSymbol
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.search.transform_file import TransformFile
from ancalagon.tools.shell.shell import Shell
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile
from ancalagon.tools.submit.submitting import TERMINAL_TOOLS, submitting
from ancalagon.tools.survey.code_stats import CodeStats
from ancalagon.tools.watch.no_watch_file import NoWatchFile
from ancalagon.tools.watch.watch_args import WatchArgs
from ancalagon.tools.watch.watch_file import WatchFile
from ancalagon.tools.web.fetch_url import FetchUrl
from ancalagon.tools.web.web_search import WebSearch
from ancalagon.transcript.history import load, repair
from ancalagon.transcript.transcript import Transcript
from ancalagon.watch.watch_for import WATCH_FOR
from ancalagon.web.web_client import WebClient


def _idle(bus: Bus, agent: int) -> Tool[IdleArgs]:
    if bus is NO_BUS:
        return NoIdle()
    return Idle(bus, agent=agent)


def _watch(
    bus: Bus, watcher: Role, run_dir: pathlib.PurePath, parent: int, fs: FileSystem
) -> Tool[WatchArgs]:
    if bus is NO_BUS:
        return NoWatchFile()
    return WatchFile(bus, watcher, run_dir, parent, fs)


def available_tools(
    role: Role,
    roles: collections.abc.Mapping[str, Role],
    run_dir: pathlib.PurePath,
    parent: int,
    output_class: type[pydantic.BaseModel],
    clock: Clock,
    fs: FileSystem,
    web: WebClient,
    bus: Bus,
) -> list[BoundTool]:
    return [
        bound_for(ReadFile(clock), role),
        bound_for(WriteFile(), role),
        bound_for(AppendFile(), role),
        bound_for(EditFile(), role),
        bound_for(DeleteFile(), role),
        bound_for(ListDir(), role),
        bound_for(DiffRegions(clock), role),
        bound_for(Ripgrep(), role),
        bound_for(AstGrep(), role),
        bound_for(TransformFile(), role),
        bound_for(FindSymbol(), role),
        bound_for(CodeStats(), role),
        bound_for(FileType(), role),
        bound_for(ExtractStrings(), role),
        bound_for(ConvertDocument(), role),
        bound_for(QueryJson(), role),
        bound_for(EditJson(), role),
        bound_for(GitHistory(), role),
        bound_for(TreeSitter(), role),
        bound_for(AstQuery(), role),
        bound_for(Shell(), role),
        bound_for(WebSearch(web), role),
        bound_for(FetchUrl(web), role),
        *delegate_tools(roles, role, run_dir=run_dir, parent=parent, fs=fs, bus=bus),
        bound_for(CheckTask(bus), role),
        bound_for(CollectTask(bus, fs), role),
        bound_for(AnswerTask(bus=bus, parent=parent, clock=clock, fs=fs), role),
        bound_for(NeedInput(), role),
        bound_for(_idle(bus, parent), role),
        bound_for(SubmitAnswer(output_class), role),
        bound_for(SubmitAnswerAsFile(), role),
    ]


# A role that runs watch_for is a watcher, and its existence is what makes watch_file
# offerable: without one there is nothing for the tool to queue.
def watcher_in(roles: collections.abc.Mapping[str, Role]) -> list[Role]:
    return [role for role in roles.values() if role.run == WATCH_FOR]


def build_registry(
    config: Config,
    spec: TaskSpec,
    run_dir: pathlib.PurePath,
    parent: int,
    depth: int,
    output_class: type[pydantic.BaseModel],
    clock: Clock,
    fs: FileSystem,
    web: WebClient,
    bus: Bus,
) -> Registry:
    spawnable = {
        name: role for name, role in config.roles.items() if f"delegate_{name}" in spec.role.tools
    }
    available = available_tools(
        spec.role, spawnable, run_dir, parent, output_class, clock, fs, web, bus
    ) + [
        bound_for(_watch(bus, watcher, run_dir, parent, fs), spec.role)
        for watcher in watcher_in(config.roles)[:1]
    ]
    wanted = set(spec.role.tools) | {Idle.name}
    unknown = wanted - {t.name for t in available}
    if unknown:
        raise ValueError(
            f"role names unknown tools: {sorted(unknown)}; "
            f"available: {sorted(t.name for t in available)}"
        )
    depth_capped = depth >= config.max_depth
    withheld = TERMINAL_TOOLS - {submitting(spec.role.tools)}
    permitted = [
        t
        for t in available
        if t.name in wanted
        and not (depth_capped and t.name.startswith("delegate_"))
        and t.name not in withheld
    ]
    return Registry(permitted)


def session_for(
    config: Config,
    spec: TaskSpec,
    ctx: ToolContext,
    transcript: Transcript,
    run_dir: pathlib.PurePath,
    llm: LLM,
    clock: Clock,
    fs: FileSystem,
    web: WebClient,
    bus: Bus = NO_BUS,
    children: Children = NO_CHILDREN,
    letterbox: Letterbox = NO_LETTERBOX,
    meter: Meter = UNMETERED,
    depth: int = 0,
) -> Session:
    output_class = resolve_class(spec.role.answer)
    history: collections.abc.Sequence[Message] = (
        repair(load(fs, transcript.path)) if fs.exists(transcript.path) else []
    )
    return Session(
        spec=spec,
        input=ctx.input,
        messages=history,
        transcript=transcript,
        agent_id=ctx.agent_id,
        llm=llm,
        registry=build_registry(
            config,
            spec,
            run_dir,
            parent=ctx.agent_id,
            depth=depth,
            output_class=output_class,
            clock=clock,
            fs=fs,
            web=web,
            bus=bus,
        ),
        ctx=ctx,
        output_class=output_class,
        clock=clock,
        children=children,
        letterbox=letterbox,
        meter=meter,
        compact_above_tokens=config.compact_above_tokens,
        keep_recent_messages=config.keep_recent_messages,
    )
