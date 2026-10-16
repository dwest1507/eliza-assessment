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

### After time windows, Section hints and risk routing

Golden Set version 1, dev split, the same 17 scored cases. The Query Scope now has a time window anchored on each Company's latest Filing, Section hints that are preferred with a fallback to the whole Filing when the Section is missing or a stub, and the risk route: a risk question with no time phrase goes to the latest 10-K's Risk Factors plus later 10-Qs that state risk text, and a later 10-Q whose Risk Factors only say "no material changes" is cited as it stands.

| | cases | hit@5 | hit@10 | hit@20 | hit@all | recall@10 | recall@all | MRR | Sources |
|---|---|---|---|---|---|---|---|---|---|
| **overall** | 17 | 0.59 | **0.71** | 0.76 | 0.76 | 0.58 | 0.74 | 0.53 | 18.5 |
| figure_trend | 4 | 0.25 | 0.50 | 0.75 | 0.75 | 0.38 | 0.75 | 0.30 | 15.2 |
| missing_company | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.0 |
| outlook | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.62 | 28.5 |
| risk | 6 | 0.50 | 0.50 | 0.50 | 0.50 | 0.42 | 0.42 | 0.50 | 22.3 |
| sector | 2 | 0.50 | 1.00 | 1.00 | 1.00 | 0.47 | 1.00 | 0.32 | 26.0 |
| stale_filing | 1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 8.0 |

Before → after, overall: hit@10 0.71 → 0.71, recall@10 0.52 → 0.58, recall@all 0.67 → 0.74, MRR 0.39 → 0.53, with fewer Sources (24.2 → 18.5). The same five cases miss at hit@10.

- **The brief's risk comparison now retrieves exactly its four expected pairs** (recall@all 0.25 → 1.00): the FY2025 10-K Risk Factors of Apple, Tesla and JPMorgan, and Apple's Q1 FY2026 10-Q pointer, and nothing else. JPMorgan's and Merck's risk questions (`missing-wells-fargo-vs-jpm`, `missing-bms-with-merck`) now return the one expected Source each, first.
- **Sector questions rank better** (MRR 0.13 → 0.32) because the pharmaceutical question is a risk question: each Company's search is held to its latest Risk Factors. The Sector phrase itself is still not resolved.
- **The misses are unchanged and belong to later tasks.** The four multi-turn misses need follow-up inheritance (ADR 0003): "How did that change over the last two years?" now gets the right window but, naming no Company or Section, searches every Company. Tesla's net income over three years now searches only its last 12 Filings, but the 10-Q MD&As rank ahead of the three expected 10-K MD&As (first at rank 11); figures will come from the Financial Facts store first.
- **hit@10 cannot move on this set from these changes alone.** Every case it misses is a follow-up or a figure question; the gain shows in recall and MRR instead.

### After deduplication and change routing

Golden Set version 1, dev split, the same 17 scored cases. Repeated text now costs the budget once ([ADR 0007](adr/0007-repeated-text-merged-only-when-identical.md)): a chunk repeated word for word across a Company's Filings is stored once and cited from the most recent Filing in the plan, or from a period the question names. A retrieved chunk at least 80% of whose 8-word shingles are in more recent retrieved chunks is dropped, and the more recent chunk takes its rank. A change question ("how has it changed", "what is new") ranks first the paragraphs new since the previous Filing of the same Form Type, cited from the Filing that added them.

| | cases | hit@5 | hit@10 | hit@20 | hit@all | recall@10 | recall@20 | recall@all | MRR | Sources |
|---|---|---|---|---|---|---|---|---|---|---|
| **overall** | 17 | 0.65 | **0.71** | 0.76 | 0.82 | 0.58 | 0.67 | 0.76 | 0.56 | 18.8 |
| figure_trend | 4 | 0.25 | 0.50 | 0.75 | 0.75 | 0.38 | 0.46 | 0.75 | 0.31 | 17.2 |
| missing_company | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.0 |
| outlook | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.62 | 26.5 |
| risk | 6 | 0.50 | 0.50 | 0.50 | 0.67 | 0.42 | 0.42 | 0.50 | 0.51 | 22.7 |
| sector | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 0.47 | 1.00 | 1.00 | 0.50 | 26.0 |
| stale_filing | 1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 8.0 |

Before → after, overall: hit@5 0.59 → 0.65, hit@10 0.71 → 0.71, hit@all 0.76 → 0.82, recall@20 0.74 → 0.67, recall@all 0.74 → 0.76, MRR 0.53 → 0.56, Sources 18.5 → 18.8. The same five cases miss at hit@10.

- **Older copies give way to the latest.** The aerospace sector question's first expected Source moves from rank 7 to 2, and Meta's revenue question from rank 10 to 6, as the older restatements that ranked ahead of them collapse into one copy each.
- **The topic-change follow-up now reaches the Answer Call.** `followup-topic-change-export-controls` finds one of its two expected Sources (rank 25) with the budget freed by dropped repeats; it still needs follow-up inheritance to rank well.
- **Figure questions phrased as change questions lose recall@20.** "How has Tesla's net income changed over the past three years?" and Meta's revenue question are change questions, so the new text of every 10-Q MD&A (mostly updated quarterly figures) ranks ahead of the expected 10-K MD&As: recall@20 for figure questions falls from 0.75 to 0.46, while recall@all is unchanged (0.75). Counting only prose as new text recovered some of it (recall@20 0.71 overall) but cost MRR (0.53), a trade on four cases that is noise. It is left as is: figure questions go to the Financial Facts store first.
- **Only 7% of chunks repeat word for word.** Index-time merging saves little because a chunk usually holds at least one small edit. Query-time near-duplicate removal is what keeps restated text out of the budget.

### After Sector phrases

Golden Set version 1, dev split, the same 17 scored cases, on top of deduplication and change routing. Sector phrases now resolve through the Sector table's industry and sector columns (assumption 5), so "the major pharmaceutical companies" is JNJ, LLY, MRK, PFE and ABBV and "the aerospace and defense companies" is BA, LMT and RTX, each with its own share of the budget. The phrase is taken out of the search terms like a Company name.

| | cases | hit@5 | hit@10 | hit@20 | hit@all | recall@10 | recall@20 | recall@all | MRR | Sources |
|---|---|---|---|---|---|---|---|---|---|---|
| **overall** | 17 | 0.65 | **0.71** | 0.76 | 0.82 | 0.65 | 0.67 | 0.76 | 0.59 | 16.9 |
| figure_trend | 4 | 0.25 | 0.50 | 0.75 | 0.75 | 0.38 | 0.46 | 0.75 | 0.31 | 17.2 |
| missing_company | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.0 |
| outlook | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.62 | 26.5 |
| risk | 6 | 0.50 | 0.50 | 0.50 | 0.67 | 0.42 | 0.42 | 0.50 | 0.51 | 22.7 |
| sector | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.75 | 9.5 |
| stale_filing | 1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 8.0 |

Before → after, overall: hit@10 0.71 → 0.71, recall@10 0.58 → 0.65, MRR 0.56 → 0.59, Sources 18.8 → 16.9. Only the two sector cases change: recall@10 0.47 → 1.00, MRR 0.50 → 0.75, and 26.0 → 9.5 Sources, because each case now searches only its Companies' latest Risk Factors instead of every Company's. The same five cases miss at hit@10, for the reasons above.

The holdout split has not been scored.
