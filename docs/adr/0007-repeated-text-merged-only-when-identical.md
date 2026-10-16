---
status: accepted
---

# Repeated text is merged in the index only when identical; near-duplicates are dropped per question

Most Filing text repeats from one period to the next (finding 17), and the spec asks for repeated chunks to be stored once at index time and near-duplicates dropped at query time. Measured on the index, only about 7% of chunks repeat word for word within a Company, because a 600-token chunk usually holds at least one small edit: a year, a figure, a reworded sentence. Merging near-duplicates in the index would save far more, but the stored text would then stand for Filings whose wording differs from it, so a citation of the FY2024 10-K could show FY2025's figures. We merge only identical chunks in the index (`chunks` holds each Company's distinct texts once, `chunk_filings` lists every Filing each appears in), and drop near-duplicates per question, among the chunks retrieved for it, where the question decides which copy to cite. A retrieved chunk is a near-duplicate when at least 80% of its 8-word shingles (the EDA's measure) are in chunks from more recent Filings or from a period the question names. It gives up its rank to the preferred chunk it shares most with. Shingles are compared over all those preferred chunks together because chunk boundaries shift between Filings, so a repeated passage is usually split across two newer chunks. No single newer chunk would contain 80% of it.

"How has it changed" questions need what is new, not the latest copy. The Corpus keeps no paragraph breaks, so the index records, for each chunk in each Filing, its runs of sentences that are at least half new since the Company's previous Filing of the same Form Type, when they add up to 30 words or more. A change question ranks those runs first and cites them from the Filing they are new in.

## Considered options

- **Content-defined chunk boundaries, so repeats line up.** Cutting chunks at sentences chosen by a hash of their text instead of by running length raised identical chunks from 6% to 7% on the five test Companies and lowered the median chunk size below 500 tokens. The edits inside chunks, not shifted boundaries, keep repeats apart.
- **MinHash or shingle near-duplicate merging at index time.** It saves the most space, but it cites one period's wording for another, which the figure and citation checks of the generation harness would rightly fail.
- **Chunk-level novelty for change questions.** A new risk paragraph of 100 words in a 450-word chunk leaves the chunk 80% old, so a threshold on the whole chunk either misses it or flags every chunk with an updated date.

## Consequences

- The index is version 3. The `filing_chunks` view joins `chunks` and `chunk_filings` back into one row per chunk per Filing.
- Exact repeats change `bm25()` statistics: a paragraph restated in 16 Filings counts once.
- On the change route, new paragraphs are cited from the Filing that added them even when later Filings repeat them. The rest of the budget is filled by the ordinary ranking, so the answer also sees the current text.
- A figure question phrased as a change ("how has revenue changed") ranks new 10-Q MD&A text, mostly updated quarterly figures, ahead of the 10-K MD&As. Figure questions are meant to go to the Financial Facts store first.
