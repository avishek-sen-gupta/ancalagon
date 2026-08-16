# Sandbox mode — design

## Why

The workspace already stops a tool from reading or writing outside its roots, but that check
lives in our own Python. A tool that forgets to call `resolve_read`, a `contracts.py` module
executed at import, or a subprocess that reads an argument as an option all sit outside it.
Two of those three have already happened: `write_output` wrote wherever it was pointed until
this week, and `rg --pre=<cmd>` executed arbitrary commands until the argv fix.

Sandbox mode puts a second check underneath, enforced by the kernel rather than by us. It is
not a replacement for `Workspace` — it is the thing that holds when `Workspace` is bypassed.

The read roots point at code the harness did not write. That is the harness's whole purpose,
and it is why the boundary matters more here than in a tool that only touches its own project.

## What was chosen, and what was rejected

**fence**, a Go binary from `fencesandbox/fence`, in Homebrew. It uses Seatbelt on macOS and
bubblewrap on Linux, with an HTTP/SOCKS5 proxy for network filtering.

Rejected, with reasons:

**Containers and VMs.** On macOS every container is a Linux VM underneath, so host Homebrew
binaries cannot execute inside one. The toolchain would have to be rebuilt in an image, and
the mounted roots would pay VM filesystem overhead. Stronger isolation than needed here.

**Writing our own bubblewrap and Seatbelt invocations.** This is what fence already is, and
what Anthropic's `srt` and `nono` also are. Three maintained implementations of the same
thing exist; a fourth is not warranted.

**`srt`.** The closest alternative and the most used, since Claude Code runs on it. Its
filesystem model is better on paper — `allowRead` takes precedence over `denyRead`, so
"deny everything, allow the roots" is expressible, which fence cannot do. It was not chosen
because it ships as npm and TypeScript, and because the restricted-read requirement it would
have satisfied was dropped.

**`nono`.** Uses Landlock on Linux rather than namespaces, so paths stay visible and merely
denied. No advantage here once reads are unrestricted.

## What the sandbox enforces

**Writes are confined to `write_root`.** This is the whole filesystem guarantee. It is the
same value `Workspace` enforces in-process, so the sandbox is a second check of a rule the
tools already apply, at a level they cannot skip.

**Reads are unrestricted.** Deliberate, and a reduction from the original requirement.

fence resolves `denyRead` in favour of denial when it overlaps `allowRead`, so denying a
parent kills its allowed children. Verified: with `denyRead: [<parent>]` and
`allowRead: [<parent>/readable]`, reading `<parent>/readable/a.txt` gave "Operation not
permitted". `denyRead: ["/"]` denies the shell itself and nothing runs at all. So "only the
roots are visible" is not expressible in fence, and enumerating every path to deny is not a
design.

Worth stating plainly: a sandboxed agent can read anything the user can. What it cannot do is
write outside `write_root` or reach an unlisted host.

**Network is deny-by-default with a domain allowlist**, carried in the config.

## Configuration

Two new fields, both derived into fence's config rather than duplicating it:

```toml
[model]
allowed_domains = ["bedrock-runtime.us-east-1.amazonaws.com"]

[sandbox]
enabled = true   # default; set false to spawn as before
```

`allowed_domains` becomes fence's `allowedDomains` unchanged. Nothing is derived from
`config.model`: mapping litellm's provider prefixes to endpoints would be a table to keep
current, and a wrong entry fails the first model call loudly rather than silently.

`write_root` becomes fence's `allowWrite`. The generated config is written into the run
directory beside `bus.db`, so a run records the policy it ran under.

Sandboxing is on by default because the safe path should be the one taken without thinking.
The escape hatch exists because fence may be absent, and because a run that needs it can say
so. There is no CI to accommodate; nothing runs in GitHub Actions today.

## Where it goes

`supervisor/subprocess_spawner.py`, which is already the only module that constructs a
process. `spawn()` prepends `fence -s <run_dir>/fence.json --` to the command it builds
today. The CLI, the supervisor and the bus stay outside: they are ours, and no agent runs in
them.

The spawner also clears `no_proxy` in the child's environment. Without that, loopback
bypasses fence's proxy and is then denied by Seatbelt — see below.

## Three findings from the spike, with evidence

**`uv run` fails inside the sandbox.** It writes to `~/.cache/uv`, which is outside
`write_root`: `failed to open file ~/.cache/uv/sdists-v9/.git: Operation not permitted`. This
does not matter, because `SubprocessSpawner` spawns `sys.executable`, the venv's Python,
which starts cleanly. It matters only if someone puts `uv run` on the spawn path later.

**Loopback needs `no_proxy` cleared.** `curl http://127.0.0.1:<port>` returned 000 even with
`127.0.0.1` in `allowedDomains`. The cause is visible with `-m`: fence sets `no_proxy` to
include `127.0.0.1`, so the request never reaches its proxy, and Seatbelt then refuses the
direct socket — `Immediate connect fail for 127.0.0.1: Operation not permitted`. With
`no_proxy` cleared and `127.0.0.1` allowed, the same request returned 200.

This is what lets a sandboxed run use a local model, and lets the scripted integration test
reach its stub server.

**Everything else worked unchanged.** `rg`, `ast-grep`, `jq`, `scc` and `ctags` all ran from
Homebrew; a write inside `write_root` succeeded; a write outside it was refused with
"Operation not permitted"; the allowed domain returned 405 from the real API while
`example.com` returned 000.

## What this does not do

**It does not restrict reads**, as above.

**It does not stop `contracts.py` executing.** A contract module is model-authored Python
imported by the worker, and it runs inside the sandbox like everything else. The sandbox
bounds what it can do — no writes outside `write_root`, no unlisted host — but does not stop
it running.

**It does not sandbox the CLI or the supervisor.** Both are ours and neither runs agent code.

**It is not tested on Linux.** Every result above is from macOS and Seatbelt. fence uses
bubblewrap on Linux, which gives absence rather than denial, so the guarantees should be at
least as strong — but "should be" is not "was observed", and the Linux path needs its own
pass before anyone relies on it.
