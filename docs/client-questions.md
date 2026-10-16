# Client Questions

Open questions for the Client, collected while building the system. Each one carries the assumption we work under until the Client answers. This list becomes the email sent once the EDA is done.

Status: `open` (not yet sent), `sent`, `answered`.

## 1. What counts as the "single LLM API call"?

- **Question:** The brief says the final answer must come from one LLM API call, while indexing and retrieval can run beforehand. Does a locally hosted model count as an LLM call? Are embedding models and cross-encoder rerankers acceptable inside retrieval? Could a small model be used at query time to parse the question (e.g. pull out tickers or periods, or generate SQL)?
- **Why it matters:** It decides whether query understanding and structured lookups (text-to-SQL) are available, or whether retrieval must be fully deterministic.
- **Our assumption:** Strict reading. Exactly one generative LLM call per question, hosted or local. Embeddings and rerankers are allowed because they score text and don't generate it. Query parsing before the Answer Call is rule-based.
- **Status:** open

## 2. May we use data outside the provided Corpus?

- **Question:** May answers draw on outside sources such as SEC EDGAR structured XBRL financial data or a sector classification source? Or must everything come only from the provided Corpus?
- **Why it matters:** Clean structured financials would make numeric questions (e.g. revenue trends) far more reliable than reading flattened tables.
- **Our assumption:** Answers are grounded only in the Corpus. Outside reference data is limited to static metadata we curate and disclose (the Sector table). The SEC XBRL company-facts API is used only as an evaluation reference, to measure how accurate our Financial Fact extraction is, and never as an answer source.
- **Status:** open

## 3. What does "2023–2025" mean?

- **Question:** The brief describes filings "spanning 2023–2025". The Corpus also contains Filings with Report Periods in 2022, FY2025 10-Ks filed in early 2026, and a GE 10-K filed in 2015 (its source URL suggests it may be GE Capital's FY2014 report). Should these be kept, dropped, or treated differently?
- **Why it matters:** It decides what "the last two years" and "latest" resolve to, and whether a ten-year-old Filing can show up in answers.
- **Our assumption:** Keep every Filing and show the Report Period in every citation. Flag the GE Filing as stale and leave it out of any "current state" answer.
- **Status:** open (to be confirmed by the EDA)

## 4. What kinds of questions should the system be built for, given the uneven coverage?

- **Question:** 15 Companies have quarterly coverage. Most of the other 39 have a single 10-K. Should we expect demo questions mostly about trends for the deep-coverage Companies, or about cross-Company comparisons across all 54?
- **Why it matters:** It decides where retrieval and prompt effort go, and how the system should answer when the data can't support a trend.
- **Our assumption:** Both kinds will be asked. The system says plainly when coverage limits an answer (e.g. "only one annual report is available for JPMorgan before 2025").
- **Status:** open

## 5. Is a curated Sector mapping acceptable?

- **Question:** No Filing carries a sector, but questions like "the major pharmaceutical companies" need one. Is it acceptable for us to curate a GICS-style Company-to-Sector table and disclose it?
- **Why it matters:** Without it, sector-scoped questions rely on retrieval guessing which Companies are relevant.
- **Our assumption:** Yes. The table is committed, its source is stated, and it is cross-checked against SEC SIC codes.
- **Status:** open
