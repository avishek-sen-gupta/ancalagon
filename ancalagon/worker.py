# Entry point for one agent process: runs a single attempt at one task directory.
import argparse
import collections.abc
import logging
import pathlib
import sys
import traceback

import pydantic

from ancalagon.bus.bus_meter import BusMeter
from ancalagon.bus.connect import connect
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.bus.meter_store import MeterStore
from ancalagon.children.bus_children import BusChildren
from ancalagon.clock.clock import Clock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.config.load import load_config
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.message import Message
from ancalagon.contracts.outcome import SUMMARY_CHARS
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.watch_request import WatchRequest
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.llm.adapters.litellm_client import LiteLLMClient
from ancalagon.schedule.depth_of import depth_of
from ancalagon.session import Session
from ancalagon.tools.artifacts.convert_document import ConvertDocument
from ancalagon.tools.artifacts.extract_strings import ExtractStrings
from ancalagon.tools.artifacts.file_type import FileType
from ancalagon.tools.artifacts.query_json import QueryJson
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
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.parse.ast_query import AstQuery
from ancalagon.tools.parse.tree_sitter_tool import TreeSitter
from ancalagon.tools.registry.bound_for import bound_for
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.ast_grep import AstGrep
from ancalagon.tools.search.find_symbol import FindSymbol
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.search.transform_file import TransformFile
from ancalagon.tools.shell.shell import Shell
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.watch.watch_file import WatchFile
from ancalagon.tools.survey.code_stats import CodeStats
from ancalagon.transcript.history import load, repair
from ancalagon.transcript.transcript import Transcript
from ancalagon.workspace.workspace import Workspace

LOGGER = logging.getLogger(__name__)


def available_tools(
    role: Role,
    roles: collections.abc.Mapping[str, Role],
    run_dir: pathlib.PurePath,
    parent: int,
    output_class: type[pydantic.BaseModel],
    clock: Clock,
    fs: FileSystem,
) -> list[BoundTool]:
    return [
        bound_for(ReadFile(clock), role),
        bound_for(WriteFile(), role),
        bound_for(AppendFile(), role),
        bound_for(EditFile(), role),
        bound_for(DeleteFile(), role),
        bound_for(ListDir(), role),
        bound_for(Ripgrep(), role),
        bound_for(AstGrep(), role),
        bound_for(TransformFile(), role),
        bound_for(FindSymbol(), role),
        bound_for(CodeStats(), role),
        bound_for(FileType(), role),
        bound_for(ExtractStrings(), role),
        bound_for(ConvertDocument(), role),
        bound_for(QueryJson(), role),
        bound_for(GitHistory(), role),
        bound_for(TreeSitter(), role),
        bound_for(AstQuery(), role),
        bound_for(Shell(), role),
        *delegate_tools(roles, role, run_dir=run_dir, parent=parent, clock=clock, fs=fs),
        bound_for(CheckTask(run_dir=run_dir, clock=clock, fs=fs), role),
        bound_for(CollectTask(run_dir=run_dir, clock=clock, fs=fs), role),
        bound_for(AnswerTask(run_dir=run_dir, parent=parent, clock=clock, fs=fs), role),
        bound_for(NeedInput(), role),
        bound_for(Idle(run_dir=run_dir, agent=parent, clock=clock, fs=fs), role),
        bound_for(SubmitAnswer(output_class), role),
    ]


# A role whose input is a WatchRequest is a watcher, and its existence is what makes
# watch_file offerable: without one there is nothing for the tool to queue.
def watcher_in(roles: collections.abc.Mapping[str, Role]) -> list[Role]:
    return [role for role in roles.values() if role.input.name == WatchRequest.__name__]


