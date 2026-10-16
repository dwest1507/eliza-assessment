# Client Questions

Open questions for the Client, collected while building the system. Each one carries the assumption we work under until the Client answers. The list is final for the EDA: it was checked against the assessment brief, and every question has its working assumption. They are raised in one email, drafted in [`client-email.md`](client-email.md) for the developer to send; when it is sent, mark each question `sent`.

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

- **Question:** The brief describes filings "spanning 2023–2025", but by Report Period (the end of the period a Filing covers) 48 Filings fall outside that window, and 27 more were filed in 2026. Should these be kept, dropped, or treated differently?
  - **GE (1 Filing):** the only GE Filing is not a General Electric Company report. It is **GE Capital's** (General Electric Capital Corporation's) 10-K for the fiscal year ended 31 December 2014, filed on 27 February 2015.
  - **2022 (47 Filings from 12 Companies):**
    - AAPL: 10-Q 2022-03-26, 10-Q 2022-06-25, 10-K 2022-09-24, 10-Q 2022-12-31
    - AMZN: 10-Q 2022-03-31, 10-Q 2022-06-30, 10-Q 2022-09-30, 10-K 2022-12-31
    - DIS: 10-Q 2022-01-01, 10-Q 2022-04-02, 10-Q 2022-07-02, 10-K 2022-10-01, 10-Q 2022-12-31
    - GOOG: 10-Q 2022-09-30, 10-K 2022-12-31
    - JNJ: 10-K 2022-01-02 (FY2021), 10-Q 2022-04-03, 10-Q 2022-07-03, 10-Q 2022-10-02
    - KO: 10-Q 2022-04-01, 10-Q 2022-07-01, 10-Q 2022-09-30, 10-K 2022-12-31
    - MSFT: 10-Q 2022-03-31, 10-K 2022-06-30, 10-Q 2022-09-30, 10-Q 2022-12-31
    - NVDA: 10-K 2022-01-30 (FY2022), 10-Q 2022-05-01, 10-Q 2022-07-31, 10-Q 2022-10-30
    - PFE: 10-Q 2022-04-03, 10-Q 2022-07-03, 10-Q 2022-10-02, 10-K 2022-12-31
    - TSLA: 10-Q 2022-03-31, 10-Q 2022-06-30, 10-Q 2022-09-30, 10-K 2022-12-31
    - UNH: 10-Q 2022-03-31, 10-Q 2022-06-30, 10-Q 2022-09-30, 10-K 2022-12-31
    - XOM: 10-Q 2022-03-31, 10-Q 2022-06-30, 10-Q 2022-09-30, 10-K 2022-12-31
  - **Filed in 2026 (27 Filings, inside the window by Report Period):** 24 FY2025 10-Ks and 3 10-Qs for quarters ending in December 2025 (AAPL, DIS, MSFT).
- **Why it matters:** It decides what "the last two years" and "latest" resolve to, and whether a ten-year-old Filing from a different legal entity can show up in answers about General Electric.
- **Our assumption:** Keep every Filing and show the Report Period in every citation. Treat the GE Filing as GE Capital's, flag it as stale, and leave it out of any "current state" answer.
- **Status:** open

## 4. What kinds of questions should the system be built for, given the uneven coverage?

- **Question:** Only 13 of the 54 Companies have at least two years of consecutive quarterly Filings, enough for a trend question such as "over the last two years". Should we expect demo questions mostly about trends for these Companies, or about cross-Company comparisons across all 54?
  - **Tracked (13):** AAPL, AMZN, DIS, GOOG, JNJ, KO, MSFT, NVDA, PFE, TSLA, UNH, XOM (14–17 consecutive quarters from 2022 to 2025), and META (exactly 8 quarters, 2024Q1–2025Q4).
  - **Snapshot (41):** BAC and JPM have one year of quarters (BAC 2024Q4–2025Q3, JPM 2025Q1–2025Q4). MCD and PEP have two Filings years apart. The other 37 have a single 10-K.
  - No bank or other Financials Company is Tracked, so "JPMorgan" in your first example question can only be answered from 2025 Filings.
- **Why it matters:** It decides where retrieval and prompt effort go, and how the system should answer when the data can't support a trend.
- **Our assumption:** Both kinds will be asked. Every Filing is labelled with its Company's class, and the system says plainly when coverage limits an answer (e.g. "only one year of Filings is available for JPMorgan, all from 2025").
- **Status:** open

## 5. Is a curated Sector mapping acceptable?

- **Question:** No Filing carries a sector, but questions like "the major pharmaceutical companies" need one. Is it acceptable for us to curate a GICS-style Company-to-Sector table and disclose it? And do you agree with the classifications below where it could be disputed?
  - The table maps the 54 Companies to 8 sectors: Information Technology (10), Financials (10), Health Care (7), Communication Services (7), Consumer Discretionary (6), Consumer Staples (6), Industrials (6), Energy (2).
  - SEC SIC codes disagree with the GICS-style label for 14 Companies, each explained in the table. The ones that change answers: UnitedHealth is a health insurer by SIC but Health Care here; Thermo Fisher is an instrument maker by SIC but Health Care (Life Sciences Tools) here; Alphabet, Meta, Disney and Netflix are Communication Services here; Visa and Mastercard are Financials; Walmart, Costco and Target are Consumer Staples.
  - We read "the major pharmaceutical companies" as **JNJ, LLY, MRK, PFE and ABBV** (all SIC 2834; GICS puts AbbVie in Biotechnology). UnitedHealth and Thermo Fisher are excluded. Only JNJ and PFE have more than one Filing.
  - The GE Filing is GE Capital's FY2014 report (see question 3), so we class it as Financials rather than as General Electric's Industrials.
  - Other sector phrases resolve the same way, on the industry column. "The major banks" is **Bank of America and JPMorgan** (Banks); Goldman Sachs and Morgan Stanley are Capital Markets and are left out unless you say otherwise. "The oil majors" is **Chevron and ExxonMobil**.
