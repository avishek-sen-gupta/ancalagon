#!/usr/bin/env zsh
# Tails every agent transcript under an ancalagon workspace, picking up runs and
# subagents as they appear. Safe to start before anything exists.
# Usage: ancwatch [config.toml | dir]   default .
# Given a config it watches that config's write_root, so the run and the watcher
# cannot disagree. Given a directory it accepts either a workspace or a runs dir.
ancwatch() {
  local given=${1:-.}
  local root=$given
  local -A pids
  local f label from
  local filter=${${(%):-%x}:A:h}/ancwatch.jq
  local -i cols=${COLUMNS:-$(tput cols 2>/dev/null || print 110)}
  local -i frame=9 floor=20

  # Mirrors load_config: absolute stays absolute, ~ goes home, else relative to the file.
  if [[ -f $given ]]; then
    root=$(python3 -c '
import pathlib, sys, tomllib
cfg = pathlib.Path(sys.argv[1])
value = pathlib.Path(tomllib.loads(cfg.read_text())["workspace"]["write_root"]).expanduser()
print(value if value.is_absolute() else (cfg.resolve().parent / value).resolve())
' "$given" 2>/dev/null) || {
      print -u2 "\e[31m-- could not read write_root from $given --\e[0m"
      return 1
    }
    print -u2 "\e[2m-- write_root from $given: $root --\e[0m"
  fi

  trap 'kill ${(v)pids} 2>/dev/null; return 130' INT

  # Anything already on disk is history: follow it from the end. Anything that
  # appears later is a new agent: show it from its first message.
  transcripts() { print -l $root/runs/*/tasks/*/transcript.jsonl(N) $root/*/tasks/*/transcript.jsonl(N) }

  for f in $(transcripts); do
    pids[${${f:h:h:h}:t}/${${f:h}:t}]=0
  done

  if [[ ! -d $root/runs && -z $(print -l $root/*/tasks(N)) ]]; then
    print -u2 "\e[33m-- no runs under $root; is this the write_root from your config? --\e[0m"
  fi

  print -u2 "\e[2m-- watching $root at $cols columns, ${#pids} existing agent(s) skipped --\e[0m"

  # resolved-path → label: prevents two watchers on the same file via symlinks
  local -A resolved_paths

  while :; do
    for f in $(transcripts); do
      real=${f:A}
      label=${${f:h:h:h}:t}/${${f:h}:t}
      [[ -n ${resolved_paths[$real]} ]] && continue
      [[ -n ${pids[$label]} && ${pids[$label]} != 0 ]] && continue
      resolved_paths[$real]=$label
      if [[ ${pids[$label]} == 0 ]]; then from="-n 0"; else from="-n +1"; fi
      local -i width=$(( cols - ${#label} - frame ))
      (( width < floor )) && width=$floor
      tail ${=from} -f "$f" |
        jq -rj --unbuffered --arg n "$label" --argjson width $width -f $filter &
      pids[$label]=$!
      [[ $from == "-n +1" ]] && print -u2 "\e[2m-- $label --\e[0m"
    done
    sleep 1
  done
}

# Run the watcher when executed directly; define only when sourced.
[[ ${ZSH_EVAL_CONTEXT:-} == *:file* ]] || ancwatch "$@"
