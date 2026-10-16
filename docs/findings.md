# EDA findings

What the exploratory data analysis found about the Corpus, and what each finding means for the design. The evidence for every entry, with the full numbers, is in the EDA notebook ([`backend/notebooks/eda.ipynb`](../backend/notebooks/eda.ipynb)); the analysis number points to its section. The assumptions these findings lead to, and which of them the Client has confirmed, are in [`assumptions.md`](assumptions.md).

Each entry has the same shape:

- **Finding:** what the data shows.
- **Implication:** why it matters for answering the Client's questions.
- **Design decision:** what the system does about it.

## In brief

- **The Corpus is not what the brief describes.** It runs from 2022 to Filings made in February 2026, and includes a 2014 GE Capital report. Only 13 of the 54 Companies have the two years of quarterly Filings a trend question needs (findings 1, 3, 6, 11).
- **The metadata can be trusted once it is derived.** Every Filing gets a Report Period, a stable Filing ID, a Fiscal Period and a Sector, and every source of each agrees (findings 2, 4, 5, 12).
- **The text needs cleaning and careful chunking.** XBRL noise, a table of contents, flattened tables and very long lines would all break naive chunking. Item headings locate Sections in almost every Filing, but some Sections only point elsewhere (findings 7–10, 13, 14).
- **Everything is too big for one Answer Call, and much of it repeats.** A median 10-K is about 98k tokens and most text repeats from one period to the next, so retrieval must pick deduplicated passages per Company (findings 15–17).
- **The example questions are answerable, each with a caveat** the answer has to state: mixed periods, Snapshot Companies, missing guidance (findings 18–20).
- **Revenue and net income can be extracted exactly** for the Tracked Companies, so a small SQLite Financial Facts store feeds figures to the Answer Call (findings 21–24, [ADR 0001](adr/0001-sqlite-financial-facts-store.md)).

## 1. Coverage is very uneven across Companies

_Analysis 1: inventory and coverage._

- **Finding:** 246 Filings from 54 Companies. 12 Companies have 14–17 Filings each, quarterly from 2022Q1 to 2025Q4. META has 8, JPM and BAC 4, MCD and PEP 2, and the other 37 Companies a single 10-K. Each Company's most recent 10-K (54 Filings) has no Report Period or Calendar Quarter in its header.
- **Implication:** Trend questions are answerable for 13 Companies only (finding 11). Pure similarity retrieval would let the many Filings of a few Companies crowd out the single Filing of others in a comparison.
- **Design decision:** Carry Company, Report Period and Tracked/Snapshot class as metadata on every chunk. Retrieval filters on Company and Report Period and retrieves per Company for comparisons. The Answer Call is told each Company's coverage and states when it limits an answer.

## 2. Every Filing can be placed on the time axis, and the metadata sources agree

_Analysis 2: metadata integrity._

- **Finding:** For the 54 Filings with no header period, 53 source URLs carry the period end date (`aapl-20250927.htm`) and the cover-page sentence ("For the fiscal year ended September 27, 2025") agrees every time. GE's URL has no date, so its period comes from the cover page. Across all 246 Filings every available source agrees. The manifest matches the files on disk, file names match headers, and each ticker has one CIK and one Company name.
- **Implication:** The Report Period can be the time axis for filtering and for resolving "latest" and "the last two years".
- **Design decision:** The Corpus seam resolves the Report Period from the header, then the URL, then the cover page, records the source used, and records any disagreement as a diagnostic instead of failing.

## 3. The "GE" Filing is GE Capital's FY2014 10-K

_Analysis 2: metadata integrity._

- **Finding:** The header says "General Electric Company", but the registrant is **General Electric Capital Corporation**, the document is `gecc10k2014.htm`, and it covers the year ended 31 December 2014, filed eight years before anything else in the Corpus.
- **Implication:** A question about General Electric would be answered from a ten-year-old report of a different legal entity.
- **Design decision:** Keep the Filing, attribute it to GE Capital, flag it as stale whenever it is used, and leave it out of "current state" answers. Assumption 3 in `assumptions.md`.

