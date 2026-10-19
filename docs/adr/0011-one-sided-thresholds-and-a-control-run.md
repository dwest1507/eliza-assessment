---
status: accepted
---

# Comparisons call a challenger ahead at one-sided p < 0.10 and behind at p < 0.20, with a Control Run in each

> **Amended on 2026-10-18 by [ADR 0015](0015-fact-level-fact-recall-for-retrieval-comparisons.md)** for the Arm and settings rules: Fact Recall is ahead by a fact-level test, the must-state facts stated summed over cases and tested by a case-cluster bootstrap, at the same p < 0.10. The per-case sign test on Fact Recall stays as a guardrail, and the Control Run is compared by the same fact-level test. The generator rule, the thresholds and everything else here are unchanged.

Under ADRs 0008, 0009 and 0010 a challenger replaced the shipped choice only if the exact sign test on paired dev cases put it ahead at two-sided p < 0.05. On 20 dev cases that test finds a real gain about one time in ten (simulated: 30% of cases differ and the better side wins three quarters of them), so every comparison so far came out "indistinguishable" and the rule kept the incumbent by default. Its "behind on none" guard was passed almost automatically, for the same reason. Claude Sonnet 5.5's 5 cases higher and 0 lower on Fact Recall (p = 0.062, ADR 0009) is the example: the data lean one way and the rule cannot say so. This is a demo-stage system whose choices are cheap to reverse, so on 2026-10-17 we traded a few false switches for the power to see a real difference. The thresholds are fixed here, before any run on Golden Set version 2 (ADR 0012), and are not changed after results.

- **Ahead:** the one-sided exact sign test puts the challenger ahead at p < 0.10, on Fact Recall (or, under the generator rule, on Coverage Gaps).
- **Behind:** the one-sided test puts it behind at p < 0.20 on any guardrail: Faithfulness, Coverage Gaps, or Contradicted Claims. The looser cut-off flags a drop sooner, which is the safe direction.
- **One threshold for every rule** (Arms, generators, the chunk size and context budget), so no decision gets its own cut-off after the fact. The cheapest qualifying challenger still wins.
- **A Control Run in every comparison:** the shipped choice is run again beside its challengers. If the Control Run comes out ahead of the shipped run, the noise is larger than the thresholds assume and nothing else in that comparison is acted on.
- **Effect sizes beside verdicts:** each comparison also reports the mean paired difference with a 95% bootstrap interval over cases. It is shown, not decided on.
- **The retrieval harness gates on Evidence Reached** (per Required Fact, paired) instead of hit@10, which was identical for all four Arms and all 16 chunk-size and budget settings.
- **At most three challengers per rule, screened for free.** Every candidate Arm and every candidate chunk size and context budget is first scored by the retrieval harness, which makes no LLM call. A candidate goes on to paid Answer Calls only if Evidence Reached does not put it behind the shipped choice (one-sided p < 0.20). If more than three pass, the three with the highest Evidence Reached go on, the cheapest first on a tie. An answer cannot state a fact whose evidence never reached it, so the screen drops only candidates that could not win.
- **One shipped run and one Control Run per round.** Comparisons run on the same code, prompt and Golden Set version share them, so the Arm, settings and generator comparisons of one round pay for the shipped choice twice, not six times.

Simulated at 60 dev cases, the size ADR 0012 sets, the new rule finds a real gain about 74% of the time and switches by mistake about 7% of the time, against 49% and 1% for the old rule. That 7% is per challenger. With the 15 setting challengers version 1 compared, at least one would qualify by chance about 66% of the time (1 − 0.93¹⁵); with at most three, about 20%.

## Considered options

- **Keep p < 0.05 and grow the dev split to about 120 cases** (84% power). Twice the labelling, about 12 hours of review, for choices a demo can reverse.
- **p < 0.20 for ahead.** 87% power at 60 cases, but about one false switch in seven: the Control Run would often beat itself.
- **Pick the higher mean, with no test.** It switches by mistake almost half the time at any size.
- **Decide on the bootstrap interval.** On 60 cases it is optimistic, and a sign test is easier to defend to the Client. The interval is reported instead.
- **Every candidate through paid Answer Calls, with a Holm correction.** It keeps the chance of a false switch down without a screen, but it takes the power back to about the old rule's, and costs about $4 more per round.

## Consequences

- The thresholds of ADRs 0008, 0009 and 0010 are superseded for comparisons on Golden Set version 2. Their choices (FTS5, `gpt-6-luna`, 600-token chunks and the 32k budget) stand until a version 2 comparison says otherwise, and their version 1 verdicts stay as recorded.
- The selection rules and the sign test change in `edgar_eval`, with the thresholds stated once.
- The deck and the documents call version 2 results directional: "one-sided p < 0.10, fixed before running", with the Control Run shown.
- **Revisit when** the system moves past the demo stage. Then return to two-sided p < 0.05 and a Golden Set large enough for it.

## Built (2026-10-17)

Everything decided here is built in `edgar_eval` and has been used:

- **The thresholds** are stated once, as `AHEAD_P` (0.10) and `BEHIND_P` (0.20) in `edgar_eval.selection`, and every rule uses them, with Contradicted Claims among the guardrails. Each comparison reports the mean paired difference with a 95% bootstrap interval (fixed seed, 10,000 resamples), shown and not decided on (issue #55).
- **The Control Run and the round** (issue #56): every comparison takes a Control Run, a Control Run ahead on an ahead metric makes the choice inconclusive, and the comparisons of one round share one shipped run and one Control Run.
- **The Evidence Reached gate and the free screen** (issue #57): the retrieval harness gates on Evidence Reached with McNemar's exact test, one-sided, and screens every candidate Arm and setting before any paid run, at most three going on.
- **Used on Golden Set version 2** (issue #73): the Arm, settings and generator comparisons on its 60 dev cases ran under this rule. The Control Run was not ahead, so every comparison was conclusive, and every shipped choice stands (the notes on ADRs 0008 to 0010). The holdout was then scored once on that setup (issue #74), deciding nothing. The numbers are in [docs/evaluation.md](../evaluation.md#the-version-2-comparisons-on-dev).
