#!/usr/bin/env zsh
# Follows every run pushing to the configured log socket, whatever workspace they live in.
# Usage: anclog.zsh [socket-path]   (default /tmp/anc.sock, the path a config's [log] socket names)
# Colours follow `ancalagon watch`: cyan for whose line it is, bold yellow for a tool, red for ERR.
# Binds the socket, so it removes a stale one first: start this before the run, and run only one
# of it per socket. A run whose [log] socket is unset, or that starts with nothing listening here,
# writes its transcripts and bus as usual and simply says nothing.
set -euo pipefail

socket=${1:-/tmp/anc.sock}
cut=${ANCLOG_RESULT_CHARS:-300}

rm -f "$socket"
print -u2 -- "-- listening on $socket, tool results cut at $cut chars --"

exec nc -lUk "$socket" | jq -r --unbuffered --argjson cut "$cut" '
def cyan: "\u001b[36m" + . + "\u001b[0m";
def yellow: "\u001b[1;33m" + . + "\u001b[0m";
def red: "\u001b[31m" + . + "\u001b[0m";
def green: "\u001b[32m" + . + "\u001b[0m";
def magenta: "\u001b[35m" + . + "\u001b[0m";
def dim: "\u001b[2m" + . + "\u001b[0m";
def statused:
  if . == "completed" or . == "collected" then green
  elif . == "crashed" or . == "failed" or . == "timed_out" or . == "exhausted" then red
  elif . == "needs_input" or . == "idling" then magenta
  elif . == "running" then yellow
  else dim end;
. as $e |
if .line.kind == "lifecycle"
then ("[\($e.run)/\($e.task)/\(.line.agent)]" | cyan) + " " + (.line.status | statused)
     + (if .line.summary == "" then "" else " " + (.line.summary | dim) end)
else .line.message as $m | ("[\($e.run)/\($e.task)/\($m.agent)#\($m.seq)]" | cyan) as $who | $m.blocks[] |
  if .kind == "text" then $who + " " + ($m.role[0:1] | ascii_upcase | dim) + " \(.text)"
  elif .kind == "tool_use" then $who + " " + ("→" | dim) + " " + (.name | yellow)
       + " " + (.arguments | gsub("\n"; " "))
  else $who + " " + ("←" | dim) + " " + (if .is_error then ("ERR" | red) + " " else "" end)
       + (.content | gsub("\n"; " ⏎ ") | if $cut > 0 then .[0:$cut] else . end | dim)
  end
end'
