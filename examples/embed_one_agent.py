# One agent inside a host program: a Config built in Python, no supervisor and no database.
import collections.abc
import pathlib
import sys
import tempfile

from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.contracts.allowance import Finite
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.role import Role
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.llm.adapters.litellm_client import LiteLLMClient
from ancalagon.session_for import session_for
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.transcript.transcript import Transcript
from ancalagon.web.real_web_client import RealWebClient
from ancalagon.workspace.workspace import Workspace

MODEL = "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"

ANALYST = Role(
    behaviour=(
        "You are given a directory of short notes. Read them, work out which one contradicts "
        "the others, and submit an answer naming that file and the contradiction in one or two "
        "sentences. Use list_dir and read_file. Do not answer without reading."
    ),
    tools=("list_dir", "read_file", "submit_answer"),
    budget=Budget(turns=Finite(value=12), tool_calls=Finite(value=20)),
)

NOTES: collections.abc.Mapping[str, str] = {
    "alpha.md": "The deploy window is Tuesday 02:00 UTC. Rollback takes nine minutes.",
    "beta.md": "Rollback takes nine minutes, so the Tuesday 02:00 UTC window is sufficient.",
    "gamma.md": "Rollback takes forty minutes; the Tuesday 02:00 UTC window cannot absorb it.",
    "delta.md": "Deploys are frozen during quarter close. Tuesday 02:00 UTC is the next window.",
}


def _notes_in(fs: FileSystem, write_root: pathlib.PurePath) -> pathlib.PurePath:
    notes = write_root / "notes"
    fs.mkdir(notes, parents=True, exist_ok=True)
    for name, text in NOTES.items():
        fs.write_text(notes / name, text + "\n")
    return notes


def _config_for(write_root: pathlib.PurePath) -> Config:
    return Config(
        write_root=write_root,
        read_roots=(write_root,),
        model=MODEL,
        roles={"analyst": ANALYST},
    )


def _say(label: str, value: str) -> None:
    sys.stdout.write(f"{label:<10}: {value}\n")


def main() -> int:
    root = pathlib.PurePath(tempfile.mkdtemp(prefix="anc-embed-"))
    fs = RealFileSystem()
    write_root = root / "ws"
    task_dir = write_root / "tasks" / "analyst"
    fs.mkdir(task_dir, parents=True, exist_ok=True)
    notes = _notes_in(fs, write_root)

    config = _config_for(write_root)
    given = FreeText(text=f"The notes are in {notes}. Which one contradicts the others?")
    spec = TaskSpec(task_id="analyst", role=ANALYST, goal=f"Examine the notes in {notes}.")
    ctx = ToolContext(
        workspace=Workspace.from_config(config, fs),
        task_dir=task_dir,
        summary_chars=config.summary_chars,
        agent_id=1,
        input=given,
    )
    transcript = Transcript(fs, path=task_dir / "transcript.jsonl", agent_id=1)

    _say("model", MODEL)
    _say("workspace", str(write_root))

    try:
        session = session_for(
            config,
            spec,
            ctx,
            transcript,
            root / "runs" / "analyst",
            LiteLLMClient(
                model=config.model,
                max_tokens=config.max_tokens,
                num_retries=config.num_retries,
                request_timeout_s=config.request_timeout_s,
            ),
            SystemClock(),
            fs,
            RealWebClient(),
        )
        _say("offered", ", ".join(sorted(session.registry.names())))
        outcome = session.run()
    finally:
        transcript.close()

    _say("outcome", type(outcome).__name__)
    _say("summary", outcome.summary)
    _say("spent", str(outcome.spent))
    _say("databases", str(sorted(str(p) for p in pathlib.Path(root).rglob("bus.db"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
