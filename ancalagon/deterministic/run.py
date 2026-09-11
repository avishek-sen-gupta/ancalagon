# A child that runs one Python function instead of a session. The contract with the
# supervisor is the worker's: read spec.json, write outcome-<agent>.json.
import argparse
import importlib
import pathlib
import sys
import traceback
import typing

import pydantic

from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.config.on_path import on_path
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.nothing import NOTHING
from ancalagon.contracts.outcome import SUMMARY_CHARS, Outcome
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.deterministic.run_context import RunContext
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem


@typing.runtime_checkable
class Run(typing.Protocol):
    def __call__(
        self, given: pydantic.BaseModel, ctx: RunContext
    ) -> Outcome[pydantic.BaseModel]: ...


def resolve_run(ref: FunctionRef) -> Run:
    found = getattr(importlib.import_module(ref.module), ref.name)
    if not isinstance(found, Run):
        raise ValueError(f"{ref.name} in {ref.module} is not callable")
    return found


def _outcome(
    run_dir: pathlib.PurePath,
    task_dir: pathlib.PurePath,
    agent_id: int,
    config_path: pathlib.PurePath,
    fs: FileSystem,
) -> Outcome[pydantic.BaseModel]:
    config = Config.model_validate_json(fs.read_text(config_path))
    on_path(config.import_paths)
    spec_text = fs.read_text(task_dir / "spec.json")
    spec = TaskSpec.model_validate_json(spec_text)
    input_class = resolve_class(spec.role.input)
    given = AgentSpec[input_class].model_validate_json(spec_text).input
    ctx = RunContext(
        fs=fs,
        clock=SystemClock(),
        task_dir=task_dir,
        run_dir=run_dir,
        agent_id=agent_id,
    )
    return resolve_run(spec.role.run)(given, ctx)


def main(
    run_dir: pathlib.PurePath,
    task_dir: pathlib.PurePath,
    agent_id: int,
    config_path: pathlib.PurePath,
) -> int:
    fs = RealFileSystem()
    outcome_path = task_dir / f"outcome-{agent_id}.json"
    try:
        produced = _outcome(run_dir, task_dir, agent_id, config_path, fs)
        fs.write_text(outcome_path, produced.model_dump_json())
        return 0
    except Exception as exc:
        failure = Failed(
            error=traceback.format_exc(), summary=str(exc)[:SUMMARY_CHARS], spent=NOTHING
        )
        fs.write_text(outcome_path, failure.model_dump_json())
        return 1


def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon.deterministic.run")
    parser.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    parser.add_argument("--dir", type=pathlib.PurePath, required=True)
    parser.add_argument("--agent-id", type=int, required=True)
    parser.add_argument("--config", type=pathlib.PurePath, required=True)
    args = parser.parse_args()
    return main(args.run_dir, args.dir, args.agent_id, args.config)


if __name__ == "__main__":
    sys.exit(cli())
