---
status: accepted
---

# Lexical retrieval is SQLite FTS5, in the same derived file as the Financial Facts

Questions like "What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?" are answered from the Filings' prose, so the index holds every cleaned, Section-bounded chunk of text alongside the Financial Facts of ADR 0001. Retrieval applies hard filters on Company and Report Period before ranking (findings, recommendation 6), so the ranker only ever scores the chunks of a few Filings. We index the chunks in an SQLite FTS5 table with the `porter` tokenizer, in one `data/derived/` SQLite file beside the Financial Facts tables, and rank with FTS5's built-in `bm25()`. Filtering and ranking are then one SQL query, the core package stays on the standard library, and the whole index is one file to rebuild, inspect and ship. If the evaluation shows dense retrieval earns its place, chunk embeddings sit beside the file as a matrix searched by exact inner product over the filtered rows, as in the developer's portfolio project.

## Considered options

- **`rank-bm25` over a pickled index, as in the portfolio.** It ranks the whole corpus and returns positions, so metadata filters would run after ranking or need one index per filter. It also adds a dependency and a second artefact that must stay in step with the chunk list.
- **A vector database.** Nothing to justify it yet: the filtered candidate set is small enough for exact search, and dense retrieval itself is still to be measured.

## Consequences

- The `porter` tokenizer stands in for the portfolio's shared Snowball tokenizer. Query terms go through FTS5's own tokenizer, so index and query always agree.
- FTS5 query syntax treats some characters as operators, so question text is reduced to quoted terms before it reaches `MATCH`.
