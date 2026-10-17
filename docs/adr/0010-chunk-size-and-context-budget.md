---
status: proposed
---

# Chunk size and the per-Company context budget: chosen on dev by a rule written before any run

Spec #14 says the chunk size and the per-Company context budget are "tuned by the evaluation". Neither has been: both are still the EDA's starting points (finding 15), prose chunks of about 600 tokens (never above 800, with 60 tokens of overlap) and 32,000 tokens of Source text per Answer Call, split evenly across the Companies in scope. The prompt iteration log blames the 14 dev Required Facts that no run reaches on that budget. This ADR records how the two settings are chosen. It is written before any run, so the rule cannot be fitted to the results.

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
