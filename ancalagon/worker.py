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
from ancalagon.tools.files.delete_file import DeleteFile
from ancalagon.tools.files.edit_file import EditFile
from ancalagon.tools.files.list_dir import ListDir
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.files.write_file import WriteFile
from ancalagon.tools.history.git_history import GitHistory
from ancalagon.tools.idle.idle import Idle
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.parse.tree_sitter_tool import TreeSitter
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.ast_grep import AstGrep
from ancalagon.tools.search.find_symbol import FindSymbol
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.search.sed import Sed
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.survey.code_stats import CodeStats
from ancalagon.transcript.history import load, repair
from ancalagon.transcript.transcript import Transcript
from ancalagon.workspace.workspace import Workspace

LOGGER = logging.getLogger(__name__)


def available_tools(
    roles: collections.abc.Mapping[str, Role],
    run_dir: pathlib.Path,
    parent: int,
    output_class: type[pydantic.BaseModel],
    clock: Clock,
    fs: FileSystem,
) -> list[BoundTool]:
    return [
        bind_tool(ReadFile()),
        bind_tool(WriteFile()),
        bind_tool(EditFile()),
        bind_tool(DeleteFile()),
        bind_tool(ListDir()),
        bind_tool(Ripgrep()),
        bind_tool(AstGrep()),
        bind_tool(Sed()),
        bind_tool(FindSymbol()),
        bind_tool(CodeStats()),
        bind_tool(FileType()),
        bind_tool(ExtractStrings()),
        bind_tool(ConvertDocument()),
        bind_tool(QueryJson()),
        bind_tool(GitHistory()),
        bind_tool(TreeSitter()),
        *delegate_tools(roles, run_dir=run_dir, parent=parent, clock=clock, fs=fs),
        bind_tool(CheckTask(run_dir=run_dir, clock=clock, fs=fs)),
        bind_tool(CollectTask(run_dir=run_dir, clock=clock, fs=fs)),
        bind_tool(AnswerTask(run_dir=run_dir, parent=parent, clock=clock, fs=fs)),
        bind_tool(NeedInput()),
        bind_tool(Idle(run_dir=run_dir, agent=parent, clock=clock, fs=fs)),
        bind_tool(SubmitAnswer(output_class)),
    ]


def build_registry(
    config: Config,
    spec: TaskSpec,
    run_dir: pathlib.Path,
    parent: int,
    depth: int,
    output_class: type[pydantic.BaseModel],
    clock: Clock,
    fs: FileSystem,
) -> Registry:
    spawnable = {
        name: role for name, role in config.roles.items() if f"delegate_{name}" in spec.role.tools
    }
    available = available_tools(spawnable, run_dir, parent, output_class, clock, fs)
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
    run_dir: pathlib.Path, task_dir: pathlib.Path, agent_id: int, config_path: pathlib.Path
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
            output_dir=task_dir / "tools",
            summary_chars=config.summary_chars,
            agent_id=agent_id,
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
    parser.add_argument("--run-dir", type=pathlib.Path, required=True)
    parser.add_argument("--dir", type=pathlib.Path, required=True)
    parser.add_argument("--agent-id", type=int, required=True)
    parser.add_argument("--config", type=pathlib.Path, required=True)
    args = parser.parse_args()
    return main(args.run_dir, args.dir, args.agent_id, args.config)


if __name__ == "__main__":
    sys.exit(cli())
