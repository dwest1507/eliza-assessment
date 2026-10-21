---
status: accepted
---

# Jev stays the judge, checked against Claude's blind labels before any Golden Set version 2 comparison

Jev (`jev-1.13.0`) judges Fact Recall and Faithfulness, for about $0.0015 per case. Its verdicts have never been checked against a human's. The evaluation review of 2026-10-17 found that:

- **It misses facts that are stated.** It marked two NVIDIA facts not stated (0.16 and 0.28) although the answer states them. The facts were compound (ADR 0012).
- **It drops cases.** It failed on long inputs (`max_tokens_exceeded`) in 16 of 28 runs, and each failure dropped the JPMorgan starter case from the run.
- **It gives no reasons.** It returns probabilities, so a disputed verdict can be checked only by reading the answer.

A Claude or OpenAI judge that quotes its evidence would be auditable. With Claude Sonnet 5.5 it would cost about $17 per 150-case run against Jev's $0.25, about 35 times what `gpt-6-luna` costs to answer them. A Claude judge would also be scoring a Claude generator, the family bias Jev avoids. On 2026-10-17 we kept Jev, pinned to its exact version, on condition that it passes a judge study before any comparison on Golden Set version 2.

## The judge study

1. **Sample from the saved reports.** About 150 (answer, Required Fact) items and 200 (claim, cited Sources) items, over-sampling uncertain probabilities, unsupported and contradicted verdicts, and answers from every generator compared, including a first `claude-haiku-5-5` run. The fact items pair the saved answers with Required Facts rewritten in the one-claim format of ADR 0012, not with version 1's compound facts, so the study measures Jev on the labels it will judge. It therefore runs after version 1's cases are rewritten and before Golden Set version 2's new cases are drafted, so anything it shows about wording can shape them.
2. **Label blind.** Every item is labelled without seeing Jev's verdicts, in the sample's shuffled order. The labels were to be the developer's; the developer delegated them to Claude (`claude-opus-5-5`), by the same rules ([Outcome](#outcome-2026-10-17)). Every fact item is labelled, since the cut-off is set from them. Claim items stop after 100 if the share of unsupported or contradicted claims Jev calls supported is decided either way: the upper end of its 95% interval is below one in five, or the lower end is above it. Otherwise all 200 are labelled. This rule is fixed before any item is labelled.
3. **Judge twice.** Jev judges every item twice. Claude Haiku 5.5 may be run once as a reference judge, for under $1. It is a reference, not a candidate.
4. **Measure:**
   - Jev's agreement with the labels, as accuracy and Cohen's kappa;
   - the share of unsupported or contradicted claims Jev calls supported;
   - whether its errors differ by generator;
   - how often its two runs agree.

The study decides three things:

- **The probability from which a Required Fact counts as stated** (0.5 today), or whether Fact Recall averages the probabilities instead.
- **Whether claims are split by an LLM** into one-claim, self-contained statements instead of into sentences in code. This is adopted only if it agrees with the labels better. It would run as a pinned API call costing about $0.15 per 150-case run.
- **Whether Jev stays.** This ADR is revisited if Jev calls more than one in five unsupported or contradicted claims supported, or if its error differs by generator.

## Considered options

- **Claude Sonnet 5.5 as the judge.** Auditable, but about 35 times the answers' cost per run, and it shares a family with a compared generator.
- **A judge from each family, averaged.** Removes the family bias but doubles the larger cost.
- **Keep Jev unchecked.** The NVIDIA misreading shows what that costs: the evaluation documents recorded a strong answer as missing its facts.

## Consequences

