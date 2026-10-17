---
status: accepted
---

# Comparisons call a challenger ahead at one-sided p < 0.10 and behind at p < 0.20, with a Control Run in each

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
