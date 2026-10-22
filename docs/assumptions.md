# Assumptions

The assumptions we build under where the brief and the Corpus leave a choice open. Each one names the evidence behind it and why it matters. Three of them (1, 2 and 3) were put to the Client as questions in an email the developer sent, and the Client confirmed all three on 2026-10-16; the rest are documented here and covered in the presentation instead of asked.

The numbers match the "Client question" numbers cited in the EDA notebook.

Status:

- `not confirmed`: our working assumption; the Client has not confirmed it.
- `confirmed`: the Client has confirmed it. If the Client answers differently, rewrite the assumption to match their answer, note what changed, and mark it `confirmed`.

| # | Assumption | Asked in email | Status |
|---|---|---|---|
| 1 | One API call per question, the Answer Call; retrieval uses no LLM and only local models | Question 1 | confirmed |
| 2 | Answers use only the provided Filings; no gap-filling from EDGAR | Question 2 | confirmed |
| 3 | Every Filing is kept, whatever its date; GE Capital's is flagged | Question 3 | confirmed |
| 4 | Both trend and cross-Company questions will be asked | No | not confirmed |
| 5 | A curated, disclosed Sector table is acceptable | No | not confirmed |
| 6 | "Latest" and "the last two years" are measured from each Company's latest Filing | No | not confirmed |
| 7 | Outlook questions are answered from commentary, without guidance | No | not confirmed |
| 8 | Answers are written for a PE analyst, in a fixed structure | No | not confirmed |
| 9 | Companies missing from the Corpus are named as missing, never answered | No | not confirmed |
| 10 | A mainstream hosted LLM API is acceptable for the demo | No | not confirmed |
| 11 | Questions are asked in a chat, and follow-ups build on earlier ones | No | not confirmed |
| 12 | An illustrative value model: about $360k a year of analyst time saved | No | not confirmed |
| 13 | An illustrative running cost: about $46k a year on Azure, mostly an engineer's time | No | not confirmed |

## 1. One API call per question

- **Assumption:** The brief says the final answer must be produced in one API request, while indexing and retrieval can run beforehand. We read it strictly: a question makes exactly one API call of any kind, the Answer Call. There is no hosted embedding call and no other request at query time. Local models inside retrieval are allowed, such as a local embedding model or the local cross-encoder, because they run on the machine and make no request. Query parsing (Companies, periods, sector phrases) is rule-based, so there is no LLM call to generate SQL or extract entities.
- **Why it matters:** It decides whether query understanding and structured lookups (text-to-SQL over the Financial Facts store) can use an LLM, or whether retrieval must be fully deterministic. It also decides which retrieval Arms can ship: an Arm that embeds the question with a hosted model makes a second API call.
- **Asked in email:** Question 1. We asked whether an earlier LLM call that only builds a SQL query, never answer text, counts as part of retrieval.
- **Client's answer:** A single LLM call is a hard requirement across the entire question-answering pipeline, so there can't be one generative call for retrieval and another for writing the answer. This matches our strict reading: query parsing, text-to-SQL and follow-up rewriting stay rule-based (ADR 0001, ADR 0003), and multi-step research that needs more than one generative call is out of scope, not a future-state option.
- **The stricter reading (2026-10-17):** Until 2026-10-17 we read the rule as one *generative* call, so a hosted embedding call inside retrieval was allowed. On 2026-10-17 the developer accepted the stricter reading: one API call of any kind per question. The `dense` and `hybrid` Arms embed each question with OpenAI `text-embedding-3-small`, a second call, so they can't ship. They are still measured and shown, as an improvement available if the one-call limit is lifted. The `fts5` and `rerank` Arms and the local embedding Arms, `dense-local` and `hybrid-local`, make no API call and can ship ([ADR 0008](adr/0008-fts5-stays-the-shipped-arm.md), [Evaluation](evaluation.md#the-one-call-rule-and-the-local-arms)).
- **Status:** confirmed

