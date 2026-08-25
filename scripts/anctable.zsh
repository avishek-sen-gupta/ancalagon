#!/usr/bin/env zsh
# Renders an anccost report as a table, sizing every column to what is actually in it.
# Usage: anccost <config.toml | dir> | anctable [--by-agent]
# Reads the JSON on stdin and decides nothing about what was measured, only how to show it.
set -uo pipefail

exec python3 -c '
import json
import sys

COLUMNS = (("calls", "CALLS"), ("prompt", "PROMPT"), ("completion", "OUT"), ("cache_read", "CACHED"))
INDENT = "  "


def grouped(count):
    return format(int(count), ",")


def sized(rows):
    size = {"label": max(len(name) for name, _ in rows)}
    for field, head in COLUMNS:
        size[field] = max([len(head)] + [len(grouped(row[field])) for _, row in rows])
    return size


def line(name, row, size):
    cells = " ".join(grouped(row[field]).rjust(size[field]) for field, _ in COLUMNS)
    return name.ljust(size["label"]) + "  " + cells


given = sys.stdin.read().strip()
if not given:
    sys.exit(1)  # anccost already said why, on stderr

report = json.loads(given)
by_agent = "--by-agent" in sys.argv

rows = []
for run in report["runs"]:
    rows.append((run["run"], run))
    if by_agent:
        for agent in run["agents"]:
            rows.append((INDENT + str(agent["agent"]) + " " + agent["task"], agent))
rows.append(("TOTAL", report["total"]))

size = sized(rows)
heads = " ".join(head.rjust(size[field]) for field, head in COLUMNS)
print(report["workspace"])
print("RUN".ljust(size["label"]) + "  " + heads)
for name, row in rows[:-1]:
    print(line(name, row, size))
print("-" * (size["label"] + 2 + len(heads)))
print(line(rows[-1][0], rows[-1][1], size))
' "$@"
