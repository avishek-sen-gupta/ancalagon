# A config without a file

## The problem

A caller that generates its settings — a service starting many runs, each with a different model,
roots or goal — has three routes today, and none fits a caller outside the process.

1. **Import `ancalagon` and construct `Config` in code.** Documented under "Starting a run from
   Python". Works, and stays. But it makes the caller take on the dependency, its Python version
   and its transitive tree, for the sake of naming a handful of values.
2. **`Config.model_validate_json`,** also documented in `README.md`. A `Config` is a Pydantic model,
   so a JSON route to it already exists — but only in-process, because **no CLI command accepts
   it.** `run` and `init` take `--config`, a TOML path, and nothing else.
3. **Write a temporary TOML file and pass `--config`.** Works, but the caller must template TOML
   and own the file's lifetime. In any language but Python that means shipping a TOML writer to
   describe values it already holds as data.

So the gap is narrower than "ancalagon cannot take JSON": it is that nothing on the command line
takes a document, and the only JSON shape that exists is the wrong one to ask a caller for (see
*What this is not*).

There is a second problem sitting inside the first. `load.py` reads the TOML document by
bracket-indexing the dict `tomllib` returns, which is the one place in the codebase that breaks
the boundary rule in `CLAUDE.md`: *anything read from a JSON file becomes a model immediately;
never index a parsed dict.* `[roles.*]` already goes through `RawRole`; `workspace`, `model`,
`limits`, `run` and `sandbox` do not. Finishing that job is what makes a second reader cost ten
lines instead of a fork of the loader.

## What this is not

**Not an overlay.** A caller supplies the whole document. There is no merging of a base TOML with
caller-supplied values, no precedence order between them, and so no question of whether an
overlaid list replaces or extends the one beneath it.

**Not a server.** The document arrives on stdin, one run per invocation. Nothing becomes
long-lived, and there is no port, no auth and no lifecycle to own.

**Not a second format for TOML files.** `ancalagon.toml`, `ancalagon.example.toml` and the files
under `examples/` stay TOML and are read exactly as they are now. The JSON route exists for
callers that have no file, not as an alternative spelling for callers that do.

**Not a key-value override language.** No `--set model.name=…`. Settings are not addressed by
dotted strings on argv, because that encodes structure in a string and defers the contract the
model already states.

**Not a widening of `--config`.** That flag takes a TOML path and only a TOML path. The JSON route
gets its own flag.

**Not `Config` JSON, and not a removal of `Config.model_validate_json`.** Two JSON shapes exist
after this change and they serve different callers:

| | `Config` JSON | `RawConfig` JSON |
|---|---|---|
| Who writes it | a host that already imports ancalagon; `run_dir/config.json`, written per run | a caller with no dependency on ancalagon |
| Paths | absolute, resolved | relative to `base`, or absolute |
| A budget | `{"turns": {"value": 12}}` — the `Finite`/`Infinite` union | `{"turns": 12}` or `{"turns": "infinite"}` |
| Checked by | Pydantic field types only | Pydantic **and** `_role` — the role-name regex, the run/input/answer exclusion |
| Route | `Config.model_validate_json`, unchanged | `--config-json` on stdin, new |

`--config-json` takes the second. Accepting the first would be a one-line change, and is rejected
deliberately: it would freeze `Finite`/`Infinite`'s nesting as a public wire format, and it skips
every check `_role` performs. `ancalagon.example.toml` documents the document's shape at length;
`Config`'s field layout is an internal representation that happens to serialise. The new flag
exposes the contract, not the representation.

## Design

### The document becomes a model

New `ancalagon/config/raw_config.py` states the TOML document as it is written, beside the
`RawRole` that already exists:

```python
class RawWorkspace(pydantic.BaseModel, frozen=True):
    home: str
    write_roots: list[str]
    read_roots: list[str]


class RawModel(pydantic.BaseModel, frozen=True):
    name: str
    custom_llm_provider: str = ""
    num_retries: int
    request_timeout_s: int
    max_tokens: int
    allowed_domains: list[str]


class RawLimits(pydantic.BaseModel, frozen=True):
    max_concurrent_agents: int
    agent_timeout_s: int
    max_depth: int
    compact_above_tokens: int
    keep_recent_messages: int
    summary_chars: int


class RawRun(pydantic.BaseModel, frozen=True):
    goal_file: str
    input_file: str
    role: str


class RawSandbox(pydantic.BaseModel, frozen=True):
    strategy: Strategy


class RawLog(pydantic.BaseModel, frozen=True):
    socket: str = ""


class RawWeb(pydantic.BaseModel, frozen=True):
    allowed_domains: list[str] = []


class RawConfig(pydantic.BaseModel, frozen=True):
    workspace: RawWorkspace
    model: RawModel
    limits: RawLimits
    run: RawRun
    sandbox: RawSandbox
    base: str = ""
    log: RawLog = RawLog()
    web: RawWeb = RawWeb()
    roles: dict[str, RawRole] = {}
```

