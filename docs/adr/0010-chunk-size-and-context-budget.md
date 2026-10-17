---
status: accepted
---

# 600-token chunks and the 32k context budget stay: no setting beat them on paired cases

Spec #14 says the chunk size and the per-Company context budget are "tuned by the evaluation". Neither has been: both are still the EDA's starting points (finding 15), prose chunks of about 600 tokens (never above 800, with 60 tokens of overlap) and 32,000 tokens of Source text per Answer Call, split evenly across the Companies in scope. The prompt iteration log blames the 14 dev Required Facts that no run reaches on that budget. This ADR records how the two settings were chosen. The rule, the grid and how candidates reach the generation harness (the next three sections) were written and pushed before any run (commit `014194a`), so they could not be fitted to the results. We ran them on the Golden Set's dev split on 2026-10-16, and **600-token chunks and the 32k budget stay**. Only a 48k budget reached more Required Facts' evidence than the shipped setting, and its answers were not distinguishably better: one case higher on Fact Recall, one lower.

## The rule

A setting (a chunk size and a context budget) replaces 600-token chunks and the 32k budget only if the exact sign test, pairing the dev cases with the shipped setting's, puts it **ahead on Fact Recall** (p < 0.05) and **behind on neither Faithfulness nor Coverage Gaps**. When several settings qualify, the cheapest per answer wins. This is the Arm rule of ADR 0008, applied in code by `edgar_eval.selection` to the generation harness's reports.

## The grid

- **Chunk sizes:** 300, 450, 600 (shipped) and 800 target tokens. The ceiling and the overlap keep the shipped proportions: the ceiling is four thirds of the target (400, 600, 800, 1,067) and the overlap a tenth (30, 45, 60, 80).
- **Context budgets:** 16,000, 24,000, 32,000 (shipped) and 48,000 tokens per Answer Call.

All 16 settings are scored on the dev split with the retrieval harness, on the Shipped Arm (`fts5`) only: it makes no LLM call and costs nothing. Each chunk size needs its own index.

## Which settings reach the generation harness

The Golden Set labels relevance by (Filing ID, Section), so a bigger budget or a different chunk size barely moves hit@10: the same Sections are found, with more or less of their text. What decides whether an answer can state a Required Fact is whether the passage stating it reaches the prompt. So the retrieval harness also reports **evidence reached**: the share of each case's Required Facts whose evidence quote appears, whitespace aside, in the text of the Answer Context's Sources.

The generation harness then answers the dev split with:

1. the shipped setting, run fresh in the same session, as the side every candidate is paired with;
2. the shipped setting again, as a control, so the run-to-run noise is visible as in ADR 0008;
3. at most three candidates: the settings that reach the most Required Facts' evidence, ties broken by recall@all, then hit@10, then the smaller budget. A setting that reaches no more evidence than the shipped one cannot be ahead on Fact Recall for a reason retrieval explains, and is not run.

Spend is capped at about $1 in all, with `gpt-6-luna` and `jev-1.13.0` (about $0.07 per run at 32k; a 48k budget costs up to half as much again in input tokens). The holdout split is not scored.

## Results

### Retrieval: 16 settings, no LLM call

Golden Set version 1, dev split, the `fts5` Arm, prompt v7's retrieval. Every setting hits and misses the same cases at hit@10 (0.88), so the Section-level metrics barely separate them; evidence reached does.

