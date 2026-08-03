import argparse
import logging
import pathlib
import sys

import pydantic

from ancalagon.bus.bus import Bus
from ancalagon.bus.depth_of import depth_of
from ancalagon.config.config import Config
from ancalagon.config.load import load_config
from ancalagon.contracts.input_json import input_json_of
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.resolve import resolve_output_class
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.llm.adapters.litellm_client import LiteLLMClient
from ancalagon.session import Session
from ancalagon.tools.delegate.check_task import CheckTask
from ancalagon.tools.delegate.collect_task import CollectTask
from ancalagon.tools.delegate.delegate import Delegate
from ancalagon.tools.files.delete_file import DeleteFile
from ancalagon.tools.files.edit_file import EditFile
from ancalagon.tools.files.list_dir import ListDir
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.files.write_file import WriteFile
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.parse.tree_sitter_tool import TreeSitter
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.search.ast_grep import AstGrep
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.search.sed import Sed
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
) -> Registry:
    available: list[Tool] = [
        ReadFile(),
        WriteFile(),
        EditFile(),
        DeleteFile(),
        ListDir(),
        Ripgrep(),
        AstGrep(),
        Sed(),
        TreeSitter(),
        Delegate(run_dir=run_dir, parent=parent),
        CheckTask(run_dir=run_dir),
        CollectTask(run_dir=run_dir),
        NeedInput(),
        SubmitAnswer(output_class),
    ]
    enabled = set(config.tools)
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
    bus = Bus.open(run_dir / "bus.db")
    try:
        spec_text = (task_dir / "spec.json").read_text()
        spec = TaskSpec.model_validate_json(spec_text)
        output_class = resolve_output_class(spec.output, task_dir)
        history = repair(load(transcript_path)) if transcript_path.exists() else []
        ctx = ToolContext(
            workspace=Workspace.from_config(config),
            output_dir=task_dir / "tools",
            summary_chars=config.summary_chars,
            agent_id=agent_id,
        )
        session = Session(
            spec=spec,
            input_json=input_json_of(spec_text),
            messages=history,
            transcript=log,
            agent_id=agent_id,
            llm=LiteLLMClient(model=config.model, max_tokens=config.max_tokens),
            registry=build_registry(
                config,
                run_dir,
                parent=agent_id,
                depth=depth_of(bus, agent_id),
                output_class=output_class,
            ),
            ctx=ctx,
            output_class=output_class,
        )
        outcome = session.run()
        outcome_path.write_text(outcome.model_dump_json())
        return 0
    except Exception as exc:
        LOGGER.exception("worker failed")
        failure = Failed(
            error=f"{type(exc).__name__}: {exc}",
            summary=str(exc)[:200],
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
