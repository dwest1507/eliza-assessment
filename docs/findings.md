# EDA findings

What the exploratory data analysis found about the Corpus, and what each finding means for the design. The evidence for every entry is in the EDA notebook ([`backend/notebooks/eda.ipynb`](../backend/notebooks/eda.ipynb)); the analysis number points to its section.

Each entry has the same shape:

- **Finding:** what the data shows, with numbers.
- **Implication:** why it matters for answering the Client's questions.
- **Design decision:** what the system does about it.

## 1. Coverage is very uneven across Companies

_Analysis 1: inventory and coverage._

- **Finding:** The 246 Filings are spread very unevenly over the 54 Companies. 12 Companies have 14–17 Filings each, quarterly from 2022Q1 to 2025Q4 (10-Qs plus annual 10-Ks). META has 8, JPM and BAC have 4, MCD and PEP have 2, and the other 37 Companies have a single 10-K. Coverage starts in 2022Q1, a year earlier than the brief's "2023–2025". Every Company's most recent 10-K (54 Filings) has no Report Period or Calendar Quarter in its header, so for the 37 single-Filing Companies the header alone cannot place them in time. Seven Company × Calendar Quarter cells hold two Filings (e.g. Coca-Cola's two 2022Q3 10-Qs).
- **Implication:** Trend questions ("How has NVIDIA's revenue changed over the last two years?") are answerable for 13 Companies only (see finding 11). For the rest the Corpus supports point-in-time questions from one annual report. Pure similarity retrieval would let the many Filings of a few Companies crowd out the single Filing of others in a cross-Company comparison, and a Calendar Quarter cannot identify a Filing.
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

## 11. 13 Tracked Companies, 41 Snapshot Companies, with a clean break between them

_Analysis 1: inventory and coverage (1.2)._

- **Finding:** Counting each Company's longest run of consecutive quarter-ends on the Report Period (a 10-K counts as a fourth quarter-end), 12 Companies cover 14–17 quarters from 2022 to 2025, META covers exactly 8 (2024Q1–2025Q4), BAC and JPM cover 4 (one year), and MCD, PEP and the 37 single-10-K Companies never cover two quarters in a row. Nothing falls between 4 and 8. No Financials Company is Tracked.
- **Implication:** "Over the last two years" is answerable for 13 Companies. For BAC and JPM only movement within one year is answerable; for the other 39 only point-in-time questions. The first example question names JPMorgan, whose Filings all cover 2025.
- **Design decision:** A Company is a Tracked Company when its Filings cover at least 8 consecutive quarter-ends (`TRACKED_MIN_QUARTERS`), otherwise a Snapshot Company. Any cut-off from 5 to 8 gives the same split; 8 matches the two-year question. The Corpus seam puts the class on every Filing, retrieval carries it into chunk metadata, and the Answer Call is told each Company's class so it states the limit when a trend is asked of a Snapshot Company. Raised with the Client in question 4.

## 12. Sectors come from a curated table; SIC disagrees for 14 Companies

_Analysis 1: inventory and coverage (1.3)._

- **Finding:** No Filing carries a sector. A curated GICS-style table (`data/reference/sectors.csv`) maps the 54 Companies to 8 sectors, with no Materials, Real Estate or Utilities Company. The Companies' SEC SIC codes disagree with the GICS-style label for 14 of them: stale codes (Netflix "video tape rental", IBM "computer equipment"), activity rather than business model (Alphabet and Meta as computer services, Disney as amusement parks, UnitedHealth as an insurer, Thermo Fisher as an instrument maker), no staples/discretionary split for retailers (Walmart, Costco, Target), later GICS moves (Visa and Mastercard to Financials), and finer GICS industries (AbbVie as Biotechnology, Berkshire as a multi-sector holding). The five drug makers JNJ, LLY, MRK, PFE and ABBV all share SIC 2834; only JNJ and PFE are Tracked.
- **Implication:** Neither SIC alone nor a Company's name decides which Companies a sector question covers. "The major pharmaceutical companies" must resolve to a defined set, and a reader must be able to see why UnitedHealth or Thermo Fisher is or isn't included. The GE Filing (GE Capital's) would mislead an Industrials question.
- **Design decision:** Use the GICS-style label as the Sector, keep the SIC code beside it, and explain every disagreement in the table. Every Filing carries Sector and industry through the Corpus seam, and sector-scoped questions filter on them with rule-based synonyms (e.g. "pharmaceutical" → Pharmaceuticals and Biotechnology), then retrieve per Company. GE is classed as Financials for the GE Capital Filing. The table and the disputable cases are raised with the Client in question 5.

## 13. Item headings locate Sections in almost every Filing

_Analysis 4: Section and Item detection._

- **Finding:** Splitting each cleaned body at its Item headings finds every required Section in 96–97% of 10-Ks and 98–100% of 10-Qs. The exception is 10-Q Risk Factors (85%), and all 24 of those misses are genuine: J&J's and ExxonMobil's 10-Qs have no Part II, Item 1A. Detection really fails in eight Filings. Morgan Stanley's, Intel's and McDonald's 10-Ks and JPMorgan's three 10-Qs have no "Item N" headings in the body: they use their own headings and map them to Items in the TOC or in a cross-reference index at the end. Bank of America's and Comcast's 10-Ks put the Company name inside the heading ("Item 7. Bank of America Corporation and Subsidiaries / Management's Discussion…"). Headings are glued into running text ("…otherwise stated.PART IItem 1.    BusinessCompany Background…"), and the same words recur in cross-references ("see Part II, Item 7, “Management's Discussion…”"), in the TOC, and in those cross-reference indexes. Bank of America's 10-Qs put MD&A before Part I, Item 1.
- **Implication:** Sections can be used to address content across both Form Types, but a splitter that matched every "Item 7" would cut Filings at cross-references and TOC rows. For the eight failing Filings, and wherever a 10-Q has no Risk Factors, a Section filter would return nothing.
- **Design decision:** The Corpus seam splits each Filing into Sections that carry a standard name (Business, Risk Factors, Cybersecurity, Legal Proceedings, MD&A, Market Risk, Financial Statements, Controls and Procedures, Other) and the original Item label ("Item 7", "Part I, Item 2"). A heading is an Item number followed by its official title. Matches preceded by a lower-case word, a comma or an opening quote are rejected as cross-references, as are matches inside the TOC and runs of index rows. Text before the first heading is kept as an Unsectioned Section, so every body is fully covered. Missing required Sections become `section_not_found` diagnostics. The standard set gains Cybersecurity (10-K Item 1C), which is substantive in every 10-K since FY2023. Chunks carry both the Section name and the Item label, so "risk factors" questions filter on the name and "Item 7" questions on the label.

## 14. An Item label says where content belongs, not always where it is

_Analysis 4: Section and Item detection._

- **Finding:** Many Sections are short stubs that point elsewhere. Legal Proceedings is under 1,000 characters in 65% of 10-Ks and 72% of 10-Qs ("See … Note 7 — Commitments and Contingencies"), 10-Q Market Risk in 66% ("no material changes"), 10-Q Risk Factors in 39%, and 10-K Financial Statements in 24% ("See Index to Financial Statements on page 67"). The content they point to often follows the last Item. JPMorgan's Item 7 says its MD&A "appears on pages 46–160" of the Annual Report appended after Item 15, so Item 15 is 86% of the body. ExxonMobil's financial section follows Item 16 (74–76% of each of its four 10-Ks), and Deere, Netflix, Disney and BlackRock put their financial statements after the last Item too (31–69% of the body).
- **Implication:** A hard filter on Section name would miss JPMorgan's MD&A and ExxonMobil's and Disney's financial statements, and return only a pointer. Excluding the last Item or Unsectioned text from the index ("it's just exhibits") would drop real content.
- **Design decision:** Treat Risk Factors, Business, MD&A and Controls and Procedures as reliable chunk boundaries and metadata filters. Use Legal Proceedings, Market Risk and Financial Statements as chunk boundaries only. A Section filter is a preference: when a Company's Filing has no such Section, or only a stub, retrieval falls back to the whole Filing, still filtered on Company and Report Period. Unsectioned text and the last Item are indexed like any other text (except the TOC span). Chunks never cross a Section boundary, and long Sections (10-K Risk Factors median 69,000 characters, MD&A 58,000) are split by the prose and table rules of findings 9 and 10.

## 15. Filings and substantive Sections are far bigger than any sensible context budget

_Analysis 5: token statistics._

- **Finding:** Counted with tiktoken `o200k_base` (a provider-independent stand-in, to be re-measured once the LLM is chosen), the cleaned Corpus is about 17.2M tokens, 4.1 characters per token. A median 10-K is about 98k tokens (64k–144k for the middle 80%) and a median 10-Q about 44k; JPMorgan's FY2025 10-K is the largest at 323k, and the large banks (JPM, BAC, GS, MS) fill the top of the list. A median 10-K Risk Factors Section is about 12k tokens, MD&A about 13k, Business about 8k and Financial Statements about 34k. The largest Sections are those that hold trailing material (JPMorgan's Item 15 at 288k tokens, the Unsectioned bodies of JPMorgan's 10-Qs and Morgan Stanley's 10-K at 187k–221k). Controls and Procedures, 10-Q Market Risk and most Legal Proceedings Sections are under 1k tokens. With 4k tokens reserved for instructions, question and answer and about 40 tokens of citation metadata per chunk, a 32k budget holds 33 chunks of 800 tokens or 50 of 512: about two typical 10-K Risk Factors Sections, or a third of one typical 10-K.
- **Implication:** The Answer Call can never be given whole Filings, and only rarely a whole substantive Section. A cross-Company question (five pharmaceutical companies) has to share the budget, so chunk size directly limits how many Companies and periods one answer can draw on.
- **Design decision:** Always retrieve chunks, never whole Filings or whole substantive Sections. Start with prose chunks of about 500–800 tokens with a small overlap, inside Section boundaries, and a retrieved-context budget of about 32k tokens (roughly 30–50 chunks, or 5–10 per Company for a five-Company comparison). Cap table chunks near the same size. Keep token counting behind one function and re-measure with the chosen LLM's tokenizer. Chunk size is tuned in the retrieval phase; this is the starting point.

## 16. Most 10-Q Risk Factors only point back to the 10-K

_Analysis 6: repetition between periods (6.1)._

- **Finding:** Of the 157 10-Qs, 64 (41%) have a Risk Factors Section that only refers back to the 10-K ("There have been no material changes to the risk factors…"), one (McDonald's) points to another part of the same 10-Q, and 24 (15%, every J&J and ExxonMobil 10-Q) have no Part II, Item 1A at all. Only 68 (43%) state risk text, either the changed risks or the full list again. A pointer is a Section under 2,500 characters; the gap is clean (longest pointer about 2,100 characters, shortest risk text about 2,600). UnitedHealth's 10-Q Risk Factors run on into Item 2 because UnitedHealth titles it "Unregistered Sale of Equity Securities" and the splitter expects "Unregistered Sales".
- **Implication:** For most Companies, the answer to "what are X's risks?" is in the latest 10-K, not in the more recent 10-Qs. A retrieved pointer paragraph looks relevant to a risk question but contains no risks.
- **Design decision:** Route risk questions to the Company's latest 10-K Risk Factors plus any later 10-Q whose Risk Factors state risk text (the material changes). Index pointer-only Risk Factors but tag them as pointers, so they can be cited ("no material changes since the 10-K") but are never retrieved as the answer itself.

## 17. Most text repeats from one period to the next

_Analysis 6: repetition between periods (6.2, 6.3)._

- **Finding:** Measured as the share of 8-word shingles already present earlier, a Tracked Company's 10-K Risk Factors repeat a median 80% of the previous 10-K (from 94% for Amazon down to 59% for NVIDIA). 10-Qs that state risk text are a median 94% repeated: Amazon, Microsoft and Meta restate their full Risk Factors every quarter (96–99% repeated), and 36 10-Qs are at least 90% repeated text (0.5M tokens). Only a few 10-Qs (Apple, Alphabet, Disney, Pfizer, Tesla) add genuinely new risks, such as Pfizer's Seagen acquisition or Tesla's 2025 tariff risks. Across all Sections, 62–64% of a Tracked Company's Filing repeats the previous Filing of the same Form Type: about 90% of Controls and Procedures, 80–85% of Unsectioned text, 79–87% of Risk Factors, but only 53% of MD&A and 55–58% of the Financial Statements, where the figures change.
- **Implication:** Similarity retrieval over a Tracked Company returns the same paragraph from up to 16 Filings. Unchecked, near-identical chunks would fill the context budget of finding 15 and crowd out other Companies and the few paragraphs that actually changed.
- **Design decision:** Deduplicate at index time: within each Company, store a chunk whose normalised text (or near-duplicate key, e.g. MinHash over the same shingles) matches an earlier one once, with the list of Filings and Report Periods it appears in, so citations can still name the latest. Diversify at query time: drop near-duplicate retrieved chunks before building the Answer Call prompt, keeping the most recent Report Period unless the question names a period. For "how have the risks changed" questions, compare consecutive 10-K Risk Factors and favour paragraphs that are new in each.

## 18. The example questions are answerable, each with a caveat

_Analysis 8: coverage of the example questions (8.1–8.4)._

- **Finding:** Each example question traces to specific Filings and Sections. Apple, Tesla and JPMorgan's risk factors come from Item 1A of `AAPL_10-K_2025-09-27`, `TSLA_10-K_2025-12-31` and `JPM_10-K_2025-12-31` (68,000–112,000 characters each); Apple's later 10-Q only reports no material changes. NVIDIA's "last two years" resolves to eight Filings, Report Periods 28 January 2024 to 26 October 2025 (Q4 FY2024 to Q3 FY2026), each with a full MD&A. "The major pharmaceutical companies" resolves through the Sector table to AbbVie, J&J, Lilly, Merck and Pfizer, whose regulatory content sits in Risk Factors, Business and MD&A. Five variant questions (a JPMorgan trend, a Meta trend, the major banks, the oil majors, General Electric) hit the same gaps: a trend asked of a Snapshot Company (JPMorgan has four 2025 Filings), MD&A and financial statements found only by falling back to the whole Filing (JPMorgan, Chevron, ExxonMobil), sector phrases that could reasonably include one or two more Companies (Goldman Sachs and Morgan Stanley are Capital Markets, not Banks), and a stale Filing of a different legal entity (GE Capital, 2014).
- **Implication:** The Corpus supports the kinds of question the Client gave, but almost every answer needs to say something about its coverage. The three Risk Factors Sections of the first question alone hold about 263,000 characters, far more than a single Answer Call should carry.
- **Design decision:** Every gap has a fixed way of being stated in an answer (the table in analysis 8.6), e.g. "Trend unavailable: JPMorgan is a Snapshot Company. The Corpus holds four JPMorgan Filings, Q1–Q4 2025, so this answer covers 2025 only." The Answer Call receives, for each Company in scope, its coverage class and the Filing IDs, Report Periods and Fiscal Periods it is given, and is told to state these gaps and never fill them from general knowledge. Sector phrases resolve through the Sector table's industry column, and the answer names the Companies it covers. Retrieval budgets the context per Company and picks passages, never whole Sections. A 10-Q that says "no material changes" to its risk factors is cited as such.

## 19. "Latest" and "the last two years" depend on the Company and the anchor

_Analysis 8: coverage of the example questions (8.2, 8.5)._

- **Finding:** The last Filing Date in the Corpus is 19 February 2026. Each Company's latest 10-K covers a year ending between March and December 2025 for 35 Companies, but 12 December year-end Companies (including AbbVie, Merck, Pfizer, Bank of America, Chevron and Coca-Cola) have no FY2025 10-K, five January year-end Companies (NVIDIA, Walmart, Salesforce, Home Depot, Target) last reported a year ending in January or February 2025, BlackRock's latest is FY2023 and GE's is GE Capital's FY2014. Anchored on each Company's latest Report Period, "the last two years" holds eight Filings for every Tracked Company; anchored on today's date (October 2026) it would hold only four or five.
- **Implication:** A cross-Company comparison built on "the latest 10-K" silently compares different years: every comparison tried in analysis 8 mixed periods (Apple's FY2025 ended in September, Merck's latest is FY2024 while Lilly's is FY2025). A time window anchored on the calendar would throw away half of the Corpus's trend data.
- **Design decision:** Rule-based query parsing anchors time phrases on each Company's latest Report Period in the Corpus: "latest" is the latest 10-K plus the 10-Qs after it, and "the last two years" is the Filings in the two years up to the latest Filing (with a week's slack for 52/53-week years). Every answer names each Company's Report Period and Fiscal Period, and says when compared periods differ. Raised with the Client in question 6.

## 20. Forward guidance is not in 10-K or 10-Q Filings

_Analysis 8: coverage of the example questions (8.2)._

- **Finding:** NVIDIA gives its revenue outlook in its quarterly earnings releases, which are not in the Corpus. The word "outlook" appears in one NVIDIA Filing, the Q2 FY2023 10-Q (outside the two-year window), and only to warn that the outlook "provided on August 24, 2022" may not be met. Forward-looking content in the Filings is qualitative: MD&A commentary on demand, supply and export controls, and the risk factors.
- **Implication:** "How has NVIDIA's growth outlook changed?" cannot be answered with the guidance figures a PE analyst would expect. An LLM asked for an outlook would be tempted to supply remembered guidance that is not in the Corpus.
- **Design decision:** The Answer Call is told that guidance figures are not in the Filings. An outlook question is answered from MD&A commentary and risk factors, and the answer says so: "NVIDIA's own revenue guidance is not in the Filings provided; the outlook below is drawn from MD&A commentary and risk factors." Raised with the Client in question 7.

## 21. Revenue can be extracted exactly from every Tracked Company Filing

_Analysis 7: whether Financial Facts can be extracted (revenue)._

- **Finding:** A rule-based extractor reads a revenue figure from all 197 Filings of the 13 Tracked Companies (100% coverage), and every value equals the SEC XBRL company-facts value for the same Filing (matched on accession number, period end and a three- or twelve-month period) to the dollar (100% accuracy; the stated tolerance is under one printed unit, $1 million for a table in millions). Eight values read by hand from the Filing text (one each for Apple, Microsoft, Coca-Cola, ExxonMobil, J&J, Pfizer, Alphabet and NVIDIA) agree with both. The layouts the rules have to handle vary: eight different revenue labels ("Total net sales", "Net Operating Revenues", "Sales to customers", "Total revenues and other income"…), the current year in the first or the last column (Alphabet's recent 10-Qs), note-reference and percent-of-sales columns, the scale in the title, a header row or capitals, and revenue below its parts. The SEC's own tagging is not uniform either: Alphabet and Pfizer move between `Revenues` and `RevenueFromContractWithCustomerExcludingAssessedTax` from one Filing to the next. A 10-K reports the fiscal year, so a quarterly series has to derive the fourth quarter (NVIDIA's Q4 FY2025: $39.3bn).
- **Implication:** Revenue trend questions for Tracked Companies can be answered from exact, cited figures instead of asking the Answer Call to read flattened tables. The rules were written against these 13 Companies, so the result says nothing yet about the 41 Snapshot Companies, and it covers revenue only.
- **Design decision:** Keep the Financial Facts seam (`edgar_rag.financial_facts`), separate from the Corpus seam. Each Financial Fact carries its Filing ID, Report Period, label as printed and position in the body, so the Answer Call can cite the row. For a revenue trend question the rule-based query parser selects the Company's facts for the window and puts them in the Answer Call's context as a small table, next to the retrieved MD&A text, deriving fourth quarters from the 10-K and saying so. The extractor returns nothing rather than a guess when a step is ambiguous. The SEC data is an evaluation reference only, cached under `data/derived/` by `make sec-facts`, and never an answer source. Whether to persist facts in a SQLite store is decided in the Financial Facts ADR, after net income and segment revenue are measured the same way.