## 4. Calendar Quarter is not a key; Report Period identifies a Filing

_Analysis 2: metadata integrity._

- **Finding:** Seven Company × Calendar Quarter cells hold two Filings, all from 52/53-week years whose periods end a day or two into the next quarter (Coca-Cola's Q2 2022 ended on 1 July, so it shares 2022Q3 with its Q3). `ticker_FormType_ReportPeriod` (e.g. `KO_10-Q_2022-07-01`) is unique across all 246 Filings.
- **Implication:** Keying on Calendar Quarter would merge or misplace Filings.
- **Design decision:** Every Filing carries the Filing ID `ticker_FormType_ReportPeriod`, used in chunk metadata, citations and Financial Facts. Calendar Quarter is an informational label only.

## 5. 17 Companies have a non-December fiscal year

_Analysis 2: metadata integrity._

- **Finding:** Fiscal year ends derived from 10-K Report Periods give December for 37 Companies and another month for 17 (e.g. NVIDIA January, Apple September, Microsoft June). Naming the fiscal year after the calendar year it ends in reproduces the Companies' own labels (NVIDIA's quarter to 27 July 2025 is Q2 FY2026), except for Home Depot and Target, which name it after the year it starts in.
- **Implication:** Users ask in the Company's own terms, which differ from calendar quarters for a third of the Companies.
- **Design decision:** Every Filing carries a derived Fiscal Period as a secondary label, and citations show both it and the Report Period. The Home Depot and Target off-by-one is recorded, not special-cased (both have a single 10-K).

## 6. 48 Filings fall outside the brief's "2023–2025"

_Analysis 2: metadata integrity._

- **Finding:** By Report Period, 48 Filings fall outside 2023–2025: GE Capital's FY2014 10-K and 47 Filings from 2022 across 12 Companies. 27 more are inside the window but were filed in 2026.
- **Implication:** "2023–2025" does not describe the Corpus by Report Period or by Filing Date, so "the last two years" and "latest" depend on the Client's intent.
- **Design decision:** Keep every Filing and show the Report Period in every citation. Assumption 3 in `assumptions.md`.

## 7. A seventh of the raw text is XBRL noise

_Analysis 3: text anatomy._

- **Finding:** Every Filing body opens with machine-readable XBRL residue glued in front of the cover page: 13.6% of all raw text, over 20% in 31 Filings and 52% in IBM's 10-K. It always ends where the cover page begins ("UNITED STATES SECURITIES AND EXCHANGE COMMISSION").
- **Implication:** Left in, it would cost embedding and context budget and could reach an Answer Call as garbage.
- **Design decision:** The Corpus seam cuts everything before the cover page; only the cleaned body is indexed. A test checks no cleaned body contains an XBRL signature.

## 8. The table of contents repeats every Item heading

_Analysis 3: text anatomy._

- **Finding:** 237 of 246 Filings have a table of contents near the top whose rows repeat the real Item headings ("Item 1A. | Risk Factors | 5"), in several different layouts.
- **Implication:** A Section splitter would find every heading twice, and a retrieved TOC row looks like an answer without containing one.
- **Design decision:** The Corpus seam locates the TOC (`Filing.toc`), Section detection skips it, and it is never indexed.

## 9. A fifth of the text is flattened tables

_Analysis 3: text anatomy._

- **Finding:** About 20% of the raw text is `|`-separated table rows holding most of the figures, with column headers on rows of their own. Exhibit indexes and signatures add another 3%.
- **Implication:** A figure cut off from its row label and column header (which period, which unit) cannot be read correctly.
- **Design decision:** Chunk tables as whole tables, or row groups that repeat the header rows, tagged as table chunks. Leave exhibit indexes and signatures out of the index.

## 10. Line breaks are not paragraph breaks

_Analysis 3: text anatomy._

