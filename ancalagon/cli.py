# Parses arguments and dispatches to the command that carries out the run.
import argparse
import logging
import pathlib
import sys

from ancalagon.answer_command import answer_command
from ancalagon.clock.clock import Clock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.load import load_config
from ancalagon.contracts.no_outcome import NoOutcome
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.migrate_command import migrate_command
from ancalagon.note_command import note_command
from ancalagon.run import run
from ancalagon.trace_command import trace_command
from ancalagon.viz_command import viz_command

LOGGER = logging.getLogger(__name__)


def _allocated_run_dir(
    write_root: pathlib.PurePath, clock: Clock, fs: FileSystem
) -> pathlib.PurePath:
    runs = write_root / "runs"
    fs.mkdir(runs, parents=True, exist_ok=True)
    return runs / clock.now().strftime("r_%Y%m%d-%H%M%S")


def created_run_dir(
    run_dir: str, write_root: pathlib.PurePath, clock: Clock, fs: FileSystem
) -> pathlib.PurePath:
    if run_dir:
        named = pathlib.PurePath(run_dir)
        fs.mkdir(named, parents=True, exist_ok=True)
        return named
    allocated = _allocated_run_dir(write_root, clock, fs)
    fs.mkdir(allocated, parents=True)
    return allocated


def init_command(config_path: pathlib.PurePath, run_dir: str) -> int:
    fs = RealFileSystem()
    config = load_config(config_path, fs)
    sys.stdout.write(f"{created_run_dir(run_dir, config.write_root, SystemClock(), fs)}\n")
    return 0


def main(config_path: pathlib.PurePath, run_dir: pathlib.PurePath) -> int:
    logging.basicConfig(level=logging.INFO)
    fs = RealFileSystem()
    config = load_config(config_path, fs)
    try:
        produced = run(config, run_dir, config_path, SystemClock(), fs)
    except NoOutcome as exc:
        LOGGER.error("%s", exc)
        return 1
    sys.stdout.write(produced.model_dump_json() + "\n")
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--config", type=pathlib.PurePath, required=True)
    run_parser.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    init = commands.add_parser("init")
    init.add_argument("--config", type=pathlib.PurePath, required=True)
    init.add_argument("--run-dir", type=str, default="")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("--db", type=pathlib.PurePath, required=True)
    migrate.add_argument("--to", type=int, default=-1)
    answer = commands.add_parser("answer")
    answer.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    answer.add_argument("--task", type=int, required=True)
    answer.add_argument("--answer", type=str, required=True)
    note = commands.add_parser("note")
    note.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    note.add_argument("--agent", type=int, required=True)
    note.add_argument("--text", type=str, required=True)
    trace = commands.add_parser("trace")
    trace.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    trace.add_argument("--output", type=str, default="")
    viz = commands.add_parser("viz")
    viz.add_argument("--input", type=str, default="")
    viz.add_argument("--output", type=str, default="")
    args = parser.parse_args()
    try:
        if args.command == "init":
            return init_command(args.config, args.run_dir)
        if args.command == "migrate":
            return migrate_command(args.db, args.to, RealFileSystem())
        if args.command == "answer":
            return answer_command(args.run_dir, args.task, args.answer)
        if args.command == "note":
            return note_command(args.run_dir, args.agent, args.text)
        if args.command == "trace":
            return trace_command(args.run_dir, args.output, RealFileSystem())
        if args.command == "viz":
            return viz_command(args.input, args.output, RealFileSystem())
        return main(args.config, args.run_dir)
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        return 2


if __name__ == "__main__":
    sys.exit(cli())
