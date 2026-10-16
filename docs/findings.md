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
