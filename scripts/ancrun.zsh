#!/usr/bin/env zsh
# Runs ancalagon against Bedrock with a bearer token read straight from the file,
# never sourced: one malformed line in an .env silently drops every variable after
# it, and litellm then falls back to ~/.aws credentials that may be stale, which
# Bedrock reports as an invalid security token. Ambient AWS vars are also cleared,
# since they would take precedence over the bearer token.
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
