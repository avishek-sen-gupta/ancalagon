# One transcript message as one line: agent, role, and its blocks, prose cut to $width.
"\u001b[36m[\($n)/\(.agent)]\u001b[0m ",
(.role[0:1] | ascii_upcase), " ",
([.blocks[] |
   if   .kind == "text"     then (.text | gsub("\n"; " ") | .[0:$width])
   elif .kind == "tool_use" then "→ \(.name) \(.arguments | gsub("\n"; " "))"
   else "← \(if .is_error then "ERR " else "" end)\(.content | gsub("\n"; " ") | .[0:$width])"
   end] | join(" | ")),
"\n"
