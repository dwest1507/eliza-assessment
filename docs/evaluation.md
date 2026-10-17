# Evaluation

How the system's quality is measured. Everything is scored against the [Golden Set](golden-set.md): choices are tuned on its dev split, and the holdout split is scored once per final setup, after every choice is made on dev, and never used to choose ([the holdout rule](#the-holdout-rule)). Two harnesses do the measuring: the [retrieval harness](#retrieval-harness) asks whether the right Sections reach the Answer Call; the [generation harness](#generation-harness) asks whether the answers are right, and what they cost. `make eval-export` puts their latest results in the workspace's "How it works" page ([Showing the results](#showing-the-results)).

Everything below describes Golden Set version 1 as measured. A review of this setup on 2026-10-17 found that it cannot see most real differences, and that some of its scores are measurement errors. Golden Set version 2, a Brief Suite, new decision thresholds and a check of the judge are decided but not built yet: see [Evaluation version 2](#evaluation-version-2).

## Retrieval harness

```sh
make eval-retrieval              # the dev split
make eval-retrieval SPLIT=all    # dev and holdout together; SPLIT=holdout only once per final setup
make eval-retrieval ARMS=fts5    # only some Arms (the Shipped Arm always runs)
make eval-retrieval ARMS=fts5 CHUNK_TOKENS=450 CONTEXT_BUDGET=24000   # another chunk size and context budget
```

It needs the index (`make index`, built automatically when missing) and no LLM call. The dense and hybrid Arms also need the chunk embeddings (`make embeddings`, built automatically when missing; see [Arm comparison](#arm-comparison)), and embed each question once, caching the vector, so a rerun makes no network call. It prints the scores and writes them as JSON to `data/derived/eval/retrieval-<split>.json`, for the evaluation export. `CHUNK_TOKENS` and `CONTEXT_BUDGET` score another chunk size or context budget without editing code ([ADR 0010](adr/0010-chunk-size-and-context-budget.md)): `CHUNK_TOKENS=450` reads `data/derived/edgar_rag-chunks450.sqlite`, built from the Corpus when missing (about 40 seconds), and the report goes to `retrieval-<split>-chunks450-budget24000.json`, so the shipped report is kept. Every report records its chunk size and context budget. The dense and hybrid Arms' embeddings belong to the shipped index, so use `ARMS=fts5` with `CHUNK_TOKENS`. The code is [`backend/src/edgar_eval/retrieval.py`](../backend/src/edgar_eval/retrieval.py); the Arms are in [`backend/src/edgar_eval/arms.py`](../backend/src/edgar_eval/arms.py).

### Method

1. **One run per case.** Each Golden Set case's conversation (its scripted history, then its question) is passed to each Arm. Multi-turn cases are therefore scored on their final turn, with the earlier turns available as they would be in the product.
2. **An Arm returns a ranking.** An Arm turns the conversation into the Sources it would put in the Answer Call, as (Filing ID, Section) pairs, best first. Every Source it returns reaches the Answer Call.
3. **The ranking is scored against the case's expected (Filing ID, Section) pairs.** Relevance is labelled by (Filing ID, Section) rather than by passage, so the labels survive any change to chunking.
   - **hit@k**: whether any expected pair is in the first k Sources.
   - **recall@k**: the share of the expected pairs in the first k Sources.
   - **hit@all, recall@all**: the same over every Source, so whether the pair reached the Answer Call at all.
   - **MRR**: the mean over cases of one over the rank of the first expected pair (0 when none is found).
   - **Sources**: the mean number of Sources returned, so a gain from simply returning more is visible.
   - **Tokens** and **evidence reached**, for an Arm that prepares the whole Answer Context (every Arm in `ARMS`): the mean tokens of Source text per Answer Context, and how many of the cases' Required Facts have their evidence quote, whitespace aside, in that text. The labels above are Sections, so a change of chunk size or context budget barely moves them; evidence reached shows whether the passages stating the facts reach the prompt, which no prompt can make up for ([ADR 0010](adr/0010-chunk-size-and-context-budget.md)).
4. **Scores are averaged overall and per question type.** Cases with no expected pair have nothing to find (a Company missing from the Corpus, General Electric today); they are listed as unscored. Whether those answers state their Coverage Gaps is the generation harness's job.
5. **Challengers are compared with the Shipped Arm question by question.** The gating metric is hit@10: about the first ten Sources are where the Answer Call's context budget starts to bite once several Companies share it. For each challenger, the cases are paired with the Shipped Arm's and McNemar's exact test is run on the discordant ones (cases only one Arm hit): a two-sided binomial test at p = 1/2. The challenger is reported **ahead** or **behind** when p < 0.05, and **indistinguishable** otherwise. On a Golden Set this small that is a high bar: among the discordant cases, 6 wins to 0 losses is ahead (p = 0.031) and so is 8 to 1 (p = 0.039), but 5 to 0 (p = 0.063) is indistinguishable. Small differences are reported as noise, not declared wins.

### The Arms

All Arms are defined in one tuple, `ARMS`, and the harness requires exactly one to be marked shipped. Each Arm runs inside the Query Scope's hard filters.

| Arm | What it does | Status |
|---|---|---|
| `fts5` | The retrieval seam as shipped: `bm25()` over the FTS5 index within each Company's hard filter ([ADR 0002](adr/0002-fts5-retrieval-in-one-derived-sqlite-file.md)) | **Shipped** |
| `dense` | OpenAI `text-embedding-3-small` embeddings of every chunk inside the hard filters, ranked by exact inner product with the question's embedding | Challenger |
| `hybrid` | Weighted reciprocal-rank fusion of the `bm25()` and dense rankings: each chunk scores `w / (1 + rank)` in each, with equal weights | Challenger |
| `rerank` | The first 20 chunks of the `bm25()` ranking re-ordered by the cross-encoder `cross-encoder/ms-marco-MiniLM-L6-v2` (ONNX, CPU, pinned to a Hugging Face commit); the rest follow in `bm25()` order | Challenger |

Every Arm is the shipped retrieval seam with its own ranker in place of `bm25()` (the `Ranker` hook of `prepare_answer_context`), so the Query Scope, hard filters, Section plan, per-Company budget, deduplication and change routing are the same for all four, and only the ranking differs. A ranker can return only chunks inside the hard filters. [ADR 0008](adr/0008-fts5-stays-the-shipped-arm.md) records the comparison and its result: FTS5 stays shipped.

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
- **hit@10 cannot move on this set from these changes alone.** Every case it misses is a follow-up or a figure question; the gain shows in recall@10, recall@all and MRR instead.

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

### After Coverage Gaps

Golden Set version 1, dev split, the same 17 scored cases. The stale GE Capital Filing is now kept out of retrieval unless a question asks for it by name, and a question naming only Companies missing from the Corpus retrieves nothing (prompt [v3](prompt-iterations.md#v3-coverage-gaps-and-each-companys-coverage)). Every metric is unchanged (hit@10 0.71, recall@10 0.65, MRR 0.59, 16.9 Sources), since the scored cases all name Companies in the Corpus. The change shows in the three unscored cases, which expect no Source: `stale-ge-recent-performance` goes from 7 Sources (all from the stale Filing) to none, `missing-citigroup` from 47 Sources (36 unrelated Companies) to none, and `followup-ge-to-honeywell` stays at none.

### After Financial Facts in the answer

Golden Set version 1, dev split, the same 17 scored cases. A question naming a metric (revenue, net income or a segment) now also gets the Financial Facts table, cited by one Facts Source per Filing and numbered before the text Sources ([ADR 0001](adr/0001-sqlite-financial-facts-store.md)). Text retrieval is unchanged, and the `fts5` Arm ranks only the text Sources: Facts Sources are looked up by rule, not retrieved, and the Golden Set labels Sections.

The scores are identical to [After Coverage Gaps](#after-coverage-gaps): hit@10 0.71, recall@10 0.65, MRR 0.59, 16.9 text Sources. This is expected, because the change adds context beside retrieval rather than changing it. What it adds shows in the figure cases' Required Facts instead:

- **Meta's revenue over two years and Tesla's net income over three years**: all five dollar figures their Required Facts state ($164,501 million and $200,966 million for Meta's 2024 and 2025 revenue; $14,997 million, $7,091 million and $3,794 million for Tesla's 2023–2025 net income) are rows in the Financial Facts table, each citing its 10-K. Before, they had to be read from MD&A text the retrieval ranked late (the first expected MD&A at rank 11 for Tesla).
- **JPMorgan's revenue** gets no rows (a Snapshot Company), and the prompt says any figure for it must be read from the Filing text and said to be.
- **"And what about Microsoft?"** names no metric, so it gets no Financial Facts until follow-ups inherit the earlier question's metric (ADR 0003).

The table costs about 700 to 1,100 prompt tokens for one Company over two or three years: eight to twelve quarters, the fiscal years, derived fourth quarters and year-on-year changes. It sits outside the per-Company text budget.

**How derived figures are checked.** The generation harness's figure check (below) asked this task to decide. A derived figure the table states is checked like any cited figure: each Facts Source's text states its reported rows, the year-on-year change of each, and the fourth quarters derived from it (a 10-K's year less its 10-Qs), so an answer that cites a derived row's tags cites text holding the figure. A figure the model computes itself, outside the table, is still unmatched unless it appears in a cited passage, and prompt rule 5 asks for such figures to be labelled as derived.

The holdout split has not been scored.

### After follow-up inheritance

Golden Set version 1, dev split, the same 17 scored cases. A follow-up now inherits each part of the Query Scope it does not name (the Companies, the time window, the Section hints, the metric, and its topic words when it has none of its own) from the most recent earlier question that named it ([ADR 0003](adr/0003-follow-ups-inherit-query-scope-by-rules.md)). Before, it was parsed on its own words alone. The "before" column is the harness run on the previous commit's code against the same index.

| | hit@10 | recall@10 | MRR | Sources |
|---|---|---|---|---|
| before | 0.71 | 0.65 | 0.59 | 16.9 |
| **after** | **0.88** | **0.82** | **0.73** | 12.3 |

Only the five multi-turn dev cases changed; every single-turn case scores exactly as before.

- `followup-regulatory-exposure` ("Which of them has the most regulatory exposure?"): 25 Sources from any Company and no hit → the three latest 10-Ks' Risk Factors, recall@10 1.00, first hit at rank 1.
- `followup-switch-to-msft` ("And what about Microsoft?"): no Sources (the question had no search word) → Microsoft's MD&A across the last two years and its revenue in the Financial Facts table, recall@10 1.00, first hit at rank 2.
- `followup-tsla-risk-change` ("How did that change over the last two years?"): 70 Sources from any Company → 8 Tesla Risk Factors Sources holding the paragraphs new in the window, recall@10 1.00, first hit at rank 1.
- `followup-ge-to-honeywell` ("What about Honeywell?"): still no Sources, now because Honeywell replaces General Electric and is a Company missing from the Corpus.
- `followup-topic-change-export-controls` (a new topic that names no Company): it found one expected NVIDIA Source at rank 25 before, by searching every Company; now it inherits Apple, as ADR 0003 predicts, and finds none. This is the known weakness the case is there to measure.

Computed Coverage Gaps now match the labels on all 20 dev cases: `followup-regulatory-exposure` gets its "Periods differ" gap, since it has Companies to compare.

The holdout split has not been scored.

### Arm comparison

Golden Set version 1, dev split, prompt v5, `gpt-6-luna`, judged by `jev-1.13.0`, 2026-10-16, on the retrieval as of [follow-up inheritance](#after-follow-up-inheritance). The three challengers of the spec were run through both harnesses, and the Shipped Arm was chosen by the spec's rule ([ADR 0008](adr/0008-fts5-stays-the-shipped-arm.md)).

```sh
make embeddings      # once: the dense and hybrid Arms' chunk embeddings (about 35 cents, about 25 minutes)
make eval-retrieval  # every Arm, no LLM call
make eval-arms       # every Arm through the generation harness, then the selection rule (about $0.07 per Arm)
```

**The rule** (`backend/src/edgar_eval/selection.py`). For each challenger, the dev cases both it and the Shipped Arm answered are paired, and an exact sign test is run on each score: Fact Recall and Faithfulness per case, and whether the case stated every expected Coverage Gap. Cases where the two tie, or that either could not score, are left out, as McNemar's test leaves out concordant cases. A challenger **qualifies** only if the test puts it **ahead** on Fact Recall (p < 0.05) and **behind** on neither Faithfulness nor Coverage Gaps. When several qualify, the cheapest per answer wins. When none does, the Shipped Arm stays. The rule is applied in code to the reports `make eval-arms` writes (`generation-arms-<split>-<arm>.json`), and the choice is written to `data/derived/eval/arm-choice-<split>.json`.

**The embeddings.** `make embeddings` embeds all 48,448 chunks of the index (17.4 million tokens) with `text-embedding-3-small` and stores them beside the index in `data/derived/embeddings/`, as a unit-length float32 matrix (300 MB) and its metadata, including a fingerprint of the index's chunks. Embeddings from a different index are refused, with a message to rebuild them. Batches are saved as they return, so a run stopped by OpenAI's rate limit resumes where it stopped, and the build is paced to stay under a 1M tokens-per-minute limit.

#### Retrieval

| Arm | hit@5 | hit@10 | hit@20 | hit@all | recall@10 | recall@all | MRR | Sources |
|---|---|---|---|---|---|---|---|---|
| **`fts5`** (shipped) | 0.82 | **0.88** | 0.94 | 0.94 | 0.82 | 0.91 | 0.73 | 12.3 |
| `dense` | 0.76 | 0.88 | 0.88 | 0.94 | 0.82 | 0.89 | 0.76 | 10.6 |
| `hybrid` | 0.82 | 0.88 | 0.88 | 0.94 | 0.82 | 0.87 | 0.80 | 11.6 |
| `rerank` | 0.76 | 0.88 | 0.94 | 0.94 | 0.82 | 0.91 | 0.68 | 12.3 |

All four Arms hit and miss exactly the same cases at hit@10, so McNemar's test finds no discordant case for any challenger (p = 1.000, indistinguishable). The two misses are the same for every Arm: Tesla's net income over three years, whose three expected 10-K MD&As rank behind the 10-Q MD&As' new text (the figures come from the Financial Facts table instead), and the topic-change follow-up that inherits Apple, the known weakness of ADR 0003. The FTS5 numbers are unchanged from [follow-up inheritance](#after-follow-up-inheritance), so adding the ranker hook changed nothing for the Shipped Arm.

- **Most of the work is done before ranking.** The hard filters and the Section plan leave each risk question only its Companies' latest Risk Factors, where every Arm finds the same Sources. Ranking only differs on the questions that search whole Filings.
- **The hybrid ranks the first expected Source highest (MRR 0.80)**, mainly on the outlook cases, where dense similarity puts the MD&A's forward-looking passages first. The dense Arm alone moves the stale GE Capital Filing's expected Section from rank 1 to 2 and Tesla's outlook from rank 1 to 7.
- **The cross-encoder lowers MRR (0.68).** It reads question and passage together, cut to 512 tokens, so a 600–800-token chunk is judged on its opening, and the model was trained on web search queries, not 10-K prose. On the outlook cases it moves the expected Sections down (Tesla rank 1 → 4, Meta 4 → 6).

#### Answers

| Arm | cases | citations valid | figures exact | gaps stated | Fact Recall | Faithfulness | $ per answer | latency s |
|---|---|---|---|---|---|---|---|---|
| **`fts5`** (shipped) | 19 | 0.84 | 0.95 | 1.00 | **0.54** | **0.95** | 0.0023 | 5.4 |
| `fts5` again (control) | 19 | 0.89 | 0.95 | 1.00 | 0.53 | 0.93 | 0.0023 | 5.7 |
| `dense` | 20 | 0.90 | 0.85 | 1.00 | 0.40 | 0.88 | 0.0026 | 5.9 |
| `hybrid` | 20 | 0.85 | 0.90 | 1.00 | 0.55 | 0.93 | 0.0026 | 5.9 |
| `rerank` | 19 | 0.89 | 0.95 | 1.00 | 0.55 | 0.94 | 0.0023 | 5.4 |

Jev refused to judge `trend-jpm-revenue-snapshot` on the `fts5` and `rerank` runs (`max_tokens_exceeded`, as in v3), so those runs score 19 cases. The comparisons below pair the 19 cases both sides scored.

| Challenger vs `fts5` | Fact Recall (higher / lower, exact p) | Faithfulness | Coverage Gaps | Qualifies |
|---|---|---|---|---|
| `dense` | 1 / 6, p = 0.125 | 2 / 8, p = 0.109 | 0 / 0, p = 1.000 | no |
| `hybrid` | 3 / 2, p = 1.000 | 2 / 7, p = 0.180 | 0 / 0, p = 1.000 | no |
| `rerank` | 2 / 2, p = 1.000 | 3 / 5, p = 0.727 | 0 / 0, p = 1.000 | no |
| `fts5` again (control) | 1 / 1, p = 1.000 | 3 / 5, p = 0.727 | 0 / 0, p = 1.000 | no |

**Chosen: `fts5`.** No challenger is ahead on Fact Recall, so none qualifies, and the Shipped Arm stays.

- **The control row is the noise floor.** Rerunning FTS5 against itself moves Faithfulness 3 cases up and 5 down, and Fact Recall 1 and 1, with nothing changed. The hybrid's and re-ranker's differences are that size. The dense Arm's are the largest (Fact Recall 1 up, 6 down) and point against it, though they are not significant either.
- **Dense retrieval loses the outlook facts.** Meta's capital expenditure outlook and Tesla's 2026 outlook fall from 1.00 and 0.50 Fact Recall to 0.00: the dense Arm reaches the right MD&A Sections but ranks general forward-looking passages above the specific sentences the Required Facts quote, which name the exact terms ("capital expenditures", "2026") that `bm25()` matches. It also states fewer figures exactly (0.85), since fewer of the passages it retrieves hold them.
- **Cost does not decide it.** Every Arm costs about a quarter of a cent per answer. The dense and hybrid Arms add an embedding call per question (a fraction of a thousandth of a cent, plus 0.2 to 0.6 seconds measured), a 300 MB matrix to rebuild whenever the chunks change, and an OpenAI dependency in retrieval. The cross-encoder adds about 1.4 seconds of CPU per Company searched (20 passages, measured on the development laptop). FTS5 adds nothing.

The holdout split was scored once, at the end, on FTS5 alone: see [The holdout run](#the-holdout-run).

## Generation harness

```sh
make eval-generation                       # the dev split, with the default generator (gpt-6-luna)
make eval-generation MODEL=gpt-6.1-sol     # another generator
make eval-generation MODEL=claude-sonnet-5-5   # a Claude generator (needs ANTHROPIC_API_KEY)
make eval-generation ARM=hybrid            # another retrieval Arm (see Arm comparison)
make eval-generation CONTEXT_BUDGET=48000  # another context budget (or CHUNK_TOKENS=...; see Chunk size and context budget)
make eval-generators                       # every compared generator, then the selection rule
make eval-generators MODELS="gpt-6-luna claude-haiku-5-5"   # only those: version 2's comparison
```

It runs each Golden Set case through the whole pipeline, one real Answer Call per case, and scores the answers. It calls the generator and the Jev judge, so it needs `JEV_API_KEY` and the key of the generator's provider (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, as the table of compared generators, `GENERATORS` in [`generators.py`](../backend/src/edgar_eval/generators.py), says) in `backend/.env`, and it costs money: about $0.07 for the 20 dev cases with `gpt-6-luna`, Jev included. It prints the scores and writes them, with every answer, every check's findings and every judgment, to `data/derived/eval/generation-<split>[-<model>].json`. The Answer Calls are logged to `data/derived/logs/answer_calls.jsonl` like any other. The code is [`backend/src/edgar_eval/generation.py`](../backend/src/edgar_eval/generation.py), with the checks in [`answer_checks.py`](../backend/src/edgar_eval/answer_checks.py) and the judge in [`judge.py`](../backend/src/edgar_eval/judge.py).

### Method

1. **One Answer Call per case.** Each case's conversation (scripted history, then question) goes to `prepare_answer_context` and then to one Answer Call, exactly as `make ask` and the API run it. Multi-turn cases are scored on their final turn. Cases run four at a time. Each Answer Call's record says why the model stopped, normalised across providers to `complete`, `token_cap` or `other` and kept with the provider's own value (OpenAI's `finish_reason`, Anthropic's `stop_reason`). An answer stopped at the token cap is **truncated**: it fails, its Fact Recall is 0 whatever Jev says, its Faithfulness is still judged on what it wrote, and the run counts and lists truncated answers. Answer Calls logged and reports saved before stop reasons were recorded have none, and load as they are.
2. **Checks in code.** An answer is read as units: each prose paragraph, list item and table body row, since each makes its own claims.
   - **Citation validity** (pass/fail per answer): every `[Sn]` tag names one of that turn's Sources, and every unit cites at least one. Tags may be grouped (`[S1, S2]`) or ranged (`[S1–S5]`). Exempt units: headings, table header rows, lead-ins ending in a colon, bold-only labels, the closing Coverage note, and units whose every sentence says what the Sources lack ("The Sources contain no Honeywell filings"), since there is nothing to cite for an absence.
   - **Figure exactness** (pass/fail per answer): every figure (an amount, a percentage or a count) matches a Financial Fact of a Filing the answer cites, or appears in a passage the answer cites. A Financial Fact of another Filing does not count, even the same Company's: a figure for another Report Period, or from a Filing the answer never cites, fails. A figure may be rounded and rescaled: "$416.2 billion" matches a passage reading "416,161" in a table in millions. A percentage must appear as written. Years, dates, single-digit counts and numbers inside labels (FY2025, Q3, 10-K, Item 1A, Filing IDs) are not figures. **Derived figures fail**: a growth rate, a difference or a share the model computed is in no passage and no Financial Fact. The spec asks for derived figures to be labelled as derived; how to check a labelled derivation is left to the Financial Facts task.
   - **Structure** (pass/fail per answer): the PE-analyst structure of assumption 8. The answer opens with a direct answer of at most three sentences of prose, not a heading, list or table; when its Sources come from two or more Companies, it has a heading naming each Company or a comparison table; it ends with a Coverage note, with no other heading after it; and it runs to 300–600 words, counted without Source tags or Markdown markup. An answer with no Sources (a missing Company, the stale GE Filing) is its Coverage Gaps alone, so only the opening rule applies to it. The report gives each failing answer's problems and the mean length in words.
   - **Coverage Gaps** (pass/fail per answer with expected gaps): every expected Coverage Gap is stated. A gap is stated for a Company when one sentence names the Company and says what the gap's kind says: the fixed wordings of EDA section 8.6, or a plain variant ("Wells Fargo is not in the Corpus", "do not include Wells Fargo filings", "guidance is not in the Filings", "the periods differ"). A sentence that names no Company counts for the Company its paragraph names, or for the only Company the gap is about. "Periods differ" is about the comparison, so it is stated once, not per Company. The wording rules are in `_GAP_MARKERS`; extra gaps an answer states are not penalised.
3. **Judgments by Jev.** Jev is TypeSafe's System One model: it returns typed answers with probabilities, not text, and it is from neither generator's family, so it judges OpenAI and Anthropic answers alike. It is pinned to `jev-1.13.0`, never an alias such as `jev-latest`, which moves with each release; the harness refuses a response from any other version.
   - **Fact Recall**: one request per answer, with the answer as the state and one yes/no question per Required Fact ("does the answer state this fact, in any wording?"). A fact counts as stated at a probability of at least 0.5. Every Required Fact is judged, whatever its tier. **Fact Recall** is the share of the case's must-state Required Facts stated, averaged over the cases that have any; **detail recall** is the same share over its detail facts, reported beside Fact Recall per case, per question type and overall, and never decided on. A case's report records each fact's tier (`fact_tiers`) beside both scores. Version 1's facts are all must-state, so its Fact Recall is the share of all its Required Facts and its detail recall is empty; reports saved before tiers existed name no tier and still load and rescore.
   - **Faithfulness**: every sentence of the answer is a claim; a sentence without a tag of its own rests on its unit's tags. Not claims: headings (with table header rows and bold-only labels), the closing Coverage note, and, among sentences that rest on no tag, lead-ins ending in a colon and sentences that state a Coverage Gap (the wordings `_GAP_MARKERS` recognises) or say what the Sources lack (the citation check's absence rule). Claims are grouped by the Sources they cite, one request per group, with those Sources' text as the state and one choice per claim between supported, unsupported and contradicted. Faithfulness is the share of claims supported by the Sources they cite, averaged over answers with claims. A claim citing no Source of the turn, an uncited sentence among them, is unsupported and is not sent to Jev, so an uncited paragraph from general knowledge lowers Faithfulness. Version 1's results below were scored before this rule, when only cited sentences were claims; on the 223 answers in the saved version 1 generation reports, the new rule leaves every cited claim as it was and adds 126 uncited ones in 36 answers, mostly list items under a cited lead-in and, in answers with no Sources, sentences on what Filings would be needed.
   - **Contradicted Claims** (pass/fail per answer): a claim Jev judges contradicted by the Sources it cites fails the answer, whatever its Faithfulness, beside the citation and Coverage Gap checks, so a wrong figure is not averaged away. Each case records its Contradicted Claims and their count; the run reports, overall and per question type, how many answers have one, and lists each such case's Contradicted Claims. Reports saved before this check (all of version 1's) lack those fields and still load; their claim verdicts are in each case's judgments.
4. **Cost and latency** come from each Answer Call's logged record: input and output tokens priced at the model's list price per million tokens (`GENERATORS` in `generators.py`: `gpt-6-luna` $0.10 in, $0.50 out; `gpt-6.1-sol` $2.00 in, $10.00 out, OpenAI's standard tier; `claude-sonnet-5-5` $2.00 in, $10.00 out; `claude-opus-5-5` $4.00 in, $20.00 out, Anthropic's API; all on 2026-10-16; and `claude-haiku-5-5` $0.10 in, $0.50 out, Anthropic's API for prompts under 100k tokens, on 2026-10-17), and the latency to the first text and to the end of the stream. Every input token is priced at the full rate, ignoring cached input, so the cost is an upper bound. Jev's own cost ($0.042 per million input tokens) is reported separately, since it is the evaluation's cost, not the product's.
5. **Scores are averaged overall and per question type**, and each failing case is listed by check, so a score can be traced to the answers behind it. A score with nothing to score (no Required Fact, no expected gap) is shown as `–`, not 0.

**Choosing the generator** (`make eval-generators`, `backend/src/edgar_eval/selection.py`). The generators, listed once with their providers and prices in `backend/src/edgar_eval/generators.py` (version 1 compared the four of user story 55; `claude-haiku-5-5` joined for version 2, and `MODELS="gpt-6-luna claude-haiku-5-5"` limits the run to those two, `gpt-6-luna` always running as the shipped one), answer the same dev cases on the Shipped Arm with the same template, each at its provider's nearest equivalent settings: OpenAI's reasoning effort `low` with a 2,500-token completion cap, and Anthropic's adaptive thinking at effort `low` with a 2,500-token cap (thinking counts in both caps). No refusal fallback is configured for the Claude models, since a fallback would answer with another model; a refused answer is reported as an error. `gpt-6-luna` stays unless a challenger is **ahead**, by the paired exact sign test, on Fact Recall or on Coverage Gaps, and **behind** on none of Fact Recall, Faithfulness and Coverage Gaps; when several qualify, the cheapest per answer wins. The default generator's report is written to `generation-<split>.json` and each other's to `generation-<split>-<model>.json`, and the choice to `data/derived/eval/generator-choice-<split>.json`.

**How the checks were validated.** The pure parts have unit tests on hand-written answers (`backend/tests/test_answer_checks.py`), and the judge's request shapes and version pin have tests with a fake Jev (`backend/tests/test_generation_harness.py`). Then every failure of the first live runs was read: each was either a real fault of the answer or a wording or format the checks had missed (range tags, a Coverage note opening mid-paragraph, "provide no Bristol Myers Squibb filing evidence"). Each miss became a test and a fix before the run below.

**Rescoring a fixed check.** The saved reports store each answer, so a corrected check is rerun on them offline with `make eval-rescore`: it prepares each case's Answer Context again through the Arm the report was answered on, at the context budget the report records (deterministic, no network call; a report from an index of another chunk size is refused), refuses a case whose Sources no longer number what they did, redoes the check and rewrites the report's scores in place, with no Answer Call and no Jev call. A rescore fixes a measurement and changes no choice, so it is allowed on the holdout. The figure check was made stricter this way on 2026-10-16: before, a figure passed if it matched any Financial Fact of a Company in the Query Scope or among the Sources, whichever Filing reported it. Every saved report from v5 on (the Arm comparison, the prompt iterations, the generator comparison and the holdout run) was rescored, and every figures-exact score in the tables below is unchanged: every figure that had passed on a Financial Fact also matched a cited Filing's or appeared in a cited passage. One answer gained a failure without changing a score: v10's `followup-switch-to-msft`, which already failed on that quarter's 18.4% growth, gives Microsoft's Q1 FY2026 revenue ($77,673 million) without citing the 10-Q that reports it. The runs before v5 (v1 and v3) have no saved report, so their figures-exact scores are as first measured, under the earlier rule.

### First scores on dev

Golden Set version 1, dev split (20 cases), prompt v1, `gpt-6-luna`, judged by `jev-1.13.0`, 2026-10-16. The retrieval is the tracer bullet's (as of commit `9b5f720`): Company recognition only, with no time windows, Section hints, deduplication, Sector phrases, follow-up inheritance, Coverage Gaps or Financial Facts in the prompt.

| | cases | citations valid | figures exact | gaps stated | Fact Recall | Faithfulness | $ per answer | latency s | first text s |
|---|---|---|---|---|---|---|---|---|---|
| **overall** | 20 | 0.75 | 0.85 | 0.67 | **0.45** | **0.90** | 0.0027 | 6.1 | 2.4 |
| figure_trend | 4 | 0.25 | 0.50 | 1.00 | 0.38 | 0.87 | 0.0024 | 4.7 | 2.2 |
| missing_company | 4 | 1.00 | 1.00 | 1.00 | 0.75 | 0.81 | 0.0021 | 5.2 | 2.3 |
| outlook | 2 | 1.00 | 1.00 | 1.00 | 0.75 | 1.00 | 0.0034 | 3.8 | 1.6 |
| risk | 6 | 0.83 | 1.00 | 0.33 | 0.25 | 0.89 | 0.0030 | 6.8 | 2.4 |
| sector | 2 | 0.50 | 0.50 | 1.00 | 0.33 | 0.92 | 0.0029 | 10.1 | 3.0 |
| stale_filing | 2 | 1.00 | 1.00 | 0.00 | 1.00 | 0.95 | 0.0029 | 6.7 | 2.9 |

Gaps stated is over the 12 dev cases with expected Coverage Gaps. The 20 answers averaged 24,900 input and 490 output tokens and cost $0.055 in all; the slowest took 10.6 seconds. Jev's judging cost $0.012.

- Citations invalid: `risk-aapl-tsla-jpm`, `sector-pharma-regulatory` (an uncited opening summary), `trend-jpm-revenue-snapshot`, `trend-meta-revenue-two-years` (uncited table rows of figures), `trend-tsla-net-income-three-years`.
- Figures not exact: `trend-meta-revenue-two-years`, `trend-tsla-net-income-three-years`, `sector-aerospace-government`: all derived figures (a two-year increase, a cumulative decline, a share of sales "calculated from those reported figures").
- Coverage Gaps not stated: `risk-aapl-tsla-jpm` and `followup-regulatory-exposure` (periods differ), `stale-ge-recent-performance` and `stale-gecc-eni-2014` (the GE Capital 2014 Filing is not called stale).

**What the numbers say**, and which later task each points to:

- **Answers are faithful but miss what they should say.** 90% of claims are supported by the Sources they cite, but under half the Required Facts are stated. The gap is mostly retrieval's: the tracer bullet fills the context with older Filings and the wrong Sections (see the retrieval numbers above), so the facts are often not in front of the model. Risk questions have the lowest Fact Recall (0.25). Time windows and Section hints, then deduplication and routing, are the tasks that should move Fact Recall.
- **Coverage Gaps are stated only when the Sources make them obvious.** Missing Companies and absent guidance are stated every time; differing periods and the stale GE Capital Filing are not, because nothing in the prompt computes them. Coverage Gaps end to end (fixed wordings in the prompt) should take this to 1.00.
- **Figures fail on derivations and uncited tables, not on wrong numbers.** No figure was found that contradicts its source; every unmatched one was computed by the model. Prompt work should make the model cite each table row and label derived figures; the Financial Facts task decides how derived figures are checked.
- **Cost is not a constraint.** About a quarter of a cent per answer with `gpt-6-luna` at about 25k input tokens, and about six seconds per answer, with the first text after about two and a half. This is the baseline the generator comparison prices other models against.
- **Run-to-run noise is large on 20 cases.** The same configuration run again during the checks' validation moved overall Fact Recall between 0.42 and 0.52 and Faithfulness between 0.88 and 0.94; one case moves a check's share by 0.05. Differences between prompt versions or generators of that size are noise, so the comparisons that choose between them should pair cases, as the retrieval harness does.

### After time windows, Section hints, risk routing and deduplication

The same configuration (prompt v1, `gpt-6-luna`, `jev-1.13.0`, 2026-10-16) on the retrieval as of [deduplication and change routing](#after-deduplication-and-change-routing), before Sector phrases.

| | cases | citations valid | figures exact | gaps stated | Fact Recall | Faithfulness | $ per answer | latency s | first text s |
|---|---|---|---|---|---|---|---|---|---|
| **overall** | 20 | 0.95 | 0.90 | 0.50 | **0.55** | **0.93** | 0.0026 | 6.1 | 2.3 |
| figure_trend | 4 | 0.75 | 0.50 | 0.00 | 0.38 | 0.83 | 0.0030 | 5.8 | 3.1 |
| missing_company | 4 | 1.00 | 1.00 | 1.00 | 0.75 | 1.00 | 0.0016 | 4.3 | 1.6 |
| outlook | 2 | 1.00 | 1.00 | 1.00 | 0.75 | 1.00 | 0.0033 | 4.6 | 1.1 |
| risk | 6 | 1.00 | 1.00 | 0.33 | 0.54 | 0.95 | 0.0026 | 6.1 | 1.9 |
| sector | 2 | 1.00 | 1.00 | 0.00 | 0.33 | 0.90 | 0.0029 | 11.2 | 4.0 |
| stale_filing | 2 | 1.00 | 1.00 | 0.00 | 1.00 | 0.92 | 0.0029 | 7.0 | 2.5 |

The answers averaged 23,900 input and 460 output tokens and cost $0.052 in all; the slowest took 14.9 seconds; Jev's judging cost $0.016. Citation validity was re-scored on the same answers after reading the failures: two follow-up answers said only that the earlier answer was not evidence, which the absence rule now recognises. Only `trend-meta-revenue-two-years` (uncited table rows) still fails it.

- **Fact Recall rose from 0.45 to 0.55, led by risk questions (0.25 to 0.54)**, as the retrieval numbers predicted: the latest 10-K's Risk Factors now reach the Answer Call. That is about two dev cases' worth, inside the run-to-run range above, so it is a direction, not yet a measured win; the prompt iterations should score both on paired cases.
- **Coverage Gaps fell from 0.67 to 0.50**, within noise, and the misses are the same kinds: differing periods, the stale GE Capital Filing and JPMorgan's snapshot, which nothing in the prompt computes yet.
- Figures and cost are unchanged: the two figure failures are derived figures again, and an answer still costs about a quarter of a cent.

### After Coverage Gaps (prompt v3)

`gpt-6-luna`, `jev-1.13.0`, 2026-10-16, prompt [v3](prompt-iterations.md#v3-coverage-gaps-and-each-companys-coverage), on the retrieval as of [Coverage Gaps](#after-coverage-gaps): Sector phrases are in, and the gaps are computed by code and stated in the prompt with fixed wordings. 19 of the 20 dev cases are scored: Jev refused to judge `trend-jpm-revenue-snapshot` (`max_tokens_exceeded`, its Sources too long for one judging request), so it has no row.

| | cases | citations valid | figures exact | gaps stated | Fact Recall | Faithfulness | $ per answer | latency s | first text s |
|---|---|---|---|---|---|---|---|---|---|
| **overall** | 19 | 0.79 | 0.95 | **0.91** | **0.55** | **0.90** | 0.0024 | 6.6 | 2.6 |
| figure_trend | 3 | 0.33 | 0.67 | – | 0.44 | 0.94 | 0.0027 | 5.3 | 3.1 |
| missing_company | 4 | 1.00 | 1.00 | 1.00 | 0.50 | 0.97 | 0.0010 | 5.6 | 2.4 |
| outlook | 2 | 1.00 | 1.00 | 1.00 | 0.75 | 0.95 | 0.0034 | 4.4 | 1.9 |
| risk | 6 | 0.83 | 1.00 | 0.67 | 0.49 | 0.87 | 0.0028 | 7.7 | 3.0 |
| sector | 2 | 1.00 | 1.00 | 1.00 | 0.50 | 0.83 | 0.0028 | 11.1 | 3.1 |
| stale_filing | 2 | 0.50 | 1.00 | 1.00 | 1.00 | 0.90 | 0.0019 | 4.4 | 1.2 |

The answers cost $0.045 in all; the slowest took 15.7 seconds; Jev's judging cost $0.015.

- **Coverage Gaps stated rose from 0.50 to 0.91** (11 scored cases with expected gaps). The stale GE Capital Filing, JPMorgan's and Bank of America's snapshots and the differing periods of the brief's first question, all missed before, are now stated, mostly in the fixed wording. The one miss is `followup-regulatory-exposure` ("Which of them has the most regulatory exposure?"): it names no Company, so until follow-ups inherit their Query Scope (ADR 0003) there are no Companies to compare periods for.
- **Fewer Sources for questions the Corpus cannot answer.** "What are Citigroup's main risk factors?" no longer carries 47 unrelated Sources, so the missing-Company answers cost $0.0010 on average against $0.0016, and the GE answer is the gap itself rather than a summary of GE Capital in 2014.
- **Citations fell from 0.95 to 0.79, mostly on the checks' wording rules, not on the answers.** `stale-ge-recent-performance` fails because its opening says the only Filing "is stale and left out of this answer", an absence the citation check does not yet recognise, and there is no Source to cite. `followup-regulatory-exposure` and `followup-switch-to-msft` fail on uncited sentences about earlier turns, and `trend-meta-revenue-two-years` on uncited table rows, as before. The stale-Filing wording should be added to the check's absence rule.
- Fact Recall (0.55) and Faithfulness (0.90 against 0.93) are within the run-to-run range measured above, and the answers cost about the same.

The holdout split has not been scored.

### After Financial Facts and follow-ups (prompt v5)

`gpt-6-luna`, `jev-1.13.0`, 2026-10-16, prompt [v5](prompt-iterations.md#v5-earlier-source-tags-named-as-filing-ids), on the retrieval as of [follow-up inheritance](#after-follow-up-inheritance). This is the first scored run since v3, so it also scores the Financial Facts table of [v4](prompt-iterations.md#v4-the-financial-facts-table). All 20 dev cases are scored.

| | cases | citations valid | figures exact | gaps stated | Fact Recall | Faithfulness | $ per answer | latency s | first text s |
|---|---|---|---|---|---|---|---|---|---|
| **overall** | 20 | 0.75 | 0.90 | **1.00** | **0.50** | **0.90** | 0.0024 | 6.1 | 1.9 |
| figure_trend | 4 | 0.50 | 0.50 | 1.00 | 0.46 | 0.86 | 0.0040 | 6.3 | 2.7 |
| missing_company | 4 | 0.75 | 1.00 | 1.00 | 0.50 | 0.95 | 0.0010 | 4.3 | 1.6 |
| outlook | 2 | 1.00 | 1.00 | 1.00 | 0.75 | 1.00 | 0.0033 | 4.0 | 1.4 |
| risk | 6 | 1.00 | 1.00 | 1.00 | 0.41 | 0.85 | 0.0021 | 7.4 | 1.8 |
| sector | 2 | 0.50 | 1.00 | 1.00 | 0.33 | 0.95 | 0.0028 | 9.7 | 2.5 |
| stale_filing | 2 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 0.0018 | 3.6 | 1.3 |

The answers cost $0.049 in all; the slowest took 12.8 seconds; Jev's judging cost $0.020.

- **Coverage Gaps stated rose from 0.91 to 1.00.** The v3 miss, `followup-regulatory-exposure`, now has Apple, Tesla and JPMorgan in scope, and its answer states the "Periods differ" gap in the fixed wording.
- **The follow-ups are answered about the right Companies.** "And what about Microsoft?" gets a table of Microsoft's FY2024, FY2025 and Q2 FY2026 revenue, every row cited to its Facts Source (Faithfulness 1.00); "How did that change over the last two years?" compares Tesla's FY2024 and FY2025 risk factors and cites the 2025 10-Qs' new tariff and tax-credit risks. Both cite only this turn's Sources: no uncited sentence about an earlier turn remains (two cases failed on those under v3). Their Fact Recall is low (0.00 and 0.33) because the Required Facts are worded as MD&A's "increased $36.6 billion or 15%", which the answers state as levels and derived percentages; the judge gave the Microsoft facts 0.03 to 0.44.
- **Citations (0.75) fail on the checks' rules, as in v3.** The uncited units are opening summaries that restate cited points (`sector-pharma-regulatory`, `trend-jpm-revenue-snapshot`), table rows of figures (`trend-meta-revenue-two-years`), and sentences saying what the Filings lack phrased in ways the absence rule doesn't yet recognise (`missing-wells-fargo-vs-jpm`, `stale-ge-recent-performance`).
- **Figures not exact** are both model-computed: Meta's quarterly differences ($36,465 million, $29,599 million) and Tesla's 74.7% decline, which the table does not state.
- Fact Recall (0.50 against 0.55) and Faithfulness (0.90 against 0.90) are within the run-to-run range, and the answers cost the same.

The holdout split has not been scored.

### After the prompt iterations (prompt v7)

`gpt-6-luna`, `jev-1.13.0`, 2026-10-16, prompt [v7](prompt-iterations.md#the-final-template-v7), on the same retrieval as v5. The template was tuned in five versions, v6 to v10, each written for named failing dev cases and kept only if it fixed them and the paired sign test put it behind its predecessor on nothing; v6 and v7 were kept and v8 to v10 discarded. A later pass on answer length, [v11 to v14](#answer-length-prompts-v11-to-v14), was discarded too. Each version's scores, the cases behind it and the paired tests are in the [prompt iteration log](prompt-iterations.md#the-iteration-pass-v6-to-v10). This is v7's second run; its first run scored structure 0.84, Fact Recall 0.63 and Faithfulness 0.95. The "How it works" page shows `gpt-6-luna`'s later run from the [generator comparison](#generator-comparison).

| | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | Faithfulness | $ per answer | latency s | first text s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **overall** | 20 | 0.90 | 0.95 | **1.00** | **0.90** | 404 | **0.65** | **0.91** | 0.0026 | 8.9 | 3.0 |
| figure_trend | 4 | 1.00 | 0.75 | 1.00 | 1.00 | 416 | 0.67 | 0.97 | 0.0043 | 10.3 | 3.7 |
| missing_company | 4 | 0.75 | 1.00 | 1.00 | 1.00 | 274 | 0.75 | 0.72 | 0.0011 | 6.3 | 2.6 |
| outlook | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 430 | 0.75 | 0.96 | 0.0036 | 8.6 | 2.6 |
| risk | 6 | 1.00 | 1.00 | 1.00 | 0.83 | 465 | 0.62 | 0.91 | 0.0023 | 9.6 | 3.1 |
| sector | 2 | 1.00 | 1.00 | 1.00 | 0.50 | 588 | 0.33 | 0.90 | 0.0029 | 12.9 | 3.9 |
| stale_filing | 2 | 0.50 | 1.00 | 1.00 | 1.00 | 251 | 1.00 | 0.92 | 0.0020 | 5.1 | 1.8 |

The answers cost $0.052 in all; the slowest took 13.6 seconds; Jev's judging cost $0.028.

- **Answers now have the analyst structure.** 0.90 of answers follow it, against 0.58 and 0.42 for v5's two runs scored by the same check, distinguishably so against one of them (9 cases higher, 0 lower, p = 0.004). Every answer opens with its direct answer and ends with a Coverage note. The two failures are length: the five-Company pharmaceutical answer runs to 632 words, and the topic-change follow-up, whose Sources are the wrong Company's (ADR 0003), to 273.
- **Answers state more of what the Sources say.** Fact Recall is 0.65 against v5's 0.54 and 0.53. Of the 30 dev Required Facts whose evidence reaches the prompt, 24 are stated against v5's 18; the other 14 never reach the prompt, which is retrieval's to fix (the pharmaceutical Companies' Inflation Reduction Act passages, for one).
- **The price is time, not money.** Answers are about 400 words and 800 output tokens against 250 and 490, so they finish in about 9 seconds rather than 5.5, with the first text after about 3 seconds. They cost $0.0026 against $0.0023.
- Faithfulness (0.91, and 0.95 in the first run) is within the run-to-run range of v5's 0.95 and 0.93. The missing-Company row's 0.72 is mostly `missing-bms-with-merck` (0.50), whose answer tags "Bristol Myers Squibb's regulatory risks cannot be assessed from the provided filings" with a Merck Source that does not say so; the topic-change follow-up does the same. That case scored 1.00 in every other run, and v10, which told the model not to tag such statements, did not stop the follow-up doing it.

### Generator comparison

Golden Set version 1, dev split (20 cases), prompt [v7](prompt-iterations.md#the-final-template-v7), the `fts5` Arm, judged by `jev-1.13.0`, 2026-10-16, run with `make eval-generators`. The four generators of user story 55 answered the same cases at their providers' nearest equivalent settings (see [Choosing the generator](#method) above), and the generator was chosen by the rule ([ADR 0009](adr/0009-gpt-6-luna-stays-the-generator.md)).

| | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | Faithfulness | input tokens | output tokens | $ per answer | latency s | first text s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **`gpt-6-luna`** (shipped) | 19 | 0.95 | 1.00 | 1.00 | 0.79 | 395 | **0.62** | **0.90** | 21,151 | 776 | 0.0025 | 7.9 | 2.8 |
| `gpt-6.1-sol` | 19 | 0.79 | 0.89 | 1.00 | 0.95 | 406 | 0.73 | 0.95 | 21,151 | 692 | 0.0492 | 13.2 | 1.4 |
| `claude-sonnet-5-5` | 20 | 0.60 | 1.00 | 1.00 | 0.80 | 479 | 0.74 | 0.92 | 33,924 | 1,267 | 0.0805 | 9.3 | 1.3 |
| `claude-opus-5-5` | 19 | 0.37 | 1.00 | 1.00 | 0.47 | 535 | 0.75 | 0.93 | 32,696 | 1,664 | 0.1641 | 15.8 | 3.7 |

Jev refused to judge `trend-jpm-revenue-snapshot` for every model but Sonnet (`max_tokens_exceeded`, as in earlier runs), so those score 19 cases; the comparisons pair the 19 cases both sides scored. Gaps stated is over the 11 or 12 scored cases with expected gaps. The answers cost $0.048 (Luna), $0.94 (Sol), $1.61 (Sonnet) and $3.12 (Opus) in all, and Jev's judging about $0.10 across the four.

| Challenger vs `gpt-6-luna` | Fact Recall (higher / lower, exact p) | Faithfulness | Coverage Gaps | Qualifies |
|---|---|---|---|---|
| `gpt-6.1-sol` | 4 / 1, p = 0.375 | 8 / 4, p = 0.388 | 0 / 0, p = 1.000 | no |
| `claude-sonnet-5-5` | 5 / 0, p = 0.062 | 8 / 6, p = 0.791 | 0 / 0, p = 1.000 | no |
| `claude-opus-5-5` | 5 / 0, p = 0.062 | 8 / 6, p = 0.791 | 0 / 0, p = 1.000 | no |

**Chosen: `gpt-6-luna`.** No challenger is ahead on Fact Recall or Coverage Gaps, so none qualifies.

- **Every challenger states more Required Facts, but not on enough cases.** Fact Recall is 0.73 to 0.75 against 0.62. Both Claude models are ahead on the same five cases (the Microsoft and Tesla follow-ups, Wells Fargo against JPMorgan, Meta's two years of revenue and the three-Company risk question) and behind on none: one case short of p < 0.05. Sol is ahead on four and behind on one. Luna's own v7 runs have scored 0.63, 0.65 and now 0.62.
- **Every model states every expected Coverage Gap**, so that test cannot separate them; the fixed wordings in the prompt (v3) settled it for all four.
- **The challengers cost 20 to 65 times as much.** Sol costs $0.049 per answer, Sonnet $0.081 and Opus $0.164, against Luna's $0.0025. Anthropic's tokenizer counts the same prompts as about 1.6 times as many input tokens, and the Claude models write longer answers (1,267 and 1,664 output tokens, thinking included, against 776). Sol and Sonnet show their first text sooner (1.3 to 1.4 seconds against 2.8) but Sol and Opus finish later (13 and 16 seconds against 8).
- **The Claude models break the checks v7 was tuned for.** Their answers run longer (479 and 535 words), open with four to seven sentences rather than two or three, and add uncited paragraphs: Opus's answer about Citigroup, a Company missing from the Corpus, adds a section on what Citigroup's 10-K would usually contain. Citation validity falls to 0.60 and 0.37, and Opus follows the structure in 0.47 of answers. The rule does not gate on these checks, but a switch to Claude would need its own prompt pass.
- **Sol's two figure failures are derived figures**, as in Luna's earlier runs: Tesla's cumulative net income decline and the increase Meta's 2026 capital expenditure range implies, both computed by the model and labelled as derived.

### The holdout run

The final configuration, the `fts5` Arm, `gpt-6-luna` and prompt v7 (with 600-token chunks and the 32k context budget, then untuned), run once on the holdout split (10 cases) on 2026-10-16, after every choice above was made on dev. Nothing was changed after it. The tuning that followed left what ships unchanged, so this run stands for the shipped setup ([Scoring the holdout once more](#scoring-the-holdout-once-more)).

```sh
make eval-retrieval SPLIT=holdout ARMS=fts5
make eval-generation SPLIT=holdout
```

**Retrieval** (Golden Set version 1, 10 cases, all with expected Sources):

| | cases | hit@5 | hit@10 | hit@20 | recall@10 | recall@all | MRR | Sources |
|---|---|---|---|---|---|---|---|---|
| **overall** | 10 | 0.90 | **0.90** | 1.00 | 0.88 | 0.97 | 0.72 | 12.8 |
| figure_trend | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.29 | 28.5 |
| outlook | 2 | 0.50 | 0.50 | 1.00 | 0.50 | 1.00 | 0.29 | 20.5 |
| risk | 3 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 6.3 |
| sector | 3 | 1.00 | 1.00 | 1.00 | 0.92 | 0.92 | 1.00 | 3.7 |

The one miss at hit@10 is `outlook-msft-cloud`, whose expected MD&A Section ranks between 11 and 20.

**Answers** (judged by `jev-1.13.0`):

| | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | Faithfulness | $ per answer | latency s | first text s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **overall** | 10 | 1.00 | 0.90 | 1.00 | 0.80 | 486 | **0.67** | **0.95** | 0.0030 | 9.5 | 3.1 |
| figure_trend | 2 | 1.00 | 0.50 | – | 1.00 | 348 | 0.67 | 0.90 | 0.0046 | 8.2 | 3.0 |
| outlook | 2 | 1.00 | 1.00 | 1.00 | 1.00 | 469 | 0.42 | 0.97 | 0.0035 | 10.0 | 3.7 |
| risk | 3 | 1.00 | 1.00 | 1.00 | 0.67 | 523 | 0.89 | 0.97 | 0.0022 | 9.5 | 3.1 |
| sector | 3 | 1.00 | 1.00 | 1.00 | 0.67 | 550 | 0.62 | 0.95 | 0.0025 | 9.9 | 2.8 |

Gaps stated is over the 6 holdout cases with expected gaps. The answers averaged 25,500 input and 960 output tokens and cost $0.030 in all; the slowest took 11.2 seconds; Jev's judging cost $0.012.

- **The holdout scores are in line with dev.** Fact Recall 0.67 and Faithfulness 0.95 against v7's 0.62 to 0.65 and 0.90 to 0.95 on dev; hit@10 0.90 against 0.88. On 10 cases one case moves a share by 0.10, so this says the dev choices did not overfit badly, not that the holdout is better.
- **The misses are on outlook and trend questions.** `outlook-msft-cloud` (Fact Recall 0.33) is the retrieval miss above, and leaves out Microsoft's remaining performance obligation and capital expenditure plans. `trend-amzn-aws-two-years` (0.33) states AWS's revenue but computes its own growth rate (19.7%) instead of quoting the MD&A's 19% and 20%. `outlook-nvda-revenue-two-years` (0.50) is a measurement miss, not an answer miss. This was first recorded as the answer leaving out the latest quarter's revenue and the H20 export charge, but on rereading (2026-10-17) the answer states both: Q3 FY2026 revenue of $57,006 million, up 62.5%, and the $4.5 billion H20 charge. Jev gave those facts 0.16 and 0.28 because each bundles a detail the answer does not give ("and 22% sequentially", "in the first quarter of fiscal 2026"). The "outlook changed" half of the question has no Required Fact at all ([Evaluation version 2](#evaluation-version-2)).
- **The one figure failure is a labelled derivation.** The Apple revenue answer gives FY2025 growth as "6.4% ... derived from those reported amounts", as prompt rule 5 asks; the check fails every derived figure by design.
- Two answers run over 600 words (621 and 609), the same length failure as on dev. Every citation is valid and every expected gap stated.

### Chunk size and context budget

Golden Set version 1, dev split, 2026-10-16, after the holdout run: the `fts5` Arm, `gpt-6-luna`, prompt v7, judged by `jev-1.13.0`. Prose chunks of about 600 tokens and a 32,000-token context budget were the EDA's starting points (finding 15), never tuned. The selection rule, the grid and how candidates reach the generation harness were written down and pushed before any run ([ADR 0010](adr/0010-chunk-size-and-context-budget.md)): a setting replaces them only if the sign test puts it ahead on Fact Recall and behind on neither Faithfulness nor Coverage Gaps, and the cheapest wins ties.

```sh
make eval-retrieval ARMS=fts5 CHUNK_TOKENS=450 CONTEXT_BUDGET=24000   # one setting of the grid, no LLM call
make eval-generation CONTEXT_BUDGET=48000                             # a candidate's answers (about $0.07-0.09)
cd backend && uv run python -m edgar_eval.selection compare SHIPPED.json CANDIDATE.json --rule settings
```

**Retrieval** on the 16 settings: Required Facts whose evidence reaches the prompt, of 44 (the full table, with hit@k, recall@k, MRR and tokens, is in the ADR).

| Chunk size | 16,000 | 24,000 | 32,000 | 48,000 |
|---|---|---|---|---|
| 300 | 21 | 23 | 24 | 26 |
| 450 | 18 | 25 | 27 | 29 |
| **600** | 22 | 27 | **30** (shipped) | 32 |
| 800 | 21 | 24 | 26 | 29 |

Every setting hits and misses the same cases at hit@10 (0.88). Only the 48k budget at 600-token chunks reaches more evidence than the shipped setting, so only it was answered, beside the shipped setting and a control rerun of it.

**Answers:**

| Setting | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | Faithfulness | input tokens | $ per answer | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **600 / 32k** (shipped) | 19 | 0.95 | 0.95 | 1.00 | 0.74 | 382 | **0.64** | **0.94** | 21,151 | 0.0025 | 6.8 |
| 600 / 32k again (control) | 19 | 0.95 | 1.00 | 1.00 | 0.74 | 387 | 0.68 | 0.97 | 21,151 | 0.0025 | 7.7 |
| 600 / 48k | 20 | 0.95 | 0.95 | 1.00 | 0.80 | 396 | 0.62 | 0.93 | 27,791 | 0.0032 | 7.7 |

| Setting vs 600 / 32k | Fact Recall (higher / lower, exact p) | Faithfulness | Coverage Gaps | Qualifies |
|---|---|---|---|---|
| 600 / 48k | 1 / 1, p = 1.000 | 5 / 5, p = 1.000 | 0 / 0, p = 1.000 | no |
| 600 / 32k again (control) | 3 / 1, p = 0.625 | 6 / 3, p = 0.508 | 0 / 0, p = 1.000 | no |

**Chosen: 600-token chunks and the 32k budget.** The setting did not change, so the index was not rebuilt with another chunk size and [the holdout run](#the-holdout-run) still describes the shipped setup.

- **More budget, the same answers.** The 48k budget states the one Inflation Reduction Act passage it adds (the pharmaceutical answer's Fact Recall 0.00 → 0.20), but the brief's risk comparison falls from 0.86 to 0.57 with the same seven facts in its prompt at both budgets. One up and one down is the control row's noise, and the budget costs 28% more per answer.
- **Smaller chunks rank better and reach less.** 450-token chunks have the best MRR (0.84 against 0.73), but carry less text around each match, and reach fewer Required Facts at every budget.
- **Of the 14 unreached facts, the budget can win two.** Five more sit in cases whose Sources do not fill even 48k, so the Section plan or the search terms leave them out; seven rank below what 48k holds.
- Jev refused to judge `trend-jpm-revenue-snapshot` on both 32k runs (`max_tokens_exceeded`, as before), so the comparisons pair 19 cases. The three runs cost $0.157 in Answer Calls and $0.075 in Jev judging, **about $0.23 in all**. The holdout split was not scored.

### Answer length (prompts v11 to v14)

Golden Set version 1, dev split, 2026-10-16, after the chunk size and context budget sweep: the `fts5` Arm with 600-token chunks and the 32k budget, `gpt-6-luna`, judged by `jev-1.13.0`. v7's answers follow the structure in 0.80 of dev answers over its five runs (0.74 to 0.90 a run), and the misses are mostly length: the comparisons of three or more Companies run over 600 words. Four versions, v11 to v14, gave each Company a budget of sentences, paragraphs or bullet points when the Sources cover three or more; the rule, from the ticket, was that a version ships only if the share following the structure rises and the sign test puts it behind v7 on none of Fact Recall, Faithfulness and Coverage Gaps. Each version's wording, scores and paired tests are in the [prompt iteration log](prompt-iterations.md#answer-length-v11-to-v14-discarded).

| | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | Faithfulness | $ per answer | latency s |
|---|---|---|---|---|---|---|---|---|---|---|
| **v7** (five runs, shipped) | 19-20 | 0.89-0.95 | 0.95-1.00 | 1.00 | **0.74-0.90** | 382-404 | **0.62-0.68** | **0.90-0.97** | 0.0025-0.0026 | 6.8-8.9 |
| v12 (two runs) | 19 | 0.95-1.00 | 0.95-1.00 | 1.00 | 0.74-0.84 | 383-390 | 0.66-0.73 | 0.92-0.96 | 0.0025 | 5.8-6.2 |
| v11, v13, v14 | 19-20 | 0.89-0.95 | 0.89-1.00 | 1.00 | 0.79-0.84 | 369-409 | 0.63-0.68 | 0.93-0.94 | 0.0025-0.0026 | 6.1-6.5 |

**v7 stays**, so the dev numbers [after the prompt iterations](#after-the-prompt-iterations-prompt-v7) and [the holdout run](#the-holdout-run) still describe the shipped template.

- **The share following the structure did not rise.** v12, the best first run, scored 0.84 and then 0.74: 30 of 38 answers (0.79) against v7's 77 of 96 (0.80).
- **A budget per Company shortened the five-Company answer, not the three-Company one.** The pharmaceutical comparison came in at 492 to 556 words under a sentence budget, against 627 to 785 in every v7 run. The brief's risk comparison of Apple, Tesla and JPMorgan ran over in every run of every version (601 to 722 words): the model gave each Company three paragraphs or bullets whatever the budget said.
- **v12's second run fell behind on Faithfulness** against one v7 run (1 case higher, 9 lower, p = 0.021). No version was ahead on anything.
- The five runs cost $0.238 in Answer Calls and $0.105 in Jev judging, **about $0.34 in all**. The holdout split was not scored.

### Scoring the holdout once more

The holdout run above came before two tickets that could change what ships, [the chunk size and context budget](#chunk-size-and-context-budget) and [the answer length](#answer-length-prompts-v11-to-v14); if either had, its numbers would describe a setup that is no longer demoed. The decision (2026-10-16) was to score the holdout once more only if what ships changed, by this rule, written down before any run.

#### The holdout rule

- **The holdout is scored once per final setup and never used to choose.** Every choice is made on dev. The holdout is scored once on the setup that ships after them, and again only if a later dev choice changes that setup: then one retrieval run and one generation run (`make eval-retrieval SPLIT=holdout ARMS=fts5`, `make eval-generation SPLIT=holdout`, about $0.04), shown beside the earlier run.
- **That run reports and decides nothing, and nothing changes after it.** Whatever it scores, no Arm, chunk size, context budget, template or generator is changed, and no Golden Set case is relabelled. A worse score is reported as it is.
- **It is read with the 10-case caveat.** On 10 cases one case moves a share by 0.10, so two holdout runs that differ by a case or two do not show that the setup got better or worse.
- Rescoring a saved holdout report offline with a corrected check ([Rescoring a fixed check](#generation-harness)) is not a run: it makes no Answer Call and changes no choice.
- **The rule applies per Golden Set version.** Version 2 brings 20 new holdout cases, scored once on the final version 2 setup ([ADR 0012](adr/0012-golden-set-version-2-and-the-brief-suite.md)). The version 1 holdout run below stands as recorded, and version 1's 10 holdout cases, scored once and never tuned on, join version 2's dev split.

**The setup a second run would measure** is the one that ships: the `fts5` Arm with prose chunks of about 600 tokens and a 32,000-token per-Company context budget, `gpt-6-luna` at reasoning effort `low`, prompt v7, judged by `jev-1.13.0`.

#### The first run stands

| | First holdout run (2026-10-16) | Ships now |
|---|---|---|
| Retrieval Arm | `fts5` | `fts5` ([ADR 0008](adr/0008-fts5-stays-the-shipped-arm.md)) |
| Chunk size | about 600 tokens (the EDA's starting point) | about 600 tokens ([ADR 0010](adr/0010-chunk-size-and-context-budget.md)) |
| Context budget per Company | 32,000 tokens (the EDA's starting point) | 32,000 tokens ([ADR 0010](adr/0010-chunk-size-and-context-budget.md)) |
| Generator | `gpt-6-luna` | `gpt-6-luna` ([ADR 0009](adr/0009-gpt-6-luna-stays-the-generator.md)) |
| Answer Call prompt | v7 | v7 (v11 to v14 discarded) |
| Judge | `jev-1.13.0` | `jev-1.13.0` |

**What ships did not change, so the holdout was not scored again**, and [the first holdout run](#the-holdout-run) stands for the shipped setup. The chunk size and context budget sweep kept 600-token chunks and the 32k budget, and the shipped index's chunks are byte-identical to the ones the first run searched; the answer length versions were discarded and v7 stays. The changes made since the first run alter how the setup is measured or served, not what it answers with: the stricter figure check was applied to the first run's saved answers offline, which prepared each holdout case's Answer Context again and found its Sources unchanged (every figures-exact score stayed the same); the retrieval seam was reorganised with no change in behaviour; and the chat API now refuses more turns than the prompt uses, which no Golden Set case reaches.

## Showing the results

```sh
make eval-export                 # the dev split's latest reports
make eval-export SPLIT=holdout   # the holdout's reports on their own
```

The export reads the harnesses' latest reports for the split from `data/derived/eval/`: `retrieval-<split>.json` (required; the retrieval harness runs first if it is missing, since it makes no LLM call) and every `generation-<split>[-<model>].json` (one scoreboard row per generator; none until `make eval-generation` has run, since that costs money). The Arm comparison's answer reports (`generation-arms-<split>-<arm>.json`) are not generator rows and are left out; the challengers show on the page through the retrieval report. When `make eval-generators` has run, it adds the generator comparison from `generator-choice-<split>.json`: each challenger's sign tests against the shipped generator and the generator chosen. A dev export also carries the holdout's reports, `retrieval-holdout.json` and every `generation-holdout[-<suffix>].json`, once the holdout has been scored, so the page shows the holdout run (or runs) beside the dev results the choices were made on. It adds the Corpus coverage grid, each Company's Filings by the calendar quarter of their Report Period, and writes everything to `frontend/data/eval-export.json` for the workspace's "How it works" page. The code is [`backend/src/edgar_eval/export.py`](../backend/src/edgar_eval/export.py).

The page shows what the reports hold, nothing more: per Arm, hit@k, recall@k at the gating k, recall@all, MRR and the mean number of Sources, with each challenger's McNemar verdict and the cases the Shipped Arm misses; per generator, the code checks, the Jev judgments, cost and latency, overall and per question type, with the shipped generator marked and each challenger's sign tests and whether it qualifies; and the holdout run's retrieval and answer scores in a section of their own, with the 10-case caveat. The export is committed, so the page shows the last results exported, dated on the page; the numbers in this document remain the record of each run.

## Evaluation version 2

Decided on 2026-10-17 and not built yet. Version 1's harnesses and results above stay as they are until it is.

### What the review found

The saved reports of version 1 (28 generation runs) were read case by case.

- **The brief's questions are not measured where they matter.**
  - *Example 1* (Apple, Tesla and JPMorgan, dev): all seven evidence quotes reach the prompt, and Fact Recall moves between 0.57 and 1.00 across the shipped setup's runs. The misses are details the answer happened to leave out, not wrong statements.
  - *Example 2* (NVIDIA): it is in the holdout, so it was scored once, and that score is a judging error ([the holdout run](#the-holdout-run)).
  - *Example 3* (pharmaceuticals, dev): it scored 0.00 Fact Recall in 24 of 27 runs, across every Arm and generator. None of its five evidence quotes reaches the prompt, and no Source even mentions the Inflation Reduction Act, so it ties in every comparison and has decided nothing.
- **The comparisons cannot see a real difference.** On 20 dev cases the two-sided sign test at p < 0.05 finds a real gain about one time in ten. Five of the 16 dev cases with Required Facts never change score in any run, so about 11 carry information. The generators' "indistinguishable" verdicts are not ties: Claude Sonnet 5.5 is +0.13 Fact Recall against `gpt-6-luna` (95% bootstrap interval +0.03 to +0.25), against +0.06 for the Control Run.
- **Some scores are measurement errors:**
  - **Compound Required Facts:** Jev marks a fact not stated when an answer gives most of it. Its probabilities have never been checked against a human's; 227 of the 1,190 fact judgments (19%) fall between 0.05 and 0.65, where the 0.5 cut-off decides.
  - **A dropped case:** Jev failed on long inputs in 16 of 28 runs. Each failure dropped `trend-jpm-revenue-snapshot`, a starter prompt, with its code checks, so the generator table compares means over 19 and 20 cases.
  - **Truncated answers:** two `claude-opus-5-5` answers stopped at the 2,500-token cap, which includes thinking, and were scored as complete.
  - **Uncited text:** Faithfulness judges only cited sentences, so an uncited paragraph from general knowledge is caught only by the pass/fail citation check.
  - **Contradicted claims averaged away:** 31 across all runs, each just a fraction of Faithfulness.
  - **A saturated retrieval gate:** hit@10 is identical for all four Arms and all 16 chunk-size and budget settings. Evidence Reached is the retrieval measure that varies.
  - **Labels drafted with the system's own rules:** an agent drafted every label, using the system's own Query Scope rules and Section plan, so the labels cannot catch where that plan falls short. The pharmaceutical question's "how are they addressing them" has one Required Fact.

### What changes

- **Decision thresholds** ([ADR 0011](adr/0011-one-sided-thresholds-and-a-control-run.md)): a challenger is ahead at one-sided p < 0.10 and behind on a guardrail (Faithfulness, Coverage Gaps, Contradicted Claims) at p < 0.20, with a Control Run in every comparison and the mean paired difference reported with a bootstrap interval. The retrieval harness gates on Evidence Reached, and it screens candidates for free: at most three per rule go on to paid Answer Calls, so the chance of a false switch stays near 20% instead of about 66% across version 1's 15 setting challengers.
- **Golden Set version 2 and the Brief Suite** ([ADR 0012](adr/0012-golden-set-version-2-and-the-brief-suite.md)): 60 dev and 20 new holdout cases, one-claim Required Facts that are must-state or detail, a split recorded per case, and the brief's questions with variants in a must-pass Brief Suite reported case by case ([Golden Set](golden-set.md#version-2)).
- **The judge** ([ADR 0013](adr/0013-jev-stays-the-judge-checked-by-a-judge-study.md)): Jev stays, checked first by a judge study against the developer's labels. The study sets the stated-fact cut-off and decides whether claims are split by an LLM. Its fact items use the rewritten one-claim Required Facts, and its claim labelling may stop at 100 items by a rule fixed in advance.
- **Measurement fixes in the harnesses:**
  - a Jev failure is recorded against its judgment, not the whole case;
  - an answer that stops at the token cap fails instead of being scored as complete (built: see [Method](#method-1), step 1);
  - Faithfulness judges every sentence, an uncited one counting as unsupported (built: [Method](#method-1), step 3);
  - any Contradicted Claim fails the answer (built: see [Method](#method-1), step 3);
  - each sentence goes to the judge with its heading and table header, so a table row or an "it" keeps its meaning;
  - the Brief Suite's cases are reported one by one.
- **Another generator:** `claude-haiku-5-5`, listed at `gpt-6-luna`'s price ($0.10 in, $0.50 out per million tokens, for prompts under 100k tokens, on 2026-10-17), is the one challenger to `gpt-6-luna` on version 2. It is in the table of compared generators, so `make eval-generation MODEL=claude-haiku-5-5` answers with it, and `make eval-generators MODELS="gpt-6-luna claude-haiku-5-5"` runs the comparison. The version 1 generators stay in the table, so their reports still price.

**Required Fact tiers are built:** a fact is `must_state` or `detail`, the loader checks it, and the generation harness scores Fact Recall on the must-state facts and reports detail recall beside it ([Method](#method), [Golden Set fields](golden-set.md#fields)). Version 1's facts all load as must-state, so its scores are unchanged.

### Order and cost

1. The Brief Suite and the label format.
2. The measurement fixes and the decision thresholds.
3. Version 1's 27 other cases, rewritten in the new format.
4. The judge study, on those rewritten facts.
5. Golden Set version 2's 53 new cases, drafted in slices of at most ten, one slice at a time, then the split frozen.
6. The Arm, settings and generator comparisons on it, then the holdout, once.

Labels are drafted in Claude Code, not through the API. The API spend is expected to be about $5 to $6, budgeted at $20 to allow for reruns: about $2 for the judge study and the rest for the comparisons and the Brief Suite, with `gpt-6-luna` and `claude-haiku-5-5` answering and Jev judging. The larger cost is the developer's time: about 4 to 7 hours labelling for the judge study and about 7 hours reviewing Golden Set version 2.
