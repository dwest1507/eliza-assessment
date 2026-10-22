# Market context

The few outside figures the [slide deck](deck.md) quotes, each checked against its primary source on 2026-10-22, with the caveat a skeptical reader would raise. Everything else in the deck is our own measurement ([evaluation](evaluation.md)) or our own illustrative assumption ([assumptions 12 and 13](assumptions.md#12-an-illustrative-value-model)).

## AI in M&A: adopted, but not yet trusted

Deloitte, *GenAI in M&A, 2026 Pulse Survey*: 500 US PE, portfolio company and corporate M&A leaders, surveyed online May 14–27, 2026 ([PDF](https://www.deloitte.com/content/dam/assets-zone3/us/en/docs/services/merger-and-acquisitions/2026/gen-ai-pluse-survey.pdf)).

- **90%** "report using GenAI to some degree in their M&A operations". Of all respondents, 37% use AI across multiple stages of the deal life cycle, 33% in limited use cases and 20% are experimenting or piloting.
- **59%** name "Outputs require significant manual validation" among the top three challenges with their current tools, the most cited; 67% cite "Unclear accountability for AI-generated content; inaccurate or inconsistent outputs" as a risk they have observed.
- Human review by functional experts is the most chosen requirement for relying on AI in high-stakes decisions (24%).

Caveats: Deloitte sells M&A advisory, and its survey data is "not validated"; the 90% counts firms only piloting; the challenge shares are read from the chart's order, the top two confirmed by the report's text. The 2025 edition (1,000 leaders, "86%" integrated into M&A workflows) is superseded by this one.

## How long a filing takes to read

An estimate, from our own Corpus and a published reading speed:

- The median 10-K in the Corpus is 69,909 words, **about 70,000 words**, and the median 10-Q 30,371 (counted on the Corpus's text files, tables included, so an upper bound on the prose).
- Adults read English non-fiction silently at **238** words a minute on average (Brysbaert, "How many words do we read per minute?", *Journal of Memory and Language* 109, 2019, a meta-analysis of 190 studies; [author's manuscript](https://reader.ku.edu/sites/reader/files/2024-01/How%20many%20words%20do%20we%20read%20per%20minute%20(1).pdf)).
- So one median 10-K takes **about 5 hours** to read once (69,909 ÷ 238 ≈ 294 minutes), and a 10-Q about 2 hours, before any comparing or writing. Our arithmetic, not a measured analyst time.

Caveat: an analyst skims and reads only the Sections a question needs. A median 10-K's Risk Factors are about 12k tokens and its MD&A 13k ([finding 15](findings.md)), roughly 40 minutes each, so a question comparing three Companies' risks reads about two hours of text. Measured expert time on single, narrower filing questions is shorter: Vals AI's Finance Agent paper reports 16.8 minutes a question for experts with search tools ([arXiv 2508.00828](https://arxiv.org/abs/2508.00828)). That is why the value model assumes 1 hour saved, not more ([assumption 12](assumptions.md#12-an-illustrative-value-model)).

## How well the best AI answers filing questions

Vals AI, *Finance Agent Benchmark* v2.1, updated 2026-10-19 ([leaderboard](https://www.vals.ai/benchmarks/fabv2-1)): 449 private questions on public company filings, written to the standard of a 2nd or 3rd-year investment banking analyst, answered with EDGAR and web search tools.

- "As of October 19, 2026, Claude Opus 5.5 ranks first on Finance Agent with **67.85%**", partial credit.
- On the strict measure, every check passing, the best system (Gemini 4 Argon) gets **58.87%** fully right, so more than 4 in 10 of these questions are not (read from the page's chart data).
- `gpt-6-luna`, our answer model, scores 56.84% (partial credit) and 43.78% (every check passing) there, on a harder task than ours: it searches for its own filings, where ours are retrieved for it.

Caveats: the tasks chain several filings with live search, unlike answering from Sources handed to the model; an LLM jury grades, including vendors on the leaderboard. The point it supports: even the best systems get a meaningful share of filing questions wrong, so quality has to be measured on the firm's own questions. It replaces FinanceBench (2023), now outdated.

## Changes in filing language carry signal

Cohen, Malloy and Nguyen, "Lazy Prices", *Journal of Finance* 75(3), 2020, pp. 1371–1415 ([DOI 10.1111/jofi.12885](https://doi.org/10.1111/jofi.12885); [NBER working paper](https://www.nber.org/papers/w25084)). Over 1995–2014, changes to the language of 10-Ks and 10-Qs predicted future returns, earnings and even bankruptcies, and markets did not react when the filings came out ("suggesting that investors are inattentive"). A portfolio long "non-changers" and short "changers" earned **34–58 basis points a month** overall (value-weighted), and up to **188** basis points a month on changes to the Risk Factors section alone.

Caveats: the 188 is the best of many specifications, which the authors call "suggestive but not definitive"; it is a public-equity trading result, published in 2018 and possibly arbitraged since; it shows that filing changes carry signal, not that alerts earn alpha.