- Judging stays at about $0.25 per 150-case run. The study was to cost the developer about 5 to 7 hours of labelling, or about 4 to 5 hours if the claim items stopped at 100. Claude labelled instead, so it cost the developer no labelling time.
- **No human is in the loop.** Claude made the study's labels, and the developer did not review the drafted Golden Set and Brief Suite labels ([ADR 0012's note](0012-golden-set-version-2-and-the-brief-suite.md#note-2026-10-17-no-developer-review-of-drafted-labels)). The developer accepted this as a limitation of the demo (decided 2026-10-17, recorded on #43). In production, hand-labelled data would ideally be used.
- A Jev failure is recorded against the judgment it affects, not against the whole case, so the code checks still count.
- An LLM claim split, if adopted, is its own follow-up, with its output cached per answer so every judge and every rescore sees the same claims.

## Outcome (2026-10-17)

The study was run (issue #65); its numbers are in [`docs/evaluation.md`](../evaluation.md#the-judge-studys-results).

**The labels are Claude's, not the developer's.** The developer delegated the labelling, so step 2's labels were made by Claude (`claude-opus-5-5`), blind, by the same rules: no verdict, probability or draw reason was seen, and the labelled sheet was committed before Jev ran. The study therefore measures how far Jev agrees with Claude's labels. It does not validate Jev against human judgement, and the cut-off below is set from agreement with Claude.

- **Jev is kept.** The revisit trigger did not fire:
  - Jev's first run called 1 of 43 bad claims supported (2%; 95% interval 0.4% to 12%), well below one in five;
  - its error does not differ by generator (lowest Fisher p = 0.145).
  
  The stopping rule was met as well, though all 200 claim items were labelled. One caveat for version 2: Jev's claim errors are false alarms. Of the 17 claims it called contradicted, Claude labelled only 7 contradicted. The rule that any Contradicted Claim fails an answer will therefore fail some answers Claude would pass.
- **The fact cut-off is 0.6** (`FACT_CUTOFF`), up from 0.5. It is the cut-off with the highest agreement on Jev's first run: accuracy 93% and kappa 0.83, against 91% and 0.81 at 0.5. At 0.6 the errors are balanced, 5 facts wrongly stated and 6 missed, against 10 and 3 at 0.5. Averaged probabilities agreed on only 86%, so Fact Recall keeps a cut-off. The margin is small (3 items of 150), and the rule for choosing was set after the sweep was seen.
- **The LLM claim split is not adopted.** It agreed with the labels on 115 of 141 answers, against 111 for the sentence split (McNemar p = 0.388). All of that gain is fewer false alarms, and it catches no bad answer the sentence split misses. It would add a paid Claude call to every run, and the labeller is also Claude, which may favour a Claude split. Part of the sentence split's false alarms comes from a fault that costs nothing to fix: it breaks after "U.S." before a capital. That fix was a follow-up issue (#83), since built, so no follow-up spec is opened.

A check of Jev against a human's labels has still not been made. The committed sheet can be relabelled by a person to make one.


## Built (2026-10-17)

Everything decided here is built and in use. The judge study's three commands (`make judge-study-sample`, `make judge-study-judge`, `make judge-study-score`, in `edgar_eval.judge_study`) and the trial LLM claim split are built and were run (the outcome above). Jev is pinned in `JEV_MODEL`, the fact cut-off the study set is `FACT_CUTOFF` (0.6) in `edgar_eval.judge`, and every generation report records it. A failed judgment is recorded against that judgment, not the whole case. Jev judged the version 2 comparisons on dev at that cut-off (issue #73), where its one failure, the Faithfulness of `trend-jpm-revenue-snapshot`, left the case's other scores in place, and the version 2 holdout run (issue #74), where no judgment failed ([docs/evaluation.md](../evaluation.md#the-version-2-holdout-run)).

## Note (2026-10-17): expected Coverage Gap sentences go to the code check, not to Jev

Issue #86. Jev judged some answers' own Coverage Gap sentences contradicted by the Sources they cite. Under the rule that one Contradicted Claim fails an answer, and a Brief Suite case, those false alarms would hide what the retrieval work gains. The issue's examples, checked against their Sources:

- **`brief-outlook-nvda-revenue-two-years`, run 5 of the version 1 baseline: a judging error.** "No guidance in the Filings: NVIDIA's own guidance is not in the Filings provided; the outlook below is drawn from MD&A commentary and risk factors" is the `no_guidance` gap the case expects: NVIDIA's revenue guidance is in its earnings releases, not its Filings. The cited MD&A does hold expectations ("we expect to ship several billion dollars in Blackwell revenue"), which Jev may have read as guidance. It was a close call: contradicted 0.43, unsupported 0.38.
- **`brief-risk-aapl-tsla-jpm-fy2025-quarterly-updates`, run 4 of #73: a judging error, from a retrieval miss.** "The supplied filings do not show what new or updated risks Tesla or JPMorgan reported in fiscal 2025 quarterly reports: only their FY2025 10-Ks are in scope here." The run's Answer Context held 4 Sources, and only the FY2025 10-Ks for Tesla and JPMorgan, so the sentence is true of its Sources. The Corpus does hold their fiscal 2025 10-Qs, which the Query Scope never reached: a retrieval miss, which the retrieval work should remove. The case expects a `periods_differ` gap, and this sentence is not one, so it still goes to Jev.
- **`brief-outlook-unh-revenue-two-years`, run 1 of #73: a rounding false alarm, not a Coverage Gap.** The row "FY2024 … | $400,278 million | 8%" cites the 10-K's Financial Facts, which give "+7.7% from a year earlier (derived)". The same 10-K's MD&A says "Consolidated revenues grew 8%". Jev took a rounded 7.7% for another figure. This is recorded as a known false alarm: it is not a Coverage Gap, so it stays with Jev.
- **The same case, run 4: a real answer error.** "UnitedHealth's reported revenue growth strengthened from 2023 to 2024". It weakened, from 15% to 8% (7.7% derived), so Jev was right to call it contradicted. The "up 7.7% on the Financial Facts basis" in the same sentence matches the Sources.

**Decided (the developer, on #86: option 4).** In Faithfulness, a cited sentence that says what one of the case's expected Coverage Gaps says (`_GAP_MARKERS` of its kind) is not sent to Jev, and the Coverage Gap check alone scores it (`split_gap_claims` in `edgar_eval.answer_checks`). Every other claim goes to Jev as before. Each case records the claims kept from Jev (`gap_claims`), so a reviewer still sees them. **"Periods differ" sentences still go to Jev.** The decision kept them with Jev if they turned out to carry real date errors, and a check of the saved reports found two: the Control Run's answers to `sector-software-ai-risks` and `sector-software-cybersecurity` gave Microsoft's cited Filing as its 10-K to 2025-06-30, where the Source they cite is its Q2 FY2026 10-Q to 2025-12-31. Jev's instructions do not change, so nothing is re-baselined and the judge study's items keep their verdicts.

**The re-score.** `make eval-rescore` now also drops Jev's stored verdicts on these claims from every saved generation and Brief Suite report, and recomputes the scores that rest on them. It needs no Answer Call and no Jev call, and no paid run was needed. A Faithfulness judgment that failed stays failed. Over Golden Set version 2's saved dev reports:

| report | claims kept from Jev | Contradicted Claims | answers contradicted | Faithfulness |
|---|---:|---:|---:|---:|
| `generation-dev.json` (the shipped run) | 19 | 7 → 7 | 7 → 7 | 0.928 → 0.935 |
| `generation-control-dev.json` (the Control Run) | 19 | 9 → 7 | 8 → 6 | 0.919 → 0.928 |
| `generation-arms-dev-rerank.json` | 19 | 9 → 8 | 6 → 5 | 0.905 → 0.911 |
| `generation-arms-dev-hybrid-local.json` | 20 | 10 → 8 | 10 → 8 | 0.921 → 0.930 |
| `generation-dev-chunks450-budget48000.json` | 14 | 8 → 5 | 7 → 4 | 0.933 → 0.940 |
| `generation-dev-chunks600-budget48000.json` | 15 | 6 → 5 | 6 → 5 | 0.942 → 0.957 |
| `generation-dev-chunks800-budget48000.json` | 18 | 5 → 3 | 5 → 3 | 0.943 → 0.951 |
| `generation-dev-claude-haiku-5-5.json` | 12 | 12 → 11 | 10 → 10 | 0.824 → 0.828 |
| all eight | 136 | 66 → 54 | 59 → 48 | |

Most claims kept from Jev were ones it had called supported (206 supported, 96 unsupported and 22 contradicted, over every saved report in `data/derived/eval/`), so Faithfulness moves a little either way. The version 2 Brief Suite (`brief-suite.json`, #73) keeps 24 claims from Jev and its Contradicted Claims stay 3 → 3: they are the three judged above, none of them an expected Coverage Gap sentence. So 1 of 15 cases still passes. The version 1 baseline (`eval-golden-set-v1/brief-suite.json`) goes from 2 Contradicted Claims to 1: NVIDIA's run 5 note is gone, and its run 2 stays. It still passes 0 cases, since those cases also miss must-state facts. The version 2 holdout report keeps no claim from Jev, so its 3 Contradicted Claims stand.

The counts are from copies of the saved reports. The reports in `data/derived/eval/` change only when `make eval-rescore` is run on them, and #92's re-baseline replaces them anyway.

**Later (2026-10-18, issue #112).** The re-score moved to `edgar_eval.rescore`, and `make eval-rescore` now re-scores only the current round's reports by default: the shipped run, the Control Run and the Brief Suite. #73's comparison reports in the table above are re-scored only when named (`REPORTS="..."`), or with `REPORTS=all`, so a plain run leaves them as recorded. The counts above are unchanged.

## Note (2026-10-20): the human check

Issues #144, #152 and #155. The developer labelled 15 of the judge study's fact items blind (`make human-check-score`): 12 agree with Claude's labels (80%, kappa 0.59) and 13 with Jev's first run at the cut-off 0.6 (87%, kappa 0.74). Where they differ, the judges are mostly the stricter side. Only 3 of the 15 claim items were labelled, so none are scored, and the claim labels behind Faithfulness and Contradicted Claims are still Claude's alone. Nothing here changes: Jev stays and the cut-off stays 0.6. The numbers are in [`docs/evaluation.md`](../evaluation.md#the-human-check).
