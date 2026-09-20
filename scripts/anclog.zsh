#!/usr/bin/env zsh
# Follows every run pushing to the configured log socket, whatever workspace they live in.
# Usage: anclog.zsh [socket-path]   (default /tmp/anc.sock, the path a config's [log] socket names)
# Binds the socket, so it removes a stale one first: start this before the run, and run only one
# of it per socket. A run whose [log] socket is unset, or that starts with nothing listening here,
# writes its transcripts and bus as usual and simply says nothing.
set -euo pipefail

socket=${1:-/tmp/anc.sock}
cut=${ANCLOG_RESULT_CHARS:-300}

rm -f "$socket"
print -u2 -- "-- listening on $socket, tool results cut at $cut chars --"

exec nc -lUk "$socket" | jq -r --argjson cut "$cut" '. as $e |
if .line.kind == "lifecycle"
then "[\($e.run)] agent \(.line.agent) \(.line.status)"
     + (if .line.summary == "" then "" else " — \(.line.summary)" end)
else .line.message as $m | $m.blocks[] |
  if .kind == "text" then "[\($e.run)] \($m.agent) \($m.role): \(.text)"
  elif .kind == "tool_use" then "[\($e.run)] \($m.agent) → \(.name) \(.arguments)"
  else "[\($e.run)] \($m.agent) ← " + (if .is_error then "ERR " else "" end)
       + (.content | gsub("\n"; " ⏎ ") | .[0:$cut])
  end
end'
