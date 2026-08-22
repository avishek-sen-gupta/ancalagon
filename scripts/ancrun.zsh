#!/usr/bin/env zsh
# Runs ancalagon against Bedrock with the bearer token taken from the environment.
# Ambient AWS credential vars are cleared, since litellm prefers them over the bearer
# token and stale ones surface as an invalid security token rather than as a missing one.
# Usage: AWS_BEARER_TOKEN_BEDROCK=... ancrun.zsh <config.toml> [run-dir]
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
: ${AWS_BEARER_TOKEN_BEDROCK:?set AWS_BEARER_TOKEN_BEDROCK in the environment before running}

run_dir=$(uv run ancalagon init --config "$config" "${named[@]}")
uv run ancalagon migrate --db "$run_dir/bus.db"
print -u2 -- "-- run dir: $run_dir"

exec env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \
         -u AWS_PROFILE -u AWS_DEFAULT_PROFILE \
         AWS_REGION_NAME=${AWS_REGION_NAME:-us-east-1} \
  uv run ancalagon run --config "$config" --run-dir "$run_dir"
