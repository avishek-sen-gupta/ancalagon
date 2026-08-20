#!/usr/bin/env bash
# Refuses any Bash command that skips the pre-commit or pre-push hooks.
set -euo pipefail

command=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')

if printf '%s' "$command" | grep -qE '(--no-verify|(^|[;&|[:space:]])git[[:space:]]+commit([[:space:]]+[^;&|]*)?[[:space:]]-[a-zA-Z]*n)'; then
  cat >&2 <<'MSG'
BLOCKED: this command skips the pre-commit hooks.

--no-verify (and `git commit -n`) is not available in this repository. The hooks
are the contract: Talisman, Black, the Any/object ban, import-linter, Pyright and
the unit suite all run before a commit lands.

If a hook is failing, fix the cause or suppress it properly:
  - Talisman false positive -> reword the line, or add/replace the .talismanrc
    entry using the checksum Talisman itself reports (never one from shasum).
    Only the FIRST entry per filename is honoured: append for a new file,
    replace in place for a file already listed.
  - python-fp-lint on pre-existing debt -> the violations are still real. Raise
    them rather than bypassing; a commit that needs a bypass needs a decision.

Do not work around this by writing the commit another way.
MSG
  exit 2
fi