| Chunk size | Budget | Evidence reached | hit@10 | recall@10 | recall@all | MRR | Sources | Source tokens |
|---|---|---|---|---|---|---|---|---|
| 300 | 16,000 | 21 of 44 | 0.88 | 0.82 | 0.91 | 0.79 | 10.6 | 15,462 |
| 300 | 24,000 | 23 of 44 | 0.88 | 0.82 | 0.91 | 0.79 | 11.4 | 21,571 |
| 300 | 32,000 | 24 of 44 | 0.88 | 0.82 | 0.91 | 0.79 | 12.1 | 25,790 |
| 300 | 48,000 | 26 of 44 | 0.88 | 0.82 | 0.91 | 0.79 | 12.5 | 29,754 |
| 450 | 16,000 | 18 of 44 | 0.88 | 0.79 | 0.88 | 0.84 | 10.0 | 15,591 |
| 450 | 24,000 | 25 of 44 | 0.88 | 0.82 | 0.91 | 0.84 | 11.7 | 22,297 |
| 450 | 32,000 | 27 of 44 | 0.88 | 0.82 | 0.91 | 0.84 | 12.6 | 27,539 |
| 450 | 48,000 | 29 of 44 | 0.88 | 0.82 | 0.91 | 0.84 | 13.1 | 33,574 |
| 600 | 16,000 | 22 of 44 | 0.88 | 0.79 | 0.81 | 0.73 | 9.7 | 15,720 |
| 600 | 24,000 | 27 of 44 | 0.88 | 0.82 | 0.91 | 0.73 | 11.7 | 22,413 |
| **600** | **32,000** (shipped) | **30 of 44** | 0.88 | 0.82 | 0.91 | 0.73 | 12.3 | 28,152 |
| 600 | 48,000 | 32 of 44 | 0.88 | 0.82 | 0.91 | 0.73 | 13.4 | 35,919 |
| 800 | 16,000 | 21 of 44 | 0.88 | 0.79 | 0.81 | 0.77 | 9.7 | 15,586 |
| 800 | 24,000 | 24 of 44 | 0.88 | 0.79 | 0.88 | 0.77 | 11.4 | 22,337 |
| 800 | 32,000 | 26 of 44 | 0.88 | 0.82 | 0.91 | 0.77 | 12.1 | 28,211 |
| 800 | 48,000 | 29 of 44 | 0.88 | 0.82 | 0.91 | 0.77 | 13.3 | 37,627 |

Source tokens are the mean tokens of Source text per Answer Context, Financial Facts Sources included (they sit outside the budget). The shipped setting's 30 of 44 matches the prompt iteration log's count of 14 Required Facts that never reach the prompt.

