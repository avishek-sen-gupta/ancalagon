#!/usr/bin/env zsh
# Runs ancalagon against Bedrock with credentials taken from the environment: either
# AWS_BEARER_TOKEN_BEDROCK, or AWS_ACCESS_KEY_ID with AWS_SECRET_ACCESS_KEY.
# Whichever form is not in use is cleared, since litellm prefers the key pair over the
# bearer token and stale vars surface as an invalid security token rather than a missing one.
# Usage: AWS_BEARER_TOKEN_BEDROCK=... ancrun.zsh <config.toml> [run-dir]
#    or: AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... ancrun.zsh <config.toml> [run-dir]
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
if [[ -n ${AWS_BEARER_TOKEN_BEDROCK:-} ]]; then
  cleared=(-u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN
           -u AWS_PROFILE -u AWS_DEFAULT_PROFILE)
elif [[ -n ${AWS_ACCESS_KEY_ID:-} && -n ${AWS_SECRET_ACCESS_KEY:-} ]]; then
  cleared=(-u AWS_BEARER_TOKEN_BEDROCK)
else
  print -u2 -- "set AWS_BEARER_TOKEN_BEDROCK, or AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, in the environment before running"
  exit 1
fi

run_dir=$(uv run ancalagon init --config "$config" "${named[@]}")
uv run ancalagon migrate --db "$run_dir/bus.db"
print -u2 -- "-- run dir: $run_dir"

exec env "${cleared[@]}" AWS_REGION_NAME=${AWS_REGION_NAME:-us-east-1} \
  uv run ancalagon run --config "$config" --run-dir "$run_dir"
