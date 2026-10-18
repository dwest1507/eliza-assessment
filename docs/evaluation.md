# Evaluation

How the system's quality is measured. Everything is scored against the [Golden Set](golden-set.md): choices are tuned on its dev split, and the holdout split is scored once per final setup, after every choice is made on dev, and never used to choose ([the holdout rule](#the-holdout-rule)). Two harnesses do the measuring: the [retrieval harness](#retrieval-harness) asks whether the right Sections reach the Answer Call; the [generation harness](#generation-harness) asks whether the answers are right, and what they cost. `make eval-export` puts their latest results in the workspace's "How it works" page ([Showing the results](#showing-the-results)).

Everything below describes Golden Set version 1 as measured. A review of this setup on 2026-10-17 found that it cannot see most real differences, and that some of its scores are measurement errors. Golden Set version 2 is built, with its split frozen at 60 dev and 20 holdout cases, and is now the harnesses' default; its dev split has been measured, and the comparisons on it confirm every shipped choice ([The version 2 comparisons on dev](#the-version-2-comparisons-on-dev)); the Brief Suite is built, with the brief's three questions ([The Brief Suite run](#the-brief-suite-run)): see [Evaluation version 2](#evaluation-version-2).

## Retrieval harness

```sh
make eval-retrieval              # the dev split
make eval-retrieval SPLIT=all    # dev and holdout together; SPLIT=holdout only once per final setup
make eval-retrieval ARMS=fts5    # only some Arms (the Shipped Arm always runs)
make eval-retrieval ARMS=fts5 CHUNK_TOKENS=450 CONTEXT_BUDGET=24000   # another chunk size and context budget
```

It needs the index (`make index`, built automatically when missing) and no LLM call. The dense and hybrid Arms also need the chunk embeddings (`make embeddings`, built automatically when missing; see [Arm comparison](#arm-comparison)), and embed each question once, caching the vector, so a rerun makes no network call. The `dense-local` and `hybrid-local` Arms need local chunk embeddings (`make local-embeddings`, free, built automatically when missing; see [The one-call rule and the local Arms](#the-one-call-rule-and-the-local-arms)), and embed each question on the machine, with no network call at all. It prints the scores and writes them as JSON to `data/derived/eval/retrieval-<split>.json`, for the evaluation export. `CHUNK_TOKENS` and `CONTEXT_BUDGET` score another chunk size or context budget without editing code ([ADR 0010](adr/0010-chunk-size-and-context-budget.md)): `CHUNK_TOKENS=450` reads `data/derived/edgar_rag-chunks450.sqlite`, built from the Corpus when missing (about 40 seconds), and the report goes to `retrieval-<split>-chunks450-budget24000.json`, so the shipped report is kept. Every report records its chunk size and context budget. The embedding Arms' embeddings belong to the shipped index, so use `ARMS=fts5` with `CHUNK_TOKENS`. The code is [`backend/src/edgar_eval/retrieval.py`](../backend/src/edgar_eval/retrieval.py); the Arms are in [`backend/src/edgar_eval/arms.py`](../backend/src/edgar_eval/arms.py).

### Method

1. **One run per case.** Each Golden Set case's conversation (its scripted history, then its question) is passed to each Arm. Multi-turn cases are therefore scored on their final turn, with the earlier turns available as they would be in the product.
2. **An Arm returns a ranking.** An Arm turns the conversation into the Sources it would put in the Answer Call, as (Filing ID, Section) pairs, best first. Every Source it returns reaches the Answer Call.
3. **The ranking is scored against the case's expected (Filing ID, Section) pairs.** Relevance is labelled by (Filing ID, Section) rather than by passage, so the labels survive any change to chunking.
   - **hit@k**: whether any expected pair is in the first k Sources.
   - **recall@k**: the share of the expected pairs in the first k Sources.
   - **hit@all, recall@all**: the same over every Source, so whether the pair reached the Answer Call at all.
   - **MRR**: the mean over cases of one over the rank of the first expected pair (0 when none is found).
   - **Sources**: the mean number of Sources returned, so a gain from simply returning more is visible.
   - **Tokens** and **evidence reached**, for an Arm that prepares the whole Answer Context (every Arm in `ARMS`): the mean tokens of Source text per Answer Context, and how many of the cases' Required Facts have their evidence quote, whitespace aside, in that text. The report records Evidence Reached per Required Fact (each case's `evidence_reached`, in the case's fact order), and the printout lists the cases with a fact not reached. The labels above are Sections, so a change of chunk size or context budget barely moves them; evidence reached shows whether the passages stating the facts reach the prompt, which no prompt can make up for ([ADR 0010](adr/0010-chunk-size-and-context-budget.md)).
4. **Scores are averaged overall and per question type.** Cases with no expected pair have nothing to find (a Company missing from the Corpus, General Electric today); they are listed as unscored. Whether those answers state their Coverage Gaps is the generation harness's job.
5. **Challengers are gated on Evidence Reached, fact by fact** (built for version 2: see [The gate and the screen](#the-gate-and-the-screen)). For each challenger, every Required Fact of the scored cases is paired with the Shipped Arm's, and McNemar's exact test is run on the discordant ones (facts only one Arm's Answer Context reached), one-sided, under the selection rules' thresholds: **ahead** at p < 0.10, **behind** at p < 0.20, **indistinguishable** otherwise. hit@k, recall@k and MRR are still reported, but not gated on. Until this was built the gate was hit@10, paired per case and two-sided at p < 0.05; that gate gave the same result for every Arm and every chunk size and context budget, and the version 1 results below were recorded under it.

### The Arms

All Arms are defined in one tuple, `ARMS`, and the harness requires exactly one to be marked shipped. Each Arm runs inside the Query Scope's hard filters.

| Arm | What it does | API call at query time | Status |
|---|---|---|---|
| `fts5` | The retrieval seam as shipped: `bm25()` over the FTS5 index within each Company's hard filter ([ADR 0002](adr/0002-fts5-retrieval-in-one-derived-sqlite-file.md)) | No | **Shipped** |
| `dense` | OpenAI `text-embedding-3-small` embeddings of every chunk inside the hard filters, ranked by exact inner product with the question's embedding | Yes: embeds the question with OpenAI | Challenger, can't ship |
| `hybrid` | Weighted reciprocal-rank fusion of the `bm25()` and dense rankings: each chunk scores `w / (1 + rank)` in each, with equal weights | Yes, as `dense` | Challenger, can't ship |
| `rerank` | The first 20 chunks of the `bm25()` ranking re-ordered by the cross-encoder `cross-encoder/ms-marco-MiniLM-L6-v2` (ONNX, CPU, pinned to a Hugging Face commit); the rest follow in `bm25()` order | No | Challenger |
| `dense-local` | As `dense`, with the chunks and the question embedded by the local `BAAI/bge-small-en-v1.5` (ONNX, CPU, pinned to a Hugging Face commit) | No | Challenger |
| `hybrid-local` | As `hybrid`, fusing `bm25()` with `dense-local` | No | Challenger |

Every Arm is the shipped retrieval seam with its own ranker in place of `bm25()` (the `Ranker` hook of `prepare_answer_context`), so the Query Scope, hard filters, Section plan, per-Company budget, deduplication and change routing are the same for all of them, and only the ranking differs.

**Which Arms can ship.** The Answer Call is a question's only API call ([assumption 1](assumptions.md#1-one-api-call-per-question), the stricter reading accepted on 2026-10-17). Each Arm records whether it makes another API call at query time (`query_api_call` in `arms.py`, and in each Arm's scores in `retrieval-<split>.json` and in each generation report). `dense` and `hybrid` do, so they can't ship: they are still scored and gated, unconstrained, and reported as "available if the one-call limit is lifted", but the screen never sends them to a paid run and the Arm rule never chooses them ([The one-call rule and the local Arms](#the-one-call-rule-and-the-local-arms)). `fts5`, `rerank`, `dense-local` and `hybrid-local` run locally and can ship. A ranker can return only chunks inside the hard filters. [ADR 0008](adr/0008-fts5-stays-the-shipped-arm.md) records the comparison and its result: FTS5 stays shipped.

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
make local-embeddings  # once: the dense-local and hybrid-local Arms' chunk embeddings (free, about 30 minutes)
make eval-retrieval  # every Arm, no LLM call
make eval-arms       # every Arm through the generation harness, then the selection rule (about $0.07 per Arm on version 1's dev, $0.25 on version 2's)
```

**The rule** (`backend/src/edgar_eval/selection.py`). For each challenger, the dev cases both it and the Shipped Arm answered are paired, and an exact sign test is run on each score: Fact Recall and Faithfulness per case, and whether the case stated every expected Coverage Gap. Cases where the two tie, or that either could not score, are left out, as McNemar's test leaves out concordant cases. Each score pairs only the cases both sides scored, so a case missing a score on one side (a failed judgment, or a case only one side answered) is never counted as a zero, and the comparison reports, per score, how many cases it paired and how many it left out (`paired` and `left_out` in the choice file). A challenger **qualifies** only if the test puts it **ahead** on Fact Recall (p < 0.05) and **behind** on neither Faithfulness nor Coverage Gaps. When several qualify, the cheapest per answer wins. When none does, the Shipped Arm stays. The rule is applied in code to the reports `make eval-arms` writes (`generation-arms-<split>-<arm>.json`), and the choice is written to `data/derived/eval/arm-choice-<split>.json`. That is version 1's rule, which every comparison in this section was decided by; the code now applies [ADR 0011's one-sided thresholds](#the-one-sided-thresholds) instead, and version 1's choice files are records, never recomputed.

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
make eval-generators                       # gpt-6-luna and claude-haiku-5-5 (version 2's comparison), then the selection rule
make eval-generators MODELS=               # every compared generator in the table, version 1's four included
make eval-brief                            # the Brief Suite, 5 runs a case, a verdict per case
```

It runs each Golden Set case through the whole pipeline, one real Answer Call per case, and scores the answers. Before the first Answer Call it prints the run's estimated cost. It calls the generator and the Jev judge, so it needs `JEV_API_KEY` and the key of the generator's provider (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, as the table of compared generators, `GENERATORS` in [`generators.py`](../backend/src/edgar_eval/generators.py), says) in `backend/.env`, and it costs money: about $0.25 for version 2's 60 dev cases with `gpt-6-luna`, Jev included ($0.17 in Answer Calls and $0.08 to $0.09 in Jev judging, measured on 2026-10-17), against about $0.07 for version 1's 20. It prints the scores and writes them, with every answer, every check's findings and every judgment, to `data/derived/eval/generation-<split>[-<model>].json`. The Answer Calls are logged to `data/derived/logs/answer_calls.jsonl` like any other. The code is [`backend/src/edgar_eval/generation.py`](../backend/src/edgar_eval/generation.py), with the checks in [`answer_checks.py`](../backend/src/edgar_eval/answer_checks.py) and the judge in [`judge.py`](../backend/src/edgar_eval/judge.py).

### Method

1. **One Answer Call per case.** Each case's conversation (scripted history, then question) goes to `prepare_answer_context` and then to one Answer Call, exactly as `make ask` and the API run it. Multi-turn cases are scored on their final turn. Cases run four at a time. Each Answer Call's record says why the model stopped, normalised across providers to `complete`, `token_cap` or `other` and kept with the provider's own value (OpenAI's `finish_reason`, Anthropic's `stop_reason`). An answer stopped at the token cap is **truncated**: it fails, its Fact Recall is 0 whatever Jev says, even when its Fact Recall judgment failed (truncation comes from the stop reason, not from Jev, so the 0 is paired by the selection rule rather than left out; built for issue #90), its Faithfulness is still judged on what it wrote, and the run counts and lists truncated answers. Answer Calls logged and reports saved before stop reasons were recorded have none, and load as they are.
2. **Checks in code.** An answer is read as units: each prose paragraph, list item and table body row, since each makes its own claims.
   - **Citation validity** (pass/fail per answer): every `[Sn]` tag names one of that turn's Sources, and every unit cites at least one. Tags may be grouped (`[S1, S2]`) or ranged (`[S1–S5]`). Exempt units: headings, table header rows, lead-ins ending in a colon, bold-only labels, the closing Coverage note, and units whose every sentence says what the Sources lack ("The Sources contain no Honeywell filings"), since there is nothing to cite for an absence.
   - **Figure exactness** (pass/fail per answer): every figure (an amount, a percentage or a count) matches a Financial Fact of a Filing the answer cites, or appears in a passage the answer cites. A Financial Fact of another Filing does not count, even the same Company's: a figure for another Report Period, or from a Filing the answer never cites, fails. A figure may be rounded and rescaled: "$416.2 billion" matches a passage reading "416,161" in a table in millions. A percentage must appear as written. Years, dates, single-digit counts and numbers inside labels (FY2025, Q3, 10-K, Item 1A, Filing IDs) are not figures. **Derived figures fail**: a growth rate, a difference or a share the model computed is in no passage and no Financial Fact. The spec asks for derived figures to be labelled as derived; how to check a labelled derivation is left to the Financial Facts task.
   - **Structure** (pass/fail per answer): the PE-analyst structure of assumption 8. The answer opens with a direct answer of at most three sentences of prose, not a heading, list or table; when its Sources come from two or more Companies, it has a heading naming each Company or a comparison table; it ends with a Coverage note, with no other heading after it; and it runs to 300–600 words, counted without Source tags or Markdown markup. An answer with no Sources (a missing Company, the stale GE Filing) is its Coverage Gaps alone, so only the opening rule applies to it. The report gives each failing answer's problems and the mean length in words.
   - **Coverage Gaps** (pass/fail per answer with expected gaps): every expected Coverage Gap is stated. A gap is stated for a Company when one sentence names the Company and says what the gap's kind says: the fixed wordings of EDA section 8.6, or a plain variant ("Wells Fargo is not in the Corpus", "do not include Wells Fargo filings", "guidance is not in the Filings", "the periods differ"). A sentence that names no Company counts for the Company its paragraph names, or for the only Company the gap is about. "Periods differ" is about the comparison, so it is stated once, not per Company. The wording rules are in `_GAP_MARKERS`; extra gaps an answer states are not penalised.
3. **Judgments by Jev.** Jev is TypeSafe's System One model: it returns typed answers with probabilities, not text, and it is from neither generator's family, so it judges OpenAI and Anthropic answers alike. It is pinned to `jev-1.13.0`, never an alias such as `jev-latest`, which moves with each release; the harness refuses a response from any other version.
   - **Fact Recall**: one request per answer, with the answer as the state and one yes/no question per Required Fact ("does the answer state this fact, in any wording?"). A fact counts as stated at a probability of at least the fact cut-off, `FACT_CUTOFF` in `backend/src/edgar_eval/judge.py`: 0.6, set by the judge study from 0.5 on agreement with labels made by Claude, not by a human ([The judge study's results](#the-judge-studys-results)). Every generation report records the cut-off it was scored at (`fact_cutoff`); a report saved before it was recorded was scored at 0.5. Every Required Fact is judged, whatever its tier. **Fact Recall** is the share of the case's must-state Required Facts stated, averaged over the cases that have any; **detail recall** is the same share over its detail facts, reported beside Fact Recall per case, per question type and overall, and never decided on. A case's report records each fact's tier (`fact_tiers`) beside both scores. Version 1's facts are all must-state, so its Fact Recall is the share of all its Required Facts and its detail recall is empty; reports saved before tiers existed name no tier and still load and rescore.
   - **Faithfulness**: every sentence of the answer is a claim; a sentence without a tag of its own rests on its unit's tags. A common abbreviation ("U.S.", "U.K." and other initialisms, "Inc.", "Corp.", "Co.", "Ltd.") ends no sentence even before a capital, unless a tag follows it, so "Apple relies on the U.S. Government [S1]." is one claim, not the fragment "Apple relies on the U.S." (issue #83). Only the claim split reads abbreviations; the other checks split sentences as before. On the 258 answers in the saved generation reports this leaves 3,263 claims where there were 3,329, in 45 answers; the one merge it gets wrong is a sentence that really ends at "JPMorgan Chase & Co." Not claims: headings (with table header rows and bold-only labels), the closing Coverage note, and, among sentences that rest on no tag, lead-ins ending in a colon and sentences with nothing to cite: the fixed Coverage Gap wordings; the plain variants `_GAP_MARKERS` recognises, but only when the sentence speaks of the Sources, Filings or Corpus or names a Company missing from the Corpus ("Wells Fargo is not in the Corpus", "the Filings cover different periods"); and sentences that say what the Sources, Filings or Corpus lack, naming them ("Guidance is not in the Filings provided"). Any other uncited sentence about a Company is a claim, however much it looks like a gap: "Apple's revenue grew only 2% in 2024", "Apple's margin did not change much versus 2023" and "Tesla has no exposure to China tariffs" are claims, though the gap patterns match them (issue #89). Until then the exemption was any sentence matching `_GAP_MARKERS` or the citation check's absence rule, which passed such sentences over; the citation check keeps that broader rule, and the three rules are described together in `answer_checks.py`. Scores recorded before the change counted fewer uncited claims; #92 re-scores version 2 dev on the narrowed rule. Claims are grouped by the Sources they cite, one request per group, with those Sources' text as the state and one choice per claim between supported, unsupported and contradicted. Each claim goes with its context, marked as context and not judged: the nearest heading or bold-only label above it and, for a table row, the table's header row, so an "it" keeps its subject and a row of figures keeps its columns. A claim with neither goes exactly as before. Each claim's verdict in the report stores its context beside it (`heading`, `table_header`, empty when it has none); reports saved before this (all of version 1's) lack those fields and still load. Faithfulness is the share of claims supported by the Sources they cite, averaged over answers with claims. A claim citing no Source of the turn, an uncited sentence among them, is unsupported and is not sent to Jev, so an uncited paragraph from general knowledge lowers Faithfulness. **A cited sentence stating one of the case's expected Coverage Gaps** (the wording `_GAP_MARKERS` gives its kind: "NVIDIA's own guidance is not in the Filings provided [S4]") is not sent to Jev either, since it says what the Filings lack and its Sources cannot judge it. The Coverage Gap check alone scores it, and the case records it in `gap_claims` (`split_gap_claims`, issue #86, [ADR 0013's note](adr/0013-jev-stays-the-judge-checked-by-a-judge-study.md#note-2026-10-17-expected-coverage-gap-sentences-go-to-the-code-check-not-to-jev)). A "periods differ" sentence still goes to Jev, because it names each Filing's Report Period and those dates can be wrong. Reports saved before this rule have no `gap_claims`; `make eval-rescore` drops Jev's verdicts on those claims from them. Version 1's results below were scored before this rule, when only cited sentences were claims; on the 223 answers in the saved version 1 generation reports, the new rule leaves every cited claim as it was and adds 126 uncited ones in 36 answers, mostly list items under a cited lead-in and, in answers with no Sources, sentences on what Filings would be needed.
   - **Contradicted Claims** (pass/fail per answer): a claim Jev judges contradicted by the Sources it cites fails the answer, whatever its Faithfulness, beside the citation and Coverage Gap checks, so a wrong figure is not averaged away. Each case records its Contradicted Claims and their count; the run reports, overall and per question type, how many answers have one, and lists each such case's Contradicted Claims. Reports saved before this check (all of version 1's) lack those fields and still load; their claim verdicts are in each case's judgments. **A known false alarm:** Jev calls a percentage rounded from a cited Source contradicted. UnitedHealth's FY2024 growth, given as "8%" beside Financial Facts that say "+7.7% (derived)", is one (`brief-outlook-unh-revenue-two-years`, run 1 of #73), although the same 10-K's MD&A says 8%.
   - **A failed judgment** (built for version 2, issue #50): each Jev request is one judgment, the Fact Recall of an answer or the Faithfulness of one group of claims. A request that fails, such as `max_tokens_exceeded` on long Sources, is recorded in the case's judgments with its error, and the case keeps its code checks and its other judgments. The score that depends on the failed judgment is missing for that case (shown as `–`, never 0, except a truncated answer's Fact Recall, which is 0 regardless), and the run counts the failed judgments in its summary (`judgments_failed`) and prints each one. Before this, a Jev failure dropped the whole case into the report's errors, code checks included, which is why `trend-jpm-revenue-snapshot` has no row in several runs below. A response from another Jev version still fails the case.
4. **Cost and latency** come from each Answer Call's logged record: input and output tokens priced at the model's list price per million tokens (`GENERATORS` in `generators.py`: `gpt-6-luna` $0.10 in, $0.50 out; `gpt-6.1-sol` $2.00 in, $10.00 out, OpenAI's standard tier; `claude-sonnet-5-5` $2.00 in, $10.00 out; `claude-opus-5-5` $4.00 in, $20.00 out, Anthropic's API; all on 2026-10-16; and `claude-haiku-5-5` $0.10 in, $0.50 out, Anthropic's API for prompts under 100k tokens, on 2026-10-17), and the latency to the first text and to the end of the stream. Every input token is priced at the full rate, ignoring cached input, so the cost is an upper bound. Jev's own cost ($0.042 per million input tokens) is reported separately, since it is the evaluation's cost, not the product's.
5. **Scores are averaged overall and per question type**, and each failing case is listed by check, so a score can be traced to the answers behind it. A score with nothing to score (no Required Fact, no expected gap) is shown as `–`, not 0.
6. **Evidence Reached** is recorded per case for each Required Fact (`evidence_reached`, in the case's fact order): whether the fact's evidence quote is in the text of the Answer Context's Sources, compared after collapsing whitespace, as the retrieval harness's "evidence" column counts it. A fact Jev finds missing although its evidence reached the prompt is a generation miss; one whose evidence never reached it is a retrieval miss. Reports saved before it was recorded have none.

### The Brief Suite run

```sh
make eval-brief                 # every Brief Suite case, 5 runs each, with the default generator
make eval-brief RUNS=1          # one run each, for a quick look (a verdict needs the full 5)
make eval-brief MODEL=claude-haiku-5-5 ARM=hybrid   # another generator or Arm, as eval-generation takes
```

The [Brief Suite](golden-set.md#the-brief-suite) is a must-pass check, not an estimate: the brief's example questions, outside the dev/holdout split, so they may be tuned on ([ADR 0012](adr/0012-golden-set-version-2-and-the-brief-suite.md)). `make eval-brief` runs it through the generation harness (`python -m edgar_eval.generation --brief-suite`, verdicts in [`brief_suite.py`](../backend/src/edgar_eval/brief_suite.py)), so its answers get the same checks and the same Jev judgments as the Golden Set's. It needs the same keys and costs money: 5 Answer Calls per case, so 75 for the fifteen current cases (the brief's three questions and four variants of each), which cost at most about $0.47 by the estimate below and about $0.40 in practice with `gpt-6-luna`, Jev included ($0.39 in [the run on the fixed measurement](#re-scored-on-the-fixed-measurement-2026-10-17)).

1. **Five runs.** Every case is answered 5 times (`RUNS=` changes it), each run one pass over every case, so a pass doesn't depend on one lucky answer. Every run's generation report is kept in the Brief Suite report, with every answer.
2. **A verdict per case.** A case **passes** when every must-state Required Fact is stated in at least 4 of the 5 runs (the same share of another run count, rounded up) and no run has a Contradicted Claim. A run that could not be answered, whose Fact Recall judgment failed, or that stopped at the token cap states no fact, so it counts against the case; the truncation rule is the harness's own (`CaseResult.facts_stated`), not a copy. Details are reported and never fail it.
3. **Case by case, never averaged.** For each case the report gives the verdict, the must-state facts stated in too few runs, every Required Fact with the number of runs that stated it and the number whose Answer Context its evidence reached (so a retrieval miss is told from a generation miss), each run's Contradicted Claims, and any truncated run, unanswered run or failed Jev judgment (a failed Faithfulness judgment leaves its claims unjudged, so a contradiction among them would not be seen). It ends with how many cases pass; there is no mean score.
4. **The cost first.** Before the first Answer Call the harness prints an estimate: each call priced at its generator's list price for the whole context budget plus 4,000 tokens of prompt and 2,000 of output, and Jev's judging at the context budget plus 8,000 tokens per answer. Version 1's saved reports stay under that (21k to 34k input and 0.5k to 1.7k output tokens per answer, about $0.0012 of Jev), so the estimate is an upper bound. A Golden Set run prints it too.

The report is written to `data/derived/eval/brief-suite[-<arm>][-<model>][<settings>].json`: the run count, each case's verdict and facts, and the five generation reports. The harness's tests cover the verdict at its boundary (a must-state fact stated in 4 of 5 runs passes and in 3 of 5 fails), one contradicted run failing the case, a failed run counting against it, the case-by-case report and the estimate printed before the first Answer Call, with a fake answer model and a fake Jev (`backend/tests/test_brief_suite_run.py`). Its first live run waits for the developer's approval, as every paid run does.

**Choosing the generator** (`make eval-generators`, `backend/src/edgar_eval/selection.py`). The generators, listed once with their providers and prices in `backend/src/edgar_eval/generators.py` (version 1 compared the four of user story 55; `claude-haiku-5-5` joined for version 2, and `make eval-generators` runs the default comparison listed beside them, `COMPARISON`, which is `gpt-6-luna` and `claude-haiku-5-5`, unless `MODELS=` names others, or is empty for every one, `gpt-6-luna` always running as the shipped one), answer the same dev cases on the Shipped Arm with the same template, each at its provider's nearest equivalent settings: OpenAI's reasoning effort `low` with a 2,500-token completion cap, and Anthropic's adaptive thinking at effort `low` with a 2,500-token cap (thinking counts in both caps). No refusal fallback is configured for the Claude models, since a fallback would answer with another model; a refused answer is reported as an error. `gpt-6-luna` stays unless a challenger is **ahead**, by the paired exact sign test, on Fact Recall or on Coverage Gaps, and **behind** on none of Fact Recall, Faithfulness and Coverage Gaps; when several qualify, the cheapest per answer wins. Version 1 decided at two-sided p < 0.05; the code now applies [ADR 0011's one-sided thresholds](#the-one-sided-thresholds), with Contradicted Claims a guardrail too. The default generator's report is written to `generation-<split>.json` and each other's to `generation-<split>-<model>.json`, and the choice to `data/derived/eval/generator-choice-<split>.json`.

**How the checks were validated.** The pure parts have unit tests on hand-written answers (`backend/tests/test_answer_checks.py`), and the judge's request shapes and version pin have tests with a fake Jev (`backend/tests/test_generation_harness.py`). Then every failure of the first live runs was read: each was either a real fault of the answer or a wording or format the checks had missed (range tags, a Coverage note opening mid-paragraph, "provide no Bristol Myers Squibb filing evidence"). Each miss became a test and a fix before the run below.

**Rescoring a fixed check.** The saved reports store each answer, so a corrected check is rerun on them offline with `make eval-rescore`: it prepares each case's Answer Context again through the Arm the report was answered on, at the context budget the report records (deterministic, no network call; a report from an index of another chunk size is refused unless that index is there), refuses a case whose Sources no longer number what they did, redoes the check and rewrites the report's scores in place, with no Answer Call and no Jev call. It also drops Jev's stored verdicts on expected Coverage Gap sentences, from every saved generation report and every saved Brief Suite report (`brief-suite*.json`, each of whose runs it rescores), and recomputes the scores that rest on them: Faithfulness, Contradicted Claims, the answer's and the Brief Suite case's pass, and the cases passed. This part prepares no Answer Context. A report from an index of another chunk size is rebuilt from that index beside the shipped one (`edgar_rag-chunks450.sqlite`, as `CHUNK_TOKENS=450` builds it) when it exists. A rescore fixes a measurement and changes no choice, so it is allowed on the holdout. The figure check was made stricter this way on 2026-10-16: before, a figure passed if it matched any Financial Fact of a Company in the Query Scope or among the Sources, whichever Filing reported it. Every saved report from v5 on (the Arm comparison, the prompt iterations, the generator comparison and the holdout run) was rescored, and every figures-exact score in the tables below is unchanged: every figure that had passed on a Financial Fact also matched a cited Filing's or appeared in a cited passage. One answer gained a failure without changing a score: v10's `followup-switch-to-msft`, which already failed on that quarter's 18.4% growth, gives Microsoft's Q1 FY2026 revenue ($77,673 million) without citing the 10-Q that reports it. The runs before v5 (v1 and v3) have no saved report, so their figures-exact scores are as first measured, under the earlier rule.

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

`gpt-6-luna`, `jev-1.13.0`, 2026-10-16, prompt [v7](prompt-iterations.md#the-final-template-v7), on the same retrieval as v5. The template was tuned in five versions, v6 to v10, each written for named failing dev cases and kept only if it fixed them and the paired sign test put it behind its predecessor on nothing; v6 and v7 were kept and v8 to v10 discarded. A later pass on answer length, [v11 to v14](#answer-length-prompts-v11-to-v14), was discarded too. Each version's scores, the cases behind it and the paired tests are in the [prompt iteration log](prompt-iterations.md#the-iteration-pass-v6-to-v10). This is v7's second run; its first run scored structure 0.84, Fact Recall 0.63 and Faithfulness 0.95. The "How it works" page showed `gpt-6-luna`'s later run from the [generator comparison](#generator-comparison) while it described version 1; it now shows version 2's round.

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

Golden Set version 1's holdout run; version 2's is [The version 2 holdout run](#the-version-2-holdout-run). The final configuration, the `fts5` Arm, `gpt-6-luna` and prompt v7 (with 600-token chunks and the 32k context budget, then untuned), run once on the holdout split (10 cases) on 2026-10-16, after every choice above was made on dev. Nothing was changed after it. The tuning that followed left what ships unchanged, so this run stands for the shipped setup ([Scoring the holdout once more](#scoring-the-holdout-once-more)).

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

- **The holdout is scored once per final setup and never used to choose.** Every choice is made on dev. The holdout is scored once on the setup that ships after them, and again only if a later dev choice changes that setup: then one retrieval run and one generation run (`make eval-retrieval SPLIT=holdout ARMS=fts5`, `make eval-generation SPLIT=holdout`, about $0.04 on version 1's 10 holdout cases and $0.09 on version 2's 20), shown beside the earlier run.
- **That run reports and decides nothing, and nothing changes after it.** Whatever it scores, no Arm, chunk size, context budget, template or generator is changed, and no Golden Set case is relabelled. A worse score is reported as it is.
- **It is read with the 10-case caveat.** On 10 cases one case moves a share by 0.10, so two holdout runs that differ by a case or two do not show that the setup got better or worse.
- Rescoring a saved holdout report offline with a corrected check ([Rescoring a fixed check](#generation-harness)) is not a run: it makes no Answer Call and changes no choice.
- **The rule applies per Golden Set version.** Version 2 brings 20 new holdout cases, scored once on the final version 2 setup ([ADR 0012](adr/0012-golden-set-version-2-and-the-brief-suite.md)). That run has been made ([The version 2 holdout run](#the-version-2-holdout-run)). Since version 2 is the harnesses' default, `SPLIT=holdout` now means version 2's holdout: score it again only if a later dev choice changes what ships, and never to tune a choice. The version 1 holdout run below stands as recorded, and version 1's 10 holdout cases, scored once and never tuned on, join version 2's dev split.

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

The export describes Golden Set version 2 (moved from version 1 in issue #85) and reads the harnesses' latest reports for the split from `data/derived/eval/`:

- `retrieval-<split>.json`, required. The retrieval harness runs first if it is missing (on the Shipped Arm and version 2), since it makes no LLM call.
- The round's shipped run, `generation-<split>.json`, and its Control Run, `generation-control-<split>.json`: none until `make eval-generation` (or a selection command) has run, since that costs money.
- `generator-choice-<split>.json`, once `make eval-generators` has run: each challenger's sign tests against the shipped generator, with the Control Run's, and the generator chosen. The challengers' own reports, which it names, are the scoreboard's other generator rows, read by name from `data/derived/eval/`. A generation report no comparison names is not read: the Arm and settings comparisons' answer reports (`generation-arms-<split>-<arm>.json`, `generation-<split>-chunks<N>-budget<B>.json`), whose challengers show on the page through the retrieval report's screen, and version 1's reports left in the same directory.
- `brief-suite.json`, once `make eval-brief` has run: the Brief Suite's verdict per case. It is outside the split, so a holdout export leaves it out.
- Beside a dev export, the holdout's reports, `retrieval-holdout.json` and every `generation-holdout[-<suffix>].json`, once the holdout has been scored.

Every Golden Set report it reads must record the version it describes: a dev or holdout report of another version is refused, never mixed in (a report that records no version is version 1's). `--golden-set ../data/eval/golden_set.json` with `--eval-dir ../data/derived/eval-golden-set-v1` still exports version 1 from its reports, as before: retrieval gated on hit@10, re-paired case by case for a version 1 report the later harness gated on Evidence Reached, and the generator comparison under version 1's two-sided rule. It adds the Corpus coverage grid, each Company's Filings by the calendar quarter of their Report Period, and writes everything to `frontend/data/eval-export.json` for the workspace's "How it works" page. The code is [`backend/src/edgar_eval/export.py`](../backend/src/edgar_eval/export.py).

The page shows what the reports hold, nothing more, with version 2's verdicts worded as directional ("one-sided p < 0.10 for ahead and p < 0.20 for behind, fixed before running"):

- **Retrieval:** per Arm, hit@k, recall@10, recall@all, MRR, the mean number of Sources and Evidence Reached, the gate, with each challenger's one-sided McNemar verdict on it (facts gained and lost, p ahead and p behind) and whether it can ship under the one-call rule; then the screen, every candidate with its Evidence Reached, gains and losses and why it was kept or dropped. hit@k, recall@k and MRR are reported, not gated on.
- **Answers:** the round's shipped run beside its Control Run and each challenger generator, with the code checks, must-state Fact Recall and detail recall, Faithfulness, the answers with a Contradicted Claim, cost and latency, overall and per question type, and the fact cut-off.
- **The generator comparison:** the Control Run and each challenger against the shipped generator on Fact Recall, Faithfulness, Coverage Gaps and Contradicted Claims (higher and lower, both one-sided p-values, the mean paired difference and its 95% bootstrap interval), whether it qualifies, and the choice.
- **The Brief Suite:** each case's verdict, its must-state facts, those it missed, how many of them never had their evidence reach the Answer Context, and its runs with a Contradicted Claim.
- **The holdout run:** its retrieval and answer scores beside dev's Shipped Arm, shipped run and Control Run, with the small-sample caveat.

The export is committed, so the page shows the last results exported, dated on the page; the numbers in this document remain the record of each run.

## Evaluation version 2

Decided and built on 2026-10-17 ([ADRs 0011](adr/0011-one-sided-thresholds-and-a-control-run.md), [0012](adr/0012-golden-set-version-2-and-the-brief-suite.md) and [0013](adr/0013-jev-stays-the-judge-checked-by-a-judge-study.md)): every change below is built, and the harnesses run version 2 by default. Version 1's results above stay as recorded. The comparisons on version 2's dev split have been run, and confirm every shipped choice ([The version 2 comparisons on dev](#the-version-2-comparisons-on-dev)), and its holdout has been scored once on that setup ([The version 2 holdout run](#the-version-2-holdout-run)).

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

- **Decision thresholds** ([ADR 0011](adr/0011-one-sided-thresholds-and-a-control-run.md)): a challenger is ahead at one-sided p < 0.10 and behind on a guardrail (Faithfulness, Coverage Gaps, Contradicted Claims) at p < 0.20, with a Control Run in every comparison and the mean paired difference reported with a bootstrap interval (the thresholds, the interval and the Control Run are built: see [The one-sided thresholds](#the-one-sided-thresholds) and [The Control Run and the round](#the-control-run-and-the-round)). The retrieval harness gates on Evidence Reached, and it screens candidates for free: at most three per rule go on to paid Answer Calls, so the chance of a false switch stays near 20% instead of about 66% across version 1's 15 setting challengers (built: see [The gate and the screen](#the-gate-and-the-screen)).
- **Golden Set version 2 and the Brief Suite** ([ADR 0012](adr/0012-golden-set-version-2-and-the-brief-suite.md)): 60 dev and 20 new holdout cases, one-claim Required Facts that are must-state or detail, a split recorded per case, and the brief's questions with variants in a must-pass Brief Suite reported case by case ([Golden Set](golden-set.md#version-2)).
- **The judge** ([ADR 0013](adr/0013-jev-stays-the-judge-checked-by-a-judge-study.md)): Jev stays, checked first by a judge study against blind labels, meant to be the developer's. The study sets the stated-fact cut-off and decides whether claims are split by an LLM. Its fact items use the rewritten one-claim Required Facts, and its claim labelling may stop at 100 items by a rule fixed in advance (its sample and blind labelling sheet, its judging, its score and the trial LLM claim split are built: see [The judge study's sample](#the-judge-studys-sample), [Judging and scoring the judge study](#judging-and-scoring-the-judge-study) and [The trial LLM claim split](#the-trial-llm-claim-split)). **It has been run** ([The judge study's results](#the-judge-studys-results)), with labels made by Claude (`claude-opus-5-5`) on the developer's delegation rather than by the developer: Jev stays, the fact cut-off moves to 0.6, and the LLM claim split is not adopted.
- **Measurement fixes in the harnesses:**
  - a Jev failure is recorded against its judgment, not the whole case (built: see "A failed judgment" in [Method](#method-1), step 3);
  - an answer that stops at the token cap fails instead of being scored as complete (built: see [Method](#method-1), step 1);
  - Faithfulness judges every sentence, an uncited one counting as unsupported (built: [Method](#method-1), step 3);
  - any Contradicted Claim fails the answer (built: see [Method](#method-1), step 3);
  - each sentence goes to the judge with its heading and table header, so a table row or an "it" keeps its meaning (built: [Method](#method-1), step 3);
  - the Brief Suite's cases are reported one by one (built: [The Brief Suite run](#the-brief-suite-run)).
- **The one-call rule and the local Arms:** the Answer Call is a question's only API call (decided 2026-10-17), so an Arm that embeds the question with OpenAI can't ship; two local embedding Arms join the comparison (built: see [The one-call rule and the local Arms](#the-one-call-rule-and-the-local-arms)).
- **Another generator:** `claude-haiku-5-5`, listed at `gpt-6-luna`'s price ($0.10 in, $0.50 out per million tokens, for prompts under 100k tokens, on 2026-10-17), is the one challenger to `gpt-6-luna` on version 2. It is in the table of compared generators, so `make eval-generation MODEL=claude-haiku-5-5` answers with it, and `make eval-generators` runs the comparison by default, for about $0.37 on dev (Haiku's run in issue #73: $0.28 in Answer Calls and $0.09 in Jev judging). The version 1 generators stay in the table, so their reports still price.

#### The one-sided thresholds

Built for version 2 (issue #55), in `backend/src/edgar_eval/selection.py` and `backend/src/edgar_eval/metrics.py`. Every selection rule (Arms, generators, the chunk size and context budget) uses one pair of thresholds, stated once as `AHEAD_P` and `BEHIND_P`:

- **Ahead:** the one-sided exact sign test gives p < 0.10 on Fact Recall, or, under the generator rule, on Coverage Gaps. For example, 7 cases higher to 2 lower is ahead (p = 0.090), 5 to 1 is not (p = 0.109).
- **Behind:** the one-sided test gives p < 0.20 on any guardrail: Faithfulness, Coverage Gaps, or Contradicted Claims, the last paired per case on "has no Contradicted Claim". For example, 1 case higher to 4 lower is behind (p = 0.188), 2 to 5 is not (p = 0.227). The generator rule also keeps its guard against falling behind on Fact Recall.

A challenger qualifies when it is ahead on one of its rule's ahead metrics and behind on none of its guardrails, and the cheapest qualifying challenger still wins. Each score's comparison in the choice file reports the cases it paired and left out (`paired`, `left_out`), the wins and losses, both one-sided p-values (`p_ahead`, `p_behind`), the verdict, and the mean paired difference, challenger minus shipped, with a 95% percentile bootstrap interval over the paired cases (`difference`: a fixed seed, 10,000 resamples, so the same reports give the same interval). The interval is shown, never decided on. The two-sided p-value version 1 decided by is kept beside them (`p_value`) for comparison with its records. A case's Contradicted Claims are unknown, and left out of that pairing, when its Faithfulness judgment failed, and in a version 1 report, which did not record them. Version 1's choice files were written under its two-sided p < 0.05 rule; they are records and are not recomputed.

#### The Control Run and the round

Built for version 2 (issue #56), in `backend/src/edgar_eval/selection.py`. Every comparison takes three kinds of report: the shipped choice's, a **Control Run** (the shipped choice run again), and the challengers'. The Control Run is compared with the shipped run under the same rule and thresholds, and printed and saved beside the challengers (`control` in the choice file, `control_report` its report). If it comes out **ahead** of the shipped run on any of the rule's ahead metrics (Fact Recall, or under the generator rule Fact Recall or Coverage Gaps), the run-to-run noise is larger than the thresholds assume: the choice is **inconclusive** (`inconclusive`, with the `reason` printed), and the shipped choice stands even if a challenger qualified. A Control Run ahead only on a guardrail, or within noise, leaves the choice to the challengers.

The comparisons of one **round** share one shipped run and one Control Run. A round is the same code, prompt and Golden Set version on one split; every Golden Set report records all three (`code_version`, a digest of the backend's source, `prompt_version` and `golden_set_version`, from `edgar_eval.generation.current_round`). The shipped run is written to `generation-<split>.json` and the Control Run to `generation-control-<split>.json`, each on the shipped setup: the Shipped Arm, `gpt-6-luna`, 600-token chunks and the 32k budget. `make eval-arms`, `make eval-settings` and `make eval-generators` reuse both when they record the shipped setup and the current round, and run them first otherwise, so a round pays for the shipped choice twice, not once per comparison. Any change to the code, the prompt or the Golden Set starts a new round. `make eval-settings CANDIDATES="450:32000 600:48000"` screens each named chunk size and context budget on Evidence Reached, answers the ones kept (building an index of another chunk size when missing) and applies the Arm rule; `compare` takes the Control Run's report with `--control`, and without one, as for version 1's reports, says the noise is not shown.

**The Brief Suite is built** with the brief's three questions, rewritten in one-claim, tiered facts, and four variants of each: a rephrasing, other Companies (for the pharmaceutical question, another Health Care Sector phrase), another time window, Section angle or a single Company, and a follow-up ([Golden Set](golden-set.md#the-brief-suite)). **Golden Set version 2's file is built**, with all 27 of version 1's other cases rewritten into it ([Golden Set](golden-set.md#the-rewritten-version-1-cases)) and all six slices of its 53 new cases: nine multi-Company risk comparisons, then seven risk questions on financials, industrials, energy, health care and consumer staples Companies and two follow-ups, then nine figure trends on Tracked Companies, then four outlook questions and five sector questions on industrials, energy and financials Companies, then eight sector questions on health care, information technology, consumer and communication services Companies and a Coverage Gap case comparing Companies whose latest fiscal years differ, then five Coverage Gap cases, one of each kind, and three follow-ups, 80 cases in all ([Golden Set](golden-set.md#the-new-cases)): each case records its split, and **the split is frozen** (issue #72): of the 53 new cases, the 20 with the lowest SHA-256 digests are holdout and the other 33 dev, with the 27 rewrites, so 60 dev and 20 holdout cases, none pending, and the file lists the holdout ids, which the loader checks every recorded split against ([Golden Set, the frozen split](golden-set.md#the-frozen-split), with the mix by kind of question). **Version 2 is the harnesses' default:** `make eval-retrieval`, `make eval-generation` and the selection commands run it, a version 1 run names its file (`--golden-set ../data/eval/golden_set.json`), `make eval-rescore` reads each saved report against the version it records, and a harness refuses a set while any case is pending ([Golden Set, version 2](golden-set.md#the-file)). Its dev split has been measured ([The version 2 comparisons on dev](#the-version-2-comparisons-on-dev)), and its holdout scored once ([The version 2 holdout run](#the-version-2-holdout-run)). **Required Fact tiers are built:** a fact is `must_state` or `detail`, the loader checks it, and the generation harness scores Fact Recall on the must-state facts and reports detail recall beside it ([Method](#method), [Golden Set fields](golden-set.md#fields)). Version 1's facts all load as must-state, so its scores are unchanged.

#### The gate and the screen

Built for version 2 (issue #57), in `backend/src/edgar_eval/retrieval.py`, with the thresholds of [The one-sided thresholds](#the-one-sided-thresholds):

- **The gate.** The retrieval harness compares each challenger Arm with the Shipped Arm on Evidence Reached, paired per Required Fact over the cases both scored, by McNemar's exact test, one-sided: ahead at p < 0.10, behind at p < 0.20. Each comparison in `retrieval-<split>.json` gives the facts paired (`facts`), the facts only the challenger reached and only the Shipped Arm reached (`result.challenger_only`, `result.shipped_only`), both one-sided p-values and the `verdict`. For example, 4 facts gained and none lost is ahead (p = 0.0625), and 3 lost and none gained is behind (p = 0.125), though neither would be at two-sided p < 0.05. hit@k, recall@k and MRR are reported beside it and not gated on.
- **The screen**, before any paid Answer Call. A candidate (an Arm, or a chunk size and context budget) goes on to paid generation only if Evidence Reached does not put it behind the shipped choice (one-sided p < 0.20). If more than three pass, the three with the highest share of Evidence Reached go on. On a tie the cheapest goes first: the fewest mean tokens of Source text per Answer Context (the Answer Call's input, and so most of its cost), then the earliest listed. The output lists every candidate screened, with its facts reached, gained and lost, and why it was kept or dropped.
  - **Arms:** `make eval-retrieval` screens the challenger Arms it scores (the report's `screen`), and `make eval-arms` runs the retrieval harness first, writing `retrieval-<split>.json`, then answers only through the Arms the screen keeps, beside the round's shipped run and Control Run. Its choice file records the screen.
  - **Settings:** `make eval-settings CANDIDATES="450:32000 600:48000"` runs the retrieval harness on the Shipped Arm for the shipped setting and each named one first, writing `retrieval-<split>-chunks<N>-budget<B>.json`, names each as the settings rule does (`chunks-600-budget-48000`), and answers only the settings the screen keeps. Its choice file records the screen.
- **The "How it works" page** shows version 2's retrieval view, gated on Evidence Reached with the screen and each Arm's shippability (issue #85, [Showing the results](#showing-the-results)). Only a version 1 export re-pairs a report gated on Evidence Reached on hit@10, as version 1's harness did.

#### The one-call rule and the local Arms

Built for version 2 (issue #84), in `backend/src/edgar_eval/arms.py`, `retrieval.py`, `selection.py` and `embeddings.py`. On 2026-10-17 the developer set the rule at one API call of any kind per question: the Answer Call ([assumption 1](assumptions.md#1-one-api-call-per-question)). Local models inside retrieval are fine. The `dense` and `hybrid` Arms embed each question with OpenAI `text-embedding-3-small`, a second API call, and version 1's evaluation hid it, because it caches question embeddings.

- **Every Arm records whether it makes an API call at query time** (`query_api_call`; see the table in [The Arms](#the-arms)). The retrieval report records it per Arm (`query_api_call` and `shippable`), and so does each generation report (`query_api_call`). For a generation report saved before the rule, the selection rule reads it from the Arm table.
- **An Arm that does is never sent to a paid run by the screen**, and doesn't take one of its three places: its reason says it makes an API call at query time and can't ship. **It is never chosen by the Arm rule** either, and `make eval-arms` skips it even if a screen saved earlier kept it.
- **It is still reported, unconstrained.** It is scored and gated like any other Arm, and its comparison still says whether it would qualify (`qualifies`, with `shippable` false). Reports label it "available if the one-call limit is lifted".
- **Two local Arms**, `dense-local` and `hybrid-local`, embed both the chunks and the question with `BAAI/bge-small-en-v1.5`, pinned to Hugging Face commit `5c38ec7c`, run by ONNX Runtime on the CPU with the `tokenizers` stack the `rerank` Arm already uses. A question gets the model's query instruction. A text is embedded as its CLS token, truncated to the model's 512 tokens, so a 600-token chunk is embedded on its opening. A query embedding only matches chunk embeddings from the same model, so `make local-embeddings` embeds the whole index again, locally and for free, into `data/derived/embeddings/bge-small-en-v1.5.npy` (48,448 chunks, about 30 minutes on 16 CPU threads). The model downloads once, then loads from the local cache with no network call, and a test refuses every socket while the model loads and ranks a question. `hybrid-local` fuses with FTS5 as `hybrid` does (weighted reciprocal-rank fusion, k = 1, equal weights).
- **If a local Arm ships**, its embeddings join `make index` and its ranker and packages move from `edgar_eval` into the product. Neither did in the version 2 comparisons (#73: `dense-local` is behind on Evidence Reached, and `hybrid-local` is not ahead on Fact Recall; [The Arm comparison](#the-arm-comparison)), so they stay in the dev dependency group.

**First numbers on dev**, free (`make eval-retrieval`, no LLM call and no API call for the local Arms): Golden Set version 1, dev split, 17 scored cases with 44 Required Facts, 600-token chunks and the 32k budget, 2026-10-17.

| Arm | API call at query time | hit@10 | recall@10 | MRR | Evidence Reached | gained / lost vs `fts5` | gate (one-sided) | screen |
|---|---|---|---|---|---|---|---|---|
| `fts5` (shipped) | No | 0.88 | 0.82 | 0.73 | 30 of 44 | – | – | – |
| `dense` | Yes | 0.88 | 0.82 | 0.76 | 30 of 44 | 5 / 5, p behind = 0.623 | indistinguishable | dropped: can't ship (available if the one-call limit is lifted) |
| `hybrid` | Yes | 0.88 | 0.82 | 0.80 | 31 of 44 | 4 / 3, p behind = 0.773 | indistinguishable | dropped: can't ship (available if the one-call limit is lifted) |
| `rerank` | No | 0.88 | 0.82 | 0.68 | 30 of 44 | 0 / 0, p behind = 1.000 | indistinguishable | kept, 1st |
| `dense-local` | No | 0.82 | 0.75 | 0.71 | 27 of 44 | 2 / 5, p behind = 0.227 | indistinguishable | kept, 3rd |
| `hybrid-local` | No | 0.88 | 0.82 | 0.72 | 28 of 44 | 1 / 3, p behind = 0.312 | indistinguishable | kept, 2nd |

- **No Arm is distinguishable from FTS5 on Evidence Reached.** The local Arms reach a few facts fewer, but not enough to be behind at p < 0.20, so the screen keeps all three shippable challengers: `rerank`, `hybrid-local` and `dense-local`, in that order. Under the old screen the two hosted Arms would have taken places.
- **The local model is weaker than OpenAI's here.** `dense-local` reaches 27 facts against `dense`'s 30 and drops to hit@10 0.82: it ranks `outlook-meta-capex-2026`'s expected MD&A 12th, outside the top 10, and leaves one of `sector-aerospace-government`'s three expected Sections out of its top 10. Fusing it with FTS5 brings hit@10 back to 0.88. Both local Arms lose `risk-aapl-tsla-jpm`'s one fact that FTS5 reaches, and `followup-regulatory-exposure`'s one.
- These are version 1 dev numbers, recorded to show the Arms run. The choice between them was made on version 2 dev, by the version 2 comparisons (#73): FTS5 stays ([The Arm comparison](#the-arm-comparison)).

#### The judge study's sample

Built for version 2 (issue #62), in `backend/src/edgar_eval/judge_study.py`. `make judge-study-sample` draws the study's items from every saved generation and Brief Suite report under `data/derived/eval/` and writes the labelling sheet the developer fills in with an editor, `data/eval/judge_study/sheet.md`, beside the sample itself, `sample.json`. Both are committed, beside the Golden Set, since they hold hand-made labels: the developer commits the labelled sheet. The verdicts and the score stay in `data/derived/judge_study/`, since they can be regenerated. It reads saved reports only and calls no provider: it removes the provider keys from its environment before it rebuilds any Source.

- **Fact items** (150) pair a saved answer with one Required Fact in the one-claim format: Golden Set version 2's facts for the case of the same id, or the Brief Suite's for its own cases and for the version 1 case each replaces. Version 1's compound facts are never sampled, and an answer whose case has no rewritten facts yet gives no fact item, so the study is drawn once version 1's cases are rewritten.
- **Claim items** (200) are re-split from each stored answer with the current claim split, each with its heading, table header and the Sources it cites. A report does not store its Sources, so each Answer Context is prepared again through the report's Arm at its own setting, as `make eval-rescore` does; an answer whose Sources cannot be rebuilt as they were (another chunk size's index missing, the dense or hybrid Arm without embeddings, or a different number of Sources), and an uncited claim, which Jev never judges, give no claim item.
- **Over-sampling:** the items are drawn at random with a fixed seed (`SEED`, recorded in the sheet and the sample; `SEED=` changes it), after quotas met in full or with every eligible item when there are fewer: claims Jev judged contradicted (a tenth of the claim items) and unsupported (a quarter); every generator in the reports, `claude-haiku-5-5` included when its report exists (half of each kind's items, split evenly); and saved probabilities between 0.05 and 0.65 (a third). A rewritten fact has a saved probability only where the answer was judged on that very fact, as in a Brief Suite run.
- **The sheet** lists the fact items, then the claim items, each in shuffled order, every item under a stable id (a digest of its content). It holds no Jev verdict, no probability and no reason an item was drawn; `sample.json` records those reasons, so it is not read while labelling. A fact item is labelled `stated` or `not stated` and a claim item `supported`, `unsupported` or `contradicted`, on its `LABEL` line; a blank label is still to do. Running the command again keeps every label entered, and refuses, writing nothing, if the new draw would drop a labelled item (another seed, or other reports). A Source's text is shown in full under the first claim item citing it.

#### Judging and scoring the judge study

Built for version 2 (issue #63), in `backend/src/edgar_eval/judge_study.py`.

**Judging.** `make judge-study-judge` has Jev judge every sampled item twice, and with `REFERENCE=1` Claude Haiku 5.5 (`claude-haiku-5-5`, pinned) once as a reference judge, a reference and not a candidate. It needs `JEV_API_KEY` (and `ANTHROPIC_API_KEY` for the reference) and costs money, and it prints its estimated cost before the first request: Jev's from the tokens of each request at its price, the reference's from each prompt's tokens and 500 output tokens a request at its list price in `GENERATORS`.

- Jev judges each saved answer's items together, as a harness run does: its fact items in one request, its claim items in one per set of cited Sources. The reference judge is asked Jev's own questions and criteria, one item a request, its answer held to a verdict by a JSON schema; it gives no probability.
- The verdicts go to `data/derived/judge_study/verdicts.json` (gitignored), apart from the sheet, which stays blind. Every item has a verdict or a recorded failure (with its error) in every run: a failed Jev request is recorded against each item it was for, and a reference request that fails, is refused, stops at its token cap or gives no verdict against its item. No item is dropped.

**Scoring.** `make judge-study-score` reads the sheet's labels and the stored verdicts, calls no provider, prints the score and writes it to `data/derived/judge_study/score.json`. For each judge (Jev's two runs, then the reference when it was run) it reports:

- accuracy and Cohen's kappa against the labels, for the fact items (at the fact cut-off) and for the claim items (three categories);
- the share of claims labelled unsupported or contradicted that the judge calls supported, with its 95% Wilson interval;
- its errors by generator, for facts and for claims, each with Fisher's exact test (two-sided) against every other generator's;
- for Jev, accuracy and kappa on the facts at each candidate cut-off from 0.1 to 0.9, and with averaged probabilities instead: each fact counts as its probability of a stated fact (agreement p with a `stated` label, 1 - p with `not stated`), as a Fact Recall averaging probabilities would;
- the items whose judgment failed, which are left out of its scores and counted.

It also reports how often Jev's two runs give the same verdict, over every item both judged. Jev's first run is the study's measure, since a harness run judges once, and it decides the two rules below.

- **ADR 0013's revisit trigger** fires when Jev calls more than one in five of the bad claims supported (strictly more: exactly one in five does not fire), or when its error differs by generator: any Fisher test below 0.05 shared out over the tests made (Bonferroni).
- **The early-stopping rule** is met once every fact item and at least 100 claim items are labelled and the 95% interval of that false-supported share lies wholly below or wholly above one in five. The claim items left unlabelled are then left out.

It refuses to score while any item is unlabelled, unless the stopping rule is met or a partial report is asked for (`PARTIAL=1`), which says it is partial.

#### The trial LLM claim split

Built for version 2 (issue #64), in `backend/src/edgar_eval/judge_study.py`, to decide whether to adopt an LLM claim split (ADR 0013). It lives only in the study: the generation harness still splits claims by sentence, and adopting the LLM split there would be a follow-up spec.

- **The split.** `make judge-study-judge LLM_SPLIT=1` also has Claude Haiku 5.5 (`SPLIT_MODEL`, `claude-haiku-5-5`, pinned) split each sampled answer with a claim item, one request an answer, its reply held to a list of statements by a JSON schema. It is given the answer and its cited sentences, numbered by their place in the sentence split, and splits each into one-claim, self-contained statements. A statement keeps its sentence's citations (the tags it names that its sentence cites, or all of them when it names none) and the sentence's heading and table header. The output is cached per answer in `data/derived/judge_study/llm_split/`, keyed by the model and the prompt, so a rerun makes no request; a split that fails is not cached, and is recorded against the answer's items.
- **Judging.** Jev judges, once, the statements of each claim item's sentence against that item's cited Sources, each answer's statements together. They are stored in `verdicts.json` beside Jev's runs (`llm_split`). Because each statement belongs to one labelled sentence, both splits are scored on the same labels.
- **Cost.** It needs `ANTHROPIC_API_KEY` as well as `JEV_API_KEY`. The judge command's cost estimate, printed before the first request, adds the split of every uncached answer (its prompt's tokens and 1,500 output tokens, thinking included, at Haiku's list price in `GENERATORS`) and Jev's pass over its statements: about $0.15 per 150 answers.
- **The comparison.** `make judge-study-score` compares the splits answer by answer, over the answers with a labelled claim item. An answer is bad when any of its claim items is labelled unsupported or contradicted. Each split finds it bad when Jev calls any of those sentences (Jev's first run), or any of their statements, unsupported or contradicted. For each answer, the report says which split's verdict agrees with the labels. For each split, it reports how many answers it agrees on, how many of the bad answers it catches, and how many false alarms it raises on clean ones. It then says which split agrees better and which catches more, with McNemar's exact test, two-sided, shown but not decided on. An answer whose split or any judgment failed is left out and counted.

#### The judge study's results

Run on 2026-10-17 (issue #65). **The labels are Claude's, not a human's.** The developer delegated the labelling, so every item was labelled by Claude (`claude-opus-5-5`), not by the developer. The study therefore measures how far Jev agrees with Claude. It does not validate Jev against human judgement, and the fact cut-off below is set from agreement with Claude's labels.

**The sample.** `make judge-study-sample` drew 150 fact items and 200 claim items from 30 saved reports (seed 20261017). The reports include a first `claude-haiku-5-5` run on Golden Set version 1 dev, made for the study (`generation-dev-claude-haiku-5-5.json`, $0.09 in answers and $0.02 in Jev judging). That run scored Fact Recall 0.34 and Faithfulness 0.82, and 8 of its 20 answers stopped at the token cap, worth knowing before the version 2 generator comparison. 84 answers had no rewritten facts and gave no fact item; every answer's Sources were rebuilt.

**The labelling.** Every item was labelled before the judge command ran, and the labelled sheet was committed before any verdict was seen (`data/eval/judge_study/sheet.md`, with each label's one-line reason in `label-reasons.md`).
- Claude did the labelling in 46 separate sessions: 6 of 25 fact items each, and 40 of 5 claim items.
- Each session was given only its slice of the sheet, with each claim's cited Sources written out in full, and the label definitions, which are Jev's own criteria.
- None of them saw Jev's verdicts or probabilities, the draw reasons in `sample.json`, or any report.
- The labels: 49 facts stated and 101 not stated; 157 claims supported, 35 unsupported and 8 contradicted.
- All 200 claim items were labelled, not 100, because the stopping rule can't be checked without Jev's verdicts. It was met anyway.

**Judging** (`make judge-study-judge REFERENCE=1 LLM_SPLIT=1`, estimated at $0.73): Jev judged every item twice and Claude Haiku 5.5 once, and the trial LLM claim split turned the 200 claim items into 394 statements. No judgment failed.

**The score** (`make judge-study-score`, written to `data/derived/judge_study/score.json`). Accuracy and Cohen's kappa are against Claude's labels; the fact columns are at the 0.5 cut-off the items were judged at.

| Judge | Facts: accuracy | Facts: kappa | Claims: accuracy | Claims: kappa | Bad claims called supported (95% interval) |
|---|---|---|---|---|---|
| Jev, run 1 (the study's measure) | 91% | 0.81 | 81% | 0.59 | 1 of 43, 2% (0.4% to 12%) |
| Jev, run 2 | 91% | 0.80 | 79% | 0.54 | 3 of 43, 7% (2% to 19%) |
| Claude Haiku 5.5, reference | 93% | 0.84 | 80% | 0.52 | 6 of 43, 14% (7% to 27%) |

- **Run to run**, Jev's two runs agree on 147 of 150 facts (98%) and 195 of 200 claims (98%).
- **Jev's claim errors are false alarms, not misses.** It called 27 claims unsupported and 8 contradicted that Claude labelled supported, and let through 1 of the 43 bad claims.
- **Contradicted Claims are noisy.** Of the 17 claims Jev called contradicted, Claude labelled 7 contradicted, 8 supported and 2 unsupported. Since version 2 fails any answer with a Contradicted Claim, that guardrail will fail some answers Claude would pass.
- **By generator,** no difference is significant. The largest are `gpt-6-luna`: 10 of 83 facts wrong (12%, Fisher p = 0.145) and 24 of 106 claims wrong (23%, p = 0.207). Every test is above the Bonferroni-shared 0.05.
- **The reference judge** agrees with Claude's labels about as well as Jev, but lets through more bad claims (14% against 2%). A Claude judge scored against Claude's labels may share their bias, so even this is not evidence for it.

**ADR 0013's revisit trigger did not fire.** Jev calls 2% of bad claims supported, below one in five, and its error does not differ by generator. The stopping rule is met: the 95% interval of that share lies wholly below one in five. **Jev stays.**

**The fact cut-off: 0.6.** Agreement with Claude's labels at each cut-off, for Jev's first run (accuracy / kappa):

| Cut-off | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 | Averaged |
|---|---|---|---|---|---|---|---|---|---|---|
| Jev, run 1 | 73% / 0.50 | 85% / 0.69 | 89% / 0.76 | 90% / 0.79 | 91% / 0.81 | **93% / 0.83** | 91% / 0.79 | 93% / 0.82 | 89% / 0.74 | 86% |
| Jev, run 2 | 72% / 0.48 | 85% / 0.69 | 89% / 0.77 | 91% / 0.80 | 91% / 0.80 | 91% / 0.80 | 91% / 0.79 | 92% / 0.81 | 91% / 0.77 | 86% |

- **The rule:** take the cut-off with the highest kappa on Jev's first run, the run the study measures by. That rule was chosen after the sweep was seen, not fixed in advance.
- **0.6 also balances the errors.** At 0.5, Jev states 10 facts Claude labels not stated and misses 3. At 0.6 the split is 5 and 6. At 0.8 Jev states none wrongly but misses 11.
- **The margin is small.** Cut-offs from 0.5 to 0.8 are within 3 items of 150 of each other, and Jev's second run is level at 0.5 and 0.6. The cut-off is a small correction, not a large finding.
- **Averaged probabilities** agree on 86%, below every cut-off from 0.3 to 0.8, so Fact Recall keeps a cut-off.
- **What changes:** `FACT_CUTOFF` is 0.6 from now on, and every new report records it. The version 1 reports were scored at 0.5, are records, and keep their scores.

**The LLM claim split: not adopted.** Answer by answer over 141 answers:

| Split | Agrees with the labels | Bad answers caught | False alarms |
|---|---|---|---|
| Sentence split | 111 of 141 | 39 of 40 | 29 of 101 clean |
| LLM split | 115 of 141 | 39 of 40 | 25 of 101 clean |

The LLM split agrees on 4 more answers (McNemar p = 0.388, shown, not decided on). ADR 0013 adopts it only if it agrees better, and that is a necessary condition, not a sufficient one. It is not adopted because:
- its whole gain is 4 fewer false alarms, and it catches no bad answer the sentence split misses;
- it adds a paid call to a second model on every run;
- the split model and the labeller are both Claude, which may favour it;
- some of the sentence split's false alarms come from a fault in code that is free to fix. The sentence split breaks after "U.S." when a capital letter follows, so 6 of the 200 claim items are fragments such as "Apple also points to the U.S." That fix was a follow-up issue (#83), not this study's, and is now built ([Method](#method-1), step 3).

**What the study does not show.** With Claude's labels it says nothing about whether Jev agrees with a human. A human-labelled sample would be needed to check that, and the committed sheet (with its labels cleared, or a fresh seed) is ready for one.

**No human is in the loop.** Claude labelled the judge study, and the developer did not review the drafted Golden Set and Brief Suite labels ([the review waiver](golden-set.md#what-is-decided)). The developer accepted this as a limitation of the demo (decided 2026-10-17, recorded on #43). In production, hand-labelled data would ideally be used.

### The version 2 comparisons on dev

Run on 2026-10-17 (issue #73): the first round on Golden Set version 2, with one code version, prompt v7, `gpt-6-luna` and `jev-1.13.0` at the fact cut-off 0.6, on the dev split's 60 cases (939 Required Facts, 316 of them must-state). The "How it works" page shows this round, the Brief Suite and the holdout beside dev ([Showing the results](#showing-the-results)). **Every verdict below is directional: one-sided p < 0.10, fixed before running** ([ADR 0011](adr/0011-one-sided-thresholds-and-a-control-run.md)). Each comparison is shown beside the round's Control Run, and each score with its mean paired difference (challenger minus shipped) and 95% bootstrap interval, shown and not decided on.

**Nothing changes what ships.** FTS5, `gpt-6-luna`, 600-token chunks and the 32k budget all stay ([ADR 0008](adr/0008-fts5-stays-the-shipped-arm.md), [ADR 0009](adr/0009-gpt-6-luna-stays-the-generator.md), [ADR 0010](adr/0010-chunk-size-and-context-budget.md)), so the Brief Suite was not run again on a new setup. The reports are in `data/derived/eval/`: `generation-dev.json` and `generation-control-dev.json`, `brief-suite.json` (since replaced by the runs on the fixed measurement, with #73's kept in `data/derived/eval-issue73/`; see [Re-scored on the fixed measurement](#re-scored-on-the-fixed-measurement-2026-10-17)), `retrieval-dev.json` and `arm-choice-dev.json`, `retrieval-dev-chunks<N>-budget<B>.json` and `settings-choice-dev.json`, and `generator-choice-dev.json`, with each challenger's generation report beside them.

#### The baseline and the Control Run

`make eval-arms` ran the round's shipped run and Control Run first, and `make eval-settings` and `make eval-generators` reused both, since the code, prompt and Golden Set version had not changed.

| Run | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | detail recall | Faithfulness | answers with a Contradicted Claim | $ per answer | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Shipped** (`fts5`, `gpt-6-luna`, 600 / 32k) | 60 | 0.87 | 0.90 | 1.00 | 0.72 | 459 | **0.72** | 0.48 | **0.93** | 7 | 0.0028 | 8.2 |
| Control Run (the same, again) | 60 | 0.87 | 0.90 | 1.00 | 0.75 | 467 | 0.71 | 0.49 | 0.92 | 8 | 0.0028 | 8.5 |

The shipped run by kind of question:

| Kind | cases | Fact Recall | detail recall | Faithfulness | structure followed |
|---|---|---|---|---|---|
| Figure trends | 14 | 0.80 | 0.47 | 0.92 | 0.93 |
| Missing Companies | 5 | 0.92 | 0.69 | 0.94 | 1.00 |
| Outlooks | 6 | 0.69 | 0.42 | 0.85 | 0.83 |
| Risk questions | 18 | 0.66 | 0.49 | 0.95 | 0.61 |
| Sector questions | 14 | 0.66 | 0.45 | 0.93 | 0.43 |
| The stale Filing | 3 | 0.83 | 0.50 | 0.94 | 1.00 |

**The Control Run against the shipped run:**

| Score | higher / lower | p ahead | p behind | paired (left out) | mean difference, 95% interval |
|---|---|---|---|---|---|
| Fact Recall | 11 / 10 | 0.500 | 0.668 | 57 (0) | −0.005 [−0.058, +0.039] |
| Faithfulness | 17 / 23 | 0.866 | 0.215 | 56 (0) | −0.008 [−0.042, +0.028] |
| Coverage Gaps | 0 / 0 | 1.000 | 1.000 | 36 (0) | +0.000 [+0.000, +0.000] |
| No Contradicted Claim | 3 / 4 | 0.773 | 0.500 | 59 (0) | −0.017 [−0.102, +0.068] |

- **The Control Run is not ahead on any ahead metric**, so every comparison of the round is conclusive. With nothing changed, Faithfulness moved 17 cases up and 23 down (p behind = 0.215), just short of the 0.20 cut-off for behind: a challenger's Faithfulness verdict within that spread is noise.
- **Failed judgments:** in both runs Jev refused the Faithfulness of `trend-jpm-revenue-snapshot` (`max_tokens_exceeded`, as in every version 1 run). It is recorded against that judgment, so the case's code checks and Fact Recall still count, and Faithfulness pairs 56 cases. Fact Recall pairs 57, since three cases expect only Coverage Gaps. No answer was cut off at the token cap.
- **Not comparable with version 1.** Fact Recall 0.72 is over one-claim, must-state facts at the 0.6 cut-off on 60 cases, against compound facts at 0.5 on 20; version 1's 0.62 to 0.65 measured something else.

#### The Brief Suite

`make eval-brief`, 5 runs a case on the shipped setup: **1 of 15 cases passes.** A case passes when every must-state Required Fact is stated in at least 4 of 5 runs and no run has a Contradicted Claim ([The Brief Suite run](#the-brief-suite-run)).

| Case | Verdict | must-state facts | missed (stated in fewer than 4 runs) | of them, evidence never reached | runs with a Contradicted Claim |
|---|---|---|---|---|---|
| `brief-risk-aapl-tsla-jpm` (the brief's first question) | fail | 9 | 1 | 1 | 0 |
| `brief-risk-aapl-tsla-jpm-rephrased` | fail | 9 | 3 | 2 | 0 |
| `brief-risk-msft-xom-unh` | fail | 9 | 5 | 3 | 0 |
| `brief-risk-aapl-tsla-jpm-fy2025-quarterly-updates` | fail | 5 | 5 | 5 | 1 |
| `brief-followup-aapl-tsla-jpm-cybersecurity` | fail | 6 | 2 | 1 | 0 |
| `brief-outlook-nvda-revenue-two-years` (the brief's second question) | fail | 7 | 3 | 2 | 0 |
| `brief-outlook-nvda-revenue-rephrased` | fail | 7 | 1 | 0 | 0 |
| `brief-outlook-unh-revenue-two-years` | fail | 5 | 1 | 0 | 2 |
| `brief-outlook-nvda-revenue-fy2024` | fail | 5 | 2 | 2 | 0 |
| `brief-followup-nvda-net-income` | **pass** | 3 | 0 | 0 | 0 |
| `brief-sector-pharma-regulatory` (the brief's third question) | fail | 9 | 8 | 8 | 0 |
| `brief-sector-pharma-regulatory-rephrased` | fail | 9 | 8 | 8 | 0 |
| `brief-sector-health-care-regulatory` | fail | 13 | 10 | 9 | 0 |
| `brief-pharma-regulatory-pfe` | fail | 4 | 3 | 3 | 0 |
| `brief-followup-pharma-340b` | fail | 8 | 5 | 5 | 0 |

- **Most misses are retrieval misses.** Of the 57 must-state facts missed across the 14 failing cases, 49 have evidence that never reached the Answer Context in any run, so no generator could have stated them from the Sources. Retrieval is deterministic, so a fact's evidence reaches the prompt in all 5 runs or in none.
- **The pharmaceutical question and its variants fail on retrieval.** All 8 must-state facts the brief's own question misses (the Inflation Reduction Act's effects on each Company, their lawsuits against it and their pricing agreements) have evidence that never reaches the prompt, and so do 25 of the 26 its four variants miss. Some related passages do reach it, such as Eli Lilly's Jardiance being selected for Medicare price negotiation, a detail fact. The question scored 0.00 Fact Recall in most version 1 runs for the same reason ([What the review found](#what-the-review-found)). Fixing it is product work, outside this spec.
- **The brief's first question misses one fact** (Apple's antitrust investigations, never reached). Its other eight must-state facts are stated in at least 4 of 5 runs.
- **The other 8 are generation misses:** the evidence reached the prompt in all 5 runs, and the answer stated the fact in fewer than 4. For example NVIDIA's H20 charge (3 of 5 runs of the rephrasing), Blackwell's share of Data Center revenue (2 of 5) and, in the first question's rephrasing, JPMorgan's limit on capital distributions (0 of 5). No run was cut off, unanswered or lost a judgment.

#### The Arm comparison

`make eval-arms`. **The screen** (the retrieval harness, free) scores all six Arms on Evidence Reached, paired per Required Fact against FTS5 with McNemar's exact test, one-sided:

| Arm | API call at query time | hit@10 | recall@10 | MRR | Evidence Reached | gained / lost vs `fts5` | gate (one-sided) | Source tokens | screen |
|---|---|---|---|---|---|---|---|---|---|
| `fts5` (shipped) | No | 0.93 | 0.85 | 0.78 | 740 of 939 | – | – | 27,321 | – |
| `dense` | Yes | 0.91 | 0.82 | 0.74 | 737 of 939 | 79 / 82, p behind = 0.437 | indistinguishable | 28,477 | dropped: can't ship (available if the one-call limit is lifted) |
| `hybrid` | Yes | 0.93 | 0.88 | 0.79 | 801 of 939 | 72 / 11, p ahead < 0.001 | ahead | 28,461 | dropped: can't ship (available if the one-call limit is lifted) |
| `rerank` | No | 0.93 | 0.87 | 0.77 | 739 of 939 | 14 / 15, p behind = 0.500 | indistinguishable | 27,354 | kept, 2nd |
| `dense-local` | No | 0.91 | 0.81 | 0.76 | 720 of 939 | 74 / 94, p behind = 0.071 | behind | 28,464 | dropped: behind on Evidence Reached |
| `hybrid-local` | No | 0.95 | 0.88 | 0.79 | 774 of 939 | 56 / 22, p ahead < 0.001 | ahead | 28,387 | kept, 1st |

Two shippable challengers pass the screen, `hybrid-local` and `rerank`; `dense-local` is behind on Evidence Reached and goes no further. **If the one-call limit were lifted**, the hosted `hybrid` Arm would be the strongest retrieval: it reaches 801 facts' evidence against FTS5's 740 (72 gained, 11 lost). It was not answered, since it can't ship, so whether that would move Fact Recall is not measured.

**The answers**, against the shipped run:

| Arm | Fact Recall | Faithfulness | answers with a Contradicted Claim | $ per answer | Fact Recall vs `fts5` (higher / lower, p ahead; difference) | Faithfulness vs `fts5` (p behind; difference) | No Contradicted Claim vs `fts5` (p behind; difference) | Qualifies |
|---|---|---|---|---|---|---|---|---|
| `fts5` (shipped) | 0.72 | 0.93 | 7 | 0.0028 | – | – | – | – |
| Control Run | 0.71 | 0.92 | 8 | 0.0028 | 11 / 10, p = 0.500; −0.005 [−0.058, +0.039] | 17 / 23, p = 0.215; −0.008 [−0.042, +0.028] | 3 / 4, p = 0.500; −0.017 [−0.102, +0.068] | – |
| `rerank` | 0.73 | 0.90 | 6 | 0.0028 | 15 / 10, p = 0.212; +0.012 [−0.031, +0.054] | 23 / 19, p = 0.780; +0.009 [−0.023, +0.045] | 3 / 1, p = 0.938; +0.034 [−0.034, +0.102] | no |
| `hybrid-local` | 0.71 | 0.92 | 10 | 0.0029 | 13 / 15, p = 0.714; −0.007 [−0.057, +0.045] | 22 / 20, p = 0.678; +0.011 [−0.020, +0.046] | 5 / 8, p = 0.291; −0.051 [−0.169, +0.068] | no |

Coverage Gaps tie for every Arm (0 / 0 over 36 cases). **Chosen: `fts5`.** Neither challenger is ahead on Fact Recall. `hybrid-local` reaches 34 more facts' evidence than FTS5, 15 of them must-state (20 gained and 5 lost, against FTS5's 248 of 316), but its answers state no more must-state facts (13 cases higher, 15 lower): evidence that reaches the prompt is not always stated. So no local Arm ships, and the local model, its embeddings and its packages stay in `edgar_eval` and the dev dependency group.

#### The settings comparison

`make eval-settings`, naming all 15 other settings of [ADR 0010's grid](adr/0010-chunk-size-and-context-budget.md#the-grid). **The screen**, on the `fts5` Arm, each against 600 / 32k:

| Chunk size | Budget | Evidence Reached | gained / lost | p behind | Source tokens | screen |
|---|---|---|---|---|---|---|
| 300 | 16,000 | 621 of 939 | 15 / 134 | < 0.001 | 14,674 | dropped: behind |
| 300 | 24,000 | 668 of 939 | 24 / 96 | < 0.001 | 20,699 | dropped: behind |
| 300 | 32,000 | 691 of 939 | 31 / 80 | < 0.001 | 25,700 | dropped: behind |
| 300 | 48,000 | 716 of 939 | 51 / 75 | 0.020 | 32,450 | dropped: behind |
| 450 | 16,000 | 607 of 939 | 14 / 147 | < 0.001 | 14,815 | dropped: behind |
| 450 | 24,000 | 685 of 939 | 21 / 76 | < 0.001 | 21,270 | dropped: behind |
| 450 | 32,000 | 716 of 939 | 32 / 56 | 0.007 | 26,731 | dropped: behind |
| 450 | 48,000 | 759 of 939 | 60 / 41 | 0.977 | 35,763 | kept, 3rd |
| 600 | 16,000 | 634 of 939 | 0 / 106 | < 0.001 | 14,837 | dropped: behind |
| 600 | 24,000 | 699 of 939 | 0 / 41 | < 0.001 | 21,505 | dropped: behind |
| **600** | **32,000** (shipped) | **740 of 939** | – | – | 27,321 | – |
| 600 | 48,000 | 780 of 939 | 40 / 0 | 1.000 | 36,922 | kept, 1st |
| 800 | 16,000 | 619 of 939 | 20 / 141 | < 0.001 | 14,621 | dropped: behind |
| 800 | 24,000 | 697 of 939 | 35 / 78 | < 0.001 | 21,468 | dropped: behind |
| 800 | 32,000 | 729 of 939 | 38 / 49 | 0.142 | 27,481 | dropped: behind |
| 800 | 48,000 | 780 of 939 | 63 / 23 | 1.000 | 37,846 | kept, 2nd |

Only the three 48k budgets are not behind, so all three go on; 600 / 48k and 800 / 48k tie at 780 facts, and 600 / 48k goes first as the cheaper in Source tokens. Every smaller budget, and every other chunk size at 32k, reaches less.

**The answers**, against the shipped run:

| Setting | Fact Recall | Faithfulness | answers with a Contradicted Claim | $ per answer | Fact Recall vs 600 / 32k (higher / lower, p ahead; difference) | Faithfulness vs 600 / 32k (p ahead, p behind; difference) | No Contradicted Claim vs 600 / 32k (p behind; difference) | Qualifies |
|---|---|---|---|---|---|---|---|---|
| **600 / 32k** (shipped) | 0.72 | 0.93 | 7 | 0.0028 | – | – | – | – |
| Control Run | 0.71 | 0.92 | 8 | 0.0028 | 11 / 10, p = 0.500; −0.005 [−0.058, +0.039] | 17 / 23, p behind = 0.215; −0.008 [−0.042, +0.028] | 3 / 4, p = 0.500; −0.017 [−0.102, +0.068] | – |
| 600 / 48k | 0.73 | 0.94 | 6 | 0.0036 | 12 / 9, p = 0.332; +0.017 [−0.019, +0.057] | 21 / 17, p behind = 0.791; +0.015 [−0.019, +0.050] | 3 / 2, p = 0.812; +0.017 [−0.051, +0.085] | no |
| 800 / 48k | 0.74 | 0.94 | 5 | 0.0036 | 14 / 13, p = 0.500; +0.021 [−0.026, +0.069] | 26 / 8, **p ahead = 0.001**; +0.033 [+0.009, +0.063] | 5 / 3, p = 0.855; +0.034 [−0.051, +0.136] | no |
| 450 / 48k | 0.69 | 0.93 | 7 | 0.0035 | 10 / 13, p = 0.798; −0.025 [−0.067, +0.014] | 22 / 18, p behind = 0.785; +0.004 [−0.026, +0.038] | 3 / 3, p = 0.656; +0.000 [−0.085, +0.085] | no |

Coverage Gaps tie for every setting (0 / 0 over 36 cases). **Chosen: 600-token chunks and the 32k budget.** No setting is ahead on Fact Recall, the one score the rule switches on.

- **800-token chunks at 48k are ahead on Faithfulness** (26 cases higher, 8 lower, p = 0.001, interval wholly above zero), well outside the Control Run's spread (17 / 23). The rule does not switch on Faithfulness, so it does not qualify; it is the first candidate if Faithfulness ever becomes a reason to switch, at about $0.0008 more per answer (30% more).
- **The 48k budget again adds evidence without adding stated facts.** At 600-token chunks it reaches 40 more facts' evidence and loses none, as in version 1, and Fact Recall moves 12 cases up and 9 down.

#### The generator comparison

`make eval-generators`: `claude-haiku-5-5` against `gpt-6-luna`, on the setup the Arm and settings comparisons kept (`fts5`, 600 / 32k).

| Generator | citations valid | structure followed | words | Fact Recall | Faithfulness | answers with a Contradicted Claim | truncated | input tokens | output tokens | $ per answer | latency s | first text s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **`gpt-6-luna`** (shipped) | 0.87 | 0.72 | 459 | **0.72** | **0.93** | 7 | 0 | 23,760 | 832 | 0.0028 | 8.2 | 2.2 |
| `claude-haiku-5-5` | 0.42 | 0.50 | 423 | 0.38 | 0.82 | 10 | 27 | 36,650 | 2,094 | 0.0047 | 9.5 | 5.3 |

| `claude-haiku-5-5` vs `gpt-6-luna` | higher / lower | p ahead | p behind | paired (left out) | mean difference, 95% interval | verdict |
|---|---|---|---|---|---|---|
| Fact Recall | 5 / 35 | 1.000 | < 0.001 | 57 (0) | −0.337 [−0.436, −0.241] | behind |
| Faithfulness | 11 / 37 | 1.000 | < 0.001 | 55 (2) | −0.099 [−0.153, −0.048] | behind |
| Coverage Gaps | 0 / 1 | 1.000 | 0.500 | 36 (0) | −0.028 [−0.083, +0.000] | indistinguishable |
| No Contradicted Claim | 5 / 7 | 0.806 | 0.387 | 59 (1) | −0.034 [−0.153, +0.085] | indistinguishable |

**Chosen: `gpt-6-luna`.** Claude Haiku 5.5 is behind on Fact Recall and Faithfulness, far outside the Control Run's spread (shown in the Arm table above), and costs 1.7 times as much per answer.

- **Truncation drives the Fact Recall gap.** 27 of Haiku's 60 answers stopped at the 2,500-token cap, which includes thinking, and each fails with Fact Recall 0 ([Method](#method-1), step 1). On the 30 cases where Haiku's answer was not cut off and both sides scored Fact Recall, Haiku states 0.72 against Luna's 0.77 (5 cases higher, 8 lower; shown, not decided on). A fair second look would need a higher cap or a prompt pass for Claude's longer answers, as ADR 0009 found for Sonnet and Opus.
- **Its price is the tokenizer and the thinking.** Both models list $0.10 in and $0.50 out per million tokens, but Haiku counts the same prompts as about 1.5 times as many input tokens and writes 2.5 times as many output tokens, thinking included.

#### Spend

Nine paid runs: the shipped run and Control Run, the Brief Suite (75 Answer Calls), two Arms, three settings and Claude Haiku 5.5. Each printed its estimate first (none above $0.51). **$1.84 in Answer Calls and $0.93 in Jev judging, $2.77 in all**, inside the $3 to $4 expected. The screens cost nothing; the hosted `dense` and `hybrid` Arms embedded the new questions once with OpenAI for the screen, at a fraction of a cent, and cached them. The holdout was scored afterwards, once ([The version 2 holdout run](#the-version-2-holdout-run)).

#### Re-scored on the fixed measurement (2026-10-17)

Issue #92, after the measurement fixes of spec #88 had landed: #86 keeps an answer's expected Coverage Gap sentences from Jev's Faithfulness judgment, #89 narrows the claim exemption to stated Coverage Gaps, #90 scores a truncated answer's Fact Recall 0 when its judgment failed, and #91 moves the default generator list into `generators.py`. The results above are #73's and stand as recorded: none of its comparisons is re-run or re-decided, and the holdout is not scored again, since a measurement fix changes no choice. This note gives the new baseline that the retrieval work measures against: the shipped setup (`fts5`, `gpt-6-luna`, 600 / 32k, prompt v7, `jev-1.13.0` at 0.6) answered the 60 dev cases twice, as this round's shipped run and Control Run, and the Brief Suite 5 runs a case, all on code version `b82c73f3d9280d98`.

**Each fix's effect on #73's reports**, re-scored offline with no Answer Call and no Jev call (`make eval-rescore`), so the answers are #73's and only the measurement moved:

| Report | Faithfulness | Contradicted Claims (answers) | Fact Recall | Brief Suite |
|---|---|---|---|---|
| Shipped run | 0.928 → **0.935** | 7 (7) → 7 (7) | 0.717, unchanged | – |
| Control Run | 0.919 → **0.928** | 9 (8) → **7 (6)** | 0.712, unchanged | – |
| Brief Suite (75 answers) | per run, 0.925–0.968 → 0.940–0.975 | 3 → 3 | unchanged | 1 of 15 → 1 of 15 |

- **#86 is the one fix that moved #73's numbers.** It kept 19 Coverage Gap sentences from Jev in each dev run and 24 in the Brief Suite. In the Control Run two of them had been judged contradicted, so two answers lost their Contradicted Claim.
- **#89 changed no claim in #73's reports**, **#90 changed nothing** (none of their answers was truncated), and **#91 changes no score.**

**The new runs, on the fixed measurement:**

| Run | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | detail recall | Faithfulness | answers with a Contradicted Claim | $ per answer | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Shipped** (`fts5`, `gpt-6-luna`, 600 / 32k) | 60 | 0.92 | 0.95 | 1.00 | 0.82 | 453 | **0.70** | 0.47 | **0.94** | 4 | 0.0028 | 7.4 |
| Control Run (the same, again) | 60 | 0.95 | 0.88 | 1.00 | 0.75 | 462 | 0.73 | 0.49 | 0.92 | 6 | 0.0028 | 8.1 |
| #73's shipped run, re-scored | 60 | 0.87 | 0.90 | 1.00 | 0.72 | 459 | 0.72 | 0.48 | 0.93 | 7 | 0.0028 | 8.2 |

| Control Run against the shipped run | higher / lower | p ahead | p behind | paired (left out) | mean difference, 95% interval |
|---|---|---|---|---|---|
| Fact Recall | 16 / 10 | 0.163 | 0.916 | 57 (0) | +0.027 [−0.013, +0.066] |
| Faithfulness | 14 / 15 | 0.644 | 0.500 | 58 (1) | −0.004 [−0.021, +0.013] |
| Coverage Gaps | 0 / 0 | 1.000 | 1.000 | 36 (0) | +0.000 [+0.000, +0.000] |
| No Contradicted Claim | 3 / 5 | 0.855 | 0.363 | 60 (0) | −0.033 [−0.133, +0.050] |

- **The baseline is the shipped run: Fact Recall 0.70, Faithfulness 0.94, 4 answers with a Contradicted Claim** (4 claims), 51 of 60 answers passing. The Control Run, the same setup again, scores 0.73 and 0.92 with 6 (7 claims). It is not ahead on any score at p < 0.10, so a comparison against this round is conclusive, but its Fact Recall spread, 16 cases up and 10 down, is the noise a retrieval change has to beat.
- **Against #73, the differences are new answers, not the fixes.** Fact Recall 0.70 and 0.73 against #73's 0.72 and 0.71, and Faithfulness 0.94 and 0.92 against the re-scored 0.935 and 0.928, sit inside one Control Run's spread. The code checks moved the same way (citations valid 0.92 and 0.95 against 0.87), with the same prompt and Sources.
- **No judgment failed.** Jev judged `trend-jpm-revenue-snapshot`'s Faithfulness in both runs, the first time on any run, so Faithfulness pairs 58 cases. No answer stopped at the token cap, so #90 had nothing to score.
- **#89 shows on the missing-Company cases.** Their Faithfulness is 0.72 in the shipped run and 0.58 in the Control Run, against 0.94 in #73's. `missing-citigroup` (both runs) and `followup-ge-to-honeywell` (Control Run) have no Sources, and score Faithfulness 0.0. Their uncited refusals ("Citigroup is not covered in this answer.", "I can't assess its recent performance from this material.") and a stray "[Coverage Gaps]" tag are now claims, unsupported because they cite nothing. #73's answers to these cases worded their refusals so that the exemption covers them, before #89 and after, so they had no claim left to judge and scored no Faithfulness. This is a measurement question for a later issue: such a refusal states no fact.

**The Brief Suite: 1 of 15 cases passes**, as in #73. The one pass is again `brief-followup-nvda-net-income`, and 3 runs have a Contradicted Claim, as before.

| Case | Verdict | must-state facts | missed (stated in fewer than 4 runs) | of them, evidence never reached | runs with a Contradicted Claim |
|---|---|---|---|---|---|
| `brief-risk-aapl-tsla-jpm` (the brief's first question) | fail | 9 | 2 | 1 | 0 |
| `brief-risk-aapl-tsla-jpm-rephrased` | fail | 9 | 3 | 2 | 0 |
| `brief-risk-msft-xom-unh` | fail | 9 | 4 | 3 | 0 |
| `brief-risk-aapl-tsla-jpm-fy2025-quarterly-updates` | fail | 5 | 5 | 5 | 1 |
| `brief-followup-aapl-tsla-jpm-cybersecurity` | fail | 6 | 1 | 1 | 0 |
| `brief-outlook-nvda-revenue-two-years` (the brief's second question) | fail | 7 | 3 | 2 | 0 |
| `brief-outlook-nvda-revenue-rephrased` | fail | 7 | 2 | 0 | 0 |
| `brief-outlook-unh-revenue-two-years` | fail | 5 | 1 | 0 | 0 |
| `brief-outlook-nvda-revenue-fy2024` | fail | 5 | 2 | 2 | 1 |
| `brief-followup-nvda-net-income` | **pass** | 3 | 0 | 0 | 0 |
| `brief-sector-pharma-regulatory` (the brief's third question) | fail | 9 | 8 | 8 | 0 |
| `brief-sector-pharma-regulatory-rephrased` | fail | 9 | 8 | 8 | 0 |
| `brief-sector-health-care-regulatory` | fail | 13 | 9 | 8 | 0 |
| `brief-pharma-regulatory-pfe` | fail | 4 | 3 | 3 | 0 |
| `brief-followup-pharma-340b` | fail | 8 | 5 | 5 | 1 |

- **Still mostly retrieval misses:** 48 of the 56 must-state facts missed across the 14 failing cases have evidence that never reached the Answer Context (49 of 57 in #73). Every must-state fact the pharmaceutical question misses is still one whose evidence never reaches the prompt.
- **Five cases moved by one fact each, all generation noise.** Retrieval is unchanged, so each fact's evidence reached the prompt in the same runs as in #73. The brief's first question now also misses JPMorgan's limit on capital distributions (stated in 1 of 5 runs, against 5 of 5), and the NVIDIA rephrasing misses the H20 export licensing effect (2 of 5, against 4). Three facts are now stated in 4 of 5 runs: Microsoft's competition (`brief-risk-msft-xom-unh`) and Tesla's unauthorized-access attempts (the cybersecurity follow-up), whose evidence reached the prompt, and Pfizer's price-control regulations (`brief-sector-health-care-regulatory`), whose evidence never did, so the answers state it from other passages. The contradicted runs moved from `brief-outlook-unh-revenue-two-years` (2 runs) to one run each of three other cases. No run was cut off or lost a judgment.

**Reports.** The new reports replace #73's in `data/derived/eval/` (`generation-dev.json`, `generation-control-dev.json` and `brief-suite.json`). #73's are kept as written in `data/derived/eval-issue73/`. The "How it works" page shows the new shipped run, Control Run and Brief Suite, beside #73's generator comparison, which stands as recorded.

**Spend.** The three runs printed their estimates first (up to $0.38, $0.38 and $0.47). They cost $0.25 (the shipped run: $0.168 in Answer Calls, $0.082 in Jev judging), $0.26 (the Control Run: $0.169 and $0.087) and $0.39 (the Brief Suite: $0.240 and $0.153), **$0.90 in all**. A version 2 dev run costs about $0.25, not version 1's $0.07: it has 60 cases, not 20.

### The version 2 holdout run

Run once on 2026-10-17 (issue #74), after [the version 2 comparisons on dev](#the-version-2-comparisons-on-dev) had confirmed every shipped choice, on Golden Set version 2's 20 holdout cases. It is the same round as those comparisons (code version `756bfadca63122a9`, prompt v7, Golden Set version 2) and the setup that ships: the `fts5` Arm, 600-token chunks and the 32k budget, `gpt-6-luna` at reasoning effort `low`, judged by `jev-1.13.0` at the fact cut-off 0.6. Under [the holdout rule](#the-holdout-rule) it reports and decides nothing: nothing was changed after it, and no case was relabelled. [Version 1's holdout run](#the-holdout-run) stands as recorded.

```sh
make eval-retrieval SPLIT=holdout ARMS=fts5
make eval-generation SPLIT=holdout
```

The reports are `data/derived/eval/retrieval-holdout.json` and `generation-holdout.json`, each recording Golden Set version 2; version 1's holdout reports of the same names are kept in `data/derived/eval-golden-set-v1/`. The generation run printed its estimate first (up to $0.13) and cost **$0.057 in Answer Calls and $0.028 in Jev judging, $0.085 in all**. The retrieval run cost nothing.

**Retrieval**, the `fts5` Arm, beside the same Arm on dev (`retrieval-dev.json`):

| Split | cases scored | hit@5 | hit@10 | hit@20 | recall@10 | recall@all | MRR | Sources | Source tokens | Evidence Reached | must-state reached |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Holdout** | 19 | 0.84 | **0.89** | 0.95 | 0.82 | 0.92 | 0.75 | 15.3 | 26,293 | 261 of 319 (82%) | 87 of 106 (82%) |
| Dev | 57 | 0.89 | 0.93 | 0.96 | 0.85 | 0.94 | 0.78 | 11.6 | 27,321 | 740 of 939 (79%) | 248 of 316 (78%) |

`missing-broadcom-revenue` expects no Source, so 19 of the 20 holdout cases are scored. The two misses at hit@10 are follow-ups: `followup-topic-change-stock-splits` (below) and `followup-aapl-buybacks-change`.

**Answers**, beside the round's shipped run and Control Run on dev ([The baseline and the Control Run](#the-baseline-and-the-control-run)):

| Run | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | detail recall | Faithfulness | answers with a Contradicted Claim | $ per answer | latency s | first text s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Holdout** | 20 | 0.95 | 0.90 | 1.00 | 0.60 | 435 | **0.74** | 0.59 | **0.95** | 3 | 0.0028 | 7.8 | 2.3 |
| Dev, shipped run | 60 | 0.87 | 0.90 | 1.00 | 0.72 | 459 | 0.72 | 0.48 | 0.93 | 7 | 0.0028 | 8.2 | 2.2 |
| Dev, Control Run | 60 | 0.87 | 0.90 | 1.00 | 0.75 | 467 | 0.71 | 0.49 | 0.92 | 8 | 0.0028 | 8.5 | – |

Gaps stated is over the 11 holdout cases with expected gaps, and Fact Recall over the 19 with must-state facts. No judgment failed and no answer stopped at the token cap. The answers averaged 24,500 input and 790 output tokens; the slowest took 11.9 seconds. 16 of the 20 answers pass, against 45 of 60 on dev.

By question type:

| Type | cases | Fact Recall | detail recall | Faithfulness | structure followed |
|---|---|---|---|---|---|
| Figure trends | 5 | 0.90 | 0.66 | 0.93 | 0.80 |
| Missing Companies | 1 | – | – | – | 1.00 |
| Outlooks | 1 | 1.00 | 0.75 | 1.00 | 0.00 |
| Risk questions | 9 | 0.64 | 0.53 | 0.95 | 0.56 |
| Sector questions | 4 | 0.70 | 0.60 | 0.96 | 0.50 |

- **The holdout scores are in line with dev.** Fact Recall 0.74 and Faithfulness 0.95 against the shipped run's 0.72 and 0.93 (and the Control Run's 0.71 and 0.92); hit@10 0.89 against 0.93; Evidence Reached 82% against 79%. On 20 cases one case moves a share by 0.05, so this says the dev choices did not overfit, not that the holdout is easier or the setup better.
- **The misses split as on dev.** The answers miss 31 of the 106 must-state facts (29%, against 95 of 316 on dev); 15 of them have evidence that never reached the Answer Context (46 on dev). The lowest are `followup-topic-change-stock-splits` (0.00), `risk-cvx-xom-commodity-prices` (0.33), `risk-v-ma-cybersecurity` (0.40) and `sector-financials-digital-assets` (0.50), most of whose misses are retrieval misses; `sector-retailers-workforce` (0.60) misses four facts whose evidence did reach it.
- **The one zero is ADR 0003's known weakness.** `followup-topic-change-stock-splits` asks "Which companies carried out a stock split in 2024 or 2025?" after a Coca-Cola question. It names no Company or Sector phrase, so the rules inherit Coca-Cola, which split no stock, and none of its facts' evidence (NVIDIA's, Walmart's and Netflix's splits) reaches the prompt. The answer says so honestly, but its uncited opening sentence makes it the one answer with an invalid citation. Dev's `followup-topic-change-export-controls` scores 0.00 for the same reason.
- **The two figure failures are labelled derivations**, as on dev and in version 1: Tesla's energy revenue growth over two years ("a derived increase of about 112%") and Apple's and Microsoft's net income increases, each computed by the model and labelled as derived.
- **Three answers have a Contradicted Claim**, each a summary sentence: Tesla's energy growth "slower than in FY2024", Amazon's segments' contribution "not stated in the provided excerpt", and a takeaway comparing Apple's and NVIDIA's research spending. The judge study found Jev's contradicted verdicts noisy ([The judge study's results](#the-judge-studys-results)), so some of these may be false alarms; they are reported as Jev gave them.
- **Fewer answers follow the structure** (0.60 against 0.72): four run over 600 words, three fall under 300 (a follow-up, a figure trend and an outlook), three have no heading for one of their Companies, and one opens with five sentences rather than two or three.

### Order and cost

1. The Brief Suite and the label format.
2. The measurement fixes and the decision thresholds.
3. Version 1's 27 other cases, rewritten in the new format.
4. The judge study, on those rewritten facts.
5. Golden Set version 2's 53 new cases, drafted in slices of at most ten, one slice at a time, then the split frozen.
6. The Arm, settings and generator comparisons on it, then the holdout, once.

Labels are drafted in Claude Code, not through the API. The API spend is expected to be about $5 to $6, budgeted at $20 to allow for reruns: about $2 for the judge study and the rest for the comparisons and the Brief Suite, with `gpt-6-luna` and `claude-haiku-5-5` answering and Jev judging. The comparisons on dev and their Brief Suite run cost $2.77 ([Spend](#spend)), and the holdout run $0.085 ([The version 2 holdout run](#the-version-2-holdout-run)). All six steps are built and run. The larger cost was to be the developer's time: about 4 to 7 hours labelling for the judge study. In the event the developer delegated that labelling to Claude ([The judge study's results](#the-judge-studys-results)). Reviewing Golden Set version 2's drafted facts would take about 7 hours more. Because this is a quick-turn demo, it is acceptable to skip it, and the developer chose to (decided 2026-10-17, recorded on #43): the mechanical checks (verbatim evidence against the Corpus, the SEC company-facts reference for figures, the duplicate-question check) and the implementer's read-back stand in for it.
