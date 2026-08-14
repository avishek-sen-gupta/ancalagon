# Specs

TLA+ models of the bus, and the toy specs used to learn each construct first.

Plan: `docs/superpowers/plans/2026-08-14-tla-curriculum-for-the-bus.md`
Design: `docs/superpowers/specs/2026-08-14-modelling-the-bus-in-tla-design.md`

## Running

In VS Code, with the TLA+ extension: ⇧⌘P → **TLA+: Parse module** to check syntax, then
**TLA+: Check model with TLC** to check the model. Parse first; TLC's complaints about an
unparseable spec are far worse than SANY's.

From a terminal:

```bash
java -cp ~/.local/lib/tla2tools.jar tla2sany.SANY Counter.tla              # parse only
java -cp ~/.local/lib/tla2tools.jar tlc2.TLC -config Counter.cfg Counter.tla
```

A `.tla` file is the specification. A `.cfg` file is one model of it: which formula to check
(`SPECIFICATION`), what to check at every state (`INVARIANT`), and what any constants are
(`CONSTANT`). One spec can have several `.cfg` files checking it at different sizes.

## Specifications

| File | Module | What it covers |
|---|---|---|
| `toy/Counter.tla` | 0 | A first spec: `Init`, `Next`, `Spec`, an invariant, and a deadlock. |

## Notes

### Module 0

An action is a **constraint on a pair of adjacent states**, not an instruction.
`x' = x + 1` says the pair `(x, x')` is legal when the second is one more than the first, so
a pair of one then two passes and a pair of one then five fails. It resembles assignment only
because that constraint admits exactly one value for `x'`. Loosen it to `x' \in (x+1)..4` and
one state gets three successors, which is the same machinery with a looser constraint.

There is no assignment operator in TLA+. `==` names a definition, `=` compares.

`CHECK_DEADLOCK FALSE` is in `Counter.cfg` because the counter is meant to stop, and TLC
treats "no action is enabled" as an error by default. Note that this disagrees with the
specification itself: `[][Next]_vars` permits steps where nothing changes, so the behaviour
`1, 2, 2, 2, ...` is legal and there is no real deadlock. TLC's check deliberately ignores
those steps, because counting them would make deadlock undetectable everywhere. The tool is
answering "is any real action possible here?", not "is this behaviour legal?"

**Deferred to Module 3:** why `[][Next]_vars` must be written with the bracket form, and
what steps-where-nothing-changes are actually for. The justification is refinement — a
concrete spec implementing an abstract one takes steps the abstract one cannot see — and it
cannot be motivated honestly before there are two specifications to compare. Until then the
line is boilerplate: every spec ends `Spec == Init /\ [][Next]_vars`.

TLA+ rejects the unabbreviated `[](Next \/ vars' = vars)` outright, with
`[] followed by action not of form [A]_v`. The grammar enforces the bracket form so that a
formula which is *not* insensitive to those steps cannot be written at all.
