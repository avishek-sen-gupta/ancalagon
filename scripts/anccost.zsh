#!/usr/bin/env zsh
# What every run under an ancalagon workspace spent, read from each run's own bus.db,
# as JSON. Pipe it to anccosttable.zsh to read it, or to jq to slice it yourself.
# Usage: anccost [config.toml | dir] [--output report.json]   default . and stdout
# Given a config it reads that config's write_root, so the run and the reckoning cannot
# disagree. Given a directory it accepts either a workspace or a runs dir.
#
# There is no `ancalagon usage` verb on purpose: the schema is the query surface, and this
# is one rollup over it rather than the only one. It emits everything it found and decides
# nothing about how to show it, which is the same split as `ancalagon trace` and `viz`.
set -uo pipefail

exec python3 -c '
import argparse
import json
import pathlib
import sqlite3
import sys
import tomllib

TOTALS = """
select count(*), coalesce(sum(prompt_tokens), 0), coalesce(sum(completion_tokens), 0),
       coalesce(sum(cache_creation_tokens), 0), coalesce(sum(cache_read_tokens), 0)
from model_calls
"""
BY_AGENT = """
select m.agent, t.dir, count(*), sum(m.prompt_tokens), sum(m.completion_tokens),
       sum(m.cache_creation_tokens), sum(m.cache_read_tokens)
from model_calls m
join agents a on a.id = m.agent
join tasks t on t.id = a.task
group by m.agent order by m.agent
"""
FIELDS = ("calls", "prompt", "completion", "cache_creation", "cache_read")


def workspace(given: pathlib.Path) -> pathlib.Path:
    if not given.is_file():
        return given
    value = pathlib.Path(tomllib.loads(given.read_text())["workspace"]["write_root"]).expanduser()
    return value if value.is_absolute() else (given.resolve().parent / value).resolve()


def spent(db: pathlib.Path) -> dict[str, object]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        totals = dict(zip(FIELDS, conn.execute(TOTALS).fetchone()))
        agents = [
            {"agent": row[0], "task": pathlib.Path(row[1]).name, **dict(zip(FIELDS, row[2:]))}
            for row in conn.execute(BY_AGENT).fetchall()
        ]
    finally:
        conn.close()
    return {"run": db.parent.name, "path": str(db.parent), **totals, "agents": agents}


parser = argparse.ArgumentParser(prog="anccost")
parser.add_argument("workspace", nargs="?", default=".", help="a config.toml or a directory")
parser.add_argument("--output", default="", help="write here instead of stdout")
given = parser.parse_args()

root = workspace(pathlib.Path(given.workspace))
found = sorted({*root.glob("runs/*/bus.db"), *root.glob("*/bus.db")})
if not found:
    sys.exit(f"-- no run databases under {root} --")

runs = [spent(db) for db in found]
report = {
    "workspace": str(root),
    "runs": runs,
    "total": {f: sum(int(r[f]) for r in runs) for f in FIELDS},
}
written = json.dumps(report, indent=2) + "\n"
if given.output:
    pathlib.Path(given.output).write_text(written)
else:
    sys.stdout.write(written)
' "$@"
