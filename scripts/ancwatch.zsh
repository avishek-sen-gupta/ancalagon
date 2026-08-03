#!/usr/bin/env zsh
# Tails every agent transcript under an ancalagon workspace, picking up runs and
# subagents as they appear. Safe to start before anything exists.
# Usage: ancwatch [workspace]      default ./output   e.g. ancwatch ws
ancwatch() {
  local root=${1:-output}
  local -A pids
  local f label from

  trap 'kill ${(v)pids} 2>/dev/null; return 130' INT

  # Anything already on disk is history: follow it from the end. Anything that
  # appears later is a new agent: show it from its first message.
  for f in $root/runs/*/tasks/*/transcript.jsonl(N); do
    pids[${${f:h:h:h}:t}/${${f:h}:t}]=0
  done

  print -u2 "\e[2m-- watching $root, ${#pids} existing agent(s) skipped --\e[0m"
  while :; do
    for f in $root/runs/*/tasks/*/transcript.jsonl(N); do
      label=${${f:h:h:h}:t}/${${f:h}:t}
      [[ -n ${pids[$label]} && ${pids[$label]} != 0 ]] && continue
      if [[ ${pids[$label]} == 0 ]]; then from="-n 0"; else from="-n +1"; fi
      tail ${=from} -f "$f" | jq -rj --unbuffered --arg n "$label" '
        "[36m[\($n)][0m ",
        (.role[0:1] | ascii_upcase), " ",
        ([.blocks[] |
           if   .kind == "text"     then (.text | gsub("\n"; " ") | .[0:110])
           elif .kind == "tool_use" then "→ \(.name) \(.arguments[0:70])"
           else "← \(if .is_error then "ERR " else "" end)\(.content | gsub("\n"; " ") | .[0:80])"
           end] | join(" | ")),
        "\n"' &
      pids[$label]=$!
      [[ $from == "-n +1" ]] && print -u2 "\e[2m-- $label --\e[0m"
    done
    sleep 1
  done
}

# Run the watcher when executed directly; define only when sourced.
[[ ${ZSH_EVAL_CONTEXT:-} == *:file* ]] || ancwatch "$@"
