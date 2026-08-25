#!/usr/bin/env zsh
# Renders an anccost report as a table, sizing every column to what is actually in it.
# Usage: anccost <config.toml | dir> | anctable [--by-agent]
#        anctable --input report.json [--output table.txt] [--by-agent]
# Decides nothing about what was measured, only how to show it.
set -uo pipefail

exec python3 -c '
import argparse
import json
import pathlib
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


parser = argparse.ArgumentParser(prog="anctable")
parser.add_argument("--input", default="", help="read here instead of stdin")
parser.add_argument("--output", default="", help="write here instead of stdout")
parser.add_argument("--by-agent", action="store_true", help="show each agent within a run")
asked = parser.parse_args()

source = pathlib.Path(asked.input).read_text() if asked.input else sys.stdin.read()
if not source.strip():
    sys.exit(1)  # anccost already said why, on stderr

report = json.loads(source)
by_agent = asked.by_agent
lines = []

rows = []
for run in report["runs"]:
    rows.append((run["run"], run))
    if by_agent:
        for agent in run["agents"]:
            rows.append((INDENT + str(agent["agent"]) + " " + agent["task"], agent))
rows.append(("TOTAL", report["total"]))

size = sized(rows)
heads = " ".join(head.rjust(size[field]) for field, head in COLUMNS)
lines.append(report["workspace"])
lines.append("RUN".ljust(size["label"]) + "  " + heads)
lines += [line(name, row, size) for name, row in rows[:-1]]
lines.append("-" * (size["label"] + 2 + len(heads)))
lines.append(line(rows[-1][0], rows[-1][1], size))

written = "\n".join(lines) + "\n"
if asked.output:
    pathlib.Path(asked.output).write_text(written)
else:
    sys.stdout.write(written)
' "$@"
