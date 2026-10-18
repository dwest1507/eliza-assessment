---
status: accepted
---

# Retrieval comparisons decide Fact Recall fact by fact, by a case-cluster bootstrap

Amends [ADR 0011](0011-one-sided-thresholds-and-a-control-run.md) for the Arm rule and the settings rule (the chunk size and context budget) only. The generator rule stays as ADR 0011 states it. Decided on 2026-10-18 (issue #118, spec #116), with the thresholds below fixed before any run that uses the rule.

Under ADR 0011 a challenger was ahead on Fact Recall when the one-sided exact sign test, pairing each case's share of must-state Required Facts stated, gave p < 0.10. A retrieval change moves a few facts in a few cases, and that test cannot see it. In issue #73, answers through `hybrid-local` stated 12 of the 20 must-state facts it newly reached, against 3 for FTS5. The 48k budget at 600-token chunks stated 10 of the 11 it added, against 4. Both were dropped as "not ahead on Fact Recall". The sign test counts a case as one win or one loss, whatever the number of facts behind it, and it pairs about 57 cases. On the roughly 240 facts both sides reach, generation noise swamps it: the Control Run flips 28 of them with nothing changed.

## The rule

- **Ahead on Fact Recall (the Arm and settings rules).**
  - For each case both sides scored, count the must-state Required Facts each side states.
  - The statistic is the total difference over those cases, challenger minus shipped.
  - Its one-sided p-value comes from a case-cluster bootstrap. The cases' differences are centred under the null (each less the mean difference), and whole cases are resampled with replacement 10,000 times from a fixed seed (`BOOTSTRAP_SEED`, 20261017). The p-value is (1 + the resampled totals at least the observed one) / (1 + 10,000). Resampling whole cases keeps the facts of one answer together, so their correlation does not make the test too eager.
  - The challenger is **ahead at p < 0.10** (`AHEAD_P`, unchanged).
  - The mean difference in facts stated per case is reported with its 95% bootstrap interval, shown and not decided on, as ADR 0011's intervals are.
- **Guardrails.** Behind at one-sided p < 0.20 (`BEHIND_P`, unchanged) on any of these disqualifies:
  - Fact Recall per case, by the existing one-sided sign test, so a challenger that loses on many cases can't ship on a few facts;
  - Faithfulness, Coverage Gaps and Contradicted Claims, unchanged.
- **The Control Run** is compared with the shipped run by the same fact-level test. If it is ahead, the comparison is inconclusive and the shipped choice stands, as ADR 0011 says.
- **The same scoring rules as the harness.** A must-state fact counts as stated at the report's fact cut-off (`FACT_CUTOFF`, 0.6, as each report records it). A truncated answer states no fact. A case whose Fact Recall judgment failed, on either side, is left out of the pairing, never counted as a zero, and a case with no must-state fact has nothing to pair.
- **The evidence-status split.** Each comparison in a choice file records the fact-level result beside the per-case one (`stated_facts`). It splits the paired facts by where their evidence reached: the challenger's Answer Context only, the shipped choice's only, both, or neither (`unrecorded` for a report saved before Evidence Reached was recorded). Each paired fact is counted once, with how many each side stated. The split shows whether a gain comes from evidence only the challenger reached, a retrieval gain, or from facts both sides had, a change in how the generator used the same evidence. It is reported, not decided on.
- **Records stand.** Version 1's and #73's choice files are records and are not recomputed. #73's reports were read under this test offline for reference only ([docs/evaluation.md](../evaluation.md#the-fact-level-test-on-73s-reports)).

## Why these numbers

- **The threshold stays ADR 0011's.** Only the statistic changes, so no decision gets a new cut-off after the fact.
- **The false-switch rate holds near the nominal 10%.** On #73's shipped run and Control Run, two runs of the same setup, assigning each case's two answers to the two sides at random puts the fact-level test ahead about 9% of the time, against about 10% for the sign test. That is 400 simulations of 2,000 resamples each, on 57 cases.
- **Its power is higher where retrieval gains fall.** Gains from retrieval come in a few cases: `hybrid-local`'s 20 newly reached must-state facts sit in 10 cases, 12 of them in three. With added stated facts placed three to a case on top of that noise, the fact-level test is ahead in about 52% of simulations at 9 more facts and 68% at 12. The sign test manages about 28% and 42%. When the same gains are spread one fact to a case, the two tests are about level (48% against 41% at 9 facts).

## Considered options

- **A fact-level McNemar test, treating facts as independent.** Facts of one answer move together, since one answer's length and focus decide all of them. Treating 316 facts as independent pairs makes the test too eager, so a Control Run would often beat itself.
- **A permutation test, swapping the two sides within each case.** It is exact when the two sides are exchangeable, and would serve as well. The bootstrap was chosen because the spec named it, and it reuses `BOOTSTRAP_SEED` and the resampling already in `edgar_eval.metrics`, which the reported intervals use.
- **Switching the generator rule as well.** A generator changes how every answer is written, not which evidence reaches it, so the per-case test fits it. Spec #116 changes only how retrieval comparisons are decided.
- **Dropping the per-case sign test.** Without it, a challenger could gain 20 facts in two cases and lose one in each of 15 others and still ship. As a guardrail at p < 0.20 it blocks that.

## Consequences

- `edgar_eval.selection.RULES` states the change. The Arm and settings rules are ahead on `stated_facts` and keep `fact_recall` among their guardrails. The generator rule still decides on `fact_recall`. `edgar_eval.metrics.cluster_bootstrap_test` holds the test.
- Each comparison prints and saves the fact-level result (`stated_facts`) beside the per-case one, under every rule. Under the generator rule it is shown and not decided on.
- The comparisons after spec #116's retrieval changes (`hybrid-local` and the 48k budget) are decided by this rule.
- **Revisit when** the system moves past the demo stage, with ADR 0011's thresholds.

## Built (2026-10-18)

Built in `edgar_eval` (issue #118). `Candidate.from_report` reads each case's must-state facts from the report: Jev's probability at the report's fact cut-off, the case's truncation, and Evidence Reached per fact. `compare` and `choose` apply the rule. The tests in `backend/tests/test_selection.py` run on hand-built reports.
