# EDA findings

What the exploratory data analysis found about the Corpus, and what each finding means for the design. The evidence for every entry is in the EDA notebook ([`backend/notebooks/eda.ipynb`](../backend/notebooks/eda.ipynb)); the analysis number points to its section.

Each entry has the same shape:

- **Finding:** what the data shows, with numbers.
- **Implication:** why it matters for answering the Client's questions.
- **Design decision:** what the system does about it.

## 1. Coverage is very uneven across Companies

_Analysis 1: inventory and coverage._

- **Finding:** The 246 Filings are spread very unevenly over the 54 Companies. 12 Companies have 14–17 Filings each, quarterly from 2022Q1 to 2025Q4 (10-Qs plus annual 10-Ks). META has 8, JPM and BAC have 4, MCD and PEP have 2, and the other 37 Companies have a single 10-K. Coverage starts in 2022Q1, a year earlier than the brief's "2023–2025". Every Company's most recent 10-K (54 Filings) has no Report Period or Calendar Quarter in its header, so for the 37 single-Filing Companies the header alone cannot place them in time. Seven Company × Calendar Quarter cells hold two Filings (e.g. Coca-Cola's two 2022Q3 10-Qs).
- **Implication:** Trend questions ("How has NVIDIA's revenue changed over the last two years?") are answerable for roughly 15 Companies only. For the rest the Corpus supports point-in-time questions from one annual report. Pure similarity retrieval would let the many Filings of a few Companies crowd out the single Filing of others in a cross-Company comparison, and a Calendar Quarter cannot identify a Filing.
- **Design decision:** Classify each Company as a Tracked Company or a Snapshot Company and carry that, the Company and the Report Period as metadata on every chunk. Retrieval filters on Company and Report Period rather than relying on similarity alone, and retrieves per Company for comparisons. The Answer Call is told the coverage of each Company in scope and states plainly when coverage limits an answer. Every Filing gets a derived Report Period, and Calendar Quarter is never used as a key.

## 2. Every Filing can be placed on the time axis, and the metadata sources agree

_Analysis 2: metadata integrity._

- **Finding:** 54 Filings (each Company's most recent 10-K) have no Report Period or Calendar Quarter in their header. For 53 of them the source URL carries the period end date (e.g. `aapl-20250927.htm`), and the cover-page sentence ("For the fiscal year ended September 27, 2025") agrees in every case. The GE Filing's URL (`gecc10k2014.htm`) has no date, so its Report Period (31 December 2014) comes from the cover page alone. Across all 246 Filings, every available source (header, URL, cover page) gives the same Report Period. The manifest matches the files on disk, every file name agrees with its header, each ticker has exactly one CIK and one Company name, and every URL sits under the Filing's CIK.
- **Implication:** The Report Period can be trusted for every Filing, so it can be the time axis for filtering and for resolving "latest" or "the last two years". Finding the cover-page sentence needs care: flattening glues the date to the phrase (`endedDecember 31, 2025`) or puts a table cell between them, and a 10-Q's body often mentions "the year ended" of the prior 10-K before the reader reaches anything else.
- **Design decision:** The Corpus seam resolves the Report Period from the header, then the URL, then the cover-page sentence, records which source it used, cross-checks every source present, and records any disagreement as a diagnostic on the Filing instead of failing. A 10-K is matched on "fiscal year ended" and a 10-Q on "quarterly period ended", so a 10-Q never picks up its 10-K reference.

## 3. The "GE" Filing is GE Capital's FY2014 10-K

_Analysis 2: metadata integrity._

- **Finding:** The Filing under ticker GE has the header Company "General Electric Company", but its cover page names **General Electric Capital Corporation** as the registrant, the document is `gecc10k2014.htm`, and it sits under CIK 0000040554, GE Capital's EDGAR folder. It covers the fiscal year ended 31 December 2014 and was filed on 27 February 2015, eight years before anything else in the Corpus.
- **Implication:** A question about General Electric would be answered from a ten-year-old report of a different legal entity (GE Capital was GE's financing arm, since wound down) unless the system says so.
- **Design decision:** Keep the Filing, attribute it to GE Capital and flag it as stale in any answer that uses it, and leave it out of "current state" answers. Raised with the Client in question 3.

## 4. Calendar Quarter is not a key; Report Period identifies a Filing

_Analysis 2: metadata integrity._

- **Finding:** Every Calendar Quarter label is correct by definition (the calendar quarter in which the Report Period ends), yet seven Company × Calendar Quarter cells hold two Filings. All are 52/53-week calendars whose periods end a day or two into the next calendar quarter: Coca-Cola's Q2 2022 ended on 1 July and shares 2022Q3 with its Q3, Apple's and Disney's Q3 2023 ended on 1 July, Disney's FY2022 ended on 1 October, and Pfizer's and J&J's Q3s ended on 1–2 October. `ticker_FormType_ReportPeriod` (e.g. `KO_10-Q_2022-07-01`) is unique across all 246 Filings.
- **Implication:** Keying, deduplicating or filtering on Calendar Quarter would merge or misplace Filings, for example treating Coca-Cola's second quarter as its third.
- **Design decision:** Every Filing carries the stable Filing ID `ticker_FormType_ReportPeriod`, used in chunk metadata, citations and Financial Facts. Calendar Quarter stays an informational label only.

## 5. 17 Companies have a non-December fiscal year

_Analysis 2: metadata integrity._

- **Finding:** Deriving each Company's fiscal year end from its 10-K Report Periods gives December for 37 Companies and another month for 17: January (NVDA, WMT, CRM, HD, TGT), September (AAPL, DIS, SBUX, V), June (MSFT, PG), May (NKE, ORCL), and one each for August (COST), July (CSCO), October (DE) and November (ADBE). Period ends in the first seven days of a month (Deere's 2 November, J&J's 2 January) belong to the previous month. Counting quarters from the fiscal year end and naming the fiscal year after the calendar year it ends in reproduces the Companies' own labels (NVIDIA's quarter ending 27 July 2025 is Q2 FY2026), except for Home Depot and Target, which name a fiscal year after the year it starts in (Home Depot calls the year ended 2 February 2025 "fiscal 2024").
- **Implication:** Users ask in the Company's own terms ("NVIDIA's Q2 FY2026"), which do not match calendar quarters for a third of the Companies.
- **Design decision:** Every Filing carries a derived Fiscal Period as a secondary label next to the Report Period, and citations show both. The Home Depot and Target off-by-one is recorded, not special-cased: both are Snapshot Companies with one 10-K, and the Report Period remains the canonical time axis.

## 6. 48 Filings fall outside the brief's "2023–2025"

_Analysis 2: metadata integrity._

- **Finding:** Keyed on Report Period, 48 Filings fall outside 2023–2025: GE Capital's FY2014 10-K and 47 Filings from 2022 across 12 Companies (AAPL, AMZN, DIS, GOOG, JNJ, KO, MSFT, NVDA, PFE, TSLA, UNH, XOM), including J&J's FY2021 10-K, whose year ended 2 January 2022. A further 27 Filings are inside the window by Report Period but were filed in 2026 (24 FY2025 10-Ks and 3 10-Qs for quarters ending in December 2025).
- **Implication:** "2023–2025" in the brief does not describe the Corpus by Report Period or by Filing Date. What "the last two years" or "latest" means depends on the Client's intent.
- **Design decision:** Keep every Filing and show the Report Period in every citation, so the time scope of each answer is visible. The full list is in Client question 3, with this as the working assumption.

## 7. A seventh of the raw text is XBRL noise

_Analysis 3: text anatomy._

- **Finding:** Every Filing body opens with machine-readable XBRL residue (context IDs, taxonomy URLs such as `http://fasb.org/us-gaap/2024#...`, unit tags, hidden facts) glued in front of the SEC cover page. It is 13.6% of all raw body text (11.1M characters): 16% of 10-Q text and 12% of 10-K text, over 20% in 31 Filings and 52% in IBM's 10-K. The residue always ends where the cover page begins ("UNITED STATES SECURITIES AND EXCHANGE COMMISSION"); no XBRL signature appears after that point in any Filing. The GE Filing (GE Capital's FY2014 10-K) is the exception: it predates inline XBRL, and its only preamble is an EDGAR document header.
- **Implication:** Left in, the noise would fill chunks with strings that look like nothing a question would match, yet still cost embedding and context budget, and could surface in an Answer Call as garbage.
- **Design decision:** The Corpus seam cuts everything before the cover page, so `Filing.body` is the cleaned body and `Filing.xbrl_noise_chars` records how much was removed. A Corpus-level test checks that no cleaned body contains an XBRL signature. Only the cleaned body is ever indexed.

## 8. The table of contents repeats every Item heading

_Analysis 3: text anatomy._

- **Finding:** 237 of the 246 Filings have a table of contents within the first tenth of the body. Its rows repeat the real Item headings ("Item 1A. | Risk Factors | 5"), but the layout varies by Company: page number last or first (Mastercard), the Item number in its own column (Chevron, AT&T, Morgan Stanley), the Item label on one row and its heading on the next (Pfizer), page references like "K-24" (Berkshire) or "Pages37-51" (Intel), or the Company's own headings with the Item mapping in a cross-reference index at the end (Intel, McDonald's). Disney's nine 10-Qs before 2025 have no TOC at all. The TOC is under 1% of the text.
- **Implication:** A Section splitter that looks for Item headings would find each one twice, first in the TOC, and could cut Risk Factors down to one TOC row. A retrieved TOC row would look like an answer about Risk Factors without containing any.
- **Design decision:** The Corpus seam locates the TOC and exposes its position as `Filing.toc` (a span in the cleaned body, or None). Section detection skips that span, and the TOC is never indexed. Cross-reference indexes at the end of a Filing are left to Section detection to handle (analysis 4).

## 9. A fifth of the text is flattened tables

_Analysis 3: text anatomy._

- **Finding:** About 20% of the raw text is rows of `|`-separated cells, the remains of HTML tables: 24% of 10-Q text, and a quarter of the text of the largest Filings. These rows hold most of the figures (revenue, segment results, balance sheet lines). Column headers sit on rows of their own above the figures. Exhibit indexes and signature blocks add another 3% (4% of 10-K text) with no business content.
- **Implication:** A figure separated from its row label and column header (which period, which unit) cannot be read correctly, so naive fixed-size chunking would hand the Answer Call numbers it cannot interpret. Exhibit lists and signatures would only dilute retrieval.
- **Design decision:** Chunk tables as whole tables, or as row groups that repeat the table's header rows, never splitting a row from its labels, and tag them as table chunks so the Answer Call knows it is reading one. Leave exhibit indexes and signatures out of the index. The flattened tables are also the input to the Financial Facts experiment (analysis 7).

## 10. Line breaks are not paragraph breaks

_Analysis 3: text anatomy._

- **Finding:** 135 Filings have a single line over 20,000 characters; META's longest is 287,855. Whole pages of prose are glued together, with page footers ("Apple Inc. | 2024 Form 10-K | 20"), page numbers and "Table of Contents" running headers embedded mid-line (7,813 running headers across 204 Filings, e.g. "2Table of ContentsAMAZON.COM, INC.").
- **Implication:** A chunker that splits on newlines would produce a handful of enormous chunks for these Filings. Page furniture inside the text would end up in chunks and embeddings, and a page footer with a `|` makes a prose line look like a table.
- **Design decision:** Split prose on sentence boundaries within a token budget, not on line breaks. Strip running page headers, page footers and bare page numbers before chunking.
