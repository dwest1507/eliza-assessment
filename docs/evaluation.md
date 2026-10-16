# Evaluation

How the system's quality is measured. Everything is scored against the [Golden Set](golden-set.md): choices are tuned on its dev split, and the holdout split is scored once, at the end. Two harnesses do the measuring: the retrieval harness (below) asks whether the right Sections reach the Answer Call; the generation harness, still to come, asks whether the answers are right.

## Retrieval harness

```sh
make eval-retrieval              # the dev split
make eval-retrieval SPLIT=all    # dev and holdout together; SPLIT=holdout only once, at the end
```

It needs the index (`make index`, built automatically when missing) and no LLM or network call. It prints the scores and writes them as JSON to `data/derived/eval/retrieval-<split>.json`, for the evaluation export. The code is [`backend/src/edgar_eval/retrieval.py`](../backend/src/edgar_eval/retrieval.py); the Arms are in [`backend/src/edgar_eval/arms.py`](../backend/src/edgar_eval/arms.py).

### Method

1. **One run per case.** Each Golden Set case's conversation (its scripted history, then its question) is passed to each Arm. Multi-turn cases are therefore scored on their final turn, with the earlier turns available as they would be in the product.
2. **An Arm returns a ranking.** An Arm turns the conversation into the Sources it would put in the Answer Call, as (Filing ID, Section) pairs, best first. Every Source it returns reaches the Answer Call.
3. **The ranking is scored against the case's expected (Filing ID, Section) pairs.** Relevance is labelled by (Filing ID, Section) rather than by passage, so the labels survive any change to chunking.
   - **hit@k**: whether any expected pair is in the first k Sources.
   - **recall@k**: the share of the expected pairs in the first k Sources.
   - **hit@all, recall@all**: the same over every Source, so whether the pair reached the Answer Call at all.
   - **MRR**: the mean over cases of one over the rank of the first expected pair (0 when none is found).
   - **Sources**: the mean number of Sources returned, so a gain from simply returning more is visible.
4. **Scores are averaged overall and per question type.** Cases with no expected pair have nothing to find (a Company missing from the Corpus, General Electric today); they are listed as unscored. Whether those answers state their Coverage Gaps is the generation harness's job.
5. **Challengers are compared with the Shipped Arm question by question.** The gating metric is hit@10: about the first ten Sources are where the Answer Call's context budget starts to bite once several Companies share it. For each challenger, the cases are paired with the Shipped Arm's and McNemar's exact test is run on the discordant ones (cases only one Arm hit): a two-sided binomial test at p = 1/2. The challenger is reported **ahead** or **behind** when p < 0.05, and **indistinguishable** otherwise. On a Golden Set this small that is a high bar: among the discordant cases, 6 wins to 0 losses is ahead (p = 0.031) and so is 8 to 1 (p = 0.039), but 5 to 0 (p = 0.063) is indistinguishable. Small differences are reported as noise, not declared wins.

### The Arms

All Arms are defined in one tuple, `ARMS`, and the harness requires exactly one to be marked shipped. Each Arm runs inside the Query Scope's hard filters.

| Arm | What it does | Status |
|---|---|---|
| `fts5` | The retrieval seam as shipped: `bm25()` over the FTS5 index within each Company's hard filter ([ADR 0002](adr/0002-fts5-retrieval-in-one-derived-sqlite-file.md)) | **Shipped** |

The challengers of the spec (OpenAI dense embeddings, a reciprocal-rank-fusion hybrid, FTS5 re-ranked by a cross-encoder) are added to `ARMS` in the Arm comparison task.

**How the FTS5 ranking is read.** The retrieval seam retrieves each Company separately, with its own share of the context budget, and numbers each Company's Sources after the previous Company's. Ranking by Source number would put the last-named Company's best Source behind every other Company's worst, which would penalise multi-Company questions for the order the Companies were named in. The `fts5` Arm instead takes each Company's next-best Source in turn.

### First FTS5 numbers on dev

Golden Set version 1, dev split, prompt v1's retrieval seam (the tracer bullet: Company recognition only, no time window, Section hints, Sector phrases or follow-up inheritance).

17 cases scored; 3 unscored (`stale-ge-recent-performance`, `missing-citigroup`, `followup-ge-to-honeywell`).

| | cases | hit@5 | hit@10 | hit@20 | hit@all | recall@10 | recall@all | MRR | Sources |
|---|---|---|---|---|---|---|---|---|---|
| **overall** | 17 | 0.53 | **0.71** | 0.76 | 0.76 | 0.52 | 0.67 | 0.39 | 24.2 |
| figure_trend | 4 | 0.25 | 0.50 | 0.75 | 0.75 | 0.38 | 0.75 | 0.29 | 17.5 |
| missing_company | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.62 | 6.0 |
| outlook | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.62 | 28.5 |
| risk | 6 | 0.50 | 0.50 | 0.50 | 0.50 | 0.29 | 0.29 | 0.29 | 34.3 |
| sector | 2 | 0.00 | 1.00 | 1.00 | 1.00 | 0.27 | 0.80 | 0.13 | 29.0 |
| stale_filing | 1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 8.0 |

Missed at hit@10: `trend-tsla-net-income-three-years`, `followup-regulatory-exposure`, `followup-switch-to-msft`, `followup-tsla-risk-change`, `followup-topic-change-export-controls`.

**What the numbers say**, and which later task each points to:

- **Every multi-turn case misses.** The tracer bullet resolves the Query Scope from the latest message only. "Which of them has the most regulatory exposure?" names no Company, so it searches the whole Corpus. "And what about Microsoft?" names a Company but no topic: every other word is a stopword, so it retrieves nothing at all. Follow-up inheritance (ADR 0003) is the full query parser's task.
- **Older Filings crowd out the latest.** For the brief's first example, the expected pairs are the latest 10-K Risk Factors of Apple, Tesla and JPMorgan, plus Apple's later 10-Q. Only Apple's FY2025 10-K is found (rank 1). The rest of the budget goes to Apple's FY2024 and FY2022 10-K Risk Factors, Tesla's 10-Q Risk Factors and the Other Sections of its 10-Ks, and JPMorgan's 10-K Other Section and 10-Q financial review: text that matches "risk" and "factors" as well as the Risk Factors Section does. Recall@all is 0.25. The time window ("latest" means the latest 10-K and later 10-Qs) and Section hints come with the full query parser; near-duplicate removal across periods comes with deduplication and routing.
- **Figure questions find MD&A late.** Tesla's net income over three years expects three MD&As; all three are among the 33 Sources, but the first is at rank 14. Figures will come from the Financial Facts store first.
- **Sector questions find the right Filings without knowing the sector.** No Sector phrase is resolved yet, so they search the whole Corpus; the Risk Factors of the pharmaceutical and aerospace Companies still turn up, but late (MRR 0.13).
- **Single-Company questions already work.** Outlook, Coverage Gap and single-Company risk questions put an expected pair in the first five Sources.

The holdout split has not been scored.