Every key `load.py` reads by bracket is a required field with no default, so an incomplete document
is refused exactly as it is today. The comment in `load.py` explaining why nothing uses `.get()`
becomes the field declarations themselves. One thing improves: Pydantic reports every missing key
at once, where the current loader fails on the first `KeyError` and hides the rest.

Every key it reads with `.get()` — `custom_llm_provider`, `log`, `web`, `roles` — carries the same
default it carries now.

Extra keys stay ignored, as they are today, so `RawWorkspace` never sees a `write_root` key to
object to. The `SPLIT_WRITE_ROOT` check therefore **stays in `load_config`**, as a membership test
on the parsed mapping before it is handed to `model_validate`:

```python
if "write_root" in document.get("workspace", {}):
    raise ValueError(SPLIT_WRITE_ROOT)
```

Two things about that. It is a membership test, not an extraction — the document still goes to
`model_validate` whole and nothing reads a value out of it, so the boundary rule holds. And
`.get("workspace", {})` rather than `["workspace"]` is deliberate: a document with no `[workspace]`
table at all should be reported by Pydantic alongside every other missing key, not by a `KeyError`
from this check.

Keeping it in the TOML reader is correct scoping rather than a compromise. The message exists for
someone migrating a config written before the split; a JSON caller is new and has no old file to
migrate, so `write_root` is simply a key it never had.

A `model_validator(mode="before")` on `RawWorkspace` would see the key and could serve both
readers, but its parameter cannot be typed — the value Pydantic hands a before-validator is
arbitrary, which means `object` or `Any`, and `CLAUDE.md` bans both outright.

`strategy` is typed `Strategy` rather than `str`, so the enum validates the value where it is
declared instead of `Strategy(...)` raising further along. The message a bad strategy produces
changes; `test_config_load.py` states what it asserts.

### The reader splits from the resolution

New `ancalagon/config/from_raw.py` holds `config_from(raw, base, fs) -> Config`, and with it
`_root`, `_optional_root`, `_run_settings`, `_class_ref`, `_hooks`, `_contracts`, `_allowance` and
`_role`, all unchanged, plus the `on_path` call that must precede role resolution.

**This is not a functional core, and the spec should not pretend otherwise.** `_contracts` calls
`run_contracts`, which imports the module a role names, and `on_path` mutates `sys.path` so that
import resolves. Both are shell, they are inseparable, and they were shell before this change.
What the split buys is not purity — it is a single place where a document becomes a `Config`,
so a second source of documents adds a caller instead of a copy.

`load.py` is then the TOML reader and nothing else:

```python
def load_config(path: pathlib.PurePath, fs: FileSystem) -> Config:
    document = tomllib.loads(fs.read_text(path))
    if "write_root" in document.get("workspace", {}):
        raise ValueError(SPLIT_WRITE_ROOT)
    raw = RawConfig.model_validate(document)
    if raw.base:
        raise ValueError(TOML_STATES_NO_BASE)
    return config_from(raw, fs.resolve(path).parent, fs)
```

The dict `tomllib` returns is handed straight to `model_validate` and never indexed. That is the
single permitted hop: text in, instance out, at the boundary where the text arrives.

### The document carries its own base

A TOML file's location supplies two things nothing in the file states: relative paths resolve
against the file's directory, and that directory goes on `sys.path` so `{module =
"checkkit.checks"}` imports. `ancalagon.example.toml` says the first outright — "Paths are
resolved relative to THIS file, not the working directory."

A document read from stdin has no location, so it declares one: `RawConfig.base: str = ""`.

Neither reader ignores the field, because a declared field that one reader silently drops is worse
than an undeclared one:

- `load_config` refuses a non-empty `base`. A file's own directory is better information than a
  field sitting beside it, and quietly preferring one would hide the disagreement rather than
  report it.
- `config_from_json` refuses an empty one. There is nothing else it could fall back to except the
  spawner's working directory, which would make correctness depend on where the caller happened to
  be standing and would fail late, as an unresolvable `read_root` or an `ImportError` on a role.

Relative paths then behave identically under both readers, and `Config.import_paths` stays
`(base,)` as it is now. One mechanism, two sources.

### Stdin is the transport

New `ancalagon/config/from_json.py`:

```python
def config_from_json(document: str, fs: FileSystem) -> Config:
    raw = RawConfig.model_validate_json(document)
    if not raw.base:
        raise ValueError(JSON_STATES_ITS_BASE)
    base = fs.expanduser(pathlib.PurePath(raw.base))
    if not base.is_absolute():
        raise ValueError(BASE_IS_ABSOLUTE.format(base=base))
    if not fs.is_dir(base):
        raise ValueError(BASE_IS_A_DIRECTORY.format(base=base))
    return config_from(raw, fs.resolve(base), fs)
