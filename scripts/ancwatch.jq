# One transcript message: header line, then each block on its own line.
"\u001b[36m[\($n)/\(.agent)]\u001b[0m \(.role[0:1] | ascii_upcase)\n",
(.blocks[] |
  if   .kind == "text"     then "  \(.text | gsub("\n"; "\n  ") | .[0:($width*4)])\n"
  elif .kind == "tool_use" then "  → \u001b[1;33m\(.name)\u001b[0m \(.arguments | gsub("\n";" ") | .[0:$width])\n"
  else "  ← \(if .is_error then "\u001b[31mERR\u001b[0m " else "" end)\(.content | gsub("\n";" ") | .[0:$width])\n"
  end)
