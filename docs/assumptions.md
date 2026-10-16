# Assumptions

The assumptions we build under where the brief and the Corpus leave a choice open. Each one names the evidence behind it and why it matters. Three of them (1, 2 and 3) are put to the Client as questions in an email the developer sends; the rest are documented here and covered in the presentation instead of asked.

The numbers match the "Client question" numbers cited in the EDA notebook.

Status:

- `not confirmed`: our working assumption; the Client has not confirmed it.
- `confirmed`: the Client has confirmed it. If the Client answers differently, rewrite the assumption to match their answer, note what changed, and mark it `confirmed`.

| # | Assumption | Asked in email | Status |
|---|---|---|---|
| 1 | One generative LLM call per question; retrieval uses no LLM | Question 1 | not confirmed |
| 2 | Answers use only the provided Filings; no gap-filling from EDGAR | Question 2 | not confirmed |
| 3 | Every Filing is kept, whatever its date; GE Capital's is flagged | Question 3 | not confirmed |
| 4 | Both trend and cross-Company questions will be asked | No | not confirmed |
| 5 | A curated, disclosed Sector table is acceptable | No | not confirmed |
| 6 | "Latest" and "the last two years" are measured from each Company's latest Filing | No | not confirmed |
| 7 | Outlook questions are answered from commentary, without guidance | No | not confirmed |
| 8 | Answers are written for a PE analyst, in a fixed structure | No | not confirmed |
| 9 | Companies missing from the Corpus are named as missing, never answered | No | not confirmed |
| 10 | A mainstream hosted LLM API is acceptable for the demo | No | not confirmed |
| 11 | Questions are asked in a chat, and follow-ups build on earlier ones | No | not confirmed |

## 1. One generative LLM call per question

- **Assumption:** The brief says the final answer must be produced in one API request, while indexing and retrieval can run beforehand. We read it strictly: exactly one generative LLM call per question (the Answer Call), hosted or local. Embedding models and cross-encoder rerankers are allowed inside retrieval because they score text and don't generate it. Query parsing (Companies, periods, sector phrases) is rule-based, so there is no LLM call to generate SQL or extract entities.
- **Why it matters:** It decides whether query understanding and structured lookups (text-to-SQL over the Financial Facts store) can use an LLM, or whether retrieval must be fully deterministic.
- **Asked in email:** Question 1. We asked whether an earlier LLM call that only builds a SQL query, never answer text, counts as part of retrieval.
- **Status:** not confirmed

## 2. Answers use only the provided Filings