```

Those three refusals are boundary validation on a document from outside the process, in the same
class as `_role`'s role-name regex — not the defensive `None`-checking `docs/guidelines/design-principles.md`
prohibits, which is about internal call sites disagreeing.

The absolute check is what keeps the cwd out. A relative `base` would resolve against wherever the
caller happened to be standing, which is exactly the implicit state declaring `base` was meant to
remove, and it would fail late as an unresolvable `read_root`. The directory check turns a typo in
the anchor into one message at load instead of an `ImportError` on a role or a failed read much
further along.

Because `ancalagon schema` shows the caller `RawConfig`, `base` carries a `description` on its
field so the constraint is visible before the first spawn rather than after it — the principle in
`docs/guidelines/refactoring.md` that a constraint belongs where the caller can see it:

```python
base: str = pydantic.Field(
    default="",
    description="Absolute directory relative paths resolve against, and the import anchor "
    "for dotted module refs. Required for a document on stdin; refused in a TOML file, "
    "whose own directory is used.",
)
```

`run` and `init` gain `--config-json`: a flag with no value, meaning "the document is on stdin", in
a mutually exclusive group with `--config` — the shape the `watch` parser already uses for
`--config`/`--dir`. There is no path to give, because there is no file.

`fork` and `watch` keep taking TOML only. No caller asks otherwise yet.

What a caller does, importing nothing:

```python
doc = json.dumps({"base": str(anchor), "workspace": {...}, "model": {...},
                  "limits": {...}, "run": {...}, "sandbox": {...}})
spawned = subprocess.run(["ancalagon", "init", "--config-json"], input=doc, ...)
run_dir = spawned.stdout.strip()
subprocess.run(["ancalagon", "migrate", "--db", f"{run_dir}/bus.db"])
subprocess.run(["ancalagon", "run", "--config-json", "--run-dir", run_dir], input=doc)
```

Three spawns, the same sequence `scripts/ancrun.zsh` already runs; the document is piped to two of
them, since each invocation has its own stdin. A role naming a dotted ref still needs that module
importable by ancalagon's interpreter, which is what `base` is for — a caller using built-in tools
and prose roles names no modules and the anchor does nothing but resolve its relative paths.

### The contract is printable

`ancalagon schema` writes `RawConfig.model_json_schema()` to stdout: field names, types, which keys
are required, `Strategy`'s values, and `RawRole`'s shape under `$defs`. That is enough for a caller
in any language to generate a document and validate it before spawning, which is the difference
between an interface and one reverse-engineered from error messages.

The `json.dumps` on that line is a boundary write to stdout, the same as `main`'s
`model_dump_json` — not a JSON value carried through a pipeline.

## Testing

1. **The refactor extends `test_config_load.py`** rather than adding a file, per the bug-fix rule
   in `docs/guidelines/testing-patterns.md`. Missing keys are reported together; `write_root` still
   raises `SPLIT_WRITE_ROOT`; a bad `strategy` is still refused; a TOML file naming `base` is
   refused with `TOML_STATES_NO_BASE`.
2. **`tests/unit/test_config_from_json.py`, one behaviour.** A document with two roles, a typed
   input and answer, a `run` ref, before- and after-hooks and relative paths produces a `Config`
   **equal to** the one `load_config` builds from the equivalent TOML file — the TOML file written
   into the directory the JSON document names as its `base`, so both readers resolve the same
   relative paths against the same anchor. Asserting equality of the two `Config` values is the
   point of the test: it says the readers agree, and it fails if either drifts. The empty-`base`
   refusal goes in the same test.
3. **`tests/integration`**: `ancalagon run --config-json` with a document on stdin completes a run
   and writes an outcome. The verification step runs `tests/integration` whole — it takes about
   forty seconds, and two plans in a row let a regression through by narrowing it.
4. **Mutation-check both new tests before trusting them.** Break `config_from` so `base` is
   ignored, and break `--config-json` so it reads argv instead of stdin. A test written after the
   code is a hypothesis until it has failed once.
5. **The schema test**: `ancalagon schema` writes something that parses, whose top-level `required`
   is exactly the five tables `load_config` demands.

## Commits

Three, in this order.

1. **`RawConfig` and `from_raw.py`.** No new capability. `load_config` keeps its signature, so
   nothing outside `ancalagon/config` changes, and the diff reads as one question: is this the same
   document, stated as a model? Error messages change; the tests say how.
2. **`config_from_json` and `--config-json`.** The new route, `base`'s two rules, the unit
   behaviour and the integration test. `README.md` and `docs/architecture.md` gain the JSON route
   in this commit, not after it.
3. **`ancalagon schema`.** Separately revertible — the route works without it, just less
   pleasantly. `README.md` gains the command.

Commit 1 lands alone. If it arrives with commit 2, a reviewer cannot tell a resolution bug from a
reader bug, which is the whole reason the seam is worth cutting first.
