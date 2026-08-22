# A proof layer over model output

A proof-of-concept. An agent answering "what does this function do?" produces prose that a
reader must take on trust. This layer replaces that with a derivation: a tree whose leaves are
tool outputs that can be re-run, whose steps are thirteen fixed logical shapes, and whose
verdict names exactly which unprovable assertions the answer rests on.

## What it promises, and what it does not

It promises: *the reasoning is valid, the evidence still reproduces, and here are the three
admissions and two assumptions the conclusion depends on.*

It does not promise the conclusion is true. It cannot. An admission is an assertion the model
could not ground; an assumption is a premise you declared. If either is false, a perfectly
checked proof carries a false conclusion. The value is not verification — it is that auditing
an answer becomes reading five labelled leaves instead of re-deriving the whole thing.

This distinction is the design. Anything that blurs it makes the layer theatre.

## The kernel

Standard intuitionistic natural deduction, due to Gentzen and Prawitz. It is ninety years old,
settled, and nothing here is invented.

| Rule | Shape | A claim step it supports |
|---|---|---|
| and-build | A, B ⊢ A∧B | "it opens the file and closes it" |
| and-take | A∧B ⊢ A | a premise arrived glued; one half is needed |
| or-build | A ⊢ A∨B | "it returns a result or raises" |
| or-cases | A∨B, A⊢C, B⊢C ⊢ C | the branch was taken or it wasn't; either way it fails |
| imp-build | assume A … derive B ⊢ A→B | "if the path is outside the roots, it fails" |
| imp-apply | A, A→B ⊢ B | since this, therefore that |
| not-build | assume A … absurdity ⊢ ¬A | "the only implementation does nothing, so the interface does not write" |
| not-clash | A, ¬A ⊢ absurdity | the collision the above depends on |
| absurd | absurdity ⊢ anything | uniformity; rarely used |
| all-build | P(a) for fresh a ⊢ ∀x.P(x) | "every caller passes an absolute path" |
| all-use | ∀x.P(x) ⊢ P(t) | apply a general language fact to this call site |
| some-build | P(t) ⊢ ∃x.P(x) | "it writes to disk", witnessed by one span |
| some-use | ∃x.P(x), P(x)⊢C ⊢ C | reason from "some caller does X" without knowing which |

Thirteen is a presentation choice, not a canon. Pfenning's Figure 1 lists nine, because he
defines `¬A` as `A → ⊥`, which makes the two negation rules the implication rules pointed at
falsehood. Either counting yields the same system; the implementation may collapse them.

**Excluded on purpose: proof by contradiction in its classical form.** Deriving A by refuting
¬A lets a proof conclude "there exists a caller that does X" without naming one, which for
grounded claims about code is the opposite of what is wanted. The kernel stays constructive: to
assert something exists, exhibit it. If a real claim turns out to need the classical rule, that
is a finding worth recording rather than a gap to pre-emptively fill.

## The leaves

The kernel is standard. The leaves are the whole domain contribution, and there are four.

| Leaf | Content | Checkable? |
|---|---|---|
| observe | a tool invocation, its arguments, and a digest of its output | yes — re-run it |
| assume | a declared premise | no, but it is written down |
| admit | an implication the model asserts and cannot ground | no; this is the leap |
| hole | a goal deliberately left unproved | n/a — it is the work remaining |

**Evidence is any tool result, not just a span.** A byte range in a file is the degenerate case
where the tool is "read this file between these offsets". A regex search, a structural match, a
type checker's verdict, an import-linter result, a call-graph query, a line count: all are
observations, differing only in what produced them and therefore in how much weight they carry.
Recording the tool means a report can say *this rests on three regex hits* rather than *this
rests on evidence*.

Two properties follow from evidence being a tool call rather than a quotation:

- **Reproducibility.** The checker re-runs each observation and compares digests. This is the
  one domain check that is fully decidable, and it is the one that matters most.
- **Expiry.** Every observation is relative to a corpus at a commit. After a change, re-checking
  names which leaves went stale, and therefore which claims must be redone. Proofs that expire
  are a feature.

**Admissions are where abstraction lives.** "These five observations amount to *it parses a
CSV*" is a judgement, not a deduction. It is not a separate rule — it is an ordinary implication
premise carrying the `admit` label, so `imp-apply` consumes it like any other. Isolating it
costs nothing and is the point of the exercise.

## Negation and exhaustiveness

