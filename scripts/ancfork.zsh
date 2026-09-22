#!/usr/bin/env zsh
# Starts a new run from an earlier one's root transcript, cut just before a chosen message.
# Usage: ancfork.zsh <config.toml> <from-run-dir> <at>
# <at> is the message number the fork replaces, as `ancalagon watch` and anclog.zsh print it
# after the agent: [run/task/agent#21] means --at 21. Everything before it is carried over.
# Credentials come from the environment, as they do for ancrun.zsh.
set -euo pipefail

config=${1:?usage: ancfork.zsh <config.toml> <from-run-dir> <at>}
from=${2:?usage: ancfork.zsh <config.toml> <from-run-dir> <at>}
at=${3:?usage: ancfork.zsh <config.toml> <from-run-dir> <at>}

run_dir=$(uv run ancalagon fork --config "$config" --from "$from" --at "$at")
uv run ancalagon migrate --db "$run_dir/bus.db"
print -u2 -- "-- forked $from at #$at into $run_dir"

exec uv run ancalagon run --config "$config" --run-dir "$run_dir"
