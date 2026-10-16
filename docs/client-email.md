# Client email (draft)

A draft for the developer to review and send to the Client. It has **not** been sent. It raises the questions in [`client-questions.md`](client-questions.md), numbered the same way; once it is sent, mark those questions `sent` there.

---

**Subject:** SEC filings Q&A: what we found in the data, and eleven questions before we build

Hi all,

Before building the question-answering system, we analysed the filings you sent. Mostly the data is in good shape: every filing can be dated, identified and split into its standard sections, and revenue and net income can be read exactly from the tables (they match the SEC's own XBRL data to the dollar for all 197 filings we checked). A few things differ from the brief, though, and some choices depend on what you intend. Below are the differences and eleven questions. Each question has the assumption we will work under until you tell us otherwise, so nothing is blocked while you look at them.

**Where the data differs from the brief**

- **Dates.** The brief says the filings span 2023–2025. By the period they cover, 47 filings are from 2022, and 27 more were filed in early 2026 (mostly FY2025 annual reports).
- **The "GE" filing** is not a General Electric report. It is GE Capital's 10-K for 2014, filed in 2015.
- **Coverage is very uneven.** Only 13 of the 54 companies have the two years of quarterly filings a trend question needs. 37 have a single annual report. No bank is among the 13: JPMorgan, named in your first example, has 2025 filings only.
- **"Latest" means different years for different companies.** Twelve companies, including AbbVie, Merck, Pfizer and Chevron, have no FY2025 annual report in the data, so a comparison of "latest" reports can mix years.
- **No sector information.** The filings carry no sector, so we built a disclosed, GICS-style sector table to answer questions like "the major pharmaceutical companies".
- **No guidance.** Companies publish revenue guidance in earnings releases, which are not in the data, so "growth outlook" can only come from the commentary and risk factors in the filings.

**Questions, with our working assumptions**

1. **What counts as the single LLM call?** We read it strictly: one generative call per question, hosted or local. Embedding models and rerankers are fine because they don't generate text, and question parsing before the call is rule-based.
2. **May we use data beyond the filings?** We assume no. Answers come only from the filings, plus the sector table we disclose. We use the SEC's XBRL data only to check the accuracy of figures we extract, never as an answer source.
3. **What does "2023–2025" mean?** We keep every filing and show the period it covers in every citation. The GE Capital filing is flagged as a 2014 report of a different legal entity and left out of answers about the company today. The full list of out-of-range filings is attached.
4. **What kinds of question should we expect?** We assume both trend questions about the 13 well-covered companies and point-in-time comparisons across all 54. When the data can't support a trend, the answer says so ("only 2025 filings are available for JPMorgan").
5. **Is a curated sector table acceptable, and do you agree with its choices?** We assume yes. "The major pharmaceutical companies" means AbbVie, J&J, Lilly, Merck and Pfizer (UnitedHealth and Thermo Fisher excluded). "The major banks" means Bank of America and JPMorgan (Goldman Sachs and Morgan Stanley are capital-markets firms). "The oil majors" means Chevron and ExxonMobil. The table is attached.
6. **What are "latest" and "the last two years" measured from?** From each company's latest filing in the data, not today's date. Measured from today, the well-covered companies would have only four or five quarters in the last two years instead of eight. "The last two years" is the eight quarters up to that filing. Every answer names the periods it uses and says when compared companies' periods differ.
7. **Should outlook questions be answered without guidance?** We answer from the commentary and risk factors, and say plainly that the company's own guidance is not in the filings.
8. **What should a good answer look like, and how will you judge it?** We assume an analyst reader: a short direct answer first, then points per company or a comparison table, then a note on gaps. Every claim is cited to a filing, section and period, and the answer runs to about 300–600 words. If you have reference answers or criteria, we would like to test against them.
9. **What about companies the data doesn't cover?** Some peers are missing (e.g. Wells Fargo, Citigroup, Bristol Myers Squibb). We answer for the companies that are in the data and say plainly which named companies are not. We never fill the gap from general knowledge.
10. **Are there constraints on which LLM we use?** We assume a mainstream hosted model whose terms exclude training on and retaining your data is acceptable for the demo. The model can be swapped, including for a locally hosted one.
11. **May we add public EDGAR filings to fill the coverage gaps?** The missing filings are public on SEC EDGAR: annual reports filed after the data was assembled (e.g. Pfizer's and AbbVie's FY2025 10-Ks, NVIDIA's FY2026 10-K), earlier filings for the thinly covered companies (including JPMorgan), General Electric's own recent reports, and companies not in the data at all. We assume no: we use only the filings you sent and state the gaps plainly. If you want some filled, tell us which; we would keep them as a clearly labelled supplement, separate from your data, that can be switched off for the demo.

None of these block us. If any assumption is wrong, the earlier we hear, the less we rebuild. Happy to go through them on a short call.

Best regards,
David

_Attachments: the full list of filings outside 2023–2025 (`client-questions.md`, question 3) and the sector table (`data/reference/sectors.csv`)._
