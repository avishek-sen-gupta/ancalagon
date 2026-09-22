# Several write roots

## The problem

A config names one `write_root`, and it does two unrelated jobs:

1. **Where agents may write.** `Workspace.resolve_write` checks against it, the fence sandbox
   allows writes there, and the system prompt tells the model "You may write under: …".
2. **The harness's home.** Run directories are allocated under `<write_root>/runs`, and `watch`
   globs it for transcripts.

An agent that must write in more than one place — a scratch area and a checkout it annotates,
say — cannot, because the only way to widen job 1 is to move job 2 with it.

## What this is not

**Not hardening.** Agents can write anywhere under the home today, including `bus.db` and other
tasks' transcripts. This change keeps that exactly as it is. Making the home readable by agents
but written only by the harness is a separate change, recorded as a known limitation in
`docs/architecture.md` so it is not forgotten.

**Not per role.** Every agent in a run sees the same roots.

## Design

### The config splits the two jobs

Under `[workspace]`, `write_root` is replaced by two keys:

```toml
[workspace]
home = "./ws"
write_roots = ["./ws", "./annotations"]
read_roots = [".", "./src"]
```

- `home` holds `runs/` and is what `watch` reads. One directory.
- `write_roots` is where agents may write. It may be empty.

`Config` replaces `write_root: PurePath` with `home: PurePath` and
`write_roots: tuple[PurePath, ...] = ()`. Both are resolved against the config file's directory
exactly as `write_root` was.

A config that still names `write_root` is refused at load with:
`[workspace] write_root was split into home (where runs live) and write_roots (where agents may
write)`. There is no fallback reading of the old key.

The shipped configs — `ancalagon.toml`, `ancalagon.example.toml`, `research.toml`,
`blackboard.toml` — are migrated, each with a TOML comment saying what the two keys are and that
they replace `write_root`.

### The workspace takes several write roots

`Workspace(fs, write_roots, read_roots)`. `resolve_write` accepts a path under any write root and
refuses one outside all of them, naming every root in the error. `from_config` passes
`(*config.write_roots, config.home)` as the write roots and
`(*config.read_roots, *config.write_roots, config.home)` as the read roots, so the home is an
implicit write root — which is what keeps tool outputs under `<home>/runs/.../outputs` writable
by the harness and readable through their `[full output: …]` pointers.

### The sandbox allows every root

`Fence` takes the write roots and the home and lists each, plus the run directory, in
`allowWrite`.

### The model is told every root

The system prompt lists every root the workspace may write under. Tool descriptions say "a write
root" instead of "the workspace write root".

### The harness uses the home

`cli.py` allocates runs under `config.home`, `watch_command.py` reads `config.home` and its hint
asks "is this the home?", and `check_contracts` uses `config.home` where it passed `write_root`.

## Testing

- The workspace test: a path under either of two write roots is written; a path outside both is
  refused, and the error names both.
- The config load test: `home` and `write_roots` load resolved against the file's directory; a
  config naming `write_root` is refused with the message above.
- The fence test: the policy's `allowWrite` lists every write root, the home and the run
  directory.
- Every other reference to `write_root` in the tests is a rename to `home`, or to `write_roots`
  where the test is about agent scope.

## Commits

One. `Config` cannot be half renamed and still type-check, so the field split, the workspace,
the sandbox, the prompt, the configs, the docs and the test rename land together.