- **Finding:** 135 Filings have a line over 20,000 characters (META's longest is 287,855), with page footers, page numbers and 7,813 "Table of Contents" running headers embedded mid-line.
- **Implication:** Splitting on newlines would produce a few enormous chunks, and page furniture would end up in embeddings.
- **Design decision:** Split prose on sentence boundaries within a token budget. Strip running headers, footers and page numbers before chunking.

## 11. 13 Tracked Companies, 41 Snapshot Companies, with a clean break between them

_Analysis 1: inventory and coverage (1.2)._

- **Finding:** By longest run of consecutive quarter-ends, 12 Companies cover 14–17 quarters, META exactly 8, BAC and JPM 4, and everyone else never two in a row. Nothing falls between 4 and 8. No Financials Company is Tracked.
- **Implication:** "Over the last two years" is answerable for 13 Companies. The first example question names JPMorgan, whose Filings all cover 2025.
- **Design decision:** A Tracked Company covers at least 8 consecutive quarter-ends (`TRACKED_MIN_QUARTERS`); any cut-off from 5 to 8 gives the same split. The class is on every Filing and chunk, and the Answer Call states the limit when a trend is asked of a Snapshot Company. Assumption 4 in `assumptions.md`.

## 12. Sectors come from a curated table; SIC disagrees for 14 Companies

_Analysis 1: inventory and coverage (1.3)._

- **Finding:** No Filing carries a sector. A curated GICS-style table (`data/reference/sectors.csv`) maps the 54 Companies to 8 sectors. SEC SIC codes disagree for 14 Companies, through stale codes (Netflix "video tape rental"), activity over business model (UnitedHealth as an insurer, Thermo Fisher as an instrument maker), or later GICS moves (Visa and Mastercard to Financials). JNJ, LLY, MRK, PFE and ABBV share SIC 2834.
- **Implication:** Neither SIC nor a Company's name decides which Companies a sector question covers, so "the major pharmaceutical companies" needs a defined, visible rule.
- **Design decision:** The GICS-style label is the Sector, with the SIC code and every disagreement explained beside it. Sector phrases resolve through the industry column with rule-based synonyms, then retrieval runs per Company. GE is Financials for the GE Capital Filing. Assumption 5 in `assumptions.md`.

## 13. Item headings locate Sections in almost every Filing

_Analysis 4: Section and Item detection._

- **Finding:** Splitting at Item headings finds every required Section in 96–97% of 10-Ks and 98–100% of 10-Qs, except 10-Q Risk Factors (85%), where all 24 misses are J&J and ExxonMobil 10-Qs that genuinely have none. Detection fails in eight Filings: Morgan Stanley's, Intel's and McDonald's 10-Ks and JPMorgan's three 10-Qs use their own headings, and Bank of America's and Comcast's 10-Ks put the Company name inside the heading. The same words recur in cross-references and the TOC.
- **Implication:** Sections can address content across both Form Types, but a naive splitter would cut at cross-references, and a Section filter returns nothing for the eight failures.
- **Design decision:** Every Section carries a standard name (Business, Risk Factors, Cybersecurity, Legal Proceedings, MD&A, Market Risk, Financial Statements, Controls and Procedures, Other) and its original Item label. Cross-references and TOC matches are rejected; text before the first heading is an Unsectioned Section; missing Sections become diagnostics. Chunks carry both name and label.

## 14. An Item label says where content belongs, not always where it is

_Analysis 4: Section and Item detection._

- **Finding:** Many Sections are stubs pointing elsewhere: Legal Proceedings is under 1,000 characters in 65% of 10-Ks, 10-Q Market Risk in 66%. The real content often follows the last Item: JPMorgan's MD&A is in its appended Annual Report (Item 15 is 86% of the body), and ExxonMobil, Deere, Netflix, Disney and BlackRock put their financial statements after the last Item.
- **Implication:** A hard Section filter would miss JPMorgan's MD&A and return only a pointer.
- **Design decision:** Risk Factors, Business, MD&A and Controls and Procedures are reliable filters; Legal Proceedings, Market Risk and Financial Statements are chunk boundaries only. A Section filter is a preference: with no Section or only a stub, retrieval falls back to the whole Filing, still filtered on Company and Report Period. Trailing and Unsectioned text is indexed like any other.

## 15. Filings and substantive Sections are far bigger than any sensible context budget

_Analysis 5: token statistics._

- **Finding:** With tiktoken `o200k_base` as a provider-independent stand-in, the cleaned Corpus is about 17.2M tokens. A median 10-K is about 98k tokens and a median 10-Q 44k (JPMorgan's FY2025 10-K: 323k). Median 10-K Risk Factors are about 12k tokens and MD&A 13k. A 32k budget holds 33 chunks of 800 tokens or 50 of 512: about two typical Risk Factors Sections.
- **Implication:** The Answer Call never gets whole Filings and rarely a whole Section, and a five-Company question has to share the budget.
- **Design decision:** Retrieve chunks only. Start with prose chunks of about 500–800 tokens inside Section boundaries and a retrieved-context budget of about 32k tokens (5–10 chunks per Company for a five-Company question), tables capped near the same size. Keep token counting behind one function and re-measure with the chosen LLM's tokenizer.

## 16. Most 10-Q Risk Factors only point back to the 10-K

_Analysis 6: repetition between periods (6.1)._

- **Finding:** Of 157 10-Qs, 64 (41%) have Risk Factors that only say "no material changes" since the 10-K, one (McDonald's) points elsewhere in the same 10-Q, 24 (15%, every J&J and ExxonMobil 10-Q) have none, and 68 (43%) state risk text. Pointers are all under 2,500 characters, risk text all above.
- **Implication:** The answer to "what are X's risks?" is usually in the latest 10-K, and a retrieved pointer looks relevant but contains no risks.
- **Design decision:** Route risk questions to the latest 10-K's Risk Factors plus any later 10-Q that states risk text. Index pointers tagged as pointers, so they can be cited ("no material changes") but never retrieved as the answer.

## 17. Most text repeats from one period to the next

_Analysis 6: repetition between periods (6.2, 6.3)._

- **Finding:** By 8-word shingles, a Tracked Company's 10-K Risk Factors repeat a median 80% of the previous 10-K, and 10-Qs that state risk text a median 94% (Amazon, Microsoft and Meta restate everything every quarter). Overall 62–64% of a Filing repeats the previous one of the same Form Type: about 90% of Controls and Procedures but only 53% of MD&A.
- **Implication:** Similarity retrieval returns the same paragraph from up to 16 Filings, filling the budget of finding 15 and crowding out what changed.
- **Design decision:** Deduplicate within each Company at index time, storing a repeated chunk once with every Filing it appears in. Drop near-duplicates at query time, keeping the most recent Report Period unless the question names one. For "how have the risks changed", favour paragraphs new in each 10-K.

## 18. The example questions are answerable, each with a caveat

_Analysis 8: coverage of the example questions (8.1–8.4)._

- **Finding:** Apple's, Tesla's and JPMorgan's risk factors come from Item 1A of `AAPL_10-K_2025-09-27`, `TSLA_10-K_2025-12-31` and `JPM_10-K_2025-12-31`. NVIDIA's "last two years" is eight Filings, Report Periods 28 January 2024 to 26 October 2025 (Q4 FY2024 to Q3 FY2026). "The major pharmaceutical companies" resolves to AbbVie, J&J, Lilly, Merck and Pfizer. Five variant questions hit the same gaps: trends asked of Snapshot Companies, Sections found only by whole-Filing fallback, debatable sector phrases, and the stale GE Capital Filing.
- **Implication:** Almost every answer needs to say something about its coverage. The three Risk Factors Sections of the first question alone hold about 263,000 characters.
- **Design decision:** Every gap has a fixed wording (notebook 8.6), e.g. "Trend unavailable: JPMorgan is a Snapshot Company. The Corpus holds four JPMorgan Filings, Q1–Q4 2025, so this answer covers 2025 only." The Answer Call gets each Company's coverage class, Filing IDs, Report Periods and Fiscal Periods, and is told to state gaps, never fill them from general knowledge. Answers name the Companies a sector phrase resolved to.

## 19. "Latest" and "the last two years" depend on the Company and the anchor

_Analysis 8: coverage of the example questions (8.2, 8.5)._

- **Finding:** The last Filing Date is 19 February 2026. 12 December year-end Companies (including AbbVie, Merck, Pfizer and Chevron) have no FY2025 10-K, and NVIDIA's latest covers the year to January 2025. Anchored on each Company's latest Report Period, "the last two years" holds eight Filings for every Tracked Company; anchored on today, four or five.
- **Implication:** A comparison of "latest 10-Ks" silently compares different years (every comparison in analysis 8 did), and a calendar anchor would discard half the trend data.
- **Design decision:** Rule-based query parsing anchors time phrases on each Company's latest Report Period: "latest" is the latest 10-K plus later 10-Qs, "the last two years" the two years up to the latest Filing. Answers name each Company's periods and say when they differ. Assumption 6 in `assumptions.md`.

## 20. Forward guidance is not in 10-K or 10-Q Filings

_Analysis 8: coverage of the example questions (8.2)._

- **Finding:** NVIDIA gives its revenue outlook in earnings releases, which are not in the Corpus. Forward-looking content in the Filings is qualitative MD&A commentary and risk factors.
- **Implication:** "How has NVIDIA's growth outlook changed?" cannot be answered with guidance figures, and an LLM would be tempted to supply remembered ones.
- **Design decision:** The Answer Call is told guidance is not in the Filings, and an outlook answer says it is drawn from MD&A commentary and risk factors. Assumption 7 in `assumptions.md`.

## 21. Revenue can be extracted exactly from every Tracked Company Filing

_Analysis 7: whether Financial Facts can be extracted (revenue)._

- **Finding:** A rule-based extractor reads revenue from all 197 Tracked Company Filings, and every value equals the SEC XBRL company-facts value for the same Filing and period to the dollar; eight hand-checked values agree. It handles eight revenue labels, current-year columns first or last, and scale words in titles or header rows. A 10-K reports the year, so a quarterly series derives the fourth quarter.
- **Implication:** Revenue trends for Tracked Companies can use exact, cited figures instead of the Answer Call reading flattened tables. Nothing is yet known about the 41 Snapshot Companies.
- **Design decision:** Keep the Financial Facts seam separate from the Corpus seam. Each fact carries its Filing ID, Report Period and printed label so it can be cited. The extractor returns nothing rather than a guess. The SEC data is an evaluation reference only, never an answer source.

## 22. Net income can be extracted exactly too, once the right row is chosen

_Analysis 7: whether Financial Facts can be extracted (net income)._

- **Finding:** Net income is read from all 197 Filings and every value equals the SEC's `NetIncomeLoss` to the dollar; six hand-checked values agree. Six Companies print a total including noncontrolling interests above the part attributable to the Company, and per-share rows sit in the same "in millions" table.
- **Implication:** Taking the first "net income" row is wrong for six Companies, and a per-share row is a million times too small. Both are easy mistakes for any reader of flattened text.
- **Design decision:** The attributable row wins over the total; per-share, continuing/discontinued and noncontrolling rows never count. Earnings per share is not extracted.

## 23. Segment revenue is exact where found, and found for two Filings in three

_Analysis 7: whether Financial Facts can be extracted (segment revenue, 7.2)._

- **Finding:** Segment revenue is extracted from 137 of 197 Filings (70%), covering 10 of 13 Companies: Apple, Amazon, Alphabet, Meta, Microsoft, Tesla, Coca-Cola and NVIDIA in every Filing, Disney in 15 of 17 and ExxonMobil in 5 of 16. Coca-Cola, NVIDIA and ExxonMobil lay their segments out as table columns, one block of rows per period; ExxonMobil also splits each segment into U.S. and non-U.S. columns. Each set adds up to the SEC-matched revenue and 16 hand-checked values agree; the SEC data has no segment breakdown to check against. Segment tables come in at least five layouts, and product or geographic tables also add up to revenue. ExxonMobil's segment tables before 2025 add up to "Sales and other operating revenue", not to the revenue the SEC reports, and nothing in them reconciles the two. Disney reorganised its segments in FY2023, and Coca-Cola stopped reporting Global Ventures as a segment in 2025.
- **Implication:** Exact segment figures exist for ten Companies, not for J&J, Pfizer or UnitedHealth, nor for ExxonMobil before 2025, and a segment trend cannot cross a reorganisation.
- **Design decision:** Report segments only when the table's introduction (or, for columns, its header) calls them segments and they add up to revenue, directly or through a reconciliation printed in the same table. A segment split into U.S. and non-U.S. columns is reported as their sum. Segment questions the store has no facts for fall back to retrieved text and say so; a segment trend stops at a reorganisation and says so.

## 24. Build a SQLite Financial Facts store, queried before the Answer Call

_Analysis 7: whether Financial Facts can be extracted._

- **Finding:** Rules extract revenue and net income exactly from every Tracked Company Filing and segment revenue for ten Companies. Read from text instead, a two-year trend needs the income statements of eight Filings.
- **Implication:** Exact figures can reach the Answer Call for a few hundred tokens, as long as they are selected without an LLM: the single-call rule leaves no room for text-to-SQL.
- **Design decision:** Build a SQLite Financial Facts store of the Tracked Companies' revenue, net income and segment revenue, rebuilt at index time under `data/derived/`. The rule-based query parser picks metric, Companies and window and runs a fixed, parameterised query; the rows go into the Answer Call with their Filing IDs and periods. Every other figure comes from retrieved text, and the answer says so. See [ADR 0001](adr/0001-sqlite-financial-facts-store.md).

## Recommendations for the retrieval phase

What to build next, roughly in the order it is needed, with the findings behind each step.

1. **Index from the Corpus seam only.** Use the cleaned `Filing.body` and its Sections, never the raw files. Leave out the TOC, exhibit indexes and signatures, and strip page furniture (findings 7–10).
2. **Chunk inside Section boundaries.** Split prose on sentences at about 500–800 tokens with a small overlap. Keep tables whole or as header-repeating row groups, tagged as tables. Tune the size in evaluation, starting here (findings 9, 10, 15).
3. **Put rich metadata on every chunk:** Filing ID, Company, Sector and industry, Form Type, Report Period, Fiscal Period, Tracked/Snapshot class, Section name, Item label, and chunk kind (prose, table, risk pointer) (findings 1, 4, 5, 11–13, 16).
4. **Deduplicate within each Company at index time,** keeping one copy of a repeated chunk with every Filing it appears in (finding 17).
5. **Parse the question with rules before retrieval:** Companies by name and ticker, sector phrases through the Sector table, time phrases anchored on each Company's latest Report Period, Form Type, Section hints, and the metric vocabulary for Financial Facts. No LLM runs before the Answer Call (findings 12, 19, 24).
6. **Retrieve with hard filters on Company and period and a soft preference on Section,** falling back to the whole Filing when a Section is missing or a stub. Retrieve and budget the context per Company (findings 1, 14, 18).
7. **Route by question type:** risk questions to the latest 10-K's Risk Factors plus later 10-Qs that state risk text; "how has it changed" questions to paragraphs that are new between periods; figure questions to the Financial Facts store first (findings 16, 17, 24).
8. **Build the SQLite Financial Facts store** of the Tracked Companies' revenue, net income and segment revenue, read by fixed, parameterised queries (finding 24, ADR 0001).
9. **Drop near-duplicate retrieved chunks at query time,** keeping the most recent Report Period unless the question names one, within a starting budget of about 32k tokens (findings 15, 17).
10. **Build the Answer Call prompt from one fixed template:** the retrieved chunks with their citation metadata, any Financial Facts table, each Company's coverage, and the gap wordings of notebook 8.6. Instruct the model to cite Filing IDs and periods, state every gap, and never fill one from general knowledge (findings 18–20).
11. **Evaluate on the traced questions.** The three example questions and five variants of analysis 8 already name the Filings and Sections that should answer them, which makes a first retrieval test set. Check every figure in an answer against the Financial Facts store (findings 18, 21–23).
12. **Re-measure tokens with the chosen LLM's tokenizer** and adjust chunk size and budget (finding 15).
