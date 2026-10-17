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
- **The LLM claim split is not adopted.** It agreed with the labels on 115 of 141 answers, against 111 for the sentence split (McNemar p = 0.388). All of that gain is fewer false alarms, and it catches no bad answer the sentence split misses. It would add a paid Claude call to every run, and the labeller is also Claude, which may favour a Claude split. Part of the sentence split's false alarms comes from a fault that costs nothing to fix: it breaks after "U.S." before a capital. That fix is a follow-up issue (#83), so no follow-up spec is opened.

A check of Jev against a human's labels has still not been made. The committed sheet can be relabelled by a person to make one.

