# Golden Set

The Golden Set is the evaluation's ground truth: 30 labelled questions that the retrieval and generation harnesses score the system against. It lives in [`data/eval/golden_set.json`](../data/eval/golden_set.json) and is read by `edgar_rag.golden_set.load_golden_set()`, which checks the schema. It was written before any retrieval Arm or prompt ran, so no label was written with results in view.

This page describes version 1, the set every result so far was measured on, the Required Fact tiers that version 2 adds, and the [Brief Suite](#the-brief-suite), the brief's questions in a file of their own. Version 2's [file](#the-file) is built and holds all 27 of version 1's cases other than the brief's, [rewritten](#the-rewritten-version-1-cases), and all six slices of its 53 [new cases](#the-new-cases); freezing the split is decided but not built yet: see [Version 2](#version-2). Version 1's file stays unchanged as a record, and a test pins its digest.

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
| `tags` | Free labels for case features: `brief_example`, `inherits_companies`, `switches_company`, `topic_change_without_company`, and `periods_differ_comparison` on a comparison asked to test the periods differ gap ([the fifth and sixth slices](#the-new-cases)) |
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

Decided on 2026-10-17 ([ADR 0012](adr/0012-golden-set-version-2-and-the-brief-suite.md)). The Required Fact tiers, the Brief Suite, with the brief's three questions and four variants of each, and version 2's file, with all three batches of version 1's 27 other cases rewritten and all six slices of new cases, 80 cases in all, are built so far. The split is frozen next.

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
- **The mix by kind of question**, counted per split against ADR 0012's table below and printed with the test run, not yet enforced. A follow-up counts as one whatever it asks; a Coverage Gap case asks about a missing Company or a stale Filing, or for a trend or outlook the Filings cannot give (a `snapshot_trend` or `no_guidance` gap), or is a comparison asked to test the periods differ gap (tagged `periods_differ_comparison`); elsewhere that gap only qualifies the answer, and the rest count by question type (`risk`; `figure_trend` and `outlook` as trends; `sector`).

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

The second slice is seven risk questions on financials, industrials, energy, health care and consumer staples Companies, two of them about a single Company, and two follow-ups, all on Companies the first slice does not ask about. A test checks the slice's ids, kinds and Sectors, that it has single-Company and multi-Company questions and covers the Legal Proceedings, Market Risk and Cybersecurity Sections, and that one follow-up names no Company and the other names a new one.

| Case | Companies | Topic | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|---|---|
| `risk-v-ma-cybersecurity` | Visa, Mastercard | Cybersecurity risks and how they manage them | 10 / 26 | Risk Factors and Cybersecurity (Item 1C) of Visa's FY2025 and Mastercard's FY2025 10-Ks |
| `risk-wmt-tgt-legal-proceedings` | Walmart, Target | Legal proceedings: opioids, regulators' suits, securities class actions | 7 / 15 | Legal Proceedings of Walmart's fiscal 2025 and Target's fiscal 2024 10-Ks (years to January 31 and February 1, 2025) |
| `risk-ups-market-risk` | UPS | Fuel, foreign currency and interest rate risk and how it manages them | 6 / 12 | Market Risk of UPS's FY2025 10-K |
| `risk-cvx-xom-commodity-prices` | Chevron, ExxonMobil | Exposure to oil and gas prices | 6 / 20 | Risk Factors of Chevron's FY2024 and ExxonMobil's FY2025 10-Ks |
| `risk-abbv-jnj-loss-of-exclusivity` | AbbVie, Johnson & Johnson | Patent loss and generic and biosimilar competition | 7 / 16 | Risk Factors of AbbVie's FY2024 and Johnson & Johnson's FY2025 10-Ks |
| `risk-ba-commercial-production` | Boeing | Producing, certifying and delivering commercial airplanes | 6 / 14 | Risk Factors of Boeing's FY2025 10-K |
| `risk-pg-pep-input-costs` | Procter & Gamble, PepsiCo | Input costs and supply chain disruption | 7 / 14 | Risk Factors of Procter & Gamble's FY2025 and PepsiCo's FY2025 10-Ks |
| `followup-cat-de-dealers` | Caterpillar, Deere, inherited | "How much do they depend on their dealers, and what risks does that create?" after a question on their main risks | 6 / 13 | Risk Factors of Caterpillar's FY2025 and Deere's FY2025 10-Ks |
| `followup-lmt-to-rtx-market-risk` | RTX, switched from Lockheed Martin | "And what about RTX?" after a question on Lockheed Martin's market risks | 5 / 10 | Market Risk of RTX's FY2025 10-K |

- **Not a repeat.** The oil majors follow-up already asks Chevron and ExxonMobil about greenhouse gas and other regulation, the pharmaceutical questions ask AbbVie and Johnson & Johnson about regulation and pricing, the aerospace and defense question asks Boeing and RTX about U.S. government contracts, and UnitedHealth's and the brief follow-up's cybersecurity cases and Coca-Cola's, Apple's and Microsoft's market risk cases name other Companies. This slice asks those Companies about other topics: commodity prices, patents, commercial production and market risk.
- **Follow-ups.** Each scripted history ends with a fixed answer that cites Filing IDs. The dealer follow-up names no Company, so it inherits Caterpillar and Deere, and its scripted answer does not mention dealers. The RTX follow-up names a new Company and inherits the topic, market risk, and its Section, as "And what about Microsoft?" does.
- **Must-state or detail.** The must-state facts are each Company's headline risk on the question's topic and, where the question asks it, how the Company manages it: Visa's Key Controls and three lines of defense and Mastercard's layers of protection, UPS's fuel surcharges, forwards, options and swaps, Procter & Gamble's pricing actions, cost saving projects and sourcing decisions. For a comparison, they include what each side says about the theme they share: a commodities business for Chevron and ExxonMobil, a quick fall in a product's sales after a loss of exclusivity for AbbVie and Johnson & Johnson, sales through independent dealers whose inventories move them for Caterpillar and Deere. Lists of causes, regulation, board oversight, staffing, insurance and further consequences are details.
- **Coverage Gaps.** Five cases compare Companies whose latest 10-Ks end more than 20 days apart, so they expect the periods differ gap; Walmart's and Target's fiscal years end a day apart, so their case expects none.
- **No amount.** No fact states a dollar amount. The amounts in these Sections (Walmart's opioid accrual, Boeing's 777X reach-forward losses, UPS's and RTX's sensitivity results) have no SEC company-facts value, and the reference does not cache Boeing or RTX; the amounts stay in the evidence quotes. The figure check runs on the slice and finds nothing to check.
- **Fact wording.** As in the first slice, each fact states one claim in the Filing's own terms and names its Company, and none renames a period or states a cause or change the Filing does not.

The third slice is nine figure trends on Tracked Companies: revenue, net income and segment revenue, the three Financial Facts metrics, three cases each; six ask about one Company and three compare two; five name a fiscal year and four ask about "the last two years". Snapshot Companies are left to the Coverage Gap slices. A test checks the slice's ids, that every case is a figure trend whose Sources are all Tracked Companies' Filings and that expects no Snapshot trend gap, and that it covers all three metrics, both sizes and both kinds of time window.

| Case | Companies | Metric and window | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|---|---|
| `trend-goog-cloud-two-years` | Alphabet | Google Cloud segment revenue, the last two years | 2 / 3 | MD&A of the FY2024 and FY2025 10-Ks |
| `trend-dis-segments-fy2025` | Disney | Each segment's revenue, fiscal 2025 against fiscal 2024 | 3 / 8 | MD&A of the FY2025 10-K |
| `trend-tsla-energy-two-years` | Tesla | Energy generation and storage segment revenue, the last two years | 2 / 6 | MD&A of the FY2024 and FY2025 10-Ks |
| `trend-ko-revenue-two-years` | Coca-Cola | Net operating revenues, the last two years | 4 / 7 | MD&A of the FY2023 and FY2024 10-Ks and the Q3 2025 10-Q |
| `trend-amzn-net-sales-2025` | Amazon | Total net sales, 2025 against 2024 | 2 / 7 | MD&A of the FY2025 10-K |
| `trend-pfe-jnj-revenue-2024` | Pfizer, Johnson & Johnson | Revenue, 2024 against 2023 | 4 / 10 | MD&A of both FY2024 10-Ks |
| `trend-xom-net-income-2025` | ExxonMobil | Net income, 2025 against 2024 | 3 / 5 | The MD&A of the FY2025 10-K, in its Financial Section (Other) |
| `trend-aapl-msft-net-income-fy2025` | Apple, Microsoft | Net income, fiscal 2025 | 6 / 7 | MD&A of both FY2025 10-Ks and Apple's income statement (Financial Statements) |
| `trend-goog-meta-net-income-two-years` | Alphabet, Meta | Net income, the last two years | 8 / 9 | MD&A of each Company's FY2024 and FY2025 10-Ks |

- **Not a repeat.** Version 1's figure trends already ask about Meta's and JPMorgan's revenue, Apple's net sales, Tesla's net income and AWS's revenue, the Microsoft follow-up about its revenue, and the Brief Suite about NVIDIA's revenue and net income and UnitedHealth's revenue. This slice asks other Companies, or the same Companies about another metric: Amazon's total net sales in one year, where `trend-amzn-aws-two-years` asks about one segment over two years; Meta's, Apple's and Microsoft's net income, where the other cases ask about their revenue.
- **The window.** "The last two years" is anchored on each Company's latest Filing (assumption 6). For Alphabet, Tesla and Meta that is the FY2025 10-K, so the years are 2024 and 2025. Coca-Cola's latest Filing is the Q3 2025 10-Q, so its window runs from the FY2023 10-K's quarter-end to Q3 2025: the full year 2024 and the first nine months of 2025, with 2023 as the start, as in the Brief Suite's UnitedHealth variant.
- **Each figure its own fact, from the reference.** A period's figure and its change are separate facts, and every dollar amount matches the SEC company-facts reference, which the figure check confirms: Coca-Cola's, Pfizer's and Disney's Revenues, Amazon's and Johnson & Johnson's RevenueFromContractWithCustomerExcludingAssessedTax, and the NetIncomeLoss of ExxonMobil, Apple, Microsoft, Alphabet and Meta, with Apple's provision for income taxes and operating income. Every growth rate agrees with those values.
- **No amount without a reference value.** The reference has no segment values, so the facts on Google Cloud's, Disney's segments', Tesla's energy segment's, Amazon's segments' and Johnson & Johnson's segments' revenue, and on ExxonMobil's segment earnings, state the growth rate or the direction and its driver only; so do the facts on Amazon's foreign exchange effect and Apple's State Aid tax decrease. The amounts stay in the evidence quotes. Where a Filing gives no growth rate for a total (Apple's and Meta's net income), the facts give both years' figures and state no rate.
- **Must-state or detail.** The must-state facts are each period's headline figure and its change, and where the change has one main cause in the Filing, that cause: lower Upstream realizations for ExxonMobil, the lower provision for income taxes related to the State Aid Decision for Apple, and the 30% effective tax rate that includes the effects of the One Big Beautiful Bill Act for Meta's fall in 2025. When the question asks for segments (Disney), each segment's change is must-state. Other drivers, segment breakdowns of a total, the year before the window, tax rates and operating income are details.
- **Coverage Gaps.** Apple's fiscal 2025 ends in September and Microsoft's in June, so their case expects the periods differ gap. Pfizer's and Johnson & Johnson's 2024 years end two days apart, and Alphabet's and Meta's on the same day, so those cases expect none.
- **Sections.** ExxonMobil's Item 7 only refers to the MD&A in its Financial Section, which the Corpus seam names Other, so its facts cite Other, as JPMorgan's 10-K financial review does. Apple's MD&A gives no net income figure, so its net income facts cite its Financial Statements.
- **Fact wording.** As in the first two slices, each fact states one claim in the Filing's own terms and names its Company, and none renames a period or states a cause or change the Filing does not. Coca-Cola's nine-month facts keep the Filing's period ("the nine months ended September 26, 2025") rather than a calendar quarter.

The fourth slice is four outlook questions and five sector questions. Two outlook questions have their guidance in the Filings and two do not, so they expect a `no_guidance` gap. Each sector question uses a Sector phrase the Sector table resolves, is about industrials, energy or financials Companies, and has facts from several of the resolved Companies. A test checks the slice's ids, that each outlook question is about one Company and expects the no guidance gap exactly when its guidance is not in the Filing, and that each sector question's phrase is in its question, its Sources and facts are Companies the phrase resolves to, at least two of them, and the slice covers all three sectors.

| Case | Companies | Topic | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|---|---|
| `outlook-amzn-q1-2026-guidance` | Amazon | First quarter 2026 guidance, in the Filing | 2 / 8 | MD&A of the FY2025 10-K, its Guidance section included |
| `outlook-mcd-2025` | McDonald's | 2025 outlook, in the Filing | 4 / 8 | The FY2024 10-K, one Unsectioned Section, its 2025 Outlook and Long-Term Outlook |
| `outlook-intc-2026` | Intel | 2026 outlook, no guidance | 4 / 6 | The FY2025 10-K, one Unsectioned Section, every 2026 expectation in it |
| `outlook-nflx-growth` | Netflix | Revenue growth and profitability outlook, no guidance | 4 / 7 | MD&A and Risk Factors of the FY2025 10-K |
| `sector-aerospace-supply-chain` | "the aerospace and defense companies": Boeing, Lockheed Martin, RTX | Supply chain risks | 7 / 11 | Risk Factors of the three FY2025 10-Ks |
| `sector-industrials-tariffs` | "the industrial companies": Boeing, Caterpillar, Deere, Lockheed Martin, RTX, UPS | Tariffs | 11 / 13 | Risk Factors and MD&A of each latest 10-K |
| `sector-energy-operational-risks` | "the energy companies": Chevron, ExxonMobil | Operational risks and how they manage them | 8 / 11 | Risk Factors of Chevron's FY2024 and ExxonMobil's FY2025 10-Ks |
| `sector-banks-capital-liquidity` | "the major banks": Bank of America, JPMorgan | Regulatory capital and liquidity requirements | 7 / 13 | Risk Factors of Bank of America's FY2024 and JPMorgan's FY2025 10-Ks |
| `sector-financials-digital-assets` | "the financial companies": the ten Financials, seven with facts | Stablecoins and other digital assets | 8 / 13 | Risk Factors of each latest 10-K of American Express, Bank of America, BlackRock, Goldman Sachs, JPMorgan, Mastercard and Visa |

- **Not a repeat.** The Golden Set's other outlook cases ask about Tesla, Microsoft, Meta, NVIDIA and UnitedHealth; this slice asks about four other Companies. The banks' main risks, the aerospace and defense companies' dependence on government contracts, Boeing's commercial production, the oil majors' regulation and commodity prices, and Nike's, Tesla's and Amazon's tariffs are already asked; this slice asks the same Sectors about capital and liquidity, supply chains, operational hazards, tariffs and digital assets.
- **Guidance or not.** Amazon's FY2025 10-K repeats the first quarter 2026 guidance of its earnings release, and McDonald's FY2024 10-K has a 2025 Outlook section, so those two cases expect no gap; the harness checks only the gaps listed, so a system that states the no guidance gap anyway is not penalised. Intel's and Netflix's 10-Ks give no guidance, so their answers state the gap and draw the outlook from commentary and risk factors, which the facts cover.
- **Coverage Gaps.** Deere's fiscal 2025 ends on November 2, Chevron's latest 10-K is FY2024, and Bank of America's is FY2024, so the tariff, energy and banks cases expect the periods differ gap. "The financial companies" resolves to all ten Financials, GE among them, so that case expects GE's stale Filing gap as well as the periods differ gap; Berkshire Hathaway, GE Capital and Morgan Stanley name no digital asset risk, so they have no facts. The aerospace and defense companies all have FY2025 10-Ks, so that case expects none.
- **Every half of a question has facts.** The energy question asks how the Companies manage their operational risks: Chevron's system of corporate policies, standards and compliance mechanisms and its self-insurance, and ExxonMobil's management systems, safety focus and enterprise risk management system are must-state. For tariffs, Lockheed Martin and RTX expect no material adverse effect, so that view and how they mitigate tariffs are their must-state facts.
- **Must-state or detail.** The must-state facts are each Company's headline statement on the question's topic: for an outlook, what it expects (a growth range, an operating margin range, supply constraints, lower expenses, continued content investment, the timing of a pending acquisition); for a sector question, what each Company says the topic does to it. Further expectations, drivers, ratios, laws, proposals and knock-on effects are details.
- **No amount.** No fact states a dollar amount. The guided and forecast amounts (Amazon's net sales and operating income ranges, McDonald's capital expenditures, Caterpillar's expected tariff costs) have no SEC company-facts value, and every Company in the slice but Amazon is a Snapshot Company the reference does not cache. Where a range is the answer, the must-state fact says the Filing gives it, as `outlook-meta-capex-2026` does; the amounts stay in the evidence quotes.
- **Sections.** The Corpus finds no Item headings in McDonald's and Intel's 10-Ks, so each is one Unsectioned Section and their facts cite it. Deere's MD&A sits in Other; its Risk Factors carry the same tariff passages, which its facts cite.
- **Names.** The Sector table writes "McDonalds Corporation"; the facts write "McDonald's", and the label test that a fact names its Company ignores apostrophes.
- **Fact wording.** As in the earlier slices, each fact states one claim in the Filing's own terms and names its Company, and none renames a period or states a cause or change the Filing does not: Intel's facts keep "Q1 2026" and Deere's "fiscal year 2025".

The fifth slice is eight sector questions and one Coverage Gap case. Each sector question uses a Sector phrase the Sector table resolves, is about health care, information technology, consumer or communication services Companies, and has facts from several of the resolved Companies. A test checks the slice's ids, that each sector question's phrase is in its question, that its Sources and facts are Companies the phrase resolves to, at least two of them, and that the slice covers all five of those sectors (Health Care, Information Technology, Consumer Discretionary, Consumer Staples, Communication Services). Another checks that the Coverage Gap case compares Companies whose latest 10-Ks end more than 20 days apart, expects the periods differ gap and no other, and counts as a Coverage Gap case in the mix.

| Case | Companies | Topic | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|---|---|
| `sector-semiconductors-customer-concentration` | "the semiconductor companies": AMD, Intel, NVIDIA | Dependence on a few large customers | 5 / 14 | Risk Factors and Financial Statements of AMD's FY2025 10-K, Intel's FY2025 10-K (one Unsectioned Section), Risk Factors and MD&A of NVIDIA's FY2025 10-K and the MD&A of its Q3 FY2026 10-Q |
| `sector-software-cybersecurity` | "the software companies": Adobe, Microsoft, Oracle, Salesforce | Cybersecurity risks | 8 / 16 | Risk Factors of each latest 10-K and of Microsoft's Q2 FY2026 10-Q, which restates them |
| `sector-pharma-research-and-development` | "the pharmaceutical companies": AbbVie, Johnson & Johnson, Eli Lilly, Merck, Pfizer | Research and development of new drugs | 9 / 15 | Risk Factors of each latest 10-K |
| `sector-health-care-liability-claims` | "the health care companies": the seven Health Care Companies | Product liability and malpractice claims and how they are insured | 13 / 16 | Risk Factors of each latest 10-K |
| `sector-consumer-staples-key-customers` | "consumer staples": the six, three with facts (Coca-Cola, PepsiCo, Procter & Gamble) | Dependence on their largest customers | 6 / 11 | Risk Factors of each latest 10-K, and PepsiCo's and Procter & Gamble's Business Sections and PepsiCo's MD&A |
| `sector-consumer-discretionary-climate` | "consumer discretionary": Amazon, Home Depot, McDonald's, Nike, Starbucks, Tesla | Climate change and extreme weather | 9 / 16 | Risk Factors of each latest 10-K, and McDonald's FY2024 10-K (one Unsectioned Section) |
| `sector-retailers-workforce` | "the retailers": Amazon, Costco, Home Depot, Target, Walmart | Labor and workforce risks | 10 / 13 | Risk Factors of each latest 10-K |
| `sector-communication-services-advertising` | "communication services": the seven, five with facts (Comcast, Walt Disney, Alphabet, Meta, Netflix) | Dependence on advertising and its risks | 9 / 10 | Risk Factors of each latest 10-K |
| `gap-aapl-nvda-research-spending-periods-differ` | Apple, NVIDIA | Research and development spending growth in their latest fiscal years, which differ | 4 / 7 | MD&A of Apple's FY2025 and NVIDIA's FY2025 10-Ks |

- **Not a repeat.** The pharmaceutical and health care questions already asked are about regulation and patent loss, the software companies' about AI, the cybersecurity cases about UnitedHealth, Visa and Mastercard, and the brief's three Companies, and the semiconductor, consumer and communication services cases about competition, supply chains, export controls, tariffs, consumer demand, input costs, legal proceedings, streaming and regulation. This slice asks about customer concentration, cybersecurity at the software companies, research and development, liability claims, climate and weather, the workforce and advertising, none of which is asked of these Companies. No case asks about research and development spending.
- **The Coverage Gap case.** Version 1 never asked a comparison whose point is the periods differ gap. Apple's latest fiscal year ended on September 27, 2025 and NVIDIA's on January 26, 2025, so the answer must compare them and say the periods differ. It is a figure trend tagged `periods_differ_comparison`, and the mix counts it as a Coverage Gap case; in the many other comparisons that expect the gap, it only qualifies the answer. The last slice adds another.
- **Companies without facts.** A Sector phrase resolves to every Company in its sector, but only those whose Sections speak to the question have facts and Sources. Costco, Target and Walmart sell to consumers and name no dependence on a customer; AT&T's and Verizon's Risk Factors mention advertising only as marketing or as privacy rules on targeted ads. The periods differ gap still names every resolved Company, as the system computes it.
- **Every half of a question has facts.** The liability question asks how the Companies insure: AbbVie's and Merck's self-insurance, Johnson & Johnson's lack of third-party insurance, Eli Lilly's predominant self-insurance, Thermo Fisher's insurance and UnitedHealth's large self-insurance are must-state beside each Company's claims. Pfizer's Risk Factors name no insurance for them, so its facts are the claims only. The advertising question asks how dependent each Company is and what risks follow, and both are must-state.
- **Must-state or detail.** The must-state facts are each Company's headline statement on the question's topic and, where the Filing gives one, the figure that measures it: Intel's three largest customers' 43% of 2025 net revenue, NVIDIA's four direct customers above 10% of revenue in the third quarter of fiscal 2026, PepsiCo's and Procter & Gamble's Walmart shares (about 14% and 16%), Procter & Gamble's top ten customers' 43%, Alphabet's more than 70% of revenues from online advertising. Earlier years, each customer's share, causes, examples, laws, insurance sufficiency and further consequences are details.
- **Figures from the reference.** The Coverage Gap case's amounts match the SEC company-facts reference, which the figure check confirms (ResearchAndDevelopmentExpense: Apple's $34,550 million for FY2025 and $31,370 million for FY2024, NVIDIA's $12,914 million for FY2025 and $8,675 million for FY2024), with both growth rates agreeing with them (10% and 49%). The sector questions' facts state no dollar amount; their percentages are not checked against the reference.
- **Sources.** NVIDIA's latest customer concentration figures are in its Q3 FY2026 10-Q's MD&A, and Microsoft's Q2 FY2026 10-Q restates its cybersecurity risk factors, so both are Sources. AMD's statement that no customer reached 10% of its revenue is in its Financial Statements, and PepsiCo's and Procter & Gamble's Walmart shares in their Business Sections. Intel's and McDonald's 10-Ks are each one Unsectioned Section, which their facts cite.
- **Fact wording.** As in the earlier slices, each fact states one claim in the Filing's own terms and names its Company, and none renames a period or states a cause or change the Filing does not: NVIDIA's facts keep "the third quarter of fiscal year 2026", and Apple's "fiscal 2025". Eli Lilly is named in full, as the label test that a fact names its Company requires.

The sixth and last slice is five Coverage Gap cases and three follow-ups, completing the 53 new cases: version 2 now holds 80. The Coverage Gap cases are one of each kind the slice was asked for: a trend asked of a Snapshot Company, a missing Company version 1 does not ask about, the stale Filing, a comparison asked to test the periods differ gap, and a covered Company asked about beside a missing one. The follow-ups are one that changes topic without naming a Company, one that switches to a Sector phrase and one that asks how something changed over time. A test checks each Coverage Gap case's kind, gaps and Sources (the Snapshot Company's Filings are a Snapshot Company's; the missing Company is on the curated list and not one version 1 names; the stale case cites only GE Capital's FY2014 10-K; the periods differ comparison's latest 10-Ks end more than 20 days apart; the mixed case has facts on its covered Company only), that each counts as a Coverage Gap case in the mix, and each follow-up's kind. Another checks that version 2 holds the 53 new cases and 80 in all.

| Case | Companies | Topic | Required Facts (must-state / detail) | Sections drafted from |
|---|---|---|---|---|
| `gap-cat-sales-snapshot` | Caterpillar, a Snapshot Company | Sales and revenues over the last two years: the Snapshot trend gap | 2 / 6 | MD&A of the FY2025 10-K, its only Filing |
| `missing-broadcom-revenue` | Broadcom, missing | Revenue growth over the last two years: the missing Company gap | 0 / 0 | None: the case expects only the missing Company Coverage Gap |
| `stale-gecc-main-risks` | GE Capital | Its main risks, asked in the present tense: the stale Filing gap | 6 / 10 | Risk Factors of GE Capital's FY2014 10-K |
| `gap-msft-goog-capex-periods-differ` | Microsoft, Alphabet | Capital expenditure growth in their latest fiscal years, which differ: the periods differ gap | 4 / 6 | MD&A of both FY2025 10-Ks and Microsoft's cash flow statement (Financial Statements) |
| `missing-kroger-with-walmart` | Walmart, and Kroger, missing | Competition | 3 / 8 | Risk Factors and the Business Section's competition passage of Walmart's fiscal 2025 10-K |
| `followup-topic-change-stock-splits` | The whole Corpus: NVIDIA, Walmart, Netflix | "Which companies carried out a stock split in 2024 or 2025?" after a question on Coca-Cola's risk factors | 3 / 5 | NVIDIA's FY2025 10-K (Item 5 and its notes, Other), Walmart's fiscal 2025 10-K (Financial Statements), Netflix's FY2025 10-K (Item 5 and its notes, Other) |
| `followup-cmcsa-to-telecom-competition` | "the telecom companies": AT&T, Verizon, switched from Comcast | "And the telecom companies?" after a question on Comcast's competition | 7 / 10 | Risk Factors of AT&T's and Verizon's FY2025 10-Ks |
| `followup-aapl-buybacks-change` | Apple, inherited | "How has that changed over the past two years?" after a question on its fiscal 2025 share repurchases | 3 / 4 | MD&A of every Apple Filing in the window, from the Q2 FY2024 10-Q to the Q1 FY2026 10-Q |

- **Not a repeat.** Version 1's Coverage Gap cases ask about JPMorgan's revenue and Bank of America's risk factors as Snapshot trends, Wells Fargo, Citigroup, Bristol Myers Squibb and Honeywell as missing Companies, and General Electric's recent performance and GE Capital's 2014 balance sheet reduction as the stale Filing; the fifth slice compares Apple's and NVIDIA's research and development. This slice asks about another Snapshot Company, another missing Company, GE Capital's risks, capital expenditures, and Walmart's competition, none of which is asked. The follow-ups ask about stock splits, competition at the telecom companies and Apple's share repurchases, also new.
- **The Coverage Gap cases.** Caterpillar's only Filing is its FY2025 10-K, which compares 2025 with 2024 and refers 2024 against 2023 to an annual report the Corpus does not hold, so the answer states the Snapshot trend gap and gives the one comparison it has. Broadcom is a well-known Company whose revenue growth tempts an answer from general knowledge, so the case expects only the gap and no facts. The GE Capital question names GE Capital, so its FY2014 10-K may be cited, but it asks about the Company today, so the answer must say the Filing is GE Capital's report for 2014. Microsoft's latest fiscal year ended June 30, 2025 and Alphabet's December 31, 2025, so their comparison expects the periods differ gap, tagged `periods_differ_comparison` as the fifth slice's is. Kroger is missing and Walmart is not, so that answer covers Walmart only and names Kroger.
- **Follow-ups.** Each scripted history ends with a fixed answer that cites Filing IDs. The stock split question names no Company or Sector phrase, so it measures ADR 0003's known weakness a second time, on another topic: the rules inherit Coca-Cola, which split no stock, while the whole-Corpus answer is NVIDIA's ten-for-one split in June 2024, Walmart's 3-for-1 split in February 2024 and Netflix's ten-for-one split in November 2025. Every Filing in the Corpus was searched for a stock split; Amazon's, Tesla's and the one PepsiCo mentions fall outside the years asked. The telecom follow-up switches to a Sector phrase and inherits the topic, competition, as "And the oil majors?" does. The share repurchase follow-up names no Company and no topic, so it inherits Apple and its repurchases, and its window, the past two years, replaces the earlier fiscal 2025.
- **Must-state or detail.** The must-state facts are what any good answer gives: Caterpillar's 4 percent increase and its cause in the Filing; GE Capital's economic, credit, ratings, funding and Federal Reserve oversight risks; each Company's capital expenditures for its latest fiscal year and the year before; Walmart's strong competition, the ways it competes and its fast-changing omni-channel landscape; each Company's stock split; AT&T's and Verizon's headline competition risks; Apple's repurchases in fiscal 2024, fiscal 2025 and the latest quarter. Segments, regions, drivers, plans, programs, strategies and further consequences are details.
- **Figures from the reference.** The capital expenditure and share repurchase amounts match the SEC company-facts reference, which the figure check confirms: Microsoft's and Alphabet's PaymentsToAcquirePropertyPlantAndEquipment ($64,551 and $44,477 million for Microsoft's FY2025 and FY2024, $91,447 and $52,535 million for Alphabet's 2025 and 2024) and Apple's StockRepurchasedAndRetiredDuringPeriodValue ($95,000 million for FY2024, $89,300 million for FY2025, $23,300 million for Q1 FY2025 and $25,000 million for Q1 FY2026). Neither the capital expenditure nor the repurchase Filings give a change rate, so the facts give each period's figure and state none, as in the third slice.
- **No amount without a reference value.** The reference does not cache Caterpillar, GE Capital, Walmart, AT&T, Verizon or Netflix, and has no value for Microsoft's $20.1 billion increase, Apple's program sizes or its other quarters' repurchases. Those facts state no amount, the amounts stay in the evidence quotes, and the quarters without a value have no facts.
- **Sections.** Microsoft's MD&A gives the change in its capital expenditures but not the totals, so its total facts cite the cash flow statement in its Financial Statements. NVIDIA's and Netflix's stock split passages sit in Item 5 and in notes that follow Item 15, which the Corpus seam names Other.
- **Fact wording.** As in the earlier slices, each fact states one claim in the Filing's own terms and names its Company, and none renames a period or states a cause or change the Filing does not: Apple's facts keep its fiscal years and quarters, and Caterpillar's change is the Filing's own 4 percent.

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
- **A split recorded per case.** The 33 new dev cases and 20 holdout cases are drafted together, and the 20 whose ids have the lowest SHA-256 digests are the holdout. Every case records its split, and no case moves when another is added. This replaces the ranking rule above, under which adding a case could move another. The recorded split, with `pending` until it is frozen, is built ([The file](#the-file)); all 53 new cases now exist, and freezing it is next.
- **One-claim Required Facts, must-state or detail.** Each fact states one claim and names its Company. A must-state fact is something any good answer covers. A detail is reported, but Fact Recall is scored on the must-state facts. The tiers are built: the loader and the generation harness handle them ([Tiers](#fields)). A fact that bundles two claims ("up 62% from a year earlier and 22% sequentially") becomes two. Every fact keeps a verbatim evidence quote, checked by the tests as before.
- **Drafted from whole Sections.** Candidate facts are drafted in Claude Code from the whole of each relevant Section, not from what retrieval returns. The developer should review every drafted fact, but because this is a quick-turn demo, it is acceptable not to, and the developer chose not to (decided 2026-10-17, recorded on #43). The mechanical checks (every evidence quote verbatim in the Corpus, every figure in the SEC company-facts reference, and the duplicate-question check) and the implementer's read-back stand in for the review. A question's every half gets facts: the pharmaceutical question's "how are they addressing them" and the NVIDIA question's "growth outlook changed" have almost none in version 1.
