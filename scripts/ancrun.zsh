#!/usr/bin/env zsh
# Runs ancalagon against Bedrock with a bearer token, isolating the call from any
# stale AWS credentials in the environment, which Bedrock would otherwise reject.
# Reads AWS_BEARER_TOKEN_BEDROCK from $ANCALAGON_ENV (default ./.env).
# Usage: ANCALAGON_ENV=path/to/.env ancrun.zsh <config.toml> <goal...>
set -euo pipefail

local_env=${ANCALAGON_ENV:-.env}
config=${1:?usage: ancrun.zsh <config.toml> <goal...>}
shift
goal="$*"
[[ -n $goal ]] || { print -u2 "usage: ancrun.zsh <config.toml> <goal...>"; exit 2 }

token=$(grep -m1 '^AWS_BEARER_TOKEN_BEDROCK=' "$local_env" | cut -d= -f2- | tr -d '"'"'"'')
[[ -n $token ]] || { print -u2 "no AWS_BEARER_TOKEN_BEDROCK in $local_env"; exit 1 }

exec env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \
         -u AWS_PROFILE -u AWS_DEFAULT_PROFILE \
         AWS_REGION_NAME=${AWS_REGION_NAME:-us-east-1} \
         AWS_BEARER_TOKEN_BEDROCK="$token" \
  uv run ancalagon run --config "$config" --goal "$goal"
