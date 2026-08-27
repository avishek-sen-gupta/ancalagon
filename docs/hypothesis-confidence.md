# Scoring Hypotheses with Log-Odds

How a hypothesis accumulates confidence from evidence. Replaces vote tallies and weighted
sums, both of which can be won by volume.

## The one idea

Do not ask "does this evidence support my hypothesis?" Ask: **how much more likely was I to
see this if the hypothesis is true than if it is false?**

That ratio is the whole information content of an observation — the likelihood ratio.

```
LR = P(I see this | H true) / P(I see this | H false)
```

- `LR = 10` — ten times more likely under H. Strong support.
- `LR = 1` — equally likely either way. **Worth nothing.**
- `LR = 0.1` — ten times more likely if H is false. Evidence against.

The middle case is what vote-counting gets wrong. A tally scores that observation `+1`. It is
worth `0`.

## Why odds, and why logs

Probabilities do not combine. You cannot multiply "70% chance" by "80% chance" and get
anything meaningful. Odds do combine. Odds are `chance-for : chance-against` — 80% is 4:1.

The update rule is `new odds = old odds × LR`, once per piece of evidence. Multiplication is
awkward to accumulate, so take logarithms and it becomes addition:

```
log-odds after = log-odds before + log10(LR)
```

Every observation becomes a number you add. Positive pushes toward H, negative pushes away,
zero does nothing. In base 10, `+1` means "ten times more likely". Turing's team at Bletchley
ran the same arithmetic and called the units *bans*.

## Worked example

Two surviving candidates for one analysis site, both plausible accounts of a duplicate-key
check:

- **H** — the check lives in `com.example.orders.OrderValidator`
- **A** — the check lives in `com.example.orders.LineItemValidator`

Start with no preference: odds 1:1, log-odds 0.

| observation | if H | if A | LR | log10 |
|---|---|---|---|---|
| guard clause reads no location fields | 100% | 100% | 1 | **0.00** |
| message reads "duplicate key" | 100% | 100% | 1 | **0.00** |
| else-branch also compares header fields | 80% | 15% | 5.3 | +0.73 |
| call graph: reachable from `OrderService`, not `LineItemService` | 90% | 10% | 9 | +0.95 |

Total `+1.68`. Odds `10^1.68` is about 48:1 for H — roughly 98%.

The top two rows are the point. They are true, they are relevant, they were expensive to
extract. Both candidates predict them equally, so they discriminate nothing and score exactly
zero. A tally would have counted them for both sides and diluted the two observations that
actually mattered.

That is the failure being fixed: **a tally can be won by volume.** Ten near-worthless
observations outvote one decisive one. Under log-odds they add zero, and volume buys nothing.

## Where the two numbers come from

Start with coarse buckets. Precision is not needed — the log is forgiving, and order of
magnitude gets the ranking right.

| feel | LR | log10 |
|---|---|---|
| decisive | 100 | +2 |
| strong | 10 | +1 |
| weak | 3 | +0.5 |
| no discrimination | 1 | 0 |
| ruled out by logic | 0 | -inf |

Then measure them. For each evidence tool, on a hand-labelled sample, count two things: how
often it fires when the answer is genuinely yes, and how often it fires when the answer is
genuinely no. Two counts per tool; the ratio is the LR.

Estimating a tool's hit rate is repeated trials of one unknown rate — exchangeable and
conjugate — so a Beta prior belongs on **each tool's hit rates**, not on the hypothesis. That
also yields uncertainty on the LRs themselves.

## What changes in the leaf contract

The leaf contract, and nothing else:

```
before:  leaf returns  vote                  -> parent does  alpha += 1
after:   leaf returns  (p_if_true, p_if_false) -> parent does  logodds += log10(p_if_true / p_if_false)
```

Two guards:

- A tool never returns 0 or 1 unless the case is genuine logical impossibility. `LR = 0` means
  ruled out, and it is the only place infinity is allowed.
- Cap each item's contribution — say +/-2. One buggy tool must not be able to assert certainty.

## What it does not fix

Correlated evidence still overcounts. Three generated sub-hypotheses that paraphrase each other
each contribute their log-LR and triple-count one observation. Log-odds makes the *units*
meaningful; it does not detect that two observations are the same observation. Separate fix.

## Why commit to it

1. Worthless evidence costs nothing automatically — no hand-tuned weights to suppress it.
2. Evidence can be negative. A tally cannot say "this makes the hypothesis less likely", so
   contradicting evidence gets its own accumulator and never actually fights.
3. The output is a claim that can be checked. "48:1" is falsifiable against labelled data;
   "belief 0.83" from a weighted sum is not.

The alternative considered was Dempster's combination rule, which gives ignorance for free but
is counterintuitive under high conflict and has no calibration story. Mixing the two inherits
neither's guarantees.
