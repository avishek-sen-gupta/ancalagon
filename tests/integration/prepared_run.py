# Creates and migrates a run directory, as the startup script does before ancalagon run.
import pathlib

from ancalagon.migrations import latest_version, migrate_file


def prepared_run_dir(run_dir: pathlib.Path) -> pathlib.Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    migrate_file(run_dir / "bus.db", latest_version())
    return run_dir
