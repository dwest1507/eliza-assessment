# SEC Filings RAG

A question-answering system for a private equity client that answers natural-language business questions grounded in a corpus of SEC EDGAR filings.

## Language

### Engagement

**Client**:
The fictitious private equity firm the system is built for, played by the interview panel.
_Avoid_: Customer, user, company

**Answer Call**:
The single LLM request that produces the final answer to a business question. Everything before it (indexing, retrieval) is preparation, not an Answer Call.
_Avoid_: LLM call (unqualified), API call

### Filings

**Company**:
A public company that files with the SEC, identified by its ticker and CIK.
_Avoid_: Issuer, registrant, firm

**Sector**:
The industry group a Company belongs to, taken from a curated GICS-style reference table, since Filings do not carry one.
_Avoid_: Industry (unqualified), vertical

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
The company's own fiscal year and quarter for a Filing (e.g. NVIDIA "Q2 FY2026"), derived from the Report Period and the company's fiscal year end. A secondary label only.
_Avoid_: Quarter (unqualified)
