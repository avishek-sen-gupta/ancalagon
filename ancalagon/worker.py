# Entry point for one agent process: runs a single attempt at one task directory.
import argparse
import logging
import pathlib
import sys
import traceback

from ancalagon.bus.bus_meter import BusMeter
from ancalagon.bus.connect import connect
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.bus.meter_store import MeterStore
from ancalagon.children.bus_children import BusChildren
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.config.on_path import on_path
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.nothing import NOTHING
from ancalagon.contracts.outcome import SUMMARY_CHARS
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.letterbox.file_letterbox import FileLetterbox
from ancalagon.llm.adapters.litellm_client import LiteLLMClient
from ancalagon.schedule.depth_of import depth_of
from ancalagon.session_for import session_for
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.transcript.transcript import Transcript
from ancalagon.web.real_web_client import RealWebClient
from ancalagon.workspace.workspace import Workspace

LOGGER = logging.getLogger(__name__)


def main(
    run_dir: pathlib.PurePath,
    task_dir: pathlib.PurePath,
    agent_id: int,
    config_path: pathlib.PurePath,
) -> int:
    fs = RealFileSystem()
    web = RealWebClient()
    config = Config.model_validate_json(fs.read_text(config_path))
    on_path(config.import_paths)
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
        input_class = resolve_class(spec.role.input)
        given = AgentSpec[input_class].model_validate_json(spec_text).input
        ctx = ToolContext(
            workspace=Workspace.from_config(config, fs),
            task_dir=task_dir,
            summary_chars=config.summary_chars,
            agent_id=agent_id,
            input=given,
        )
        session = session_for(
            config,
            spec,
            ctx,
            log,
            run_dir,
            LiteLLMClient(
                model=config.model,
                max_tokens=config.max_tokens,
                num_retries=config.num_retries,
                request_timeout_s=config.request_timeout_s,
                custom_llm_provider=config.custom_llm_provider,
            ),
            clock,
            fs,
            web,
            bus=bus,
            children=BusChildren(bus, agent_id),
            letterbox=FileLetterbox(fs, task_dir),
            meter=BusMeter(meter_store),
            depth=depth_of(bus.snapshot(), agent_id),
        )
        outcome = session.run()
        fs.write_text(outcome_path, outcome.model_dump_json())
        return 0
    except Exception as exc:
        LOGGER.exception("worker failed")
        failure = Failed(
            error=traceback.format_exc(),
            summary=str(exc)[:SUMMARY_CHARS],
            spent=NOTHING,
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
