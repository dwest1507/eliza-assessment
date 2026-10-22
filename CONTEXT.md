# SEC Filings RAG

A question-answering system for a private equity client that answers natural-language business questions grounded in a corpus of SEC EDGAR filings.

## Language

### Engagement

**Client**:
The fictitious private equity firm the system is built for, played by the interview panel.
_Avoid_: Customer, user, company

### Answering

**Answer Call**:
The single LLM request that produces the final answer to a business question. Everything before it (indexing, retrieval) is preparation, not an Answer Call.
_Avoid_: LLM call (unqualified), API call

**Query Scope**:
What the rules resolve from a question before retrieval: the Companies (including those a Sector phrase resolves to), the time window, any named Fiscal Period, any Section hints, any metric, and whether it asks how something changed. A follow-up inherits each part it does not name from the most recent earlier question that named it. Once retrieval has run, it also records where retrieval searched: each Filing's planned Sections, or the Filing whole.
_Avoid_: Filters, entities, intent

**Source**:
One numbered, citable item in an Answer Call's context: the retrieved text of one Section of one Filing, or the Financial Facts taken from one Filing.
_Avoid_: Reference, document, context item

**Answer Context**:
Everything one Answer Call is given to answer from: the Sources, each Company's coverage, the Financial Facts and the Coverage Gaps, prepared by retrieval from the Query Scope.
_Avoid_: Prompt context, retrieved context

**Coverage Gap**:
A part of a question the Corpus cannot answer (a trend asked of a Snapshot Company, a Company not in the Corpus, a stale Filing, guidance the Filings don't contain, or Companies whose latest periods differ). Every Coverage Gap is shown with the answer, in a fixed wording, as a Coverage note after it; the answer never fills one from general knowledge, and says in its own words only those that leave part of the question unanswered.
_Avoid_: Limitation, missing data, caveat

### Evaluation

**Golden Set**:
The labelled questions retrieval and answers are scored against, each with its expected (Filing ID, Section) pairs, Required Facts and expected Coverage Gaps, and each assigned to dev or holdout by a hash of its id, a split it keeps for good. From version 2 each case records its split, which is pending while new cases are drafted; a set with a pending case is not run. Version 2's split is frozen, with its holdout ids listed in the file, and a case added later is dev.
_Avoid_: Test set, benchmark, eval data

**Brief Suite**:
The brief's example questions and variants of them, kept outside the Golden Set's split: a must-pass check that every change which could alter an answer is run against, case by case.
_Avoid_: Demo set, smoke test, starter prompts

**Required Fact**:
One claim, naming its Company, that a good answer to a Golden Set or Brief Suite question must state, with an evidence quote from the Section that supports it. Each is either must-state (something any good answer covers) or a detail.
_Avoid_: Expected answer, key point

**Fact Recall**:
The share of a case's must-state Required Facts that an answer states, as judged by Jev: a fact is stated when Jev's probability reaches the fact cut-off, 0.6, set by the judge study (ADR 0013). The same share over its details is detail recall, reported beside Fact Recall and never decided on. An answer cut off at the Answer Call's token cap fails, with a Fact Recall of 0.
_Avoid_: Recall (unqualified), coverage

**Faithfulness**:
The share of an answer's claims that the Sources they cite support, as judged by Jev. Every sentence of the answer is a claim, except its headings, its Coverage Gap wordings (and uncited sentences that say what the Sources or Filings lack, naming them) and its lead-ins ending in a colon. An uncited sentence about a Company is a claim, however much it looks like a Coverage Gap. A claim that cites no Source is unsupported. A cited sentence stating one of the case's expected Coverage Gaps, other than "periods differ", is left to the Coverage Gap check and not judged by Jev.
_Avoid_: Groundedness, accuracy, hallucination rate

**Contradicted Claim**:
A claim whose cited Sources say something different from it: another figure, period, Company or direction of change. One fails the answer, whatever its Faithfulness.
_Avoid_: Error, hallucination

**Evidence Reached**:
Whether a Required Fact's evidence quote is in the text of an Answer Context's Sources: retrieval's measure of whether an answer could state that fact at all.
_Avoid_: Recall (unqualified), coverage

**Generation Miss**:
A must-state Required Fact whose evidence reached the Answer Context (Evidence Reached) but which the answer did not state: a fact lost by generation, not by retrieval.
_Avoid_: Answer miss, recall miss

**Retrieval Miss**:
A must-state Required Fact whose evidence did not reach the Answer Context: a planning miss (the Section plan left its Section out) or a ranking miss (its Section was searched, but the passage was not ranked into the context budget).
_Avoid_: Search miss, recall miss

**Control Run**:
The shipped choice run again beside its challengers in a comparison, so the comparison shows its own run-to-run noise. If it comes out ahead of the shipped run, the comparison is inconclusive and the shipped choice stands. The comparisons of one round (the same code, prompt and Golden Set version) share one shipped run and one Control Run.
_Avoid_: Baseline, rerun

**Arm**:
One way of ranking the chunks that become an Answer Call's Sources (FTS5, dense embeddings, a hybrid, a re-ranker), scored by the retrieval and generation harnesses on the Golden Set. Each Arm records whether it makes an API call at query time, such as a hosted embedding of the question; under the one-call rule (the Answer Call is a question's only API call) such an Arm can't ship, and is reported as available if the one-call limit is lifted.
_Avoid_: Retriever, strategy, variant