- **Why it matters:** Without it, sector-scoped questions rely on retrieval guessing which Companies are relevant, and a disputed mapping changes which Companies an answer covers.
- **Our assumption:** Yes. The table (`data/reference/sectors.csv`) is committed, its source is stated, and it is cross-checked against SEC SIC codes. We use the classifications above until told otherwise.
- **Status:** open

## 6. What should "latest" and "the last two years" be measured from?

- **Question:** The Corpus stops at Filings made by 19 February 2026, and not every Company's latest annual report covers the same year. Should "the last two years" and "latest" be measured from each Company's latest Filing in the Corpus, or from today's date? And does "the last two years" mean the last eight quarters or the last two fiscal years?
  - Anchored on each Company's latest Filing, every one of the 13 Tracked Companies has eight quarterly Filings in "the last two years". For NVIDIA that is Q4 FY2024 to Q3 FY2026 (Report Periods 28 January 2024 to 26 October 2025). Anchored on today, each has only four or five.
  - "Latest" differs by Company: 12 December year-end Companies, including AbbVie, Merck, Pfizer, Bank of America and Chevron, have no FY2025 10-K in the Corpus, so their latest annual report is FY2024 while J&J's, Lilly's and JPMorgan's is FY2025. NVIDIA's FY2026 10-K is not in the Corpus either.
- **Why it matters:** It decides which Filings a trend or comparison answer uses, and whether a comparison across Companies mixes years.
- **Our assumption:** Measure from each Company's latest Filing in the Corpus. "The last two years" is the eight quarter-ends up to it, and "latest" is the latest 10-K plus any 10-Qs after it. Every answer states each Company's Report Period and Fiscal Period, and says when the periods it compares differ.
- **Status:** open

## 7. Should outlook questions be answered without the Companies' guidance?

- **Question:** Your second example asks how NVIDIA's "growth outlook" has changed. NVIDIA, like most Companies, publishes its revenue outlook in its earnings releases, which are not 10-K or 10-Q Filings and are not in the Corpus. Is an answer built from the Filings' MD&A commentary and risk factors what you want, or should the system decline outlook questions it cannot support with guidance figures?
- **Why it matters:** An answer that sounds like guidance but isn't would mislead an investment discussion, and an LLM may fill the gap with remembered figures that are not grounded in the Corpus.
- **Our assumption:** Answer from MD&A commentary and risk factors, and say plainly that the Company's own guidance is not in the Filings provided.
- **Status:** open

## 8. What should a good answer look like, and how will you judge it?

- **Question:** The brief asks for "a well-structured answer grounded in the filing data". Who reads the answer (an analyst, a deal team, an investment committee), how long should it be, and what structure do you expect? Do you have reference answers or criteria you will judge quality against?
- **Why it matters:** It sets the Answer Call's prompt template and output format, and what we measure when we evaluate quality (one of the deliverables).
- **Our assumption:** The reader is a PE analyst. An answer opens with a two- or three-sentence direct answer, then gives the points per Company (or a comparison table when several Companies are compared), and ends with a short coverage note listing the gaps. Every claim cites its Filing ID, Section and Report Period, and figures come from extracted Financial Facts where they exist. It runs to about 300–600 words. With no reference answers from you, we judge quality on our own test set, built from the example and variant questions traced in the EDA: are the right Filings retrieved, is every claim cited and supported by its source, are the figures exact, and is every gap stated.
- **Status:** open

## 9. How should the system answer about Companies the Corpus does not cover?

- **Question:** The Corpus holds 54 Companies, and some well-known peers are missing: for example, Wells Fargo and Citigroup among banks, and Bristol Myers Squibb and Amgen among drug makers. If a demo question names a Company that is not in the Corpus, or a sector phrase would normally include one, should the system decline that part, or answer from what it has and say what is missing?
- **Why it matters:** An LLM asked about a missing Company will happily answer from what it remembers, which is not grounded in the Filings and cannot be cited.
- **Our assumption:** Answer for the Companies the Corpus covers, and say plainly which named Companies have no Filings in it, e.g. "Wells Fargo is not in the Filings provided." Sector phrases resolve only to Companies in the Sector table (question 5), and the answer names them. Nothing is answered from general knowledge.
- **Status:** open

## 10. Are there constraints on which LLM we use?

- **Question:** The Filings are public, but the questions a deal team asks can reveal what it is looking at. Is there any restriction on sending questions and retrieved text to a hosted LLM API (a particular provider, data-retention or training terms, region), or a preference for one provider or for a locally hosted model?
- **Why it matters:** It decides which models we can choose for the Answer Call and the embeddings, and whether the demo depends on an outside service.
- **Our assumption:** For the demo, a mainstream hosted API whose terms exclude training on and retaining API data is acceptable. The provider sits behind one interface, so it can be swapped, or replaced with a locally hosted model, without changing retrieval.
- **Status:** open
