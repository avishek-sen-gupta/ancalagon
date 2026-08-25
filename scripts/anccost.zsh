#!/usr/bin/env zsh
# What every run under an ancalagon workspace spent, read from each run's own bus.db.
# Usage: anccost [config.toml | dir] [--by-agent]   default .
# Given a config it reads that config's write_root, so the run and the reckoning cannot
# disagree. Given a directory it accepts either a workspace or a runs dir.
#
# There is no `ancalagon usage` verb on purpose: the schema is the query surface, and this
# is one rollup over it rather than the only one. cache_read is shown apart from prompt
# because a cached token is not billed as a fresh one.
set -uo pipefail

local given=${1:-.}
local by_agent=""
[[ ${2:-} == --by-agent || $given == --by-agent ]] && by_agent=1
[[ $given == --by-agent ]] && given=.

local root=$given
if [[ -f $given ]]; then
  root=$(python3 -c '
import pathlib, sys, tomllib
cfg = pathlib.Path(sys.argv[1])
value = pathlib.Path(tomllib.loads(cfg.read_text())["workspace"]["write_root"]).expanduser()
print(value if value.is_absolute() else (cfg.resolve().parent / value).resolve())
' "$given" 2>/dev/null) || {
    print -u2 "\e[31m-- could not read write_root from $given --\e[0m"
    exit 1
  }
fi

local -a found
found=(${~root}/runs/*/bus.db(N) ${~root}/*/bus.db(N))
if (( ${#found} == 0 )); then
  print -u2 "\e[31m-- no run databases under $root --\e[0m"
  exit 1
fi

local db run calls sent got cached
local -i all_calls=0 all_prompt=0 all_completion=0 all_cached=0

printf "%-24s %6s %11s %11s %11s\n" RUN CALLS PROMPT COMPLETION CACHE_READ
for db in $found; do
  run=${db:h:t}
  IFS=' ' read -r calls sent got cached <<<"$(sqlite3 -separator ' ' "$db" "
    select count(*), coalesce(sum(prompt_tokens), 0),
           coalesce(sum(completion_tokens), 0), coalesce(sum(cache_read_tokens), 0)
    from model_calls")"
  printf "%-24s %6s %11s %11s %11s\n" "$run" "$calls" "$sent" "$got" "$cached"
  (( all_calls += calls, all_prompt += sent, all_completion += got, all_cached += cached ))

  if [[ -n $by_agent ]]; then
    sqlite3 -separator '|' "$db" "
      select m.agent, replace(t.dir, '${db:h}/tasks/', ''), count(*),
             sum(m.prompt_tokens), sum(m.completion_tokens), sum(m.cache_read_tokens)
      from model_calls m
      join agents a on a.id = m.agent
      join tasks t on t.id = a.task
      group by m.agent order by m.agent" |
      while IFS='|' read -r agent task n p c r; do
        printf "  agent %-4s %-16s %5s %11s %11s %11s\n" "$agent" "$task" "$n" "$p" "$c" "$r"
      done
  fi
done

printf "%-24s %6s %11s %11s %11s\n" TOTAL "$all_calls" "$all_prompt" "$all_completion" "$all_cached"
