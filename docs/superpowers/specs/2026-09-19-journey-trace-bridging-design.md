# Journey Trace Bridging — Design

## Problem

Given a Java codebase, a prose description of a user journey, and a mechanical analysis
toolbox, derive the end-to-end path the program takes for that journey.

Static analysis produces most of the path. It breaks wherever the link from one piece of code
to the next is not written in the code — a DI container's XML, a JSP expression, a reflective
lookup, a message queue, a home-grown registry keyed by a properties file. Each break is a
**bridge**: a claimed link that must carry mechanically-checkable evidence and a rationale.

## Toolbox

The mechanical tools are those in `java-bytecode-tools`: `buildcg` (call graph),
`calltree` (forward and backward method-level trees), `cfg-root` / `xtrace-slice`
(interprocedural CFG), `ddg-slice` (backward data-dependency slice), `symbol-types`
(source-level symbol resolution), `jspmap`, `bean-registry` and the J2EE bean pipeline,
`bridge-cross-war`, and the `logging-agent` runtime trace pipeline.

## Artifact

A **connected segment graph**. Nodes are mechanically-derived segments — regions of the call
graph reachable without crossing a break. Edges between segments are bridges, and a bridge is
a first-class record:

```
(claimed link, evidence spans, verifier results, rationale, candidates, status)
```

The rationale explains the *selection* among candidates. It never argues for the existence of
the edge — that is the verifiers' job.

## Anchors

The journey arrives as prose, so anchor resolution is a two-step with a mechanical gate.

1. **Hypothesise** (model). Input: the prose plus a cheap inventory — `dump` for the
   method/line map, the bean registry, the endpoint scan, the JSP/EL map. Output is a typed
   contract: ranked candidate `(entry, outcome)` pairs with rationale.
2. **Confirm** (mechanical). Every proposed reference is resolved with `symbol-types` /
   `dump`. A reference that does not exist, or is not the kind claimed, is dropped before the
   search starts. The model never hands the search a symbol it invented.

Anchors stay revisable. If the search exhausts without connecting, the failure and what the
search actually reached feed back into step 1 and the next-ranked pair is tried. Retries are
bounded by the program, not by the model.

## Search strategy

Bidirectional, with the work done on the backward side.

**Step 1 — check whether a bridge is needed at all.** Expand callees forward from the entry
and test whether the outcome is in that set. One expansion, one membership test. If it is
there, the path is already in the call graph and there is nothing to bridge. This is cheap and
is often the answer.

**Step 2 — only on failure, expand backward.** The forward set is already in hand but is the
wrong side to work from: its edge is wide — every method the entry transitively reaches that
calls nothing further in-project, hundreds of leaves, most irrelevant. Expand callers backward
from the outcome instead. That edge is narrow: methods that reach the outcome but that nothing
in-project calls. On a real codebase that is a handful.

Backward roots are computable from the existing `callgraph.json` by inverting `callees`. No
tool change is required.

**Step 3 — ask why each root is a root.** A method that exists but has no in-project caller is
invoked by something outside the code. The method's own shape usually settles which: its
annotations, its class's supertypes, its signature, whether its class appears in `web.xml`,
`faces-config`, Spring XML or `ejb-jar.xml`, whether it appears in `jspmap` output, whether
its class is ever constructed in-project.

**Step 4 — the answer to step 3 names one thing to search for on the forward side.** This is
what collapses the search from a cross-product of edge pairs to a lookup:

| Root's classification | What to look for |
|---|---|
| implements an interface whose method is called in the forward set | that call site, plus the binding that names this class |
| container-dispatched HTTP | the request the journey issues, and its URL mapping |
| message consumer | a publish to the same destination among the entry's descendants |
| EL-invoked | the JSP the forward path renders |
| thread entry | the `submit` / `start` that hands it over |
| reflective target | the `Class.forName` / `invoke` whose argument resolves here |

The first row is expected to account for most roots: a method that is a root only because CHA
could not pick the implementation is the ordinary DI case, not a real discontinuity.

Two classifications are **negative results** and matter as much as the positive ones: a root
that is `@Scheduled`, a lifecycle callback, `main`, or in the test source tree is evidence that
it is *not on the journey*. It is dismissed, not bridged. Cheap dismissal keeps the search from
spending its whole budget on ghosts.

**Step 5 — multiple bridges.** When the forward and backward sides are separated by more than
one break, the same step repeats with the backward side growing one component at a time:

- `B` = everything that transitively calls the outcome.
- Classify a root of `B`, search for its invoker **across the whole codebase**, not just the
  forward set.
- If the invoker is in the forward component, the search is done.
- Otherwise the invoker sits in some other component `C`. That is a bridge, and `B := B ∪ C`.
  Repeat.