- **Only one setting reaches more evidence than the shipped one**: the 48k budget at 600-token chunks, 32 of 44. It adds one Inflation Reduction Act passage to the pharmaceutical sector question and a second JPMorgan revenue passage to `trend-jpm-revenue-snapshot`, for about 7,800 more tokens of Sources per answer. The other 12 stay out even at 48k. Five are in cases whose Sources do not fill even that budget (UnitedHealth's cybersecurity question, Merck's Keytruda forecast, Tesla's 2026 outlook, and the topic-change follow-up's two, ADR 0003), so the Section plan or the search terms leave them out, not the budget. The other seven (four pharmaceutical Inflation Reduction Act passages and Tesla's 10-K net income narrative) rank below what even 48k holds.
- **Every other chunk size reaches less at the same budget.** Smaller chunks rank the first expected Section higher (MRR 0.79 and 0.84 against 0.73) but carry less around each match; 800-token chunks spend the budget on fewer, longer passages. The count is not an artefact of chunk boundaries: counting a quote as reached when each half of it is in the Sources, so one spanning two chunks still counts, gives exactly the same numbers for all 16 settings.
- **A smaller budget always reaches less**, so no cheaper setting could be ahead on Fact Recall for a reason retrieval explains, and none was run through the generation harness.

### Answers: the shipped setting, a control and the 48k budget

`gpt-6-luna`, prompt v7, `jev-1.13.0`, the `fts5` Arm, 2026-10-16.

| Setting | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | Faithfulness | input tokens | $ per answer | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **600 / 32k** (shipped) | 19 | 0.95 | 0.95 | 1.00 | 0.74 | 382 | **0.64** | **0.94** | 21,151 | 0.0025 | 6.8 |
| 600 / 32k again (control) | 19 | 0.95 | 1.00 | 1.00 | 0.74 | 387 | 0.68 | 0.97 | 21,151 | 0.0025 | 7.7 |
| 600 / 48k | 20 | 0.95 | 0.95 | 1.00 | 0.80 | 396 | 0.62 | 0.93 | 27,791 | 0.0032 | 7.7 |

Jev refused to judge `trend-jpm-revenue-snapshot` on both 32k runs (`max_tokens_exceeded`, as in every earlier run); at 48k it judged it, so the comparisons pair the 19 cases both sides scored.

| Setting vs 600 / 32k | Fact Recall (higher / lower, exact p) | Faithfulness | Coverage Gaps | Qualifies |
|---|---|---|---|---|
| 600 / 48k | 1 / 1, p = 1.000 | 5 / 5, p = 1.000 | 0 / 0, p = 1.000 | no |
| 600 / 32k again (control) | 3 / 1, p = 0.625 | 6 / 3, p = 0.508 | 0 / 0, p = 1.000 | no |

**Chosen: 600-token chunks and the 32k budget.** The 48k budget is not ahead on Fact Recall, so it does not qualify. The rule was applied in code (`python -m edgar_eval.selection compare ... --rule settings`).

- **The extra evidence was stated once.** The pharmaceutical answer's Fact Recall rose from 0.00 to 0.20, stating the Inflation Reduction Act passage the 48k budget added. But the brief's risk comparison fell from 0.86 to 0.57 with the same seven facts in its prompt at both budgets, so the one gain and the one loss are run-to-run noise in size, as the control row shows: nothing changed and Fact Recall moved 3 cases up and 1 down.
- **The 48k budget costs 28% more per answer** ($0.0032 against $0.0025, 31% more input tokens) and adds about a second of latency.

**Spend.** The retrieval runs cost nothing. The three generation runs cost $0.157 in Answer Calls and $0.075 in Jev judging: **about $0.23 in all**, under the $1 cap. The holdout split was not scored.

## Considered options

- **Ship the 48k budget for the two Required Facts it adds.** They reach the prompt, but the answers did not state more facts on paired cases (1 up, 1 down), and the budget's cost is paid on every answer. Under the rule that is not a measured win.
- **Ship smaller chunks for their MRR (0.84 at 450 tokens against 0.73).** MRR measures where the first expected Section ranks, not what reaches the prompt; at every budget the smaller chunks reach fewer Required Facts' evidence, so they could only lose Fact Recall.
- **Measure evidence by Section, as the Golden Set labels relevance.** The Section-level metrics hit and miss the same cases for all 16 settings, because the hard filters and the Section plan choose the Sections before chunks are ranked. Evidence quotes are the only labels at passage level, so they are what a chunk size or budget can move.
- **Score the generation harness on more of the grid.** At about $0.07 a run it was affordable, but a setting that reaches no more evidence has no reason to state more facts, and every extra comparison is another chance to mistake noise for a win.

## Consequences

- `CHUNK_TOKENS` (600) and `CONTEXT_BUDGET_TOKENS` (32,000) stay in `edgar_rag.retrieval`. Both can now be set per harness run without editing code: `make eval-retrieval CHUNK_TOKENS=450 CONTEXT_BUDGET=24000 ARMS=fts5` builds an index of 450-token chunks beside the shipped one when it is missing, and every harness report records its chunk size and context budget and names the setting. The index records its chunk size in a `settings` table, so `INDEX_VERSION` is 5 and an older index asks for `make index`. The shipped index's chunks are unchanged.
- The retrieval harness reports **evidence reached** for every Arm that prepares the Answer Context. It is a cheap, free proxy for whether a retrieval change can move Fact Recall, and it is worth checking before paying for a generation run.
- **Revisit when** the Golden Set grows enough for a sign test to see a two-case difference, or when retrieval's ranking changes: a ranking that puts more of the 12 unreached facts near the top changes what each budget holds, so the budget question should be asked again. The 48k budget is the first candidate, at $0.0007 more per answer.
