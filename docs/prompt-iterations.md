# Prompt iteration log

Every version of the Answer Call's prompt template, newest last. The template lives in [`backend/src/edgar_rag/_prompt.py`](../backend/src/edgar_rag/_prompt.py), and its `PROMPT_VERSION` constant is logged with every Answer Call (`data/derived/logs/answer_calls.jsonl`), so each logged answer can be traced to the template that produced it.

A change to the template bumps `PROMPT_VERSION` and adds an entry here: what changed, why, and the dev-split scores before and after (retrieval and generation harnesses, on the Golden Set's dev cases only). Up to v15 each version was kept or discarded by a rule written on its ticket before its run, recorded in its entry; from v16, a version is decided by [ADR 0017](adr/0017-prompt-changes-decided-by-two-rules.md)'s `prompts` or `prompt-fix` rule, applied offline to its report (`make eval-generation NAME=v16`, then `python -m edgar_eval.selection compare ... --rule prompts`). The holdout split is scored once per final setup, on the final version, and never used to choose ([the holdout rule](evaluation.md#the-holdout-rule)).

## v1: the tracer bullet

**What.** The first complete template, in this order:

1. System rules: use only the Sources, cite every claim `[Sn]`, earlier turns are not evidence, give form type and fiscal period, quote figures exactly, and the PE-analyst structure of assumption 8.
2. The Sources, grouped by Company under `## Company (TICKER)` headings. Each opens with its tag and label, e.g. `[S1] AAPL 10-K FY2025, Risk Factors (Item 1A). Filing ID AAPL_10-K_2025-09-27, Report Period 2025-09-27.`
3. The earlier conversation: the last 10 turns, capped at about 6k tokens by dropping the oldest. Earlier answers lose their `[Sn]` tags, which pointed at that turn's Sources.
4. The latest question.

The rules go in a system message; everything else goes in one user message.

**Why.** It is the thinnest prompt that makes a grounded, cited answer possible from the tracer-bullet retrieval, so the harnesses have something to score. Coverage Gaps and the Financial Facts table are not computed yet; they join the template between the rules and the Sources when the Query Scope parser and the Financial Facts store reach the Answer Context.

**Known gaps.** Earlier Source tags are dropped rather than rewritten as Filing IDs, because the browser does not send the earlier turns' Sources yet. There are no fixed Coverage Gap wordings, so the model writes its own coverage note.

**Scores.** Retrieval on dev, from the retrieval harness: hit@10 0.71, recall@10 0.52, MRR 0.39 over 17 scored cases ([evaluation notes](evaluation.md#first-fts5-numbers-on-dev)). Generation on dev, from the generation harness (`gpt-6-luna`, judged by `jev-1.13.0`): Fact Recall 0.45, Faithfulness 0.90, citations valid 0.75, figures exact 0.85, Coverage Gaps stated 0.67, $0.0027 and 6.1 seconds per answer ([evaluation notes](evaluation.md#first-scores-on-dev)); after time windows, Section hints, risk routing and deduplication, Fact Recall 0.55 and Faithfulness 0.93 ([evaluation notes](evaluation.md#after-time-windows-section-hints-risk-routing-and-deduplication)). Hand check on the brief's first example (`make ask`, `gpt-6-luna`): every point cites Sources from Apple, Tesla and JPMorgan, it says the Companies' periods differ, and it says JPMorgan's Item 1A risk factors were not among the Sources. About 26k input and 900 output tokens, 9 seconds.

### The v1 system rules

```text
You are a research assistant for private equity analysts. You answer business questions about public companies using only the excerpts from their SEC 10-K and 10-Q filings given to you as numbered Sources.

Rules:
1. Use only the Sources. Never use general knowledge, memory or any outside data, even for well-known facts. If the Sources do not answer part of the question, say so plainly.
2. Cite every claim with the tag of the Source it comes from, e.g. [S3], placed right after the claim. Use several tags when a claim rests on several Sources. Cite only tags listed in this turn's Sources.
3. The earlier conversation is there to help you understand the question. It is not evidence: never repeat a claim from an earlier answer unless a Source in this turn supports it, and then cite that Source.
4. When you use a Company's filings, give the filing's form type and fiscal period, and say so when the Companies you compare report for different periods.
5. Quote figures exactly as the Sources give them, with their units and periods.

Structure the answer for a PE analyst, in Markdown:
- Open with a direct answer in two or three sentences.
- Then give the points for each Company under its own heading, or a comparison table when several Companies are compared on the same dimensions.
- End with a short "Coverage" note saying what the Sources could not answer.
- Aim for 300 to 600 words.
```

### The v1 user message

```text
# Sources

## Apple Inc (AAPL)

[S1] AAPL 10-K FY2025, Risk Factors (Item 1A). Filing ID AAPL_10-K_2025-09-27, Report Period 2025-09-27.
<the retrieved chunks of that Section, in body order, separated by […]>

[S2] ...

## Tesla Inc (TSLA)

...

# Earlier conversation (context only, not evidence)

User: <earlier question>

Assistant: <earlier answer, Source tags removed>

# Question

<the latest user message>
```

The earlier-conversation block is left out when there is no history.

## v2: Companies a Sector phrase resolved to

**What.** When the question uses a Sector phrase, a `# Companies in scope` block goes before the Sources, one line per phrase:

```text
# Companies in scope

"pharmaceutical companies" was resolved through the Sector table (industry: Pharmaceuticals or Biotechnology) to: Johnson & Johnson (JNJ), Eli Lilly and Company (LLY), Merck & Co Inc (MRK), Pfizer Inc (PFE), AbbVie Inc (ABBV).
```

A sixth system rule tells the model what the block means:

```text
6. When the question names a group of companies ("the major banks"), it was resolved through a curated Sector table to the Companies listed under "Companies in scope". Name those Companies near the start of the answer, say they come from the Sector table, and cover no other company for that group.
```

Everything else is unchanged from v1. A question with no Sector phrase gets no block.

**Why.** The analyst must be able to dispute a mapping (user story 15, assumption 5), so the answer has to say which Companies "the major pharmaceutical companies" meant. Under v1 the model saw only Sources grouped by Company and could name some Companies and skip the ones whose Sources said little, or add a company it remembered as a drug maker.

**Scores.** Retrieval on dev, from the retrieval harness: hit@10 0.71 → 0.71, recall@10 0.58 → 0.65, MRR 0.56 → 0.59; the two sector cases go from recall@10 0.47 to 1.00 ([evaluation notes](evaluation.md#after-sector-phrases)). The retrieval gain comes from resolving the phrase, not from the template. The generation harness is not built yet, so there are no answer scores before and after. Hand check on the brief's third example ("What regulatory risks do the major pharmaceutical companies face?", `make ask`, `gpt-6-luna`): the answer opens "The Sector table defines the companies in scope as Johnson & Johnson (JNJ), Eli Lilly and Company (LLY), Merck & Co. (MRK), Pfizer (PFE), and AbbVie (ABBV)", covers those five and no other company, and cites a Source from each. About 21.5k input and 1,000 output tokens, 13.5 seconds.

## v3: Coverage Gaps and each Company's coverage

**What.** The user message gains two blocks, so it now runs: Coverage Gaps, Companies in scope (when the question uses a Sector phrase), Coverage, Sources, earlier conversation, question.

- `# Coverage Gaps` comes first, one bullet per gap, or `None.` Code computes every gap ([`_coverage.py`](../backend/src/edgar_rag/_coverage.py)) and words it the same way every time, after EDA notebook section 8.6. Each wording starts with a fixed label:
  - **Trend unavailable** (a trend asked of a Snapshot Company): "Trend unavailable: JPMorgan Chase is a Snapshot Company. The Corpus holds 4 JPMorgan Chase Filings, Q1 FY2025 to FY2025 (JPM_10-Q_2025-03-31, JPM_10-Q_2025-06-30, JPM_10-Q_2025-09-30, JPM_10-K_2025-12-31), so this answer covers Report Periods 2025-03-31 to 2025-12-31 only." A trend is a change or trend word ("changed", "evolved", "trend", "grew", "over time", "year over year") or a time window longer than a quarter. "How do they differ" compares Companies and is not a trend.
  - **Not in the Corpus** (a Company on the curated list of notable missing Companies, [`data/README.md`](../data/README.md#companies-missing-from-the-corpus-referencemissing_companiescsv)): "Not in the Corpus: Wells Fargo is not in the Filings provided, so this answer does not cover it."
  - **Stale Filing** (GE Capital's FY2014 10-K, whenever General Electric is in scope): "Stale Filing: the only General Electric Filing is GE Capital's 10-K for FY2014 (Report Period 2014-12-31); it does not describe General Electric today, so it is left out of this answer." When the question asks for GE Capital or 2014 by name, the Filing is retrieved and the wording ends "so it is cited here only as GE Capital's report for FY2014." instead.
  - **No guidance in the Filings** (a question about the outlook, guidance, forecasts, projections or next year): "No guidance in the Filings: NVIDIA's own guidance is not in the Filings provided; the outlook below is drawn from MD&A commentary and risk factors."
  - **Periods differ** (two or more Companies whose latest 10-Ks in scope, or latest Filings when the window holds no 10-K, end more than 20 days apart): "Periods differ: the Companies' latest Filings here cover different periods (Apple: 10-K FY2025, year to 2025-09-27; Tesla: 10-K FY2025, year to 2025-12-31; JPMorgan Chase: 10-K FY2025, year to 2025-12-31), so the comparison is not of the same period."
- `# Coverage` gives one paragraph per Company in scope (or, for a question naming no Company, per Company a Source came from): its coverage class, how many Filings the Corpus holds and over which Fiscal Periods, every Filing in the time window with its Form Type, Fiscal Period and Report Period, and any stale Filing left out:

```text
# Coverage

JPMorgan Chase & Co (JPM): Snapshot Company; 4 Filings in the Corpus, Q1 FY2025 to FY2025.
In scope: JPM_10-K_2025-12-31 (10-K FY2025, Report Period 2025-12-31).
```

Two system rules change and one is added:

```text
4. When you use a Company's filings, give the filing's form type, fiscal period and report period, as listed under "Coverage", and say so when the Companies you compare report for different periods.
7. "Coverage Gaps" lists what the filings cannot answer: a trend asked of a company with only a snapshot of filings, a company not in the filings, a stale filing, guidance the filings do not contain, or periods that differ. State every gap listed there, in the words given, near the start of the answer. Never fill a gap from general knowledge: say nothing about a company the filings do not include, never use a filing listed as left out, and never present MD&A commentary as the company's guidance.
```

and the closing structure line becomes `- End with a short "Coverage" note repeating the Coverage Gaps and saying what else the Sources could not answer.`

Retrieval changes with it: the stale GE Capital Filing is kept out of every Answer Context unless the question asks for GE Capital or its period by name, and a question that names only missing Companies retrieves no Sources (before, "What are Citigroup's main risk factors?" searched every Company and brought 47 Sources from 36 other Companies).

**Why.** Under v2 the model wrote its own coverage note, so whether a Snapshot trend, a missing Company or the stale GE Filing was mentioned, and in what words, depended on the model (user stories 20–26, assumptions 3, 4, 6, 7 and 9). The gaps are facts about the Corpus, so code can compute them exactly and the prompt only has to ask for them to be stated. The coverage block gives the model the Report Period and Fiscal Period of every Filing it may cite, so it can state them beside each Company's points without reading them out of Source labels. The same gaps stream to the workspace as a `data-coverage-gaps` part and show as a callout beside the answer, so they are visible even if an answer leaves one out.

**Scores.** Retrieval on dev, from the retrieval harness: unchanged (hit@10 0.71, recall@10 0.65, MRR 0.59 over 17 scored cases). The three dev cases with no expected Source now get none: `stale-ge-recent-performance` 7 → 0 Sources (all from GE Capital's FY2014 10-K before), `missing-citigroup` 47 → 0, `followup-ge-to-honeywell` 0 → 0. Computed gaps against the Golden Set's expected Coverage Gaps on dev: 19 of 20 cases get every expected gap, with no gap the labels do not expect. The miss is `followup-regulatory-exposure` ("Which of them has the most regulatory exposure?"), which names no Company and needs follow-up inheritance (ADR 0003) before its periods can be compared. Generation on dev (`gpt-6-luna`, `jev-1.13.0`), against the last scored run (prompt v1, retrieval before Sector phrases; prompt v2 was never scored): Coverage Gaps stated 0.50 → 0.91, Fact Recall 0.55 → 0.55, Faithfulness 0.93 → 0.90, citations valid 0.95 → 0.79, figures exact 0.90 → 0.95, $0.0026 → $0.0024 per answer ([evaluation notes](evaluation.md#after-coverage-gaps-prompt-v3)). The only gap still missed is the same follow-up. The citation drop is mostly the check's wording rules: the GE answer's "it is stale and left out of this answer" is an absence the check does not yet exempt. 19 of 20 cases were scored, since Jev refused one judging request as too long.

## v4: the Financial Facts table

**What.** When the question names a metric (revenue, net income, a segment name, or "segment"), a `# Financial Facts` block goes between `# Coverage` and the Sources. It lists the Facts Sources (one per Filing the figures come from, numbered first), then one table, then a note for anything the store can't answer:

```text
# Financial Facts

Figures extracted from the Filings' income statements and segment tables. Each tag below is the Financial Facts of one Filing; cite the tags a row lists. Values are in US dollars. Rows marked derived are computed from the rows they cite, not reported.

[S1] NVDA 10-Q Q1 FY2024, Financial Facts. Filing ID NVDA_10-Q_2023-04-30, Report Period 2023-04-30.
...
[S11] NVDA 10-Q Q3 FY2026, Financial Facts. Filing ID NVDA_10-Q_2025-10-26, Report Period 2025-10-26.

| Company | Metric | Fiscal Period | Period | Value | Basis | Change from a year earlier (derived) | Sources |
|---|---|---|---|---|---|---|---|
| NVDA | Revenue | Q4 FY2024 | 3 months ended 2024-01-28 | $22,103 million | derived: FY2024 less Q1–Q3 FY2024, $60,922 million [S4] less $7,192 million [S1], $13,507 million [S2], $18,120 million [S3] |  | [S4] [S1] [S2] [S3] |
| NVDA | Revenue | FY2024 | 12 months ended 2024-01-28 | $60,922 million | reported as "Revenue" |  | [S4] |
...
| NVDA | Revenue | Q3 FY2026 | 3 months ended 2025-10-26 | $57,006 million | reported as "Revenue" | +62.5% [S11] [S7] | [S11] |

- JPMorgan Chase & Co (JPM) is a Snapshot Company, so no Financial Facts are extracted for it. Any revenue figure for it must be read from the Sources' text. The answer must say such a figure was read from the Filing text, not from extracted Financial Facts.
```

The rows are the Filings in the Query Scope's time window, or of the Fiscal Periods the question names. A fourth quarter is derived as the 10-K's year less its three 10-Q quarters when the store holds all three (citing those 10-Qs even when they fall before the window), and a year-on-year change is derived when the same period a year earlier is also in the table. A segment series stops at a segment reorganisation, and a note says where the segments changed and which were dropped or added.

System rule 5 changes from "Quote figures exactly as the Sources give them, with their units and periods." to:

```text
5. Take revenue, net income and segment revenue from the Financial Facts table when it has them, cite the row's Source tags, and quote figures exactly with their units and periods. Label a derived figure as derived: a fourth quarter computed from a 10-K less three 10-Qs, a growth rate, or any figure you compute yourself, citing the rows it comes from. When a figure is not in the table and you read it from a Source's text instead, say it was read from the Filing text.
```

The text Sources are unchanged and numbered after the Facts Sources. The `# Sources` block lists only text Sources, since the Facts Sources' figures are in the table. A question naming no metric gets no block, and its prompt is the same as under v3.

**Why.** Figures read from flattened tables are the answers most likely to be wrong (ADR 0001): the model would have to line up columns, scales and periods that vary by Company, across eight or more Filings for a two-year trend. The store has every Tracked Company's revenue and net income to the dollar, so the template hands the model exact rows with their citations and says which figures are computed. The fallback note and the new rule keep the analyst able to tell an extracted figure from one read off the text.

**Scores.** Retrieval on dev, from the retrieval harness: unchanged at hit@10 0.71, recall@10 0.65, MRR 0.59, since text retrieval did not change and the `fts5` Arm ranks text Sources only ([evaluation notes](evaluation.md#after-financial-facts-in-the-answer)). Every dollar figure in the Required Facts of the two dev figure cases with a Tracked Company (Meta's revenue, Tesla's net income) is now a cited row of the table. No Answer Call was made for this change (the run had no provider keys), so there are no generation-harness scores or hand check for v4 yet: the next `make eval-generation` run on dev should score it against [v3's](#v3-coverage-gaps-and-each-companys-coverage), with `trend-meta-revenue-two-years` and `trend-tsla-net-income-three-years` (figures and citations), and `trend-jpm-revenue-snapshot` (saying a figure was read from the Filing text), as the cases to read.

## v5: earlier Source tags named as Filing IDs

**What.** The earlier-conversation block no longer drops an earlier answer's `[Sn]` tags: each run of tags is rewritten as the Filing IDs they cited, in parentheses. An earlier answer that read

```text
Apple outsources manufacturing [S1][S2]. Tesla depends on Elon Musk [S3].
```

now reaches the prompt as

```text
Assistant: Apple outsources manufacturing (AAPL_10-K_2025-09-27; AAPL_10-Q_2025-12-27). Tesla depends on Elon Musk (TSLA_10-K_2025-12-31).
```

The browser sends, with each earlier answer, the Filing ID each of its tags cited (from that answer's `data-sources` part; never the passages), and a tag it can't resolve is still dropped. The block is otherwise as before: the last 10 turns, oldest dropped first until they fit in about 6k tokens, under the heading "Earlier conversation (context only, not evidence)". The system rules are unchanged: rule 2 already limits citations to this turn's tags, and rule 3 says the earlier conversation is not evidence.

Retrieval changes with it, which is where most of the follow-up behaviour lives: a follow-up inherits each part of the Query Scope it does not name from the most recent earlier question that named it, and its topic words when it has none of its own ([ADR 0003](adr/0003-follow-ups-inherit-query-scope-by-rules.md)). So the Sources, Coverage, Financial Facts and Coverage Gaps blocks of a follow-up are now about the Companies the conversation is about.

**Why.** v1 dropped the tags because the browser did not yet send the earlier turns' Sources ([v1's known gaps](#v1-the-tracer-bullet)). With the tags gone the model could not tell which Filing an earlier claim came from, so "How did that change?" lost the period the earlier answer was about. With `[S3]` left in, it would point at whatever this turn's S3 is, a different Filing. A Filing ID says which Company, Form Type and Report Period the earlier claim rested on, in the same words the Coverage block uses, without being citable in this turn.

**Scores.** Retrieval on dev, from the retrieval harness: hit@10 0.71 → 0.88, recall@10 0.65 → 0.82, MRR 0.59 → 0.73; only the five multi-turn cases changed ([evaluation notes](evaluation.md#after-follow-up-inheritance)). Generation on dev (`gpt-6-luna`, `jev-1.13.0`), against v3 (v4 was never scored, so this run also scores the Financial Facts table): Coverage Gaps stated 0.91 → 1.00, Fact Recall 0.55 → 0.50, Faithfulness 0.90 → 0.90, citations valid 0.79 → 0.75, figures exact 0.95 → 0.90, $0.0024 → $0.0024 per answer, 6.6 → 6.1 seconds ([evaluation notes](evaluation.md#after-financial-facts-and-follow-ups-prompt-v5)). The Fact Recall and citation moves are within the run-to-run range; the multi-turn answers no longer have uncited sentences about earlier turns. The Golden Set's scripted histories already cite Filing IDs in this form, so the harness scores of the multi-turn cases measure the inheritance, not the rewriting; the rewriting is checked by tests through the retrieval seam and the API.

## The iteration pass: v6 to v10

With retrieval settled ([ADR 0008](adr/0008-fts5-stays-the-shipped-arm.md)), the template was tuned on the dev split's failures. Each version below is one change to the template, written for named failing cases or a named metric, and scored with `make eval-generation` on the 20 dev cases (`gpt-6-luna`, `jev-1.13.0`, 2026-10-16, the `fts5` Arm). The holdout split was not run.

**Before.** v5's two scored runs from the Arm comparison (the `fts5` run and its control rerun, on the same code and retrieval) are what each version is compared with, so every version is compared with two samples of v5 and the noise between them is visible.

**A new check: the answer's structure.** The harness now checks each answer against assumption 8 in code ([`answer_checks.check_structure`](../backend/src/edgar_eval/answer_checks.py)): it opens with a direct answer of at most three sentences of prose (not a heading, list or table); when its Sources come from two or more Companies, it has a heading per Company or a comparison table; it ends with a Coverage note; and it runs to 300–600 words. An answer with no Sources (a question about a Company missing from the Corpus, or the stale GE Filing) is its Coverage Gaps alone, so only the opening rule applies to it. v5's answers were scored by the same check after the fact: 0.58 and 0.42 of answers followed the structure, mostly failing on length (8 to 11 answers under 300 words).

**How a version is kept.** A version is kept when it fixes the failing cases it was written for and the exact sign test, pairing the dev cases with its predecessor's, puts it behind on none of Fact Recall, Faithfulness, Coverage Gaps or structure. A version that fails either test is discarded, and the next one starts again from the last kept version. On 20 cases the two v5 runs differ by up to 5 cases on one score with nothing changed, so a version is also never kept for an overall score that moved by less than that.

**Where Fact Recall can move.** Of the 44 Required Facts on dev, 14 have evidence quotes that never reach the prompt: the Inflation Reduction Act passages of the five pharmaceutical Companies and Merck's Keytruda forecast (`sector-pharma-regulatory`, `missing-bms-with-merck`), Tesla's 10-K net income narrative, UnitedHealth's date of the Change Healthcare intrusion, and the topic-change follow-up's Sources. No prompt can state them; they are retrieval's to fix. So each version below also reports the share of the 30 reachable facts that its answers state (Jev probability at least 0.5).

| Version | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | reachable facts stated | Faithfulness | $ per answer | latency s | first text s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v5 | 19 | 0.84 | 0.95 | 1.00 | 0.58 | 257 | 0.54 | 18 of 29 | 0.95 | 0.0023 | 5.4 | 1.7 |
| v5 again | 19 | 0.89 | 0.95 | 1.00 | 0.42 | 248 | 0.53 | 18 of 29 | 0.93 | 0.0023 | 5.7 | 2.1 |
| v6 | 20 | 0.85 | 0.95 | 1.00 | 0.55 | 326 | 0.58 | 23 of 30 | 0.94 | 0.0025 | 5.6 | 1.9 |
| **v7** | 19 | 0.89 | 0.95 | 1.00 | **0.84** | 389 | **0.63** | 21 of 29 | 0.95 | 0.0025 | 8.0 | 2.5 |
| **v7 again** | 20 | 0.90 | 0.95 | 1.00 | **0.90** | 404 | **0.65** | 24 of 30 | 0.91 | 0.0026 | 8.9 | 3.0 |
| v8 (discarded) | 20 | 0.90 | 0.95 | 1.00 | 0.80 | 373 | 0.61 | 23 of 30 | 0.93 | 0.0026 | 7.0 | 2.0 |
| v9 (discarded) | 20 | 0.95 | 0.95 | 1.00 | 0.75 | 382 | 0.64 | 24 of 30 | 0.93 | 0.0026 | 9.0 | 3.5 |
| v10 (discarded) | 20 | 0.90 | 0.95 | 1.00 | 0.75 | 408 | 0.69 | 26 of 30 | 0.94 | 0.0026 | 8.7 | 3.1 |

Jev refused to judge `trend-jpm-revenue-snapshot` on the v5 runs and on v7's first (`max_tokens_exceeded`), so those score 19 cases. Each run's answers cost about $0.05 in all, and Jev's judging about $0.02.

### v6: the specifics the Sources state

**What.** Rule 5 gains a sentence, and a rule 8 is added:

```text
5. ... When a Source's text states a change itself ("Revenue increased $36.6 billion or 15%") or what drove it, give that too, in its words and with its tag, rather than computing the change yourself.
8. Be specific. For each point, give the particulars the Sources state: the laws and programs, products, people, places, dates, amounts and percentages they name, in their words. Never reduce them to broad categories ("regulatory risk", "pricing pressure") that would fit any company.
```

**Why.** Fact Recall (0.54 and 0.53 under v5) was the lowest score, and on four cases the missed facts were in the prompt but the answer summarised them away. `risk-aapl-tsla-jpm` (0.43 in both v5 runs) said "global supply-chain dependence" where Apple's 10-K names its outsourcing partners' countries and the tariffs announced from the second quarter of fiscal 2025, and never named Elon Musk or Cybercab. `trend-meta-revenue-two-years` (0.50) gave the table's levels but not the MD&A's "an increase of 22% compared to 2023". `followup-switch-to-msft` (0.33 and 0.67) gave Microsoft's revenue levels but not "Revenue increased $36.6 billion or 15%". `followup-regulatory-exposure` (0.33) said Apple faces "regulation" without the Digital Markets Act's fines. And `trend-tsla-net-income-three-years` failed figure exactness in both runs on a 74.7% decline the model computed itself.

**Scores.** Kept. Reachable facts stated rose from 18 of 29 to 23 of 30: `risk-aapl-tsla-jpm` 0.43 → 0.86, `trend-meta-revenue-two-years` 0.50 → 1.00 and `followup-regulatory-exposure` 0.33 → 0.67, while `followup-switch-to-msft` stated the fiscal 2025 change but lost the quarter's (0.33). Against each v5 run, Fact Recall is 3 cases higher and 1 lower (exact p = 0.625), Faithfulness 4 higher and 4 lower (p = 1.000) and 4 higher and 2 lower (p = 0.688), structure 3 higher and 4 lower (p = 1.000) and 3 higher and 1 lower (p = 0.625), and Coverage Gaps unchanged: behind on nothing, ahead on nothing yet distinguishable. Tesla's computed decline did not go away (the Sources state no change over three years, so the rule does not apply); Meta's answer instead computed a dollar increase, labelled derived as rule 5 asks, which the figure check fails by design. The answers grew from about 250 to 326 words, still with 8 of 20 under 300.

### v7: the PE-analyst structure

**What.** The structure lines at the end of the system message change from

```text
- Open with a direct answer in two or three sentences.
- ...
- End with a short "Coverage" note repeating the Coverage Gaps and saying what else the Sources could not answer.
- Aim for 300 to 600 words.
```

to

```text
- Open with the direct answer: two or three sentences of prose, citing their Sources like any other claim. Put nothing before it: no heading, list or table.
- ...
- Always end with a short "Coverage" note, even when there is no Coverage Gap: repeat the Coverage Gaps (or say there are none) and say what else the Sources could not answer.
- Write 300 to 600 words. When the question is narrow, reach 300 words with the specifics of rule 8 that bear on it (what drove a figure, the segments, periods or plans behind it, the risks the Sources attach to it), never with repetition or general knowledge. When the Sources hold more than 600 words can carry, keep the most material points. Only an answer whose question the Sources cannot answer at all may be shorter.
```

**Why.** The structure check failed 45% of v6's answers. Answers opened with a heading (`missing-wells-fargo-vs-jpm` with "## Comparison", `missing-citigroup` with "## Citigroup" under v6 and v5's rerun), left out the Coverage note when there was no gap (`outlook-meta-capex-2026`, a 38-word answer, in v5 and v6), and ran short: `trend-meta-revenue-two-years`, `trend-tsla-net-income-three-years`, `followup-switch-to-msft` and `outlook-meta-capex-2026` were under 300 words in all three runs. "Aim for" read as a ceiling, not a range. Citation validity also failed on opening summaries with no tag (`sector-pharma-regulatory` in all three runs, `missing-bms-with-merck` in v5, `trend-jpm-revenue-snapshot` in v6), so the opening is told to cite like any other claim.

**Scores.** Kept, and run twice, since it is the final version. Structure followed rose to 0.84 and 0.90. Paired with each v5 run, structure is 7 cases higher and 2 lower (p = 0.180) and 9 higher and 1 lower (p = 0.021) for the first run, 7 and 1 (p = 0.070) and 9 and 0 (p = 0.004) for the second: distinguishably better against one v5 run, and in the same direction against the other. No answer opens with a heading or leaves out its Coverage note, and no opening summary of cited points is left without a tag. Every short figure answer now gives the MD&A's stated changes and drivers (Meta's advertising impressions and price per ad, Microsoft's segment growth), and Fact Recall is 0.63 and 0.65 (4 to 5 cases higher and 1 to 2 lower against v5, p = 0.219 to 0.453). Faithfulness is 0.95 and 0.91, within the v5 runs' own range (3 to 6 cases higher and 5 to 8 lower, p = 0.227 to 1.000). The cost: answers are about 400 words and 800 output tokens against v5's 250 and 490, so an answer takes 8 to 9 seconds to finish rather than 5.5 (first text after 2.5 to 3 seconds, as it streams) and costs $0.0025 rather than $0.0023. The remaining structure failures are length: the five-Company `sector-pharma-regulatory` (702 and 632 words) and `risk-aapl-tsla-jpm` (652) run over, and `followup-topic-change-export-controls`, whose Sources are the wrong Company's (ADR 0003's known weakness), runs under.

### v8: a word budget for comparisons (discarded)

**What.** The length line of v7 became: "Write 300 to 600 words in all, the Coverage note included. ... When the Sources hold more than 600 words can carry, as they do when several Companies are compared, give each Company only its two or three most material points, keep each table cell to one or two sentences, and stop at 600 words. ..."

**Why.** v7's over-length answers, `risk-aapl-tsla-jpm` (652 words) and `sector-pharma-regulatory` (702 and 632), all compare three or more Companies.

**Scores.** Discarded: `sector-pharma-regulatory` came in at 567 words, but `risk-aapl-tsla-jpm` grew to 753, and `outlook-meta-capex-2026` (55 words) and `followup-switch-to-msft` (265) fell back under 300. Structure followed 0.80 against v7's 0.84 and 0.90.

### v9: no closing summary (discarded)

**What.** On top of v8, after the per-Company line: "Add no closing summary or "Comparison" section that restates them: the direct answer is the summary."

**Why.** v8's 753-word `risk-aapl-tsla-jpm` answer ends with a "Comparison" section that restates its opening, about 70 words of repetition.

**Scores.** Discarded: `risk-aapl-tsla-jpm` (775 words) and `sector-pharma-regulatory` (779) both ran over, and `sector-aerospace-government` opened with five sentences. Structure followed 0.75. The model does not count words: across v7 to v9 the same comparison questions land anywhere from about 570 to 780 words whatever the length line says, so the over-length cases are left as they are.

### v10: no tags on statements of absence (discarded)

**What.** On top of v7, a line after the opening rule: "Give a Coverage Gap, or anything else the Sources do not contain, no tag: no Source says it, so a tag would cite a Source for a claim it does not make."

**Why.** In v7's second run, Faithfulness fell to 0.50 on `missing-bms-with-merck` and 0.62 on `followup-topic-change-export-controls`, because the answers tagged sentences such as "Bristol Myers Squibb's regulatory risks cannot be assessed from the provided filings [S1]" with a Merck or Apple Source, and Jev rightly judged the Source not to say so. v7's "citing their Sources like any other claim" may have encouraged it.

**Scores.** Discarded. `missing-bms-with-merck` returned to 1.00, but it scored 1.00 in v5, v6 and v7's first run too, so its miss was noise; `followup-topic-change-export-controls` still had three unsupported claims (0.70), and `stale-gecc-eni-2014` two. Structure followed 0.75 (0 cases higher and 3 lower than v7's second run, p = 0.250). Its Fact Recall (0.69, 26 of 30 reachable facts) is the highest of the pass, but 3 cases higher and 0 to 1 lower than v7 (p = 0.250 and 0.625) is not distinguishable, and it was not the change's purpose.

### The final template (v7)

`PROMPT_VERSION = "v7"`. The user message is as described under v1 to v5: Coverage Gaps, Companies in scope (when the question uses a Sector phrase), Coverage, Financial Facts (when the question names a metric), Sources grouped by Company, the earlier conversation (the last 10 turns, about 6k tokens at most, with earlier Source tags named as Filing IDs), and the question. The system message:

```text
You are a research assistant for private equity analysts. You answer business questions about public companies using only the excerpts from their SEC 10-K and 10-Q filings given to you as numbered Sources.

Rules:
1. Use only the Sources. Never use general knowledge, memory or any outside data, even for well-known facts. If the Sources do not answer part of the question, say so plainly.
2. Cite every claim with the tag of the Source it comes from, e.g. [S3], placed right after the claim. Use several tags when a claim rests on several Sources. Cite only tags listed in this turn's Sources.
3. The earlier conversation is there to help you understand the question. It is not evidence: never repeat a claim from an earlier answer unless a Source in this turn supports it, and then cite that Source.
4. When you use a Company's filings, give the filing's form type, fiscal period and report period, as listed under "Coverage", and say so when the Companies you compare report for different periods.
5. Take revenue, net income and segment revenue from the Financial Facts table when it has them, cite the row's Source tags, and quote figures exactly with their units and periods. Label a derived figure as derived: a fourth quarter computed from a 10-K less three 10-Qs, a growth rate, or any figure you compute yourself, citing the rows it comes from. When a figure is not in the table and you read it from a Source's text instead, say it was read from the Filing text. When a Source's text states a change itself ("Revenue increased $36.6 billion or 15%") or what drove it, give that too, in its words and with its tag, rather than computing the change yourself.
6. When the question names a group of companies ("the major banks"), it was resolved through a curated Sector table to the Companies listed under "Companies in scope". Name those Companies near the start of the answer, say they come from the Sector table, and cover no other company for that group.
7. "Coverage Gaps" lists what the filings cannot answer: a trend asked of a company with only a snapshot of filings, a company not in the filings, a stale filing, guidance the filings do not contain, or periods that differ. State every gap listed there, in the words given, near the start of the answer. Never fill a gap from general knowledge: say nothing about a company the filings do not include, never use a filing listed as left out, and never present MD&A commentary as the company's guidance.
8. Be specific. For each point, give the particulars the Sources state: the laws and programs, products, people, places, dates, amounts and percentages they name, in their words. Never reduce them to broad categories ("regulatory risk", "pricing pressure") that would fit any company.

Structure the answer for a PE analyst, in Markdown:
- Open with the direct answer: two or three sentences of prose, citing their Sources like any other claim. Put nothing before it: no heading, list or table.
- Then give the points for each Company under its own heading, or a comparison table when several Companies are compared on the same dimensions.
- Always end with a short "Coverage" note, even when there is no Coverage Gap: repeat the Coverage Gaps (or say there are none) and say what else the Sources could not answer.
- Write 300 to 600 words. When the question is narrow, reach 300 words with the specifics of rule 8 that bear on it (what drove a figure, the segments, periods or plans behind it, the risks the Sources attach to it), never with repetition or general knowledge. When the Sources hold more than 600 words can carry, keep the most material points. Only an answer whose question the Sources cannot answer at all may be shorter.
```

**After the template.** The [generator comparison](evaluation.md#generator-comparison) scored this template with all four models and kept `gpt-6-luna` ([ADR 0009](adr/0009-gpt-6-luna-stays-the-generator.md)); the Claude models' answers break its structure and citation rules more often, so a switch to Claude would need its own pass. The final configuration was then [run once on the holdout split](evaluation.md#the-holdout-run): Fact Recall 0.67, Faithfulness 0.95, structure followed by 0.80 of answers. Three things for later work: the 14 unreachable Required Facts are retrieval's (the per-Company budget leaves out the pharmaceutical Companies' Inflation Reduction Act passages; [ADR 0010](adr/0010-chunk-size-and-context-budget.md) later found that a 48k budget reaches only two of them and states no more facts); the longer answers make more claims for Jev to judge, so Faithfulness is worth watching across generators; and the citation check still fails statements of absence it does not recognise ("The stated Coverage Gap applies: ...", "[Coverage Gaps]" written as a tag), which are wording rules for the check, not faults of the answers.

## Answer length: v11 to v14 (discarded)

The code review of the spec (2026-10-16) found the structure criterion only partly met: v7's answers follow the structure in 0.79 to 0.90 of dev answers and 0.80 of holdout answers, and most misses are length. This pass tried to keep the long answers within 600 words. v8 to v10 already name discarded versions above, so its versions are numbered from v11.

**The rule, from the ticket, before any run.** A version ships only if the share of answers following the structure rises on dev and the exact sign test, pairing the dev cases, puts it behind v7 on none of Fact Recall, Faithfulness and Coverage Gaps; otherwise v7 stays. The holdout split was not scored. Every run is `gpt-6-luna`, `jev-1.13.0`, the `fts5` Arm with 600-token chunks and the 32k budget that [ADR 0010](adr/0010-chunk-size-and-context-budget.md) kept, on the 20 dev cases, 2026-10-16.

**Before.** v7 has five dev runs on that retrieval: the two of the iteration pass, the generator comparison's `gpt-6-luna` run, and the shipped setting and its control in the [chunk size and context budget sweep](evaluation.md#chunk-size-and-context-budget). Together 77 of 96 answers follow the structure (0.80). Two cases run over 600 words in nearly every run, and both compare three or more Companies: `sector-pharma-regulatory` (five Companies: 702, 632, 627, 785 and 640 words) and `risk-aapl-tsla-jpm` (three: 652, 597, 652, 708 and 746). Every other structure miss in those runs is an answer under 300 words (`outlook-meta-capex-2026`, and `followup-topic-change-export-controls`, whose Sources are the wrong Company's) or an opening of four sentences.

**What.** v8 and v9 showed the model does not keep to a word count for a whole answer. So each version adds a length plan that code computes from the Sources: when they cover three or more Companies, the user message gets a "# Length" block just before the question, with a budget per Company, and the length line of the system rules ends "... keep the most material points, and follow the "Length" plan when the message gives one." The block also says "Add no closing summary or comparison section after them: the direct answer is the comparison. In the Coverage note, name each Coverage Gap in a few words instead of repeating its full wording." The budget per Company is all that differs between versions:

- **v11**: "give each Company at most 4 sentences of points in all, under its heading or in its table row" (14 sentences shared among the Companies, at least 2 each: 4 for three Companies, 2 for five).
- **v12**: "give each Company one paragraph of at most 4 sentences under its heading, or one table row of at most 4 sentences in all".
- **v13**: "give each Company at most 3 bullet points under its heading, each a single sentence, or one table row with a single sentence per cell" (10 bullet points shared, at least 2 each).
- **v14**: v12's paragraph "of at most 4 sentences and about 120 words" (360 words shared).

Within the dev split, the plan reaches `risk-aapl-tsla-jpm`, `sector-pharma-regulatory`, `sector-aerospace-government` and `followup-regulatory-exposure`.

**Scores.**

| Version | cases | citations valid | figures exact | gaps stated | structure followed | words | Fact Recall | Faithfulness | $ per answer | latency s | over 600 words |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **v7** (five runs) | 19-20 | 0.89-0.95 | 0.95-1.00 | 1.00 | **0.74-0.90** (0.80 pooled) | 382-404 | **0.62-0.68** | **0.90-0.97** | 0.0025-0.0026 | 6.8-8.9 | 1 or 2 |
| v11 | 19 | 0.89 | 0.89 | 1.00 | 0.84 | 386 | 0.68 | 0.94 | 0.0025 | 6.1 | `risk-aapl-tsla-jpm` 681 |
| v12 | 19 | 1.00 | 1.00 | 1.00 | 0.84 | 383 | 0.73 | 0.96 | 0.0025 | 5.8 | `risk-aapl-tsla-jpm` 690 |
| v12 again | 19 | 0.95 | 0.95 | 1.00 | 0.74 | 390 | 0.66 | 0.92 | 0.0025 | 6.2 | `risk-aapl-tsla-jpm` 718, `missing-wells-fargo-vs-jpm` 629, `followup-tsla-risk-change` 618 |
| v13 | 20 | 0.95 | 1.00 | 1.00 | 0.80 | 409 | 0.63 | 0.93 | 0.0026 | 6.5 | `risk-aapl-tsla-jpm` 722, `sector-pharma-regulatory` 682, `missing-wells-fargo-vs-jpm` 605 |
| v14 | 19 | 0.89 | 1.00 | 1.00 | 0.79 | 369 | 0.66 | 0.93 | 0.0025 | 6.1 | `risk-aapl-tsla-jpm` 601, `sector-pharma-regulatory` 674 |

Jev refused to judge `trend-jpm-revenue-snapshot` (`max_tokens_exceeded`) on every run but v13's, as on four of v7's five, so most runs score 19 cases.

**Discarded: v7 stays.**

- **The five-Company answer shortened; the three-Company one did not.** Under a sentence budget (v11 and both v12 runs), `sector-pharma-regulatory` came in at 532, 492 and 556 words, against 627 to 785 in all five v7 runs. `risk-aapl-tsla-jpm` ran over in every run of every version (601 to 722 words): whatever the plan asked for, the model gave each of the three Companies three paragraphs or bullets of two or three sentences each. Under v13 it kept to three bullets per Company but not to one sentence per bullet.
- **The share following the structure did not rise.** v12, the best first run, was run again because it would have shipped: 0.84 and 0.74, or 30 of 38 answers (0.79) against v7's 77 of 96 (0.80). Answers the plan never reaches ran over in the rerun (`missing-wells-fargo-vs-jpm` 629, `followup-tsla-risk-change` 618), as they had not in any v7 run, which is the run-to-run noise the iteration pass found. Paired with each v7 run, structure is 0 to 3 cases higher and 0 to 4 lower for every version (p = 0.375 to 1.000).
- **And v12's rerun fell behind on Faithfulness.** Against v7's control run from the sweep it is 1 case higher and 9 lower (p = 0.021), and 2 higher and 9 lower against the shipped run (p = 0.065). Its first run was behind on nothing (Fact Recall 2 to 5 cases higher and 0 to 1 lower, p = 0.219 to 0.500; Faithfulness 3 to 8 higher and 2 to 4 lower, p = 0.109 to 1.000), nor were v11, v13 and v14. No version was ahead on anything.

The over-length answers are left as they are, as after v9. A five-Company comparison is the one case the plan fixed every time; a plan for four or more Companies only would reach that case alone, one answer in 20, which this rule cannot tell from noise. The five runs cost $0.238 in Answer Calls and $0.105 in Jev judging, **about $0.34 in all**.

## v15: Coverage Gaps shown by the product, comparison tables (ADR 0016) and calendar months

Spec #136, issue #139, 2026-10-20. v8 to v14 already name discarded versions above, so this one is v15. It is the first change of the spec's prompt, and the spec's calendar months for fiscal periods join it. Its dev scores are taken once #136's answer-path changes are all in, with `gpt-6-luna`, before the freeze and the final round.

**Corrected (#157, 2026-10-21).** This entry first said #132's prompt decisions would join v15 rather than make a v16. They don't: spec #132's candidates are each built on v15 alone and numbered v16 onwards (v16 state each point in full, v17 length scaled to Companies, v18 quote figures), with a confirmed combination taking the next number, and each is decided against v15 by [ADR 0017](adr/0017-prompt-changes-decided-by-two-rules.md)'s rules. The version that freezes may so be v15 or a later one.

**What.** Four changes to the system rules; the user message is unchanged (it still lists the Coverage Gaps, or "None.", so the answer knows what it cannot cover).

- Rule 4 drops "and say so when the Companies you compare report for different periods".
- Rule 7 drops "State every gap listed there, in the words given, near the start of the answer". Every gap is now shown below the answer, so the list is not repeated; where a gap leaves part of the question unanswered (a company not in the filings, a trend asked of a snapshot company, a stale filing left out, guidance the filings do not contain), the answer says so briefly, in its own words, where that part of the answer would be, naming the company and what the filings cannot answer about it. It never mentions that the companies' periods differ for its own sake. "Never fill a gap from general knowledge" stays.
- The opening rule adds that nothing goes before the direct answer, "no heading, list, table or note on what the filings lack", and that it answers the question from the Sources.
- "Then give the points for each Company under its own heading, or a comparison table ..." becomes: when the question compares two or more Companies on the same dimensions, a comparison table first, one row per Company, then each Company's detail under its own heading. The closing "Coverage" note is gone: "End with the last point. Add no closing "Coverage" or "Limitations" section: the Coverage Gaps are shown below your answer."

**Why.** [ADR 0016](adr/0016-coverage-gaps-shown-by-the-product.md): the reader saw each gap two or three times (the workspace's callout above the answer, the answer's opening and its closing Coverage note), and the opening, the part shown before "Show full analysis", spent itself on gap wordings: on the brief's first question, half the direct answer repeated the "periods differ" callout word for word. The workspace now shows every gap below the complete answer as Coverage notes, in their fixed wordings, `make ask` still prints them and the chat API still streams them. Comparisons got headings rather than a table as often as not, so the table is now asked for whenever Companies are compared.

**The harness follows.** The Coverage Gap check scores only the gaps that leave part of the question unanswered (`checked_gaps`), acknowledged in any wording anywhere in the answer; "periods differ" is not checked, and a case expecting only that gap has no Coverage Gap score. Its missing-Company markers also recognise "isn't in the filings", "absent from" and "outside the filings". The structure check no longer asks for a closing Coverage note. The Faithfulness exemption for sentences that say what the Filings lack is unchanged. "Coverage Gaps stated" before and after v15 measure different things and are not compared; reports scored before stand as recorded.

**Hand check** (`make ask`, `gpt-6-luna`, on the final wording):

- The brief's three questions open with the direct answer: Apple's, Tesla's and JPMorgan's exposures; NVIDIA's revenue from FY2024 to Q3 FY2026 with its outlook commentary, saying in its second sentence that the filings give no revenue guidance; and the five pharmaceutical Companies named from the Sector table with their shared exposure to the Inflation Reduction Act and 340B. None mentions that the periods differ, and none ends with a Coverage note. Each comparison has a comparison table before the per-Company headings. NVIDIA's one-Company answer puts its revenue and outlook in a one-row table too, before and after the rule was limited to "two or more Companies"; it does no harm, and is left as it is.
- "Compare the risk factors of JPMorgan and Wells Fargo." opens with JPMorgan's FY2025 10-K risk factors and says "The supplied corpus contains no Wells Fargo filing, so a filing-based comparison of Wells Fargo's risk factors is not possible", and its table gives Wells Fargo a row reading "Not covered".
- "Compare JPMorgan and Wells Fargo" has no topic word, so retrieval finds no Sources (the spec's Overview route is for that). The answer is a refusal that says Wells Fargo is not included.
- A first draft of the rules, without the "periods differ" sentence, still ended the brief's first and third openings with "the periods are not aligned" or "filings covering different fiscal periods", and its Wells Fargo answer said only "the other requested company". So rule 7 now says to name the company and not to mention periods differing for its own sake. The answers ran 450 to 600 words, apart from the five-Company pharmaceutical answer (603) and the refusal. The three rounds of hand checks cost about 4 cents.

### Calendar months (#147)

Issue #147, 2026-10-20, joins v15 as the spec planned.

**What.** Rule 4 gains a sentence: the first time the answer names a fiscal period of a Company whose fiscal year does not end in December, it gives the period's calendar months after it, copied from "Coverage", as in "Q2 FY2026 (May–Jul 2025)". The user message now supplies them:

- each Company's line under "Coverage" names the month its fiscal year ends in, from its latest 10-K ("NVIDIA Corporation (NVDA): Tracked Company; fiscal year ends in January; ...");
- each Filing in scope gives its calendar months between its fiscal period and its Report Period ("NVDA_10-Q_2025-07-27 (10-Q Q2 FY2026, May–Jul 2025, Report Period 2025-07-27)");
- each Source label gives them beside the fiscal period ("NVDA 10-Q Q2 FY2026 (May–Jul 2025), Management's Discussion and Analysis (Item 2). Filing ID ..."), and so does each Financial Facts row ("Q4 FY2025 (Nov 2024–Jan 2025)").

The months are worked out in code (`edgar_rag.corpus.calendar_months`), never by the model: a quarter or year ends in the month its Report Period stands for, a 52/53-week period ending in a month's first days standing for the month before, as the Fiscal Period does. The evaluation export's Company Calendar formats its months with the same helper.

**Why.** "Q3 FY2026" means August to October 2025 for NVIDIA and nothing a reader can place without looking it up; Apple's Q1 is October to December, Microsoft's July to September. A December year needs no months, since its fiscal periods are the calendar's, so the rule leaves them out of the answer there, while the Coverage block and the labels still give them.

**Hand check** (`make ask "How has NVIDIA's revenue and growth outlook changed over the last two years?"`, `gpt-6-luna`, 2026-10-20). The answer gives the months the first time it names each of NVIDIA's Filing periods: "FY2024 (Feb 2023–Jan 2024)", "FY2025 (Feb 2024–Jan 2025)", "Q1 FY2026 (Feb–Apr 2025)", "Q2 FY2026 (May–Jul 2025)", "Q3 FY2026 (Aug–Oct 2025)", "Q2 FY2025 (May–Jul 2024)" and "Q3 FY2025 (Aug–Oct 2024)", and leaves them out when it names a period again. Two mentions have none: "Q4 FY2025", in management's expectation of Blackwell revenue, and "FY2026" as a whole year still under way; neither is a Filing in the Coverage block. Every Source label gives the months too ("NVDA 10-Q Q2 FY2026 (May–Jul 2025), MD&A (Part I, Item 2)"). About 32k input and 1,750 output tokens, 17 seconds, under half a cent.

### Company Groups (#146)

Issue #146, 2026-10-20, joins v15 like #147, since v15 is the spec's prompt and is scored once all of the spec's answer-path changes are in.

**What.** The system rules are unchanged. The user message's "Companies in scope" now names a curated Company Group as one: "big tech companies" resolves through the Sector table's `group` column, and its line reads `"big tech companies" was resolved through the curated Company Group "Big Tech" in the Sector table to: Apple Inc (AAPL), Amazon.com Inc (AMZN), ...`, where a Sector phrase's still reads `... was resolved through the Sector table (industry: Banks) to: ...`. Rule 6 already asks the answer to name the Companies near the start and say they come from the Sector table.

**Why.** "Big tech" means Apple, Microsoft, Alphabet, Amazon, Meta, NVIDIA and Tesla, which no Sector captures; read as the Information Technology Sector it dropped three of them and added Adobe, Cisco and IBM ([assumption 5](assumptions.md#5-a-curated-sector-table-is-acceptable)). The answer should say the group is a curated one, as it says a Sector phrase's Companies come from the table.

**Hand check** (`make ask "What are the main AI risks for big tech companies?"`, `gpt-6-luna`, 2026-10-20). The answer opens "The curated Sector table defines "Big Tech" here as Apple, Amazon.com, Alphabet, Meta Platforms, Microsoft, NVIDIA and Tesla", then gives a comparison table of the seven and a section for each, citing each one's latest Risk Factors (Microsoft's and NVIDIA's latest 10-Qs). It does not mention the periods differing. About 23k input and 1,900 output tokens, 23.5 seconds, under a cent.

### The v15 system rules

```text
You are a research assistant for private equity analysts. You answer business questions about public companies using only the excerpts from their SEC 10-K and 10-Q filings given to you as numbered Sources.

Rules:
1. Use only the Sources. Never use general knowledge, memory or any outside data, even for well-known facts. If the Sources do not answer part of the question, say so plainly.
2. Cite every claim with the tag of the Source it comes from, e.g. [S3], placed right after the claim. Use several tags when a claim rests on several Sources. Cite only tags listed in this turn's Sources.
3. The earlier conversation is there to help you understand the question. It is not evidence: never repeat a claim from an earlier answer unless a Source in this turn supports it, and then cite that Source.
4. When you use a Company's filings, give the filing's form type, fiscal period and report period, as listed under "Coverage". The first time the answer names a fiscal period of a Company whose fiscal year does not end in December, give its calendar months after it, copied from "Coverage": "Q2 FY2026 (May–Jul 2025)".
5. Take revenue, net income and segment revenue from the Financial Facts table when it has them, cite the row's Source tags, and quote figures exactly with their units and periods. Label a derived figure as derived: a fourth quarter computed from a 10-K less three 10-Qs, a growth rate, or any figure you compute yourself, citing the rows it comes from. When a figure is not in the table and you read it from a Source's text instead, say it was read from the Filing text. When a Source's text states a change itself ("Revenue increased $36.6 billion or 15%") or what drove it, give that too, in its words and with its tag, rather than computing the change yourself.
6. When the question names a group of companies ("the major banks"), it was resolved through a curated Sector table to the Companies listed under "Companies in scope". Name those Companies near the start of the answer, say they come from the Sector table, and cover no other company for that group.
7. "Coverage Gaps" lists what the filings cannot answer: a trend asked of a company with only a snapshot of filings, a company not in the filings, a stale filing, guidance the filings do not contain, or periods that differ. Every gap listed there is shown below your answer, in its own wording, so do not repeat the list. Where a gap leaves part of the question unanswered (a company not in the filings, a trend asked of a snapshot company, a stale filing left out, guidance the filings do not contain), say so briefly, in your own words, where that part of the answer would be: name the company and what the filings cannot answer about it, without citing the "Coverage Gaps" list. Never mention that the companies' periods differ for its own sake: rule 4 gives each filing's period, and the difference is shown below your answer. Never fill a gap from general knowledge: say nothing more about a company the filings do not include, never use a filing listed as left out, and never present MD&A commentary as the company's guidance.
8. Be specific. For each point, give the particulars the Sources state: the laws and programs, products, people, places, dates, amounts and percentages they name, in their words. Never reduce them to broad categories ("regulatory risk", "pricing pressure") that would fit any company.

Structure the answer for a PE analyst, in Markdown:
- Open with the direct answer: two or three sentences of prose that answer the question from the Sources, citing them like any other claim. Put nothing before it: no heading, list, table or note on what the filings lack.
- When the question compares two or more Companies on the same dimensions, give a comparison table first, one row per Company, then each Company's detail under its own heading. Otherwise give the points for each Company under its own heading.
- End with the last point. Add no closing "Coverage" or "Limitations" section: the Coverage Gaps are shown below your answer.
- Write 300 to 600 words. When the question is narrow, reach 300 words with the specifics of rule 8 that bear on it (what drove a figure, the segments, periods or plans behind it, the risks the Sources attach to it), never with repetition or general knowledge. When the Sources hold more than 600 words can carry, keep the most material points. Only an answer whose question the Sources cannot answer at all may be shorter.
```

## v16: each point stated in full (candidate, #161)

Spec #132's first candidate, issue #161, 2026-10-21. Built on v15 alone: only rule 8 changes, and the user message is v15's. Decided by [ADR 0017](adr/0017-prompt-changes-decided-by-two-rules.md)'s `prompts` rule, two runs a side (its note of 2026-10-21), with every side's structure read under v17's word range (below). Its code is on the branch `candidate/v16` (`8d176df`) and is not merged; the combination ticket (#165) merges the winners' code, so the shipped prompt stayed v15 until v19 merged it (#165).

**What.** Rule 8 was:

> 8. Be specific. For each point, give the particulars the Sources state: the laws and programs, products, people, places, dates, amounts and percentages they name, in their words. Never reduce them to broad categories ("regulatory risk", "pricing pressure") that would fit any company.

and becomes:

> 8. State each point in full. For each point, give first the Company's own claim as its Source states it, including its own assessment of how material the matter is, or of its outlook; then the particulars the Source names: the laws and programs, products, people, places, courts, counts, dates, amounts and percentages, and its words of scale ("a substantial number", "large numbers", "very few"), in its words. When a Source says something has happened, is happening, or has happened in the past and may again, say that it has; never reduce it to "could" or "may". Attribute each claim to the one Company whose Source states it, and never pool Companies in one claim. Give each text Source at least one cited point. Never replace the particulars with a category that would fit any company ("regulatory risk", "pricing pressure").

The clauses on the Company's own assessment, the tense and the words of scale come from #160's diagnosis, posted on #161 before the run.

**Why.** Most of the v15 round's Generation Misses are generalised (32 and 28 a run) or headline dropped (22 and 12). The commonest generalisation is a past event softened to a possible one, and v15's ban on "broad categories" reads as a ban on the Company's own summary sentence, which is often the fact ([evaluation notes](evaluation.md#the-v15-base-round-and-its-generation-misses-160-2026-10-21)).

**Scores** (dev, 63 cases, `gpt-6-luna` at low, `fts5`, 600-token chunks, the 32k budget, `jev-1.13.0` at 0.6, code version `5d1feeffb3cb466d`; structure followed under v15's check, then v17's):

| Side (2 runs each) | must-state facts stated, of 334 (runs) | Fact Recall | Faithfulness | structure followed, v15's check | v17's check | words | answers with a Contradicted Claim | cases failing the figure check |
|---|---|---|---|---|---|---|---|---|
| **v15**, shipped pair | 232 (229, 235) | 0.69, 0.70 | 0.95, 0.96 | 0.81, 0.76 | 0.92, 0.86 | 436, 444 | 2, 4 | 3, 2 |
| v15, Control pair | 235 (241, 229) | 0.72, 0.70 | 0.95, 0.94 | 0.68, 0.71 | 0.81, 0.83 | 444, 438 | 4, 4 | 4, 5 |
| **v16** | **244** (244, 244) | 0.74, 0.74 | 0.95, 0.95 | 0.67, 0.76 | 0.83, 0.89 | 475, 469 | 4, 5 | 4, 1 |

**Read on v15's structure check, it was not decided.** v16 was ahead on facts stated and behind on structure followed alone (p behind = 0.132). That margin is inside the Control pair's (p behind = 0.011), so the developer decided. v16's misses were nearly all answers over 600 words, most of them sector questions, which is the length #162's v17 range allows.

**The developer's choice: read the structure under v17's range.** v16's two reports were re-scored on copies with v17's structure check, as #162 had re-scored the four v15 reports. Only the structure scores moved.

**The verdict under `prompts`, structure under v17's range: v16 qualifies** (`prompt-choice-dev-v16-v17range.json`).

- **Facts stated:** 244 must-state facts a run against v15's 232, +12, p ahead = 0.043.
- **Behind on no guardrail:**
  - Fact Recall case by case: 28 cases higher and 13 lower (p ahead = 0.014);
  - Faithfulness: p behind = 0.678;
  - Coverage Gaps: p behind = 0.812;
  - Contradicted Claims: p behind = 0.387;
  - structure followed: 8 cases higher and 9 lower, p behind = 0.500.
- **The Control pair is not ahead** (+3, p ahead = 0.334), so the comparison is conclusive.

It goes to the combination (#165) with v17's range, which its qualification rests on. At two Companies, where that range stays at 600 words, its answers still run over 600 more often than v15's; the [evaluation notes](evaluation.md#v16-each-point-stated-in-full-161-2026-10-21) have the reading by number of Companies.

The two runs cost $0.59 ($0.37 in answers, $0.21 in Jev judging).

### The v16 system rules

```text
You are a research assistant for private equity analysts. You answer business questions about public companies using only the excerpts from their SEC 10-K and 10-Q filings given to you as numbered Sources.

Rules:
1. Use only the Sources. Never use general knowledge, memory or any outside data, even for well-known facts. If the Sources do not answer part of the question, say so plainly.
2. Cite every claim with the tag of the Source it comes from, e.g. [S3], placed right after the claim. Use several tags when a claim rests on several Sources. Cite only tags listed in this turn's Sources.
3. The earlier conversation is there to help you understand the question. It is not evidence: never repeat a claim from an earlier answer unless a Source in this turn supports it, and then cite that Source.
4. When you use a Company's filings, give the filing's form type, fiscal period and report period, as listed under "Coverage". The first time the answer names a fiscal period of a Company whose fiscal year does not end in December, give its calendar months after it, copied from "Coverage": "Q2 FY2026 (May–Jul 2025)".
5. Take revenue, net income and segment revenue from the Financial Facts table when it has them, cite the row's Source tags, and quote figures exactly with their units and periods. Label a derived figure as derived: a fourth quarter computed from a 10-K less three 10-Qs, a growth rate, or any figure you compute yourself, citing the rows it comes from. When a figure is not in the table and you read it from a Source's text instead, say it was read from the Filing text. When a Source's text states a change itself ("Revenue increased $36.6 billion or 15%") or what drove it, give that too, in its words and with its tag, rather than computing the change yourself.
6. When the question names a group of companies ("the major banks"), it was resolved through a curated Sector table to the Companies listed under "Companies in scope". Name those Companies near the start of the answer, say they come from the Sector table, and cover no other company for that group.
7. "Coverage Gaps" lists what the filings cannot answer: a trend asked of a company with only a snapshot of filings, a company not in the filings, a stale filing, guidance the filings do not contain, or periods that differ. Every gap listed there is shown below your answer, in its own wording, so do not repeat the list. Where a gap leaves part of the question unanswered (a company not in the filings, a trend asked of a snapshot company, a stale filing left out, guidance the filings do not contain), say so briefly, in your own words, where that part of the answer would be: name the company and what the filings cannot answer about it, without citing the "Coverage Gaps" list. Never mention that the companies' periods differ for its own sake: rule 4 gives each filing's period, and the difference is shown below your answer. Never fill a gap from general knowledge: say nothing more about a company the filings do not include, never use a filing listed as left out, and never present MD&A commentary as the company's guidance.
8. State each point in full. For each point, give first the Company's own claim as its Source states it, including its own assessment of how material the matter is, or of its outlook; then the particulars the Source names: the laws and programs, products, people, places, courts, counts, dates, amounts and percentages, and its words of scale ("a substantial number", "large numbers", "very few"), in its words. When a Source says something has happened, is happening, or has happened in the past and may again, say that it has; never reduce it to "could" or "may". Attribute each claim to the one Company whose Source states it, and never pool Companies in one claim. Give each text Source at least one cited point. Never replace the particulars with a category that would fit any company ("regulatory risk", "pricing pressure").

Structure the answer for a PE analyst, in Markdown:
- Open with the direct answer: two or three sentences of prose that answer the question from the Sources, citing them like any other claim. Put nothing before it: no heading, list, table or note on what the filings lack.
- When the question compares two or more Companies on the same dimensions, give a comparison table first, one row per Company, then each Company's detail under its own heading. Otherwise give the points for each Company under its own heading.
- End with the last point. Add no closing "Coverage" or "Limitations" section: the Coverage Gaps are shown below your answer.
- Write 300 to 600 words. When the question is narrow, reach 300 words with the specifics of rule 8 that bear on it (what drove a figure, the segments, periods or plans behind it, the risks the Sources attach to it), never with repetition or general knowledge. When the Sources hold more than 600 words can carry, keep the most material points. Only an answer whose question the Sources cannot answer at all may be shorter.
```

## v17: answers get more room for more Companies (candidate)

Spec #132, issue #162, 2026-10-21. A candidate built on v15 alone, decided against v15 by [ADR 0017](adr/0017-prompt-changes-decided-by-two-rules.md)'s `prompts` rule, two runs a side (ADR 0017's note of 2026-10-21). Its code is on the branch `candidate/v17` and is not merged: the combination ticket (#165) merges the winners' code, which v19 did.

**What.** The answer's word range scales to the number of Companies with text Sources, from one function in the core package, `edgar_rag.retrieval.answer_words`:

- **The range:** 300 to 600 words for one or two Companies; the ceiling rises 150 for each further Company, to at most 1,000 (750 for three, 900 for four, 1,000 for five or more).
- **In the prompt:** the user message carries a one-line "# Length" block, just before the question, with the range for the Companies the text Sources come from, and none when there are no text Sources:

  ```text
  # Length

  Write 300 to 750 words: the Sources cover 3 Companies.
  ```

- **The system rules' length line** refers to it and keeps "keep the most material points". Nothing else changes. It was:

  > Write 300 to 600 words. When the question is narrow, reach 300 words with the specifics of rule 8 ... When the Sources hold more than 600 words can carry, keep the most material points. ...

  and becomes:

  > Write the number of words given under "Length", which allows more words when the Sources cover more Companies. When the question is narrow, reach its lower end with the specifics of rule 8 ... When the Sources hold more than its upper end can carry, keep the most material points. ...

- **The structure check** takes its word range from the same function, applied to the answer's Source Companies, so the prompt and its check can't drift. The offline re-score redoes the structure check too, and the round's four v15 reports were re-scored that way, on copies, before the comparison ([the evaluation notes](evaluation.md#v17-answers-get-more-room-for-more-companies-162-2026-10-21)).

**Why.** v7's Generation Misses rose with the number of Companies (0.15 with one, 0.35 with three) under a 600-word ceiling that held answers to about 490 words, and the second must-state fact per Company was usually the one dropped. Unlike v11 to v14, v17 lengthens many-Company answers rather than shortening them. On v15 the miss rate jumps at two Companies, which v17's range leaves at 600 words (noted on #162 before the run); the range was left as the spec set it.

**Scores** (dev, 63 cases, `gpt-6-luna` at reasoning effort low, `fts5`, 600-token chunks, the 32k budget, `jev-1.13.0` at 0.6, code version `bdbf8d350beaa248`; v15's structure re-scored with v17's range):

| Side (2 runs each) | must-state facts stated, of 334 (runs) | Fact Recall | Faithfulness | structure followed | words | answers with a Contradicted Claim | cases failing the figure check |
|---|---|---|---|---|---|---|---|
| **v15**, shipped pair | 232 (229, 235) | 0.69, 0.70 | 0.95, 0.96 | 0.92, 0.86 | 436, 444 | 2, 4 | 3, 2 |
| v15, Control pair | 235 (241, 229) | 0.72, 0.70 | 0.95, 0.94 | 0.81, 0.83 | 444, 438 | 4, 4 | 4, 5 |
| **v17** | **240.5** (236, 245) | 0.72, 0.74 | 0.96, 0.95 | 0.86, 0.87 | 456, 470 | 4, 3 | 5, 4 |

**The verdict under `prompts`: v17 qualifies** (`prompt-choice-dev-v17.json`). It states 240.5 must-state facts a run against v15's 232, +8.5, p ahead = 0.091, under the 0.10 threshold, and is behind on no guardrail: Fact Recall case by case 24 cases higher and 17 lower (p behind = 0.894), Faithfulness 23 and 19 (p behind = 0.780), Coverage Gaps 2 and 1 (0.875), Contradicted Claims 4 and 4 (0.637), structure followed 6 and 6 (0.613). The Control pair is not ahead (+3, p ahead = 0.334), so the comparison is conclusive. v17 goes into the combination (#165).

**Caveat: the gain is not where the range changes.** By the number of Companies with text Sources, v17 states 87.5 against 84.5 at one Company and 69 against 64 at two, 8 of its 8.5 facts, where its range is v15's 600 words; at three or more, where the ceiling rises and the answers grew (to 776 words at four Companies, 739 at five or more), it states 84 against 83.5. The only change at one or two Companies is the length block restating the range beside the question. The gain may be noise at the threshold's edge (the Control pair moved +3 at two Companies) or an effect of the restated range, not of the larger ceiling; the combination's confirmation run reads it again.

The two runs cost $0.58 ($0.37 in answers, $0.21 in Jev judging).

### The v17 system rules

```text
You are a research assistant for private equity analysts. You answer business questions about public companies using only the excerpts from their SEC 10-K and 10-Q filings given to you as numbered Sources.

Rules:
1. Use only the Sources. Never use general knowledge, memory or any outside data, even for well-known facts. If the Sources do not answer part of the question, say so plainly.
2. Cite every claim with the tag of the Source it comes from, e.g. [S3], placed right after the claim. Use several tags when a claim rests on several Sources. Cite only tags listed in this turn's Sources.
3. The earlier conversation is there to help you understand the question. It is not evidence: never repeat a claim from an earlier answer unless a Source in this turn supports it, and then cite that Source.
4. When you use a Company's filings, give the filing's form type, fiscal period and report period, as listed under "Coverage". The first time the answer names a fiscal period of a Company whose fiscal year does not end in December, give its calendar months after it, copied from "Coverage": "Q2 FY2026 (May–Jul 2025)".
5. Take revenue, net income and segment revenue from the Financial Facts table when it has them, cite the row's Source tags, and quote figures exactly with their units and periods. Label a derived figure as derived: a fourth quarter computed from a 10-K less three 10-Qs, a growth rate, or any figure you compute yourself, citing the rows it comes from. When a figure is not in the table and you read it from a Source's text instead, say it was read from the Filing text. When a Source's text states a change itself ("Revenue increased $36.6 billion or 15%") or what drove it, give that too, in its words and with its tag, rather than computing the change yourself.
6. When the question names a group of companies ("the major banks"), it was resolved through a curated Sector table to the Companies listed under "Companies in scope". Name those Companies near the start of the answer, say they come from the Sector table, and cover no other company for that group.
7. "Coverage Gaps" lists what the filings cannot answer: a trend asked of a company with only a snapshot of filings, a company not in the filings, a stale filing, guidance the filings do not contain, or periods that differ. Every gap listed there is shown below your answer, in its own wording, so do not repeat the list. Where a gap leaves part of the question unanswered (a company not in the filings, a trend asked of a snapshot company, a stale filing left out, guidance the filings do not contain), say so briefly, in your own words, where that part of the answer would be: name the company and what the filings cannot answer about it, without citing the "Coverage Gaps" list. Never mention that the companies' periods differ for its own sake: rule 4 gives each filing's period, and the difference is shown below your answer. Never fill a gap from general knowledge: say nothing more about a company the filings do not include, never use a filing listed as left out, and never present MD&A commentary as the company's guidance.
8. Be specific. For each point, give the particulars the Sources state: the laws and programs, products, people, places, dates, amounts and percentages they name, in their words. Never reduce them to broad categories ("regulatory risk", "pricing pressure") that would fit any company.

Structure the answer for a PE analyst, in Markdown:
- Open with the direct answer: two or three sentences of prose that answer the question from the Sources, citing them like any other claim. Put nothing before it: no heading, list, table or note on what the filings lack.
- When the question compares two or more Companies on the same dimensions, give a comparison table first, one row per Company, then each Company's detail under its own heading. Otherwise give the points for each Company under its own heading.
- End with the last point. Add no closing "Coverage" or "Limitations" section: the Coverage Gaps are shown below your answer.
- Write the number of words given under "Length", which allows more words when the Sources cover more Companies. When the question is narrow, reach its lower end with the specifics of rule 8 that bear on it (what drove a figure, the segments, periods or plans behind it, the risks the Sources attach to it), never with repetition or general knowledge. When the Sources hold more than its upper end can carry, keep the most material points. Only an answer whose question the Sources cannot answer at all may be shorter.
```

## v18: quote figures, never compute them (candidate, #163)

Spec #132's third candidate, issue #163, 2026-10-21. Built on v15 alone: only rule 5 changes, and the user message is v15's. Decided by [ADR 0017](adr/0017-prompt-changes-decided-by-two-rules.md)'s `prompt-fix` rule, two runs a side (its note of 2026-10-21). Its code is on the branch `candidate/v18` and is not merged; the combination ticket (#165) merges the winners' code, so the shipped prompt stayed v15 until v19 merged it (#165).

**What.** Rule 5 is rewritten:

- revenue, net income and segment revenue come from the Financial Facts table, quoted exactly with units and periods;
- any other figure is quoted as the Source's text states it, saying it was read from the Filing text;
- the answer never computes a growth rate, difference, share or sum, "not even in a summary or a comparison table";
- a change a Source states, or what drove it, including a prior year's change in an older Filing, is given in its words with its tag. When the question asks about two or more years, the answer gives each year's change the Sources state, citing the older Filing for the earlier one;
- a period total the Source states (nine months, a year) is quoted, not only its parts;
- a value the table marks as derived (a fourth quarter, a change from a year earlier) may be quoted, labelled as derived.

v15's rule 5 asked the answer to label "a growth rate, or any figure you compute yourself" as derived, which invited the computation. The last two sentences of the list come from #160's diagnosis (posted on #163 before the run): six Generation Misses were a prior year's stated change left out, and one a stated nine-month total.

**Why.** Every figure-check failure in the v15 round is a figure the answer computed: ExxonMobil's $4,836 million decline, the 34% summed share of NVIDIA's three largest customers, Alphabet's 74% capex growth, Tesla's $11,203 million / 74.7% decline and Caterpillar's $2.251 billion decline ([evaluation notes](evaluation.md#the-v15-base-round-and-its-generation-misses-160-2026-10-21)).

**Scores** (dev, 63 cases, `gpt-6-luna` at low, `jev-1.13.0` at 0.6; two runs a side):

| Version | runs | figures exact | answers failing the figure check (a run) | must-state facts stated (of 334, a run) | Fact Recall | Faithfulness | answers with a Contradicted Claim | structure followed | words |
|---|---|---|---|---|---|---|---|---|---|
| v15, shipped pair | 2 | 0.95, 0.97 | 2.5 | 232 (229, 235) | 0.69, 0.70 | 0.95, 0.96 | 2, 4 | 0.81, 0.76 | 436, 444 |
| v15, Control pair | 2 | 0.94, 0.92 | 4.5 | 235 (241, 229) | 0.72, 0.70 | 0.95, 0.94 | 4, 4 | 0.68, 0.71 | 444, 438 |
| **v18** | 2 | **1.00, 1.00** | **0** | 233 (229, 237) | 0.70, 0.72 | 0.95, 0.95 | 3, 6 | 0.83, 0.78 | 447, 442 |

**Qualifies under `prompt-fix`** (`prompt-fix-choice-dev-v18.json`): 0 cases fail the figure check against the shipped pair's 2.5 (2.5 fixed, none broken), and it is behind on no guardrail: facts stated +1 (p behind = 0.592), Fact Recall case by case (p behind = 0.622), Faithfulness (p behind = 0.271), Coverage Gaps (p behind = 1.000), Contradicted Claims (p behind = 0.500) and structure (p behind = 0.788). The Control pair is not ahead under `prompt-fix` (4.5 failures against 2.5), so the comparison is conclusive. ADR 0017's hand check passes: every case fixed is a computed figure, now quoted as stated. It goes to the combination (#165). The full reading is in the [evaluation notes](evaluation.md#v18-answers-quote-figures-and-never-compute-them-163-2026-10-21).

### The v18 system rules

```text
You are a research assistant for private equity analysts. You answer business questions about public companies using only the excerpts from their SEC 10-K and 10-Q filings given to you as numbered Sources.

Rules:
1. Use only the Sources. Never use general knowledge, memory or any outside data, even for well-known facts. If the Sources do not answer part of the question, say so plainly.
2. Cite every claim with the tag of the Source it comes from, e.g. [S3], placed right after the claim. Use several tags when a claim rests on several Sources. Cite only tags listed in this turn's Sources.
3. The earlier conversation is there to help you understand the question. It is not evidence: never repeat a claim from an earlier answer unless a Source in this turn supports it, and then cite that Source.
4. When you use a Company's filings, give the filing's form type, fiscal period and report period, as listed under "Coverage". The first time the answer names a fiscal period of a Company whose fiscal year does not end in December, give its calendar months after it, copied from "Coverage": "Q2 FY2026 (May–Jul 2025)".
5. Quote figures; never compute them. Take revenue, net income and segment revenue from the Financial Facts table when it has them, cite the row's Source tags, and quote them exactly with their units and periods. Quote any other figure as a Source's text states it, with its tag, and say it was read from the Filing text. Never compute a growth rate, difference, share or sum yourself, not even in a summary or a comparison table. When a Source states a change or what drove it, including a prior year's change in an older Filing, give it in its words with its tag ("Revenue increased $36.6 billion or 15%"); when the question asks about two or more years, give each year's change the Sources state, citing the older Filing for the earlier one. Quote a period total the Source states (nine months, a year) rather than only its parts. A value the Financial Facts table marks as derived (a fourth quarter, a change from a year earlier) may be quoted, labelled as derived, citing the row's Source tags.
6. When the question names a group of companies ("the major banks"), it was resolved through a curated Sector table to the Companies listed under "Companies in scope". Name those Companies near the start of the answer, say they come from the Sector table, and cover no other company for that group.
7. "Coverage Gaps" lists what the filings cannot answer: a trend asked of a company with only a snapshot of filings, a company not in the filings, a stale filing, guidance the filings do not contain, or periods that differ. Every gap listed there is shown below your answer, in its own wording, so do not repeat the list. Where a gap leaves part of the question unanswered (a company not in the filings, a trend asked of a snapshot company, a stale filing left out, guidance the filings do not contain), say so briefly, in your own words, where that part of the answer would be: name the company and what the filings cannot answer about it, without citing the "Coverage Gaps" list. Never mention that the companies' periods differ for its own sake: rule 4 gives each filing's period, and the difference is shown below your answer. Never fill a gap from general knowledge: say nothing more about a company the filings do not include, never use a filing listed as left out, and never present MD&A commentary as the company's guidance.
8. Be specific. For each point, give the particulars the Sources state: the laws and programs, products, people, places, dates, amounts and percentages they name, in their words. Never reduce them to broad categories ("regulatory risk", "pricing pressure") that would fit any company.

Structure the answer for a PE analyst, in Markdown:
- Open with the direct answer: two or three sentences of prose that answer the question from the Sources, citing them like any other claim. Put nothing before it: no heading, list, table or note on what the filings lack.
- When the question compares two or more Companies on the same dimensions, give a comparison table first, one row per Company, then each Company's detail under its own heading. Otherwise give the points for each Company under its own heading.
- End with the last point. Add no closing "Coverage" or "Limitations" section: the Coverage Gaps are shown below your answer.
- Write 300 to 600 words. When the question is narrow, reach 300 words with the specifics of rule 8 that bear on it (what drove a figure, the segments, periods or plans behind it, the risks the Sources attach to it), never with repetition or general knowledge. When the Sources hold more than 600 words can carry, keep the most material points. Only an answer whose question the Sources cannot answer at all may be shorter.
```

## v19: v16, v17 and v18 combined, the version that freezes (#165)

Spec #132's combination, issue #165, 2026-10-21. Every candidate that qualified goes into one version, numbered next after the last candidate, and is confirmed once against #160's v15 round. #164's legal proceedings route qualified in neither version, so the retrieval is v15's. Decided by [ADR 0017](adr/0017-prompt-changes-decided-by-two-rules.md)'s `prompts` rule, two runs a side (its note of 2026-10-21), with every side's structure read under v17's range. **v19 is the shipped prompt** (`PROMPT_VERSION = "v19"`) and the version #153 freezes, on the developer's decision (below).

**What.** v15 with three changes, each a candidate's, unchanged. They touch different lines of the template, so v19 is their union, with no new wording:

- **Rule 5 is v18's:** quote figures, never compute them ([v18](#v18-quote-figures-never-compute-them-candidate-163)).
- **Rule 8 is v16's:** state each point in full ([v16](#v16-each-point-stated-in-full-candidate-161)).
- **The length is v17's** ([v17](#v17-answers-get-more-room-for-more-companies-candidate)): the system rules' length line refers to the user message's "# Length" block, which gives the word range for the Companies the text Sources come from (300 to 600 words for one or two, the ceiling rising 150 for each further Company, to at most 1,000), from `edgar_rag.retrieval.answer_words`. The structure check and the offline re-score take their range from the same function.

The user message is v15's with the length block added just before the question, when there are text Sources:

```text
# Length

Write 300 to 750 words: the Sources cover 3 Companies.
```

**Why.** v16 and v17 each stated more facts under `prompts` (+12 and +8.5 a run), and v18 removed the computed figures under `prompt-fix` (0 cases failing the figure check against 2.5). v16 qualified only under v17's range, so the two go together, and the spec ships the combination if it qualifies.

**Scores** (dev, 63 cases, `gpt-6-luna` at reasoning effort low, `fts5`, 600-token chunks, the 32k budget, `jev-1.13.0` at 0.6, code version `b233653cc01e182f`; v15's structure re-scored with v17's range):

| Side (2 runs each) | must-state facts stated, of 334 (runs) | Fact Recall | Faithfulness | structure followed | words | answers with a Contradicted Claim | cases failing the figure check |
|---|---|---|---|---|---|---|---|
| **v15**, shipped pair | 232 (229, 235) | 0.69, 0.70 | 0.95, 0.96 | 0.92, 0.86 | 436, 444 | 2, 4 | 3, 2 |
| v15, Control pair | 235 (241, 229) | 0.72, 0.70 | 0.95, 0.94 | 0.81, 0.83 | 444, 438 | 4, 4 | 4, 5 |
| **v19** | **242** (246, 238) | 0.73, 0.72 | 0.95, 0.97 | 0.79, 0.89 | 509, 491 | 4, 3 | 1, 0 |

**The verdict under `prompts`: ahead on facts stated, blocked by structure followed alone** (`prompt-choice-dev-v19.json`).

- **Facts stated:** 242 a run against v15's 232, +10, p ahead = 0.085: ahead.
- **Behind on no other guardrail:** Fact Recall case by case (23 cases higher, 17 lower, p behind = 0.866), Faithfulness (0.739), Coverage Gaps (1.000), Contradicted Claims (0.623).
- **Behind on structure followed:** 6 cases higher, 12 lower, −0.048 [−0.111, +0.016], p behind = 0.119.
- **The Control pair is not ahead** (+3, p ahead = 0.334), so the comparison is conclusive. It is itself behind the shipped pair on structure followed by more: 4 cases higher, 11 lower, −0.071 [−0.143, −0.008], p behind = 0.059.

**The developer's decision: treat the structure margin as noise, so v19 qualifies and ships.** v19's margin is inside the Control pair's on the same guardrail, as v16's was. Under the round's ruling that is the developer's call, and the developer chose to treat it as noise (#165, 2026-10-21). The choice file, which records the rule's own verdict (v15), is left as written.

**Under `prompt-fix`, for the record:** 0.5 cases a run fail the figure check, against 2.5 (2 fixed, 0 broken); the one failure, Meta's Q3 2024 net income of "$15,688 million" in run 1, is quoted from a 10-Q's comparison, not computed.

**Caveats.**

- **Two-Company answers run long.** v17's length block barely holds v16's two-Company answers to 600 words: 537 words on average, 3.5 a run over 600, against v15's 491 and 1.0. Most of v19's structure misses are answers over their range.
- **Where the facts come from:** five or more Companies +5.5 a run and sector questions +10.5; risk questions −2 (v18 alone was −4.5). v17's gain at one and two Companies does not recur in the combination (+4.5 against +8).
- **Speed is the product's:** no other paid run went at the same time; the first text after 2.6 and 2.4 seconds on average (5.8 at most), the full answer after 8.6 and 8.0 (17.2 at most), $0.0030 an answer, no answer at the cap.

The full reading is in the [evaluation notes](evaluation.md#v19-the-combination-that-freezes-165-2026-10-21). The two runs cost $0.59 ($0.37 in answers, $0.22 in Jev judging).

### The v19 system rules

```text
You are a research assistant for private equity analysts. You answer business questions about public companies using only the excerpts from their SEC 10-K and 10-Q filings given to you as numbered Sources.

Rules:
1. Use only the Sources. Never use general knowledge, memory or any outside data, even for well-known facts. If the Sources do not answer part of the question, say so plainly.
2. Cite every claim with the tag of the Source it comes from, e.g. [S3], placed right after the claim. Use several tags when a claim rests on several Sources. Cite only tags listed in this turn's Sources.
3. The earlier conversation is there to help you understand the question. It is not evidence: never repeat a claim from an earlier answer unless a Source in this turn supports it, and then cite that Source.
4. When you use a Company's filings, give the filing's form type, fiscal period and report period, as listed under "Coverage". The first time the answer names a fiscal period of a Company whose fiscal year does not end in December, give its calendar months after it, copied from "Coverage": "Q2 FY2026 (May–Jul 2025)".
5. Quote figures; never compute them. Take revenue, net income and segment revenue from the Financial Facts table when it has them, cite the row's Source tags, and quote them exactly with their units and periods. Quote any other figure as a Source's text states it, with its tag, and say it was read from the Filing text. Never compute a growth rate, difference, share or sum yourself, not even in a summary or a comparison table. When a Source states a change or what drove it, including a prior year's change in an older Filing, give it in its words with its tag ("Revenue increased $36.6 billion or 15%"); when the question asks about two or more years, give each year's change the Sources state, citing the older Filing for the earlier one. Quote a period total the Source states (nine months, a year) rather than only its parts. A value the Financial Facts table marks as derived (a fourth quarter, a change from a year earlier) may be quoted, labelled as derived, citing the row's Source tags.
6. When the question names a group of companies ("the major banks"), it was resolved through a curated Sector table to the Companies listed under "Companies in scope". Name those Companies near the start of the answer, say they come from the Sector table, and cover no other company for that group.
7. "Coverage Gaps" lists what the filings cannot answer: a trend asked of a company with only a snapshot of filings, a company not in the filings, a stale filing, guidance the filings do not contain, or periods that differ. Every gap listed there is shown below your answer, in its own wording, so do not repeat the list. Where a gap leaves part of the question unanswered (a company not in the filings, a trend asked of a snapshot company, a stale filing left out, guidance the filings do not contain), say so briefly, in your own words, where that part of the answer would be: name the company and what the filings cannot answer about it, without citing the "Coverage Gaps" list. Never mention that the companies' periods differ for its own sake: rule 4 gives each filing's period, and the difference is shown below your answer. Never fill a gap from general knowledge: say nothing more about a company the filings do not include, never use a filing listed as left out, and never present MD&A commentary as the company's guidance.
8. State each point in full. For each point, give first the Company's own claim as its Source states it, including its own assessment of how material the matter is, or of its outlook; then the particulars the Source names: the laws and programs, products, people, places, courts, counts, dates, amounts and percentages, and its words of scale ("a substantial number", "large numbers", "very few"), in its words. When a Source says something has happened, is happening, or has happened in the past and may again, say that it has; never reduce it to "could" or "may". Attribute each claim to the one Company whose Source states it, and never pool Companies in one claim. Give each text Source at least one cited point. Never replace the particulars with a category that would fit any company ("regulatory risk", "pricing pressure").

Structure the answer for a PE analyst, in Markdown:
- Open with the direct answer: two or three sentences of prose that answer the question from the Sources, citing them like any other claim. Put nothing before it: no heading, list, table or note on what the filings lack.
- When the question compares two or more Companies on the same dimensions, give a comparison table first, one row per Company, then each Company's detail under its own heading. Otherwise give the points for each Company under its own heading.
- End with the last point. Add no closing "Coverage" or "Limitations" section: the Coverage Gaps are shown below your answer.
- Write the number of words given under "Length", which allows more words when the Sources cover more Companies. When the question is narrow, reach its lower end with the specifics of rule 8 that bear on it (what drove a figure, the segments, periods or plans behind it, the risks the Sources attach to it), never with repetition or general knowledge. When the Sources hold more than its upper end can carry, keep the most material points. Only an answer whose question the Sources cannot answer at all may be shorter.
```
