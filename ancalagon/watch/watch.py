# A child that waits for a file to change, then ends. No model is involved, and the
# contract with the supervisor is the worker's: read spec.json, write outcome-<agent>.json.
import argparse
import pathlib
import sys
import traceback

from ancalagon.clock.clock import Clock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.outcome import SUMMARY_CHARS
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.contracts.watch_request import WatchRequest
from ancalagon.contracts.watched import Watched

NOTHING = Budget(turns=0, tool_calls=0)


def watch_for(request: WatchRequest, fs: FileSystem, clock: Clock) -> Watched:
    watched = pathlib.PurePath(request.path)
    while fs.mtime(watched) <= request.since:
        clock.sleep(request.poll_s)
    return Watched(path=request.path, at=fs.mtime(watched))


def _completed(task_dir: pathlib.PurePath, fs: FileSystem) -> Completed[Watched]:
    spec_text = fs.read_text(task_dir / "spec.json")
    request = AgentSpec[WatchRequest].model_validate_json(spec_text).input
    watched = watch_for(request, fs, SystemClock())
    return Completed(
        value=watched, summary=f"{watched.path} changed at {watched.at}", spent=NOTHING
    )


def main(task_dir: pathlib.PurePath, agent_id: int) -> int:
    fs = RealFileSystem()
    outcome_path = task_dir / f"outcome-{agent_id}.json"
    try:
        fs.write_text(outcome_path, _completed(task_dir, fs).model_dump_json())
        return 0
    except Exception as exc:
        failure = Failed(
            error=traceback.format_exc(), summary=str(exc)[:SUMMARY_CHARS], spent=NOTHING
        )
        fs.write_text(outcome_path, failure.model_dump_json())
        return 1


def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon.watch")
    parser.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    parser.add_argument("--dir", type=pathlib.PurePath, required=True)
    parser.add_argument("--agent-id", type=int, required=True)
    parser.add_argument("--config", type=pathlib.PurePath, required=True)
    args = parser.parse_args()
    return main(args.dir, args.agent_id)


if __name__ == "__main__":
    sys.exit(cli())
