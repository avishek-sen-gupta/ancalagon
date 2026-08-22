# Applies the paired SQL files, tracking schema version in PRAGMA user_version.
import pathlib
import sqlite3

from ancalagon.fs.file_system import FileSystem

DIRECTORY = pathlib.Path(__file__).parent / "migrations"


def user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def latest_version(fs: FileSystem) -> int:
    return max(int(p.name.split("_", 1)[0]) for p in fs.glob(DIRECTORY, "*.up.sql"))


def _script(version: int, direction: str, fs: FileSystem) -> pathlib.Path:
    matches = fs.glob(DIRECTORY, f"{version:03d}_*.{direction}.sql")
    if not matches:
        raise FileNotFoundError(f"no {direction} migration for version {version}")
    return matches[0]


def migrate_file(path: pathlib.Path, target: int, fs: FileSystem) -> tuple[int, int]:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 5000")
    before = user_version(conn)
    migrate(conn, target, fs)
    return before, user_version(conn)


def migrate(conn: sqlite3.Connection, target: int, fs: FileSystem) -> None:
    current = user_version(conn)
    versions, direction = (
        (range(current + 1, target + 1), "up")
        if target > current
        else (range(current, target, -1), "down")
    )
    for version in versions:
        conn.executescript(fs.read_text(_script(version, direction, fs)))
    conn.commit()
