#!/usr/bin/env zsh
# Runs ancalagon. Credentials come from the environment — litellm reads the appropriate
# provider vars (ANTHROPIC_API_KEY, AWS_BEARER_TOKEN_BEDROCK, AWS_ACCESS_KEY_ID, etc.).
# Usage: ancrun.zsh <config.toml> [run-dir]
# Allocates runs/r_YYYYMMDD-HHMMSS in UTC, or creates and continues the run directory given.
# Migration is a separate invocation so that a schema upgrade is never a side effect
# of starting a run; on an already-current database it is a no-op.
# The goal comes from the config's [run] goal_file.
set -euo pipefail

config=${1:?usage: ancrun.zsh <config.toml> [run-dir]}
named=()
if [[ -n ${2:-} ]]; then
  named=(--run-dir "$2")
fi

run_dir=$(uv run ancalagon init --config "$config" "${named[@]}")
uv run ancalagon migrate --db "$run_dir/bus.db"
print -u2 -- "-- run dir: $run_dir"

exec uv run ancalagon run --config "$config" --run-dir "$run_dir"