## 2. Answers use only the provided Filings

- **Assumption:** Answers are grounded only in the Corpus. We do not add public SEC EDGAR filings to fill coverage gaps, and we use no other outside source as an answer source. The only outside data that can affect an answer is static metadata we curate and disclose (the Sector table, assumption 5). The SEC XBRL company-facts API is used only as an evaluation reference, to measure how accurate our Financial Fact extraction is. Answers state plainly where data is missing.
- **Evidence:** The gaps are public on SEC EDGAR: annual reports filed after the Corpus was assembled (e.g. Pfizer's and AbbVie's FY2025 10-Ks, NVIDIA's FY2026 10-K), earlier Filings for the thinly covered Companies (including JPMorgan), General Electric's own recent reports, and Companies not in the Corpus at all (assumption 9).
- **Why it matters:** Filling the gaps would make trend and "latest" questions answerable for more Companies, and clean structured financials would make numeric questions more reliable. Both take work and change what the system can claim to be grounded in.
- **Asked in email:** Question 2.
- **Client's answer:** Filling the gaps wasn't necessary for the exercise. We call the gaps out in the interview, say we saw them, and propose scraping public filings from SEC EDGAR as a next step. That proposal belongs in the presentation's future state; if it were built, added Filings would be kept as a clearly labelled supplement, separate from the Corpus.
- **Status:** confirmed

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
- **Client's answer:** Keeping the out-of-range Filings and calling them out is fine.
- **Status:** confirmed

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

- **Assumption:** No Filing carries a sector, but questions like "the major pharmaceutical companies" need one. We curate a GICS-style Company-to-Sector table (`data/reference/sectors.csv`), state its source, cross-check it against SEC SIC codes, and disclose it. Sector phrases, and the curated Company Groups it also holds ("big tech"), resolve only through it.
  - The table maps the 54 Companies to 8 sectors: Information Technology (10), Financials (10), Health Care (7), Communication Services (7), Consumer Discretionary (6), Consumer Staples (6), Industrials (6), Energy (2).
  - SEC SIC codes disagree with the GICS-style label for 14 Companies, each explained in the table. The ones that change answers: UnitedHealth is a health insurer by SIC but Health Care here; Thermo Fisher is an instrument maker by SIC but Health Care (Life Sciences Tools) here; Alphabet, Meta, Disney and Netflix are Communication Services here; Visa and Mastercard are Financials; Walmart, Costco and Target are Consumer Staples.
  - "The major pharmaceutical companies" is **JNJ, LLY, MRK, PFE and ABBV** (all SIC 2834; GICS puts AbbVie in Biotechnology). UnitedHealth and Thermo Fisher are excluded. Only JNJ and PFE have more than one Filing.
  - The GE Filing is GE Capital's FY2014 report (assumption 3), so it is classed as Financials rather than as General Electric's Industrials.
  - Other sector phrases resolve the same way, on the industry column. "The major banks" is **Bank of America and JPMorgan** (Banks); Goldman Sachs and Morgan Stanley are Capital Markets and are left out. "The oil majors" is **Chevron and ExxonMobil**.
  - The table also holds one curated **Company Group**, a named set of Companies that no Sector captures, in its `group` column, resolved the same way and disclosed with it: "big tech" (or "megacap tech") is **Apple, Microsoft, Alphabet, Amazon, Meta, NVIDIA and Tesla**, the group the phrase means in the industry, not the Information Technology Sector, which would leave out Alphabet and Meta (Communication Services) and Amazon and Tesla (Consumer Discretionary) and bring in Adobe, Cisco, IBM and the other software and chip makers. "Tech companies" alone is still the Sector. The answer says the group comes from the curated table, as it does for a Sector phrase.
- **Why it matters:** Without it, sector-scoped questions rely on retrieval guessing which Companies are relevant, and a disputed mapping changes which Companies an answer covers.
- **Asked in email:** No.
- **Status:** not confirmed

## 6. "Latest" and "the last two years" are measured from each Company's latest Filing

- **Assumption:** Time phrases are anchored on each Company's latest Filing in the Corpus, not on today's date. "The last two years" is the eight quarter-ends up to that Filing, and "latest" is the latest 10-K plus any 10-Qs after it. A question with no time phrase gets "latest" too, unless it asks how something changed: a risk, cybersecurity, dependence or outlook question (finding 16), a question naming no Company ("Which companies are most exposed to tariffs?"), and a broad question naming Companies and no topic ("Compare Coke and Pepsi"), which reads each one's latest Business, MD&A and Risk Factors (the Overview route, #145). Any other question with no time phrase about named Companies, and a change question, searches every Filing. A named time phrase, or a Fiscal Period a Filing covers, keeps its own window. Every answer states each Company's Report Period and Fiscal Period, and says when the periods it compares differ.
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

- **Assumption:** The brief asks for "a well-structured answer grounded in the filing data". The reader is a PE analyst. An answer opens with a two- or three-sentence direct answer, then gives the points per Company (or a comparison table when several Companies are compared), and the product shows every gap below it as a Coverage note, in its fixed wording; the answer says, in its own words, only where a gap leaves part of the question unanswered ([ADR 0016](adr/0016-coverage-gaps-shown-by-the-product.md)). Every claim cites its Filing ID, Section and Report Period, and figures come from extracted Financial Facts where they exist. It runs to about 300–600 words, up to 1,000 when its Sources cover more than two Companies (from prompt v19, the word range of v17). With no reference answers from the Client, we judge quality on our own test set, built from the example and variant questions traced in the EDA: are the right Filings retrieved, is every claim cited and supported by its source, are the figures exact, and is every gap that leaves part of the question unanswered acknowledged.
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

## 12. An illustrative value model

- **Assumption:** An illustrative model of what the workspace is worth to a deal team, with inputs we chose and the Client has not given us. None of them is measured. They are there so the Client can replace them with their own, and a pilot would measure them.
  - **Inputs:** 10 analysts, each asking 5 questions a week, each question saving 1 hour of reading, net of the minutes spent checking the answer's citations, at $150 an hour, over 48 working weeks a year.
  - **Formula:** analysts × questions a week × hours saved per question × hourly rate × working weeks = value a year.
  - **Result:** 10 × 5 × 1 × $150 × 48 = $360,000, **about $360k a year**: 50 questions a week, 2,400 a year, 2,400 analyst hours saved.
  - **A conservative case:** at 15 minutes saved per question, a quarter of the base case, it is **about $90k a year**.
  - **Why 1 hour:** a median 10-K in the Corpus is about 70,000 words, about 5 hours to read once, and a question comparing three Companies' risks reads about two hours of Risk Factors ([market context](market-context.md#how-long-a-filing-takes-to-read)). Experts answering narrower single questions with search tools took 16.8 minutes in one benchmark, so 2 hours would be easy to attack; 1 hour is the base case and 15 minutes the conservative one. This model used 2 hours, about $720k a year, until 2026-10-22.
  - **Against the cost:** the Answer Calls alone cost little: 50 a week at the shipped `gpt-6-luna`'s $0.0030 per answer is $0.15 a week, and even at the most expensive model compared, `claude-opus-5-5` at $0.1925 per answer, $9.63 a week, about $462 a year ([The final all-model round](evaluation.md#the-final-all-model-round-154-2026-10-21)). The fully loaded running cost, with hosting, security and an engineer's time, is assumption 13: about $46k a year expected, so the value is about 8× the cost in the base case and about 2× in the conservative one. At the high cost, $91k, the conservative case about breaks even. The analysts' time checking the cited Sources is netted out of the hours saved.
- **Why it matters:** The brief's value case rests on analyst time, which we cannot measure without the Client. A worked figure lets the Client weigh the investment, as long as it is read as illustrative: the answer is fast and cheap (measured), and the time it saves is the Client's to confirm.
- **Asked in email:** No. To agree with the Client, or to measure in a pilot: how many analysts, how many questions each asks a week, and how long one takes to answer by hand today.
- **Status:** not confirmed

## 13. An illustrative running cost

- **Assumption:** An illustrative fully loaded cost of running the workspace in production inside the firm's own Microsoft Azure tenant, for the usage of assumption 12 (about 2,400 questions a year). Azure prices are verified list prices; the engineering effort and the security test's hours are our assumptions. A pilot would set the real figures.
  - **Totals, a year:** low $21,717 (about $22k), **expected $45,799, about $46k**, high $90,546 (about $91k).

    | Line, a year | Low | Expected | High |
    |---|---|---|---|
    | Computing: hosting, firewall, private network, monitoring, Defender for Cloud, model calls, evaluation runs, a nightly EDGAR job | $2,066 | $7,424 | $13,935 |
    | of which the Answer Calls (`gpt-6-luna` on Azure, US data zone) | $7.82 | $7.82 | $78.24 |
    | Engineering upkeep: 0.10, 0.15 or 0.25 of an engineer | $19,650 | $32,103 | $60,907 |
    | Annual security test: 0, 40 or 80 hours | $0 | $6,273 | $15,704 |

  - **Computing:** the expected case is App Service Premium v4 (two zone-redundant P0v4 instances, $0.073 an hour each, and a staging instance), Front Door Premium for the web application firewall and Private Link ($330 a month, the largest computing line), four private endpoints, Log Analytics at 3 GB a month beyond the free allowance, Blob Storage and Defender for Cloud. Prices are pay-as-you-go list prices for East US, read from Microsoft's [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices) on 2026-10-22, before any discount the firm has negotiated. The low case uses Front Door Standard ($35 a month) and no Defender; the high case larger instances and Application Gateway WAF v2. A pilot can run on a minimal setup for about $291 a year (Container Apps, no firewall or private network).
  - **The Answer Calls:** `gpt-6-luna` is offered on Azure at OpenAI's own list price ($0.10 and $0.50 per million input and output tokens), 10% more in the US data zone. At the final round's mean of 25,180 input and 891 output tokens an answer, that is $7.82 a year; $78.24 at ten times the usage.
  - **Engineering:** a fully loaded engineer costs $196,503 to $243,627 a year: the BLS median and mean wages for Software Developers, May 2025 ($135,980 and $148,100, and $168,590 in securities and investment firms), divided by the wage share of compensation for professional occupations, 69.2% ([BLS Employer Costs for Employee Compensation, June 2026](https://www.bls.gov/news.release/ecec.t04.htm)). The fraction of an engineer is ours, built bottom-up at about 264 hours a year (0.13 of an engineer): updates and patching, monitoring, a quarterly re-run of the evaluation on new models, the nightly EDGAR job, user support and the security review. No credible source gives the upkeep of a small internal app.
  - **Security test:** at the median federal-schedule rate for a penetration tester, $156.83 an hour (GSA CALC+); the hours are ours. SOC 2 is not needed while the firm operates the workspace in its own tenant: a SOC 2 report attests a service an outside organisation provides.
  - **Left out:** the one-time build, the firm's existing Microsoft 365 and Entra ID licences (Entra ID P1, $7 a user a month, if not already held), and a DDoS Network Protection plan if the firm's landing zone requires one and its hub does not already pay it ($2,943.55 a month).
- **Why it matters:** Set beside assumption 12, it shows that the cost of the workspace is mostly an engineer's time, not the AI: the Answer Calls cost under $10 a year. A value case that counted only the Answer Calls would understate the cost by thousands of times.
- **Asked in email:** No. To agree with the Client, or to measure in a pilot: where it would run, the firm's Azure discounts and security policies, and who would maintain it.
- **Status:** not confirmed