**Shipped Arm**:
The Arm the product uses, which every other Arm is compared with question by question. FTS5 unless a challenger that makes no API call at query time is shown to be better.
_Avoid_: Baseline, default retriever

### Filings

**Company**:
A public company that files with the SEC, identified by its ticker and CIK.
_Avoid_: Issuer, registrant, firm

**Sector**:
The industry group a Company belongs to, taken from a curated GICS-style reference table, since Filings do not carry one.
_Avoid_: Industry (unqualified), vertical

**Company Group**:
A curated, named set of Companies that no Sector captures (e.g. "big tech"), which a question can name in place of its Companies. Disclosed like the Sector table.
_Avoid_: Basket, peer set, Sector (for a group that cuts across Sectors)

**Filing**:
One 10-K or 10-Q document submitted to the SEC by a single company, as one file in the corpus.
_Avoid_: Document, report, file

**Filing ID**:
The stable identifier of a Filing, built from ticker, Form Type and Report Period (e.g. `KO_10-Q_2022-07-01`). Unique across the Corpus.
_Avoid_: Using Calendar Quarter or file name as a key

**Form Type**:
The kind of Filing: `10-K` (annual) or `10-Q` (quarterly).
_Avoid_: Filing type, doc type

**Corpus**:
The full set of Filings provided with the assessment, described by its manifest.
_Avoid_: Dataset, data

**Section**:
A standard, form-independent part of a Filing (e.g. Risk Factors, MD&A, Financial Statements, Market Risk, Legal Proceedings, Business). The default unit for talking about filing content. Items with no standard Section of their own map to Other. Text outside any Item (cover page, TOC, a Filing with no Item headings) is kept as an Unsectioned Section, so a Filing's Sections cover its whole body.
_Avoid_: Chapter, part

**Item**:
The form-specific label a Filing uses for a Section (e.g. 10-K "Item 7", 10-Q "Part I, Item 2", both MD&A). Kept so citations and Item-specific questions stay possible.
_Avoid_: Using Item numbers as Section names

**Tracked Company**:
A Company with quarterly Filings across multiple years, so trend questions can be answered. Concretely, its Filings cover at least eight consecutive quarter-ends (two years) by Report Period.
_Avoid_: Full-coverage company

**Snapshot Company**:
A Company with one or a few Filings, so only point-in-time questions can be answered. Any Company that is not a Tracked Company.
_Avoid_: Partial company, sparse company

**Financial Fact**:
One reported figure pulled from a Filing's tables: Company, Report Period, metric, value, unit (e.g. NVDA, 2025-07-27, revenue, value, USD). The metrics are revenue, net income (attributable to the Company) and segment revenue, which also names its segment.
_Avoid_: Metric, data point, number

### Time

**Report Period**:
The end date of the period a Filing covers. The canonical time axis for ordering and filtering Filings. Missing from some Filing headers, in which case it is derived from the date in the source URL or the cover-page "period ended" sentence; each Filing records which source its Report Period came from.
_Avoid_: Period, as-of date

**Filing Date**:
The date the Filing was submitted to the SEC. Always later than the Report Period.
_Avoid_: Date, publish date

**Calendar Quarter**:
The calendar quarter in which the Report Period ends (the `Quarter:` header field, e.g. `2024Q3`). Not the company's own fiscal quarter.
_Avoid_: Quarter (unqualified)

**Fiscal Period**:
The company's own fiscal year and quarter for a Filing (e.g. NVIDIA "Q2 FY2026"), derived from the Report Period and the company's fiscal year end. A secondary label only, always given with its calendar months where a reader sees it (NVIDIA's "Q2 FY2026 (May–Jul 2025)").
_Avoid_: Quarter (unqualified)
