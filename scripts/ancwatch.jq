# One transcript message as one line: agent, role, and its blocks, prose cut to $width.
"\u001b[36m[\($n)/\(.agent)]\u001b[0m ",
(.role[0:1] | ascii_upcase), " ",
([.blocks[] |
   if   .kind == "text"     then (.text | gsub("\n"; " ") | .[0:$width])
   elif .kind == "tool_use" then "→ \u001b[1;33m\(.name)\u001b[0m \(.arguments | gsub("\n"; " "))"
   else "← \(if .is_error then "\u001b[31mERR\u001b[0m " else "" end)\(.content | gsub("\n"; " ") | .[0:$width])"
   end] | join(" | ")),
"\n"