Every negative claim about code — never, only, no path — bottoms out in a closed-world step, and
the failure mode is that the step hides inside an innocuous-looking premise.

"This interface does not write to the filesystem, because its only implementation does nothing"
is a sound contradiction argument. The load is carried by **only**: nobody else implements it,
nothing registers one at runtime, no test substitutes one, no file outside the search was
looked at.

The rule is not to forbid this. It is:

> A conclusion that is negative must trace to an exhaustiveness assumption among its leaves, and
> the checker reports which one.

Stated as an observation rather than an assumption where possible — an exhaustive structural
search over a declared corpus is a tool result — which shrinks the residual assumption to two
reusable ones: *the corpus is the whole world*, and *this tool finds every instance of this
pattern*. Those are declared once for a project, not per claim.

If a negative conclusion has no exhaustiveness leaf at all, that is a lint failure, not a
soundness failure: something got smuggled in as an ordinary observation.

## What the checker does

**Verification, which is total and linear in the size of the proof:**

1. Every node's premises match one of the thirteen schemas.
2. Every discharged hypothesis is discharged by the rule that introduced it, and labels are
   distinct.
3. The parameter in `all-build` is fresh — not used outside its scope.
4. Every leaf is one of the four kinds, and every observation re-runs to its recorded digest.

Items 2 and 3 are the only parts that are not shape-matching; they are scope checks, and they
are where a model's output will fail most often. Their error messages therefore matter more
than the rest of the checker put together.

**Reporting, which is the actual product:**

- the claim, and whether it is fully proved or has open holes
- the observations it depends on, with the tool that produced each
- the assumptions, exhaustiveness ones flagged separately
- the admissions, each with the step that consumed it
- leaves cited but never used — a sign of decoration rather than derivation

**What it cannot do, stated so nobody expects it:** decide whether the leaves are jointly
consistent. A valid derivation can rest on contradictory premises, and `absurd` then yields
anything. For the propositional fragment this is decidable (PSPACE-complete); with quantifiers
it is undecidable. The approximations worth shipping are a syntactic clash check and a
budget-bounded search for absurdity — finding one is a real result, failing to find one means
nothing.

## Notation

The model emits **JSON proof terms**, validated into a Pydantic union with one variant per rule.
Validation emits a **canonical term file**, and the checker is **SWI-Prolog** reading it with
`read_term/2`.

Each side does one job. Python owns *is this a well-formed proof object* — which is where the
repair loop's error messages have to come from, since that is what the model reads. Prolog owns
*does this derivation follow the rules*, as one clause per rule threading a hypothesis context:

```prolog
proves(G, hyp(U),              A) :- member(U-A, G).
proves(G, andI(P,Q),       and(A,B)) :- proves(G,P,A), proves(G,Q,B).
proves(G, impI(U,P),       imp(A,B)) :- proves([U-A|G],P,B).
proves(G, impE(P,Q),           B) :- proves(G,P,imp(A,B)), proves(G,Q,A).
proves(G, orE(P,U,Q,W,R),      C) :- proves(G,P,or(A,B)),
                                     proves([U-A|G],Q,C), proves([W-B|G],R,C).
proves(_, observe(Tool,Args,Digest), A) :- evidence(Tool,Args,Digest,A).
```

The term file carries two things: the derivation, and the `evidence/4` facts. Re-running tools
is Python's job — Prolog never shells out — so by the time the checker sees a proof, each
observation either has a fact backing it or does not, and a stale digest is simply a missing
fact. That keeps the checker pure and makes it testable without a corpus.

Threading `G` is the whole of hypothesis discharge; freshness for `all-build` is a term walk
guarded by `\+`. The thirteen rules plus contexts land around eighty lines, and the same clauses
run backwards if proof *search* is ever wanted — which a checker written in Python would not.

**A proof is never emitted as Prolog source.** Consulting a file executes it, so a generated
`:- initialization(...)` in model output would be a directive rather than data. Terms are read,
never consulted. This is the one hard rule in this section.

The cost is two representations of the same thing, the Pydantic union and the term shapes. One
module owns the mapping in both directions, and a round-trip property test keeps them from
drifting.

Considered and rejected for the PoC, each for one reason:

Note what Prolog is and is not doing here. Its *native* logic — Horn clauses — is weaker than
this kernel: no disjunction in the head, no hypothesis discharge, no witnesses. It is the
implementation language, not the proof system. Derivations are terms it pattern-matches, exactly
as a VM interpreter pattern-matches instruction terms.

