---
status: accepted
---

# Jev stays the judge, checked against the developer's labels before any Golden Set version 2 comparison

Jev (`jev-1.13.0`) judges Fact Recall and Faithfulness, for about $0.0015 per case. Its verdicts have never been checked against a human's. The evaluation review of 2026-10-17 found that:

- **It misses facts that are stated.** It marked two NVIDIA facts not stated (0.16 and 0.28) although the answer states them. The facts were compound (ADR 0012).
- **It drops cases.** It failed on long inputs (`max_tokens_exceeded`) in 16 of 28 runs, and each failure dropped the JPMorgan starter case from the run.
- **It gives no reasons.** It returns probabilities, so a disputed verdict can be checked only by reading the answer.

A Claude or OpenAI judge that quotes its evidence would be auditable. With Claude Sonnet 5.5 it would cost about $17 per 150-case run against Jev's $0.25, about 35 times what `gpt-6-luna` costs to answer them. A Claude judge would also be scoring a Claude generator, the family bias Jev avoids. On 2026-10-17 we kept Jev, pinned to its exact version, on condition that it passes a judge study before any comparison on Golden Set version 2.

## The judge study

1. **Sample from the saved reports.** About 150 (answer, Required Fact) items and 200 (claim, cited Sources) items, over-sampling uncertain probabilities, unsupported and contradicted verdicts, and answers from every generator compared, including a first `claude-haiku-5-5` run. The fact items pair the saved answers with Required Facts rewritten in the one-claim format of ADR 0012, not with version 1's compound facts, so the study measures Jev on the labels it will judge. It therefore runs after version 1's cases are rewritten and before Golden Set version 2's new cases are drafted, so anything it shows about wording can shape them.
2. **Label by hand.** The developer labels every item without seeing Jev's verdicts, in the sample's shuffled order. Every fact item is labelled, since the cut-off is set from them. Claim items stop after 100 if the share of unsupported or contradicted claims Jev calls supported is decided either way: the upper end of its 95% interval is below one in five, or the lower end is above it. Otherwise all 200 are labelled. This rule is fixed before any item is labelled.
3. **Judge twice.** Jev judges every item twice. Claude Haiku 5.5 may be run once as a reference judge, for under $1. It is a reference, not a candidate.
4. **Measure:**
   - Jev's agreement with the labels, as accuracy and Cohen's kappa;
   - the share of unsupported or contradicted claims Jev calls supported;
   - whether its errors differ by generator;
   - how often its two runs agree.

The study decides three things:

- **The probability from which a Required Fact counts as stated** (0.5 today), or whether Fact Recall averages the probabilities instead.
- **Whether claims are split by an LLM** into one-claim, self-contained statements instead of into sentences in code. This is adopted only if it agrees with the developer's labels better. It would run as a pinned API call costing about $0.15 per 150-case run.
- **Whether Jev stays.** This ADR is revisited if Jev calls more than one in five unsupported or contradicted claims supported, or if its error differs by generator.

## Considered options

- **Claude Sonnet 5.5 as the judge.** Auditable, but about 35 times the answers' cost per run, and it shares a family with a compared generator.
- **A judge from each family, averaged.** Removes the family bias but doubles the larger cost.
- **Keep Jev unchecked.** The NVIDIA misreading shows what that costs: the evaluation documents recorded a strong answer as missing its facts.

## Consequences

- Judging stays at about $0.25 per 150-case run. The study's cost is the developer's time, about 5 to 7 hours of labelling, or about 4 to 5 hours if the claim items stop at 100.
- A Jev failure is recorded against the judgment it affects, not against the whole case, so the code checks still count.
- An LLM claim split, if adopted, is its own follow-up, with its output cached per answer so every judge and every rescore sees the same claims.