def build_registry(
    config: Config,
    spec: TaskSpec,
    run_dir: pathlib.PurePath,
    parent: int,
    depth: int,
    output_class: type[pydantic.BaseModel],
    clock: Clock,
    fs: FileSystem,
) -> Registry:
    spawnable = {
        name: role for name, role in config.roles.items() if f"delegate_{name}" in spec.role.tools
    }
    available = available_tools(spec.role, spawnable, run_dir, parent, output_class, clock, fs) + [
        bound_for(WatchFile(watcher, run_dir, parent, clock, fs), spec.role)
        for watcher in watcher_in(config.roles)[:1]
    ]
    wanted = set(spec.role.tools) | {Idle.name, SubmitAnswer.name}
    unknown = wanted - {t.name for t in available}
    if unknown:
        raise ValueError(
            f"role names unknown tools: {sorted(unknown)}; "
            f"available: {sorted(t.name for t in available)}"
        )
    depth_capped = depth >= config.max_depth
    permitted = [
        t
        for t in available
        if t.name in wanted and not (depth_capped and t.name.startswith("delegate_"))
    ]
    return Registry(permitted)


def main(
    run_dir: pathlib.PurePath,
    task_dir: pathlib.PurePath,
    agent_id: int,
    config_path: pathlib.PurePath,
) -> int:
    fs = RealFileSystem()
    config = load_config(config_path, fs)
    outcome_path = task_dir / f"outcome-{agent_id}.json"
    transcript_path = task_dir / "transcript.jsonl"
    log = Transcript(fs, path=transcript_path, agent_id=agent_id)
    clock = SystemClock()
    conn = connect(run_dir / "bus.db", fs)
    bus = LifecycleStore(conn, clock)
    meter_store = MeterStore(conn, clock)
    try:
        spec_text = fs.read_text(task_dir / "spec.json")
        spec = TaskSpec.model_validate_json(spec_text)
        output_class = resolve_class(spec.role.answer)
        input_class = resolve_class(spec.role.input)
        given = AgentSpec[input_class].model_validate_json(spec_text).input
        history: collections.abc.Sequence[Message] = (
            repair(load(fs, transcript_path)) if fs.exists(transcript_path) else []
        )
        ctx = ToolContext(
            workspace=Workspace.from_config(config, fs),
            task_dir=task_dir,
            summary_chars=config.summary_chars,
            agent_id=agent_id,
            input=given,
        )
        session = Session(
            spec=spec,
            input=given,
            messages=history,
            transcript=log,
            agent_id=agent_id,
            llm=LiteLLMClient(
                model=config.model,
                max_tokens=config.max_tokens,
                num_retries=config.num_retries,
                request_timeout_s=config.request_timeout_s,
            ),
            registry=build_registry(
                config,
                spec,
                run_dir,
                parent=agent_id,
                depth=depth_of(bus.snapshot(), agent_id),
                output_class=output_class,
                clock=clock,
                fs=fs,
            ),
            ctx=ctx,
            output_class=output_class,
            clock=clock,
            children=BusChildren(bus, agent_id),
            meter=BusMeter(meter_store),
            compact_above_tokens=config.compact_above_tokens,
            keep_recent_messages=config.keep_recent_messages,
        )
        outcome = session.run()
        fs.write_text(outcome_path, outcome.model_dump_json())
        return 0
    except Exception as exc:
        LOGGER.exception("worker failed")
        failure = Failed(
            error=traceback.format_exc(),
            summary=str(exc)[:SUMMARY_CHARS],
            spent=Budget(turns=0, tool_calls=0),
        )
        fs.write_text(outcome_path, failure.model_dump_json())
        return 1
    finally:
        log.close()


def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon.worker")
    parser.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    parser.add_argument("--dir", type=pathlib.PurePath, required=True)
    parser.add_argument("--agent-id", type=int, required=True)
    parser.add_argument("--config", type=pathlib.PurePath, required=True)
    args = parser.parse_args()
    return main(args.run_dir, args.dir, args.agent_id, args.config)


if __name__ == "__main__":
    sys.exit(cli())
