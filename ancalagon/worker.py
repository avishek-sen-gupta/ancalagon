# Entry point for one agent process: runs a single attempt at one task directory.
import collections.abc
import argparse
import logging
import pathlib
import sys

import pydantic
import traceback

from ancalagon.bus.agent_status import AgentStatus
from ancalagon.bus.bus import Bus
from ancalagon.bus.bus_meter import BusMeter
from ancalagon.bus.event_source import EventSource
from ancalagon.bus.depth_of import depth_of
from ancalagon.clock.clock import Clock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.config.load import load_config
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.message import Message
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.outcome import SUMMARY_CHARS
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.llm.adapters.litellm_client import LiteLLMClient
from ancalagon.session import Session
from ancalagon.tools.artifacts.convert_document import ConvertDocument
from ancalagon.tools.artifacts.extract_strings import ExtractStrings
from ancalagon.tools.artifacts.file_type import FileType
from ancalagon.tools.artifacts.query_json import QueryJson
from ancalagon.tools.delegate.answer_task import AnswerTask
from ancalagon.tools.delegate.check_task import CheckTask
from ancalagon.tools.delegate.collect_task import CollectTask
from ancalagon.tools.delegate.delegate import Delegate
from ancalagon.tools.files.delete_file import DeleteFile
from ancalagon.tools.files.edit_file import EditFile
from ancalagon.tools.files.list_dir import ListDir
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.files.write_file import WriteFile
from ancalagon.tools.history.git_history import GitHistory
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.parse.tree_sitter_tool import TreeSitter
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.search.ast_grep import AstGrep
from ancalagon.tools.search.find_symbol import FindSymbol
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.search.sed import Sed
from ancalagon.tools.survey.code_stats import CodeStats
from ancalagon.transcript.history import load, repair
from ancalagon.transcript.transcript import Transcript
from ancalagon.workspace.workspace import Workspace

LOGGER = logging.getLogger(__name__)


def build_registry(
    config: Config,
    run_dir: pathlib.Path,
    parent: int,
    depth: int,
    output_class: type[pydantic.BaseModel],
    budget: Budget,
    clock: Clock,
) -> Registry:
    available: list[BoundTool] = [
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
        bind_tool(Delegate(run_dir=run_dir, parent=parent, budget=budget, clock=clock)),
        bind_tool(CheckTask(run_dir=run_dir, clock=clock)),
        bind_tool(CollectTask(run_dir=run_dir, clock=clock)),
        bind_tool(AnswerTask(run_dir=run_dir, parent=parent, clock=clock)),
        bind_tool(NeedInput()),
        bind_tool(SubmitAnswer(output_class)),
    ]
    enabled = set(config.tools)
    unknown = enabled - {t.name for t in available}
    if unknown:
        raise ValueError(
            f"unknown tool names in [tools] enabled: {sorted(unknown)}; "
            f"available: {sorted(t.name for t in available)}"
        )
    permitted = [t for t in available if not enabled or t.name in enabled]
    if depth >= config.max_depth:
        permitted = [t for t in permitted if t.name != "delegate"]
    return Registry(permitted)


def main(
    run_dir: pathlib.Path, task_dir: pathlib.Path, agent_id: int, config_path: pathlib.Path
) -> int:
    config = load_config(config_path)
    outcome_path = task_dir / "outcome.json"
    transcript_path = task_dir / "transcript.jsonl"
    log = Transcript(path=transcript_path, agent_id=agent_id)
    clock = SystemClock()
    bus = Bus.open(run_dir / "bus.db", clock)
    try:
        spec_text = (task_dir / "spec.json").read_text()
        spec = TaskSpec.model_validate_json(spec_text)
        output_class = resolve_class(spec.answer_schema)
        input_class = resolve_class(spec.input_schema)
        given = AgentSpec[input_class].model_validate_json(spec_text).input
        history: collections.abc.Sequence[Message] = (
            repair(load(transcript_path)) if transcript_path.exists() else []
        )
        ctx = ToolContext(
            workspace=Workspace.from_config(config),
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
                run_dir,
                parent=agent_id,
                depth=depth_of(bus, agent_id),
                output_class=output_class,
                budget=spec.budget,
                clock=clock,
            ),
            ctx=ctx,
            output_class=output_class,
            clock=clock,
            meter=BusMeter(bus),
            compact_above_tokens=config.compact_above_tokens,
            keep_recent_messages=config.keep_recent_messages,
        )
        outcome = session.run()
        bus.record(
            agent_id,
            AgentStatus(outcome.kind.value),
            EventSource.WORKER,
            summary=outcome.summary,
        )
        outcome_path.write_text(outcome.model_dump_json())
        return 0
    except Exception as exc:
        LOGGER.exception("worker failed")
        failure = Failed(
            error=traceback.format_exc(),
            summary=str(exc)[:SUMMARY_CHARS],
            spent=Budget(turns=0, tool_calls=0),
        )
        outcome_path.write_text(failure.model_dump_json())
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