Considered and rejected for the PoC:

| Option | Why not now |
|---|---|
| Model emits Prolog source | Consulting executes. No upside worth an eval surface fed by model output. |
| Prolog parses the JSON itself | Same conversion work, done in the language whose error messages the repair loop can least afford. |
| λProlog / ELPI | Genuinely native: `A => B` and `pi x\ …` give discharge and freshness from the metalanguage, saving the context threading. A second runtime to save twenty lines. |
| LF / Twelf | Built for exactly this. Steep, and the model has never seen it. |
| Lean 4 | A kernel others already trust, and `sorry` is the hole primitive. But only the kernel would be used, none of mathlib, the leaf vocabulary would still be ours, and elaboration errors are a poor repair signal. Porting eighty lines of checker later is a weekend; do it when credibility matters more than iteration speed. |

The deciding factor is not expressiveness but the repair loop. A malformed proof should fail at
a boundary whose message this project writes, not inside a foreign elaborator. The model will be
wrong often; the failure type *is* the interface.

## The loop

```
model proposes a derivation (holes allowed)
        ↓
checker validates shape, scope, and evidence
        ↓
verdict: proved | holes remain | invalid at step N
        ↓
typed failure back to the model, which repairs
```

`hole` is what makes this converge instead of thrash: an incomplete proof is still well-formed,
so the model gets told *what remains* rather than *this is wrong*. Failures are typed values,
not prose — the same discipline this codebase already applies to tool results.

## Scope of the proof of concept

One claim, one function, end to end. `Shell.run` in `ancalagon/tools/shell/shell.py` is the
candidate: small, recent, and with a claim worth proving — *it can return a failed result
without running a command* — that needs an observation from a second file, one admission about
language semantics, and no quantifiers.

Success is not "the proof checks". It is answering three questions:

1. Can a model produce a well-formed derivation at all, and how many repair rounds does it take?
2. When it fails, is it the shapes or the scope conditions?
3. Is the admission count a useful signal — do heavily-admitted proofs correlate with answers a
   human would distrust?

Out of scope: proof search, a rule library of language semantics, multi-claim documents,
anything touching the harness's own run loop.

## Open questions

- Do claims need conjunction and disjunction inside them, or is one claim per proof enough? This
  decides whether four rules earn their place.
- Are admissions reusable? "A call in a `try` whose `except` returns R…" is a general fact about
  Python and will recur. A promoted library of admissions is really a rule library, and reviewing
  it once beats re-reading it per proof.
- Should the checker re-run observations by default, or trust digests and re-run on demand?
- Where does the corpus definition live — per proof, or per project?

## Reading, for someone starting from zero

In order. The first two are enough to work on this.

1. ***forall x: Calgary*** (Magnus, Button, Zach — free online). A genuine beginner's logic
   textbook. Read the natural deduction chapters. Caveat: it uses Fitch style — numbered lines
   with indented scope boxes — where Pfenning uses trees. Same rules, different picture; knowing
   that in advance saves an hour of confusion.
2. **Pfenning, *Constructive Logic* 15-317 notes.** Lecture 2 is the kernel; Figure 1 on page 14
   is the reference card. Lecture 5 adds the quantifiers, and page 40 has the freshness
   condition the checker must enforce. Lecture 7 is classical logic, worth reading only to
   understand what is being left out.
3. ***Theorem Proving in Lean 4*** (Avigad et al., free online). Chapters 3 and 4 are these
   exact rules as executable code. For a programmer this is often the fastest route from "I can
   read the shapes" to "I can tell whether a proof is right", because the machine says no.
4. **The Open Logic Project** (openlogicproject.org). Free, modular, and the natural-deduction
   material is thorough. Use as a reference rather than a read-through.
5. **Software Foundations, Volume 1** (Pierce et al., free). Longer, and Coq-flavoured, but it
   teaches proof by making you write them. Worth it if the topic sticks.
6. **Prawitz, *Natural Deduction* (1965)** — the source. Short and dense. Read after the others,
   if at all.

Two conceptual pieces worth reading early, both short: the Stanford Encyclopedia entries on
*Natural Deduction Systems in Logic* and on *Intuitionistic Logic*. The second explains why
"prove it by refuting its negation" is disallowed here, which is the design's least obvious
choice.
