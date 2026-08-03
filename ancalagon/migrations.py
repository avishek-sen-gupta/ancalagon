# Applies the paired SQL files, tracking schema version in PRAGMA user_version.
import pathlib
import sqlite3

DIRECTORY = pathlib.Path(__file__).parent / "migrations"


def user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def latest_version() -> int:
    return max(int(p.name.split("_", 1)[0]) for p in DIRECTORY.glob("*.up.sql"))


def _script(version: int, direction: str) -> pathlib.Path:
    matches = sorted(DIRECTORY.glob(f"{version:03d}_*.{direction}.sql"))
    if not matches:
        raise FileNotFoundError(f"no {direction} migration for version {version}")
    return matches[0]


def migrate(conn: sqlite3.Connection, target: int) -> None:
    current = user_version(conn)
    if target > current:
        versions = range(current + 1, target + 1)
        direction = "up"
    else:
        versions = range(current, target, -1)
        direction = "down"
    for version in versions:
        conn.executescript(_script(version, direction).read_text())
    conn.commit()