The search terminates when the backward side touches the forward side. The number of bridges
is never guessed, and intermediate components are never enumerated — only the specific
component containing the invoker being searched for is ever discovered.

The cost shifts with each round: the search for an invoker is a text search over the whole
codebase for one identifier (a bean name, a topic, a properties entry), not a graph query.

## Verification

Bridge *kinds* cannot be enumerated. Every codebase has bespoke wiring, and no fixed list
survives it. So the taxonomy above is a **cache of shapes already seen** — a shortcut to the
right probe when the shape is recognised — and never a gate.

What is fixed is the set of **verifiers**. A bridge may be hypothesised freely, but it must be
backed by checks drawn from this closed set:

1. **Spans exist and contain the cited text.** Weak, but it stops fabrication outright.
2. **Both endpoints resolve.** `symbol-types` confirms the two methods exist with the claimed
   shapes.
3. **The value reaches the lookup.** `ddg-slice` confirms the constant actually arrives at the
   call site. Generic: it does not care whose container performs the lookup.
4. **It happens.** The `logging-agent` observes the journey. The only fully general verifier,
   and the only one that can confirm a bridge whose key is computed at runtime.

None of these depend on knowing which framework caused the bridge.

Worked example, for wiring no taxonomy covers. The forward side ends at
`registry.get(key).handle(req)`; the backward root is `com.example.OrderProcessor.handle`; the
registry is hand-written. The model claims they connect via `registry.properties`. Checks:
`ddg-slice` on `key` resolves it to the constant `"orderProcessor"`; `registry.properties:12`
contains `orderProcessor=com.example.OrderProcessor`; `symbol-types` confirms the method
exists. The bridge stands, and no rule for "home-grown registry" was ever written.

A bridge that fails all four verifiers is recorded **unverified, with the slice showing why**
— a URL assembled from request data, a class name read from a database. That is an output, not
a failure: it tells the reader exactly where to point the logging agent.

## Ambiguity

A probe often returns several candidates — two beans implement the interface, an abstract
method has six overrides. Every candidate becomes a bridge edge and the graph forks. The model
may rank edges with rationale; it never deletes one. The final artifact shows the real
fan-out and a human prunes.

## Granularity

The search runs at method granularity because that is cheap. Only once a path from entry to
outcome is found is that one path re-derived in full control-flow detail with
`cfg-root` / `xtrace-slice`. That refinement produces the line-level evidence, and it can also
*disprove* the path — a branch unreachable under the journey's conditions kills it and the
search resumes. Cheap search, expensive proof, with the expense proportional to the answer
rather than to the search space.

The skeleton and the refinement are two representations that must agree. Disagreement is a
state the program handles, not a bug.

## Division of labour

The model decides what to try and in what order. Tools decide what is true.

Model touch points, each a typed contract:

1. hypothesise anchors from prose
2. classify a backward root when the mechanical tests do not settle it
3. rank probe candidates
4. write rationale

In none of these does the model name a symbol that a tool has not confirmed exists.

Ordering is the model's, and a bad order costs budget rather than correctness — it wastes
probes, it does not produce a wrong trace. Where a root costs one text search to test, order
matters little: try them all and keep what verifies. Ranking only earns its place when probes
are expensive.

## Root ranking

Dismiss before ranking. Test-tree roots, `@Scheduled`, lifecycle callbacks and `main` go first
and mechanically.

What remains is ordered by:

1. roots whose classification yields a searchable identifier — a topic, a bean name, a properties entry.
   A root with no extractable identifier cannot be acted on regardless of how plausible it looks.
2. the model, on name and package fit against the journey prose.

## Rejected during design

**Detecting breaks by differencing `callsites` against `callees`.** Checked against a real
`callgraph.json` and it does not work. Of the in-prefix call sites with no matching resolved
callee in a sample graph, every one was a constructor, a call into a leaf class that never
calls anything, or `Enum.ordinal()` — none were unresolved dispatch. The artifact carries no
signal for "could not resolve this call site": an unresolved virtual call and a call to a
record accessor are indistinguishable in it. The signal exists one layer up, in the empty
branch of `MethodResolver.resolveCallee`'s `Optional`, and is discarded before serialisation.

Working from backward roots sidesteps this entirely — "method with no in-project caller" is
computable from the artifact as it stands — so no change to `java-bytecode-tools` is needed.

**Ordering roots by dominance over the outcome.** Dominance requires a single entry point,
which is precisely what is unknown here, and roots have no predecessors by construction, so
when there are many roots none dominates. The idea was unfounded and is dropped.

**A closed taxonomy of bridge kinds as a completeness requirement.** See Verification.

## Open

Separating dead code and test fixtures from genuine reflective targets. Both present as "class
never constructed in-project, no config mention, no annotation", and most backward roots in a
real codebase reach the outcome but are never invoked by anything. Dismissing them cheaply and
correctly is unsolved.
