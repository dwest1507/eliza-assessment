# Golden Set

The Golden Set is the evaluation's ground truth: 30 labelled questions that the retrieval and generation harnesses score the system against. It lives in [`data/eval/golden_set.json`](../data/eval/golden_set.json) and is read by `edgar_rag.golden_set.load_golden_set()`, which checks the schema. It was written before any retrieval Arm or prompt ran, so no label was written with results in view.

This page describes version 1, the set every result so far was measured on, the Required Fact tiers that version 2 adds, and the [Brief Suite](#the-brief-suite), the brief's questions in a file of their own. Version 2's [file](#the-file) is built and holds all 27 of version 1's cases other than the brief's, [rewritten](#the-rewritten-version-1-cases), and the first slice of its [new cases](#the-new-cases); the rest of version 2 is decided but not built yet: see [Version 2](#version-2). Version 1's file stays unchanged as a record, and a test pins its digest.

## What it covers

| Question type | Cases | What it tests |
|---|---|---|
| `risk` | 9 | Risk comparisons across Companies, single-Company risk questions, and the Legal Proceedings and Market Risk Sections |
| `figure_trend` | 6 | Revenue, net income and segment revenue over named years or "the last two years" |
| `sector` | 5 | Sector phrases resolved through the Sector table: pharmaceutical companies, banks, software companies, aerospace and defense, oil majors |
| `missing_company` | 4 | Companies not in the Corpus (Wells Fargo, Citigroup, Bristol Myers Squibb, Honeywell) |
| `outlook` | 4 | Outlook questions. Three have no guidance in the Filings; Meta's expected 2026 capital expenditures are in its 10-K |
| `stale_filing` | 2 | The GE Capital FY2014 Filing, asked about as General Electric today and as GE Capital in 2014 |

The cases are seeded from the eight questions traced in EDA analysis 8 (the brief's three examples and variants V1 to V5) and add the question types and Sections the spec names.

**Multi-turn cases.** Six cases have a scripted history: earlier user messages and fixed earlier answers that cite Filing IDs, the way the Answer Call's prompt rewrites earlier Source tags. They test the follow-up rules of [ADR 0003](adr/0003-follow-ups-inherit-query-scope-by-rules.md):

- Inheriting the Companies: "Which of them has the most regulatory exposure?" and "How did that change over the last two years?"
- Switching the Company: "And what about Microsoft?", "And the oil majors?" and "What about Honeywell?"
- A change of topic that names no Company (`followup-topic-change-export-controls`, tagged `topic_change_without_company`). The rules wrongly inherit Apple from the earlier question. The case expects the whole-Corpus answer (NVIDIA and AMD), so it measures ADR 0003's known weakness rather than hiding it.

**Starter prompts.** The cases with a `starter` object are the front-end's starter prompts. `order` sets their position and `label` is the button text. They are the brief's three example questions, a sector phrase (the major banks), a Coverage Gap (JPMorgan's revenue trend, a Snapshot Company) and a Company missing from the Corpus (Wells Fargo). Every starter is therefore measured, and none was picked after seeing results. Starters may come from either file: the brief's three now point at their [Brief Suite](#the-brief-suite) cases, which take over the starter of the version 1 case each replaces (`edgar_rag.golden_set.starter_cases`), and the other three stay here. The text is unchanged, and the front-end's sync test reads both files.

## Fields

The file holds `version`, `split_rule` and `cases`. Each case has:

| Field | Meaning |
|---|---|
| `id` | Stable, unique case id. The split is computed from it. |
| `question` | The latest user message, the one the Answer Call answers |
| `history` | Earlier turns, oldest first, as `{role, content}` with role `user` or `assistant`. Always ends with an assistant answer. Empty for a single-turn case. |
| `question_type` | One of `risk`, `figure_trend`, `sector`, `outlook`, `missing_company`, `stale_filing` |
| `split` | `dev` or `holdout`, as computed by the split rule. From version 2, recorded per case, and `pending` while new cases are drafted ([The file](#the-file)) |
| `starter` | `{order, label}` for a starter prompt, else `null` |
| `tags` | Free labels for case features: `brief_example`, `inherits_companies`, `switches_company`, `topic_change_without_company` |
| `notes` | Why the case exists and what makes it hard |
| `expected_sources` | The (`filing_id`, `section`) pairs that should reach the Answer Call. These are what hit@k, recall@k and MRR are scored against. Empty when nothing should be retrieved (a Company missing from the Corpus, GE today). |
| `required_facts` | What a good answer must state. Each is `{fact, filing_id, section, evidence, tier}`: a self-contained sentence naming its Company, the Filing and Section that support it, a quote from that Section, and its tier (see below). |
| `expected_coverage_gaps` | The Coverage Gaps the answer must state, as `{kind, companies}`. Companies are tickers, or names for Companies missing from the Corpus. |

Coverage Gap kinds follow EDA notebook section 8.6:

| Kind | When |
|---|---|
| `snapshot_trend` | A trend is asked of a Snapshot Company |
| `missing_company` | A named Company is not in the Corpus |
| `stale_filing` | The answer would rest on GE Capital's FY2014 Filing |
| `no_guidance` | An outlook question whose guidance is not in the Filings |
| `periods_differ` | The compared Companies' latest Filings cover different periods |

**Tiers.** A Required Fact's `tier` is `must_state`, something any good answer covers, or `detail`. The generation harness asks Jev about every fact, scores Fact Recall on the must-state facts only and reports detail recall beside it, so a missed detail is visible but never counts as a miss ([evaluation](evaluation.md#method)). Version 1's facts have no `tier` field and load as `must_state`, so version 1 is scored exactly as before; from version 2 on every fact must name its tier. The loader rejects an unknown tier, and a case with no must-state fact unless it has no Required Facts at all and expects a Coverage Gap (a Company missing from the Corpus, GE today).

The generation harness checks only the gaps listed. A system that states an extra gap is not penalised by the Golden Set; Faithfulness judging covers whether it was warranted.

Section names are the Corpus seam's standard names (`Risk Factors`, `MD&A`, `Legal Proceedings`, `Market Risk`, and so on). Where a Filing has no Item heading for the text, the label names the Section the text actually sits in: JPMorgan's 10-Q financial review is `Unsectioned`, and its 10-K's financial review comes after Item 15, in `Other`.

## The split rule

Sort the case ids by the SHA-256 hex digest of each id (UTF-8). The first third, rounded to the nearest whole case, are holdout; the rest are dev. That gives 10 holdout cases and 20 dev cases.

The rule is written in the file (`split_rule`), each case records its split, and a test recomputes the split from the ids and checks it matches. Prompt and Arm choices are tuned on dev only, and the holdout is scored once per final setup and never used to choose ([the holdout rule](evaluation.md#the-holdout-rule)).

The first rule tried was a per-case threshold: holdout when the hash modulo 10 is 7, 8 or 9, about 30% of cases. On these 30 ids it put only 5 cases in the holdout, too few to score. It was replaced by ranking before any Arm or prompt had run, so no score could have influenced the change. Ranking keeps the holdout at exactly a third. The cost is that adding a case can move one other case across the boundary, so cases should not be added after the holdout has been scored.

## How the cases were drafted and reviewed

No second human was available to label, so an agent drafted every case from the Corpus and the review was made mechanical where it could be.

1. **Drafted from the Corpus, not from memory.** For each question, the agent resolved the Query Scope by the rules the spec sets: Companies and Sector phrases through the Sector table, "latest" as the latest 10-K plus later 10-Qs, "the last two years" anchored on each Company's latest Filing (assumption 6). It then searched the cleaned Sections of those Filings for the passages that answer it. Every Required Fact was written from a passage that was read, and its evidence quote was copied from that passage.
2. **Checked by tests** (`backend/tests/test_golden_set.py`):
   - the schema is valid, ids are unique, and every question type is covered;
   - every expected Filing ID exists in the Corpus and has a Section of the expected name;
   - every evidence quote is found verbatim in a Section of that name in that Filing, after collapsing runs of whitespace (flattened tables and non-breaking spaces vary only in whitespace);
   - every Required Fact is a sentence that names its Company and cites one of its case's expected sources;
   - there are about six multi-turn cases, one of which changes topic without naming any Company;
   - the six starters are present in order, include the brief's three questions, and cover a sector phrase, a Snapshot trend and a missing Company;
   - the recorded split matches the rule.
3. **Reviewed by reading.** Each case was read back against its notes: is the question one an analyst would ask, are the expected Sources the ones that answer it, and is anything the answer must say missing from Required Facts or Coverage Gaps?

The tests prove that the labels point at real text. They cannot prove that the labels are complete: an answer may cite a correct Source or state a correct fact that the case does not list. Fact Recall is therefore scored against the Required Facts, while Faithfulness is judged separately from the cited passages.

## The Brief Suite

The brief's example questions, kept outside the dev/holdout split in their own file, [`data/eval/brief_suite.json`](../data/eval/brief_suite.json), read by `edgar_rag.golden_set.load_brief_suite()` ([ADR 0012](adr/0012-golden-set-version-2-and-the-brief-suite.md)). It is a must-pass check, not an estimate, so it may be tuned on freely and never loses a case to the holdout. Each case runs 5 times, passes or fails on its own, and is reported one by one ([The Brief Suite run](evaluation.md#the-brief-suite-run)).

**The cases.** The brief's three questions, with the same wording as version 1:

| Case | Replaces | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|---|
| `brief-risk-aapl-tsla-jpm` | `risk-aapl-tsla-jpm` | 9 / 19 | Risk Factors of the three latest 10-Ks, and Apple's later 10-Q |
| `brief-outlook-nvda-revenue-two-years` | `outlook-nvda-revenue-two-years` | 7 / 12 | MD&A of NVIDIA's eight Filings from the FY2024 10-K to the Q3 FY2026 10-Q |
| `brief-sector-pharma-regulatory` | `sector-pharma-regulatory` | 9 / 35 | Risk Factors of each latest 10-K, and its Business and MD&A regulation and pricing passages; the MD&A of Pfizer's Q3 2025 10-Q, the only 10-Q in the five latest windows |

**The variants.** Each of the three questions has four variants, one per angle ADR 0012 names, so a pass reflects the kind of question rather than one wording. Each records the brief question it varies (`variant_of`) and its angle as a tag (`rephrasing`, `other_companies`, `other_angle`, `follow_up`). For the pharmaceutical question, the other Companies come from another Health Care Sector phrase and the other angle is a single Company.

| Case | Angle | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|---|
| `brief-risk-aapl-tsla-jpm-rephrased` | Rephrasing: "How do the biggest risks that Apple, Tesla and JPMorgan disclose stack up against each other?" | 9 / 19 | The brief case's Sources, with its facts and Coverage Gap |
| `brief-risk-msft-xom-unh` | Other Companies: Microsoft, Exxon Mobil and UnitedHealth, one per Sector | 9 / 17 | Risk Factors of each latest 10-K and the 10-Qs after it |
| `brief-risk-aapl-tsla-jpm-fy2025-quarterly-updates` | Another window and Section angle: the risk factors updated in their fiscal 2025 10-Qs | 5 / 10 | Risk Factors of the nine fiscal 2025 10-Qs |
| `brief-followup-aapl-tsla-jpm-cybersecurity` | Follow-up: "How do their cybersecurity risks compare?" after the brief question | 6 / 8 | The cyber passages of the three latest 10-Ks' Risk Factors |
| `brief-outlook-nvda-revenue-rephrased` | Rephrasing: "Over the past two years, what has happened to NVIDIA's revenue, and how has its view of future growth shifted?" | 7 / 12 | The brief case's Sources, with its facts and Coverage Gap |
| `brief-outlook-unh-revenue-two-years` | Other Companies: UnitedHealth, another Tracked Company | 5 / 11 | MD&A of UnitedHealth's Filings from the FY2023 10-K to the Q3 2025 10-Q |
| `brief-outlook-nvda-revenue-fy2024` | Another window: NVIDIA's fiscal 2024, the year before the brief's | 5 / 12 | MD&A of the FY2023 10-K, the three FY2024 10-Qs and the FY2024 10-K |
| `brief-followup-nvda-net-income` | Follow-up: "How did its net income change over the same period?" after the brief question | 3 / 7 | MD&A of the FY2024 and FY2025 10-Ks and the Q1 and Q3 FY2026 10-Qs |
| `brief-sector-pharma-regulatory-rephrased` | Rephrasing: "Which regulatory risks do the big drugmakers disclose, and what are they doing in response?" | 9 / 35 | The brief case's Sources, with its facts and Coverage Gap |
| `brief-sector-health-care-regulatory` | Another Sector phrase: "the major health care companies", the whole Health Care sector, which adds Thermo Fisher and UnitedHealth to the five | 13 / 23 | The brief case's Sources; Risk Factors of Thermo Fisher's and UnitedHealth's latest 10-Ks, Thermo Fisher's Business regulation passages, and the MD&A of UnitedHealth's and Pfizer's Q3 2025 10-Qs |
| `brief-pharma-regulatory-pfe` | A single Company: Pfizer, from its FY2024 10-K and the 2025 10-Qs after it | 4 / 20 | Risk Factors and the Business pricing and regulation passages of the FY2024 10-K, and the Q3 2025 10-Q's MD&A |
| `brief-followup-pharma-340b` | Follow-up: "How are they dealing with the 340B drug discount program?" after the brief question | 8 / 15 | Every 340B passage in the five latest 10-Ks' Risk Factors, Business and MD&A, and Merck's 340B litigation note in its Financial Statements |

A rephrasing keeps its brief case's Query Scope, so it keeps that case's labels: only the wording changes ("the big drugmakers" resolves through the Sector table to the same five Companies as "the major pharmaceutical companies"). Each follow-up's scripted answer cites Filing IDs, and the follow-up names no Company, so it measures inheritance by ADR 0003's rules; the net income follow-up inherits the time window too ("the same period"), and the 340B follow-up's scripted answer does not mention the program.

- **Every half of a question has facts.** The risk comparison's must-state facts are each Company's defining risks, and the comparison rests on the themes all three name (tariffs and trade policy, regulation, cyber attacks, competition). NVIDIA's outlook facts trace how it changed: next-generation products expected to be supply-constrained at the end of FY2024, Blackwell demand ahead of supply through FY2025, then Blackwell as the majority of Data Center revenue and H20 export licensing hurting future revenue. The pharmaceutical facts cover "how are they addressing them" from the Business and MD&A Sections: Janssen's and Merck's lawsuits over the IRA's price negotiation, Lilly's preliminary agreements with the U.S. government, Pfizer's engagement with payors and the government, and each Company's 340B and compliance responses. Pfizer's September 2025 agreements with the U.S. government, from its Q3 2025 10-Q, are a detail: its must-state response is already its engagement with the government. AbbVie's 10-K names no specific response beyond evaluating the IRA and the cost of compliance, so its responses are details. Each pharmaceutical variant has must-state facts on the responses too: the health care variant keeps the brief case's and adds Thermo Fisher's internal controls and compliance systems and UnitedHealth's tighter cost management in response to Medicare Advantage benchmark cuts; Pfizer's are its September 2025 agreements with the U.S. government and its engagement with payors and the government; the 340B follow-up's are J&J's delivery policy, Lilly's Contract Pharmacy Limited Distribution System, Merck's commitment to the program and Pfizer's contract pharmacy integrity policy.
- **Figures from the reference.** NVIDIA's revenue figures and growth rates match the SEC company-facts reference (Revenues: $60,922 million for FY2024, $130,497 million for FY2025, $57,006 million for Q3 FY2026). The $4.5 billion H20 charge has no company-facts value, so its fact states the charge without the amount; the amount is still in its evidence quote. The variants' figures match the same reference, which the figure check confirms: UnitedHealth's Revenues ($371,622 million for 2023, $400,278 million for 2024, $113,161 million for Q3 2025), NVIDIA's fiscal 2024 Revenues ($26,974 million for FY2023, $7,192, $13,507 and $18,120 million for Q1 to Q3 FY2024) and NVIDIA's NetIncomeLoss ($29,760 million for FY2024, $72,880 million for FY2025, $18,775 million for Q1 FY2026 against $22,091 million the quarter before, $31,910 million for Q3 FY2026 against $19,309 million a year earlier), with every growth rate recomputed from them. Facts that rest on figures without a company-facts value (earnings from operations, inventory charges, Pfizer's expected revenue impact of the Part D redesign) state no amount.

**Fields.** The same case schema as the Golden Set's, with four differences:

- no `split`: the loader rejects one, and the Golden Set's loader rejects a Brief Suite case, which has none;
- every Required Fact names its `tier`;
- `replaces`, on a case rewritten from a version 1 case, names that case, so saved version 1 answers can be matched to the rewritten facts. It must name a Golden Set case.
- `variant_of`, on a variant, names the brief question's case it varies. It must name a Brief Suite case that replaces one, and the Golden Set's loader rejects the field.

No id is in both files: the loader rejects one that is.

**Checks.** The Golden Set's label tests run over the Brief Suite too (every expected Filing and Section exists, every evidence quote is verbatim in its Section, every fact names its Company and cites one of its case's expected Sources), and the Brief Suite's own tests check that its cases replace the version 1 brief cases with the same questions, that every case has facts of both tiers, that each brief question has four variants, one per angle, with a history only on the follow-up, and the loader's refusals. Version 2's checks for a repeated question and for figures against the SEC company-facts reference ([Checks](#the-file)) cover the Brief Suite too. The repeated-question check catches a repeated wording only; a repeat in other words (the same Companies and topic) is caught in review.

## Version 2

Decided on 2026-10-17 ([ADR 0012](adr/0012-golden-set-version-2-and-the-brief-suite.md)). The Required Fact tiers, the Brief Suite, with the brief's three questions and four variants of each, and version 2's file, with all three batches of version 1's 27 other cases rewritten and the first of six slices of new cases, are built so far.

### The file

Version 2 lives in [`data/eval/golden_set_v2.json`](../data/eval/golden_set_v2.json), beside version 1, which stays unchanged. It is read by the same loader, `load_golden_set(DEFAULT_GOLDEN_SET_V2)`, with the same case schema and three differences:

- `version` is 2, and every Required Fact names its `tier`;
- `split_rule` states version 2's rule (`SPLIT_RULE_V2`): each case records its split, and no case ever moves. Version 1's cases rewritten here keep their ids and are `dev`. New cases are `pending` until all of them exist; then the 20 whose ids have the lowest SHA-256 digests become `holdout` and the rest `dev`;
- `split` is `dev`, `holdout` or `pending`. Version 1's loader still allows only `dev` and `holdout`.

**Runs.** The harnesses keep version 1 as their default until the split is frozen. A version 2 run names the file (`python -m edgar_eval.retrieval --golden-set ../data/eval/golden_set_v2.json`, and likewise `edgar_eval.generation`), and it refuses, naming the cases, while any case is pending (`GoldenSet.require_frozen`). A Brief Suite run is checked against both versions whichever file is named, since its cases replace version 1 cases.

**Checks** (`backend/tests/test_golden_set.py`). The label tests run over version 1, version 2 and the Brief Suite alike: every expected Filing ID and Section exists, every evidence quote is verbatim in its Section after collapsing whitespace, and every fact names its Company and cites one of its case's expected Sources. Version 2 adds:

- **No repeated question.** No question is asked twice across Golden Set version 1, Golden Set version 2 and the Brief Suite, once case and whitespace are normalised. A version 1 case may share its question with the version 2 case that rewrites it under the same id, and with the Brief Suite case that replaces it.
- **No shared id** between version 2 and the Brief Suite; the Brief Suite's loader checks both versions.
- **Figures from the reference.** Every dollar amount a version 2 or Brief Suite Required Fact states must match a USD value that the SEC company-facts reference records for the fact's own Filing (matched on the accession number in its source URL), at the amount's printed precision: "$60.9 billion" matches 60.85 to 60.95 billion. A figure about a Company the reference does not cache fails. The test is skipped when the cache is absent (`make sec-facts`). Percentages are not checked against it.
- **The mix by kind of question**, counted per split against ADR 0012's table below and printed with the test run, not yet enforced. A follow-up counts as one whatever it asks; a Coverage Gap case asks about a missing Company or a stale Filing, or for a trend or outlook the Filings cannot give (a `snapshot_trend` or `no_guidance` gap); the rest count by question type (`risk`; `figure_trend` and `outlook` as trends; `sector`).

### The rewritten version 1 cases

Version 1's 27 cases other than the brief's are rewritten into version 2 in three batches of nine, all `dev`. Each keeps its id, question, history, question type and starter, and tests check that a version 2 case with a version 1 id keeps them and is `dev`, and that all 27 are in version 2. Its labels are drafted again from the whole of each relevant Section, never from what retrieval returns: compound facts split into one-claim facts, every fact tiered, and facts added for anything the version 1 labels left out. The first batch:

| Case | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|
| `risk-aapl-legal-proceedings` | 4 / 12 | Legal Proceedings of Apple's FY2025 10-K and Q1 FY2026 10-Q |
| `risk-ko-market-risk` | 5 / 11 | Market Risk of Coca-Cola's FY2024 10-K, its foreign currency and interest rate passages |
| `risk-unh-cybersecurity` | 4 / 14 | Risk Factors, MD&A and, new in version 2, Cybersecurity (Item 1C) of UnitedHealth's FY2024 10-K |
| `risk-aapl-nvda-supply-chain` | 7 / 16 | Risk Factors of Apple's FY2025 10-K and, new, its Q1 FY2026 10-Q; of NVIDIA's FY2025 10-K and Q3 FY2026 10-Q |
| `sector-banks-risks` | 7 / 13 | Risk Factors of Bank of America's FY2024 10-K and Q3 2025 10-Q, and of JPMorgan's FY2025 10-K |
| `sector-software-ai-risks` | 8 / 24 | Risk Factors of Adobe's, Salesforce's, Microsoft's and Oracle's latest 10-Ks and, new, Microsoft's Q2 FY2026 10-Q |
| `sector-aerospace-government` | 4 / 13 | Risk Factors of Boeing's, Lockheed Martin's and RTX's FY2025 10-Ks and, new, RTX's Business Section |
| `risk-bac-change-snapshot` | 1 / 2 | Risk Factors of Bank of America's FY2024 10-K and, new, all three of its 2025 10-Qs |
| `missing-wells-fargo-vs-jpm` | 3 / 9 | Risk Factors of JPMorgan's FY2025 10-K |

- **New Sources.** Five cases gain an expected Source that version 1 left out because a passage answering the question sits there: UnitedHealth's Cybersecurity Section, Apple's later 10-Q, Microsoft's latest 10-Q (which restates its risk factors with new AI passages), RTX's Business Section (the share of its sales made to the U.S. government) and Bank of America's first two 2025 10-Qs.
- **Must-state or detail.** The must-state facts are what any good answer gives: each Company's defining risks, its headline figure (Boeing's 35%, Lockheed Martin's 72%, RTX's 38% of sales to the U.S. government), and, for a comparison, each side's. Dates, the second half of a split fact, risk categories beyond the main ones and remediation steps are details.
- **No amount without a reference value.** None of this batch's dollar amounts has an SEC company-facts value: Coca-Cola's $28.7 billion of revenue outside the U.S. and $18,442 million of foreign currency notional value, UnitedHealth's Change Healthcare costs, and every amount for Companies the reference does not cache (Boeing, Lockheed Martin, RTX). Their facts state no amount, as in the Brief Suite; the amount stays in the evidence quote. Version 1's Coca-Cola facts stated two of these amounts.
- **Review.** The developer waived the review of drafted labels on 2026-10-17 (spec #43), so the label tests and the read-back of each case against its notes are the review.

The second batch, version 1's figure trend, outlook and General Electric cases:

| Case | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|
| `trend-jpm-revenue-snapshot` | 2 / 8 | The financial review of JPMorgan's FY2025 10-K (Other) and, new, of all three of its 2025 10-Qs (Unsectioned) |
| `trend-meta-revenue-two-years` | 4 / 11 | MD&A of Meta's FY2024 and FY2025 10-Ks |
| `trend-aapl-revenue-fy2025` | 5 / 11 | MD&A of Apple's FY2025 10-K, its segment and category tables and their commentary |
| `trend-tsla-net-income-three-years` | 6 / 4 | MD&A of Tesla's FY2023, FY2024 and FY2025 10-Ks |
| `trend-amzn-aws-two-years` | 2 / 5 | MD&A of Amazon's FY2024 and FY2025 10-Ks |
| `outlook-tsla-2026` | 3 / 9 | The 2026 Outlook passages of the MD&A of Tesla's FY2025 10-K |
| `outlook-msft-cloud` | 4 / 8 | MD&A of Microsoft's Q2 FY2026 10-Q |
| `outlook-meta-capex-2026` | 2 / 2 | MD&A of Meta's FY2025 10-K |
| `stale-ge-recent-performance` | 0 / 0 | None: the case expects only the stale Filing Coverage Gap, as in version 1 |

- **Each figure its own fact.** A period's figure and the change from the period before are separate facts: Meta's revenue for 2024 and for 2025 and the 22% growth of each, Tesla's net income for each year and the decrease from the year before, Apple's total net sales for each fiscal year and the 6% between them.
- **Figures from the reference.** The total figures match the SEC company-facts reference, which the figure check confirms: Meta's RevenueFromContractWithCustomerExcludingAssessedTax ($134,902, $164,501 and $200,966 million for 2023 to 2025), Apple's ($391,035 and $416,161 million for FY2024 and FY2025), Tesla's NetIncomeLoss ($14,997, $7,091 and $3,794 million for 2023 to 2025) and Tesla's 2025 PaymentsToAcquirePropertyPlantAndEquipment ($8,527 million), with every growth rate recomputed from them.
- **No amount without a reference value.** The reference has no segment, category or forecast values and does not cache JPMorgan, a Snapshot Company. So the facts on AWS's, Apple's segments' and categories', Meta's segments' and Microsoft Cloud's revenue, Microsoft's commercial remaining performance obligation (the reference records total remaining performance obligations of $631 billion, not the MD&A's $625 billion commercial figure) and every JPMorgan figure state the growth rate or direction only. So do the facts on Tesla's year-on-year changes in dollars and its 2023 tax benefit. Where the forecast is the answer, the must-state fact says the Filing gives it: Meta "gives a range for the capital expenditures it anticipates making in 2026" ($115 billion to $135 billion) and Tesla "gives a minimum figure" for its 2026 capital expenditures (more than $20 billion). An answer states the fact by giving the range or the minimum, which stays in the evidence quote. Ten of this batch's version 1 facts stated an amount like these.
- **New Sources.** JPMorgan's case gains its first two 2025 10-Qs, whose quarters are in the window: revenue up 8% in the first quarter and down 11% in the second, when the Visa share gain of the year before was absent.
- **Must-state or detail.** The must-state facts are each period's headline figure and its change, and for an outlook what the Filing expects: Tesla's capital expenditures driven by AI and its Robotaxi growth, Microsoft's cloud growth rates, backlog and continued capital investment, Meta's expected capital expenditures. Segment and category breakdowns, drivers, the year before the window and risks to the outlook are details. Apple's Services growth and Greater China decline stay must-state, as in version 1.

The third batch, version 1's GE Capital, Citigroup and Bristol Myers Squibb cases and its six follow-ups, completes the rewrite: version 2 now holds all 27 of version 1's cases other than the brief's.

| Case | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|
| `stale-gecc-eni-2014` | 3 / 8 | MD&A of GE Capital's FY2014 10-K |
| `missing-citigroup` | 0 / 0 | None: the case expects only the missing Company Coverage Gap, as in version 1 |
| `missing-bms-with-merck` | 4 / 12 | Risk Factors of Merck's FY2024 10-K |
| `followup-regulatory-exposure` | 10 / 24 | Risk Factors of Apple's FY2025, Tesla's FY2025 and JPMorgan's FY2025 10-Ks, their legal and regulatory risk factors in particular |
| `followup-switch-to-msft` | 6 / 11 | MD&A of Microsoft's FY2024 and FY2025 10-Ks and Q2 FY2026 10-Q and, new, its Q1 FY2026 10-Q |
| `followup-tsla-risk-change` | 5 / 7 | Risk Factors of every Tesla Filing in the window: the Q1 and Q2 2025 10-Qs, the FY2025 10-K and, new, the FY2024 10-K |
| `followup-topic-change-export-controls` | 2 / 9 | MD&A of NVIDIA's Q3 FY2026 10-Q and, new, its Q1 FY2026 10-Q, and of AMD's FY2025 10-K |
| `followup-pharma-to-oil-majors` | 7 / 17 | Risk Factors of Chevron's FY2024 and ExxonMobil's FY2025 10-Ks |
| `followup-ge-to-honeywell` | 0 / 0 | None: the case expects only the missing Company Coverage Gap, as in version 1 |

- **Every half of a question has facts.** The oil majors follow-up inherits the pharmaceutical question's "how are they addressing them", and each Risk Factors Section answers it: Chevron's aspiration to net zero upstream Scope 1 and 2 emissions by 2050, ExxonMobil's net zero ambition for its operated assets and its Low Carbon Solutions business are must-state, beside each Company's greenhouse gas and regulatory risks. The regulatory exposure follow-up asks which Company is most exposed; the Filings do not rank the three, so its must-state facts are each Company's main regulatory exposures and none names a winner.
- **Tracing a change.** Tesla's risk change follow-up compares the FY2024 and FY2025 10-Ks as well as reading the 2025 10-Qs' additions (tariffs, protests, lost tax credits): the FY2025 10-K puts driver assistance and autonomy first where the FY2024 10-K put mass-market vehicles, and adds Optimus, Robotaxi and the 2025 CEO Performance Award. The 2024 10-Qs report no change from the FY2023 10-K, and the Q3 2025 10-Q adds none.
- **The whole Corpus.** The export controls follow-up still expects the whole-Corpus answer, so it keeps measuring ADR 0003's known weakness. Every 2025 and 2026 Filing was searched for a charge caused by export controls, and only NVIDIA's and AMD's report one. NVIDIA's Q1 FY2026 10-Q, which first reports the H20 charge, is a new Source.
- **Figures from the reference.** Microsoft's revenue for each period matches the SEC company-facts reference, which the figure check confirms (RevenueFromContractWithCustomerExcludingAssessedTax: $245,122 million for FY2024, $281,724 million for FY2025, $77,673 million for Q1 FY2026 and $81,273 million for Q2 FY2026), with every growth rate agreeing with it. Each period's revenue and its growth are separate facts.
- **No amount without a reference value.** GE Capital, AMD, Chevron and Merck are not in the reference, and NVIDIA's H20 charge and Microsoft Cloud's revenue have no company-facts value. So the facts on GE Capital's ending net investment and its target, NVIDIA's and AMD's charges and Microsoft Cloud's growth state no amount; the amount stays in the evidence quote. Seven of this batch's version 1 facts stated an amount like these, among them Microsoft's yearly increases in dollars.
- **Must-state or detail.** The must-state facts are what any good answer gives: GE Capital's reduced ending net investment, its target and its strategy of exiting non-core businesses; Merck's pricing pressure from Medicare and Medicaid law, its expected Keytruda decline, increasing U.S. regulation and the need for approval; each period's Microsoft revenue and growth; each export control charge. Drivers, particular programs, taxes, sanctions and investigations, and each Company's later steps are details. The three cases that expect only a Coverage Gap keep no Required Facts.

### The new cases

Version 2's 53 new cases are drafted in six slices of at most ten, one slice at a time, each with its own kinds of question and Companies. Every new case is `pending` until the last slice is done and the split is frozen, and a test checks that every case version 1 does not hold is `pending`. Each is drafted by the same rules as the rewrites, from the whole of each relevant Section and never from what retrieval returns, after reading every case already in both Golden Set versions and the Brief Suite so that none asks the same Companies about the same topic.

The first slice is nine multi-Company risk comparisons among information technology, communication services and consumer Companies: six compare two Companies and three compare three, across the Risk Factors, Legal Proceedings and Market Risk Sections. A test checks the slice's ids, kinds, Sectors and Sections.

| Case | Companies | Topic | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|---|---|
| `risk-meta-amzn-legal-proceedings` | Meta, Amazon | Legal proceedings: antitrust, privacy, youth, AI training, patents | 8 / 13 | Legal Proceedings of Meta's FY2025 10-K; Amazon's Item 3 refers to its Financial Statements' Legal Proceedings note, which its facts cite |
| `risk-goog-meta-ai` | Alphabet, Meta | AI | 7 / 13 | Risk Factors of both FY2025 10-Ks |
| `risk-nflx-dis-streaming-competition` | Netflix, Disney | Competition in streaming | 6 / 12 | Risk Factors of Netflix's FY2025 and Disney's FY2025 10-Ks |
| `risk-t-vz-cmcsa-regulation` | AT&T, Verizon, Comcast | Regulation | 9 / 14 | Risk Factors of the three FY2025 10-Ks |
| `risk-amd-csco-supply-chain` | AMD, Cisco | Supply chain | 7 / 16 | Risk Factors of AMD's FY2025 and Cisco's FY2025 10-Ks |
| `risk-nke-sbux-hd-consumer-demand` | Nike, Starbucks, Home Depot | Consumer demand | 9 / 14 | Risk Factors of Nike's FY2025, Starbucks' FY2025 and Home Depot's fiscal 2024 10-Ks |
| `risk-aapl-msft-market-risk` | Apple, Microsoft | Interest rate and foreign exchange risk | 6 / 10 | Market Risk of Apple's FY2025 10-K and Q1 FY2026 10-Q, and of Microsoft's FY2025 10-K and Q2 FY2026 10-Q |
| `risk-nvda-amd-competition` | NVIDIA, AMD | Competition, AI accelerators included | 6 / 12 | Risk Factors of NVIDIA's FY2025 10-K and Q3 FY2026 10-Q, and of AMD's FY2025 10-K |
| `risk-nke-tsla-amzn-tariffs` | Nike, Tesla, Amazon | Tariffs and trade policy | 6 / 13 | Risk Factors of Nike's FY2025, Tesla's FY2025 and Amazon's FY2025 10-Ks |

- **Not a repeat.** Apple, Tesla and JPMorgan together and Apple with NVIDIA on supply chain are already asked, and so are Apple's legal proceedings, Coca-Cola's market risk, the software companies' AI risks and NVIDIA's and AMD's export control charges. This slice's Companies and topics differ from each of them.
- **Must-state or detail.** The must-state facts are each Company's headline risk on the question's topic and, for a comparison, what each side says about the theme they share: the FCC and state broadband rules for the three telecom and cable Companies, the lead-sheathed cable allegations for AT&T and Verizon, outsourced manufacturing and single or limited sources for AMD and Cisco. Dates, appeals, examples and the further risks of each passage are details.
- **Coverage Gaps.** Six cases compare Companies whose latest 10-Ks cover different periods, so they expect the periods differ gap; the AI, regulation and legal proceedings cases compare Companies with the same fiscal year.
- **No amount.** No fact states a dollar amount. The settlement, damages, sensitivity and value-at-risk amounts in these Sections have no SEC company-facts value, and the fines are in euros; the amounts stay in the evidence quotes.
- **Fact wording.** The judge study measured Jev on one-claim facts and set the fact cut-off at 0.6 ([The judge study's results](evaluation.md#the-judge-studys-results)). Each fact here states one claim in the Filing's own terms and names its Company. None renames the Filing's period (a fiscal quarter given as a calendar date) or states a cause or change the Filing does not, the wordings of several study items on which Jev and the labels disagreed.
- **Names.** The Sector table names Disney "The Walt Disney Company", so its facts name it Walt Disney, which the label test that a fact names its Company recognises.

### What is decided

Version 1 has too few cases for a comparison to see a real difference, and some of its labels make the judge misread answers ([Evaluation version 2](evaluation.md#evaluation-version-2)).

- **The Brief Suite.** The brief's three example questions move out of the dev/holdout split, each with four variants: about 15 cases in all. Each case runs 5 times on every change that could alter an answer. It passes when every must-state Required Fact is stated in at least 4 of the 5 runs and no run has a Contradicted Claim. Its cases are reported one by one and may be tuned on, since it is a must-pass check, not an estimate. The starter prompts keep the brief's three questions, now from the Brief Suite. Built with the three questions and their twelve variants, 15 cases ([The Brief Suite](#the-brief-suite)).
- **60 dev cases and 20 holdout cases:**

  | Kind of question | Dev | Holdout |
  |---|---|---|
  | Multi-Company risk comparisons | ~15 | ~5 |
  | Figure and outlook trends | ~15 | ~5 |
  | Sector questions | ~12 | ~4 |
  | Coverage Gap cases | ~10 | ~3 |
  | Follow-ups | ~8 | ~3 |

  Figure facts are labelled from the SEC company-facts reference, independently of the system's own Financial Facts.
- **Version 1's 27 cases other than the brief's join dev**, including its 10 holdout cases, which were scored once and never tuned on. Their labels are rewritten in the new format.
- **A split recorded per case.** The 33 new dev cases and 20 holdout cases are drafted together, and the 20 whose ids have the lowest SHA-256 digests are the holdout. Every case records its split, and no case moves when another is added. This replaces the ranking rule above, under which adding a case could move another. The recorded split, with `pending` until it is frozen, is built ([The file](#the-file)); freezing it waits for the new cases.
- **One-claim Required Facts, must-state or detail.** Each fact states one claim and names its Company. A must-state fact is something any good answer covers. A detail is reported, but Fact Recall is scored on the must-state facts. The tiers are built: the loader and the generation harness handle them ([Tiers](#fields)). A fact that bundles two claims ("up 62% from a year earlier and 22% sequentially") becomes two. Every fact keeps a verbatim evidence quote, checked by the tests as before.
- **Drafted from whole Sections.** Candidate facts are drafted in Claude Code from the whole of each relevant Section, not from what retrieval returns. The developer should review every drafted fact, but because this is a quick-turn demo, it is acceptable not to, and the developer chose not to (decided 2026-10-17, recorded on #43). The mechanical checks (every evidence quote verbatim in the Corpus, every figure in the SEC company-facts reference, and the duplicate-question check) and the implementer's read-back stand in for the review. A question's every half gets facts: the pharmaceutical question's "how are they addressing them" and the NVIDIA question's "growth outlook changed" have almost none in version 1.