- **Assumption:** Answers are grounded only in the Corpus. We do not add public SEC EDGAR filings to fill coverage gaps, and we use no other outside source as an answer source. The only outside data that can affect an answer is static metadata we curate and disclose (the Sector table, assumption 5). The SEC XBRL company-facts API is used only as an evaluation reference, to measure how accurate our Financial Fact extraction is. Answers state plainly where data is missing.
- **Evidence:** The gaps are public on SEC EDGAR: annual reports filed after the Corpus was assembled (e.g. Pfizer's and AbbVie's FY2025 10-Ks, NVIDIA's FY2026 10-K), earlier Filings for the thinly covered Companies (including JPMorgan), General Electric's own recent reports, and Companies not in the Corpus at all (assumption 9).
- **Why it matters:** Filling the gaps would make trend and "latest" questions answerable for more Companies, and clean structured financials would make numeric questions more reliable. Both take work and change what the system can claim to be grounded in.
- **If the Client says yes:** Added Filings are kept as a clearly labelled supplement, separate from the Corpus, that can be switched off for the demo.
- **Asked in email:** Question 2.
- **Status:** not confirmed

## 3. Every Filing is kept, whatever its date

- **Assumption:** The brief describes the Filings as "spanning 2023–2025". We keep every Filing and show its Report Period in every citation. The GE Filing is treated as GE Capital's, flagged as stale whenever it is used, and left out of any answer about General Electric today.
- **Evidence:** By Report Period (the end of the period a Filing covers), 48 Filings fall outside 2023–2025, and 27 more were filed in 2026.
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
- **Why it matters:** It decides whether a ten-year-old Filing from a different legal entity can show up in answers about General Electric, and which Filings are available to trend and "latest" questions.
- **Asked in email:** Question 3.
- **Status:** not confirmed

## 4. Both trend and cross-Company questions will be asked

- **Assumption:** Demo questions include both trends for the well-covered Companies and point-in-time comparisons across all 54. Every Filing is labelled with its Company's coverage class, and the system says plainly when coverage limits an answer (e.g. "only one year of Filings is available for JPMorgan, all from 2025").
- **Evidence:** Only 13 of the 54 Companies have at least two years of consecutive quarterly Filings, enough for a trend question such as "over the last two years".
  - **Tracked (13):** AAPL, AMZN, DIS, GOOG, JNJ, KO, MSFT, NVDA, PFE, TSLA, UNH, XOM (14–17 consecutive quarters from 2022 to 2025), and META (exactly 8 quarters, 2024Q1–2025Q4).
  - **Snapshot (41):** BAC and JPM have one year of quarters (BAC 2024Q4–2025Q3, JPM 2025Q1–2025Q4). MCD and PEP have two Filings years apart. The other 37 have a single 10-K.
  - No bank or other Financials Company is Tracked, so "JPMorgan" in the brief's first example question can only be answered from 2025 Filings.
- **Why it matters:** It decides where retrieval and prompt effort go, and how the system answers when the data can't support a trend.
- **Asked in email:** No.
- **Status:** not confirmed

## 5. A curated Sector table is acceptable

- **Assumption:** No Filing carries a sector, but questions like "the major pharmaceutical companies" need one. We curate a GICS-style Company-to-Sector table (`data/reference/sectors.csv`), state its source, cross-check it against SEC SIC codes, and disclose it. Sector phrases resolve only through it.
  - The table maps the 54 Companies to 8 sectors: Information Technology (10), Financials (10), Health Care (7), Communication Services (7), Consumer Discretionary (6), Consumer Staples (6), Industrials (6), Energy (2).
  - SEC SIC codes disagree with the GICS-style label for 14 Companies, each explained in the table. The ones that change answers: UnitedHealth is a health insurer by SIC but Health Care here; Thermo Fisher is an instrument maker by SIC but Health Care (Life Sciences Tools) here; Alphabet, Meta, Disney and Netflix are Communication Services here; Visa and Mastercard are Financials; Walmart, Costco and Target are Consumer Staples.
  - "The major pharmaceutical companies" is **JNJ, LLY, MRK, PFE and ABBV** (all SIC 2834; GICS puts AbbVie in Biotechnology). UnitedHealth and Thermo Fisher are excluded. Only JNJ and PFE have more than one Filing.
  - The GE Filing is GE Capital's FY2014 report (assumption 3), so it is classed as Financials rather than as General Electric's Industrials.
  - Other sector phrases resolve the same way, on the industry column. "The major banks" is **Bank of America and JPMorgan** (Banks); Goldman Sachs and Morgan Stanley are Capital Markets and are left out. "The oil majors" is **Chevron and ExxonMobil**.
- **Why it matters:** Without it, sector-scoped questions rely on retrieval guessing which Companies are relevant, and a disputed mapping changes which Companies an answer covers.
- **Asked in email:** No.
- **Status:** not confirmed

## 6. "Latest" and "the last two years" are measured from each Company's latest Filing

- **Assumption:** Time phrases are anchored on each Company's latest Filing in the Corpus, not on today's date. "The last two years" is the eight quarter-ends up to that Filing, and "latest" is the latest 10-K plus any 10-Qs after it. A question with no time phrase searches every Filing, except a risk question, which gets "latest" (finding 16). Every answer states each Company's Report Period and Fiscal Period, and says when the periods it compares differ.
- **Evidence:** The Corpus stops at Filings made by 19 February 2026, and not every Company's latest annual report covers the same year.
  - Anchored on each Company's latest Filing, every one of the 13 Tracked Companies has eight quarterly Filings in "the last two years". For NVIDIA that is Q4 FY2024 to Q3 FY2026 (Report Periods 28 January 2024 to 26 October 2025). Anchored on today, each has only four or five.
  - "Latest" differs by Company: 12 December year-end Companies, including AbbVie, Merck, Pfizer, Bank of America and Chevron, have no FY2025 10-K in the Corpus, so their latest annual report is FY2024 while J&J's, Lilly's and JPMorgan's is FY2025. NVIDIA's FY2026 10-K is not in the Corpus either.
- **Why it matters:** It decides which Filings a trend or comparison answer uses, and whether a comparison across Companies mixes years.
- **Asked in email:** No.
- **Status:** not confirmed

## 7. Outlook questions are answered without guidance

- **Assumption:** Outlook questions are answered from the Filings' MD&A commentary and risk factors, and the answer says plainly that the Company's own guidance is not in the Filings provided.
- **Evidence:** The brief's second example asks how NVIDIA's "growth outlook" has changed. NVIDIA, like most Companies, publishes its revenue outlook in earnings releases, which are not 10-K or 10-Q Filings and are not in the Corpus.
- **Why it matters:** An answer that sounds like guidance but isn't would mislead an investment discussion, and an LLM may fill the gap with remembered figures that are not grounded in the Corpus.
- **Asked in email:** No.
- **Status:** not confirmed

## 8. Answers are written for a PE analyst

- **Assumption:** The brief asks for "a well-structured answer grounded in the filing data". The reader is a PE analyst. An answer opens with a two- or three-sentence direct answer, then gives the points per Company (or a comparison table when several Companies are compared), and ends with a short coverage note listing the gaps. Every claim cites its Filing ID, Section and Report Period, and figures come from extracted Financial Facts where they exist. It runs to about 300–600 words. With no reference answers from the Client, we judge quality on our own test set, built from the example and variant questions traced in the EDA: are the right Filings retrieved, is every claim cited and supported by its source, are the figures exact, and is every gap stated.
- **Why it matters:** It sets the Answer Call's prompt template and output format, and what we measure when we evaluate quality (one of the deliverables).
- **Asked in email:** No.
- **Status:** not confirmed

## 9. Companies missing from the Corpus are named as missing

- **Assumption:** If a question names a Company that is not in the Corpus, or a sector phrase would normally include one, the system answers for the Companies the Corpus covers and says plainly which named Companies have no Filings in it, e.g. "Wells Fargo is not in the Filings provided." Sector phrases resolve only to Companies in the Sector table (assumption 5), and the answer names them. Nothing is answered from general knowledge. Missing Companies are recognised through a small curated, disclosed list of notable Companies not in the Corpus (`data/reference/missing_companies.csv`, described in `data/README.md`); a Company not on it is not recognised as missing.
- **Evidence:** The Corpus holds 54 Companies, and some well-known peers are missing: for example, Wells Fargo and Citigroup among banks, and Bristol Myers Squibb and Amgen among drug makers.
- **Why it matters:** An LLM asked about a missing Company will happily answer from what it remembers, which is not grounded in the Filings and cannot be cited.
- **Asked in email:** No.
- **Status:** not confirmed

## 10. A mainstream hosted LLM API is acceptable

- **Assumption:** For the demo, a mainstream hosted LLM API whose terms exclude training on and retaining API data is acceptable for the Answer Call and the embeddings. The provider sits behind one interface, so it can be swapped, or replaced with a locally hosted model, without changing retrieval.
- **Why it matters:** The Filings are public, but the questions a deal team asks can reveal what it is looking at. It decides which models we can choose and whether the demo depends on an outside service.
- **Asked in email:** No.
- **Status:** not confirmed

## 11. Questions are asked in a chat

- **Assumption:** The Client asks questions in a conversation, not one at a time: an analyst asks about Apple, Tesla and JPMorgan's risks, then "Which of them has the most regulatory exposure?". Each user message is a question and gets exactly one Answer Call, which sees the last 10 turns of the conversation. Earlier answers help the model understand the question but are never evidence: every claim cites a Source retrieved for the current message. A follow-up that leaves out the Companies, time window, Section or metric inherits them from earlier messages by rules ([ADR 0003](adr/0003-follow-ups-inherit-query-scope-by-rules.md)), and each answer shows the Query Scope it used.
- **Why it matters:** The brief asks for "a natural-language business question as input", which reads as one question at a time. A chat is closer to how an analyst works, but it makes follow-up handling part of retrieval and of what we evaluate.
- **Asked in email:** No.
- **Status:** not confirmed
