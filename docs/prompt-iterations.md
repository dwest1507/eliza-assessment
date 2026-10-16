# Prompt iteration log

Every version of the Answer Call's prompt template, newest last. The template lives in [`backend/src/edgar_rag/_prompt.py`](../backend/src/edgar_rag/_prompt.py), and its `PROMPT_VERSION` constant is logged with every Answer Call (`data/derived/logs/answer_calls.jsonl`), so each logged answer can be traced to the template that produced it.

A change to the template bumps `PROMPT_VERSION` and adds an entry here: what changed, why, and the dev-split scores before and after (retrieval and generation harnesses, on the Golden Set's dev cases only). The holdout split is scored once, at the end, on the final version.

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
