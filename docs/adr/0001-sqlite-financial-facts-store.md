---
status: accepted
---

# Build a SQLite Financial Facts store, queried deterministically before the Answer Call

Trend and comparison questions about figures ("How has NVIDIA's revenue changed over the last two years?") are among the Client's example questions, and the figures sit in flattened tables that chunk retrieval and the Answer Call read poorly. Analysis 7 of the EDA measured whether rules can extract them as Financial Facts over all 197 Filings of the 13 Tracked Companies. Revenue and net income were extracted from every Filing (100% coverage), and every value equals the SEC XBRL company-facts value for the same Filing and period to the dollar (100% accuracy), confirmed by 14 values checked by hand. Segment revenue was extracted from 101 Filings (51%), covering 7 of the 13 Companies, and, once segment tables laid out in columns were read too, from 137 Filings (70%) covering 10 Companies. Every extracted set adds up to the SEC-matched revenue, and 16 values checked by hand agree. The other 3 Companies lay their segments out in ways the rules don't read, and the SEC data has no segment breakdown to measure against.

We will build a SQLite Financial Facts store holding the revenue, net income and segment revenue of the Tracked Companies. It is rebuilt from the Corpus by the `edgar_rag.financial_facts` seam at index time, and is gitignored under `data/derived/` like the other derived files. The rule-based query parser that runs before the single Answer Call recognises the metric, the Companies and the time window. It then runs one of a fixed set of parameterised queries, and puts the resulting rows into the Answer Call's context as a small table next to the retrieved text. Each row carries its Filing ID, Report Period, Fiscal Period and the label as printed, so the answer can cite it. The SEC data is never loaded into the store and never used as an answer source.

## Considered options

- **Text-only retrieval.** The Answer Call reads figures from retrieved table chunks. A two-year quarterly trend needs the income statement of eight Filings, which costs a large share of the context budget (finding 15). The model would also have to line up periods, scales and columns that analysis 7 shows vary by Company: the current year comes first or last, the scale is in the title or a header row, the figures sit beside percent-of-sales columns, and net income comes as a total or the part attributable to the Company. Every one of those is a chance to misread a number that the rules now read exactly.
- **A SQLite Financial Facts layer, queried deterministically (chosen).** Exact, cited figures at a few hundred tokens per question. It works under the single-call rule because choosing and running the query is rule-based and needs no LLM.
- **Text-to-SQL.** An LLM writes the query from the question. This needs a second generative call before the Answer Call, which the single-call rule (exactly one generative LLM call per question) rules out.
- **Facts held in memory at API start-up, no store.** This avoids SQLite, but parses all 246 Filings on every start and leaves the facts nowhere to inspect. SQLite is in the Python standard library, so a file costs nothing extra.

## Consequences

- **Coverage is explicit, and the fallback is text.** The store answers only what it holds. Segment questions for J&J, Pfizer, UnitedHealth and ExxonMobil before 2025, any other metric, and every Snapshot Company fall back to retrieved table and MD&A chunks. In those cases the answer says the figure was read from the Filing text, not from extracted Financial Facts.
- **Snapshot Companies stay out until measured.** The rules were written against the Tracked Companies, so their accuracy on the 41 Snapshot Companies is unknown. Adding those Companies means measuring them against the SEC reference first, in the same way.
- **Derived figures are computed, not stored.** A 10-K reports the fiscal year, so a fourth quarter is derived as the year less its three 10-Q quarters when a quarterly series needs it, and the answer says so. The same applies to growth rates.
- **Segments are compared only within one set of segments.** Disney reorganised its segments in FY2023 and Coca-Cola dropped Global Ventures as a segment in 2025, so a segment trend stops at the change and says so.
- **The query parser grows a metric vocabulary.** "Revenue", "sales" and "top line" map to revenue; "net income", "earnings" and "profit" map to net income; a segment name maps to that segment. A question the parser can't map gets no facts and is answered from text alone.
