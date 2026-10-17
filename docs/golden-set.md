# Golden Set

The Golden Set is the evaluation's ground truth: 30 labelled questions that the retrieval and generation harnesses score the system against. It lives in [`data/eval/golden_set.json`](../data/eval/golden_set.json) and is read by `edgar_rag.golden_set.load_golden_set()`, which checks the schema. It was written before any retrieval Arm or prompt ran, so no label was written with results in view.

## What it covers

| Question type | Cases | What it tests |
|---|---|---|
| `risk` | 9 | Risk comparisons across Companies, single-Company risk questions, and the Legal Proceedings and Market Risk Sections |
| `figure_trend` | 6 | Revenue, net income and segment revenue over named years or "the last two years" |
| `sector` | 5 | Sector phrases resolved through the Sector table: pharmaceutical companies, banks, software companies, aerospace and defense, oil majors |
| `missing_company` | 4 | Companies not in the Corpus (Wells Fargo, Citigroup, Bristol Myers Squibb, Honeywell) |
| `outlook` | 4 | Outlook questions. Three have no guidance in the Filings; Meta's expected 2026 capital expenditures are in its 10-K |
| `stale_filing` | 2 | The GE Capital FY2014 Filing, asked about as General Electric today and as GE Capital in 2014 |

The cases are seeded from the eight questions traced in EDA analysis 8 (the brief's three examples and variants V1 to V5) and add the question types and Sections the spec names.

**Multi-turn cases.** Six cases have a scripted history: earlier user messages and fixed earlier answers that cite Filing IDs, the way the Answer Call's prompt rewrites earlier Source tags. They test the follow-up rules of [ADR 0003](adr/0003-follow-ups-inherit-query-scope-by-rules.md):

- Inheriting the Companies: "Which of them has the most regulatory exposure?" and "How did that change over the last two years?"
- Switching the Company: "And what about Microsoft?", "And the oil majors?" and "What about Honeywell?"
- A change of topic that names no Company (`followup-topic-change-export-controls`, tagged `topic_change_without_company`). The rules wrongly inherit Apple from the earlier question. The case expects the whole-Corpus answer (NVIDIA and AMD), so it measures ADR 0003's known weakness rather than hiding it.

**Starter prompts.** The six cases with a `starter` object are the front-end's starter prompts. `order` sets their position and `label` is the button text. They are the brief's three example questions, a sector phrase (the major banks), a Coverage Gap (JPMorgan's revenue trend, a Snapshot Company) and a Company missing from the Corpus (Wells Fargo). Every starter is therefore measured, and none was picked after seeing results.

## Fields

The file holds `version`, `split_rule` and `cases`. Each case has:

| Field | Meaning |
|---|---|
| `id` | Stable, unique case id. The split is computed from it. |
| `question` | The latest user message, the one the Answer Call answers |
| `history` | Earlier turns, oldest first, as `{role, content}` with role `user` or `assistant`. Always ends with an assistant answer. Empty for a single-turn case. |
| `question_type` | One of `risk`, `figure_trend`, `sector`, `outlook`, `missing_company`, `stale_filing` |
| `split` | `dev` or `holdout`, as computed by the split rule |
| `starter` | `{order, label}` for a starter prompt, else `null` |
| `tags` | Free labels for case features: `brief_example`, `inherits_companies`, `switches_company`, `topic_change_without_company` |
| `notes` | Why the case exists and what makes it hard |
| `expected_sources` | The (`filing_id`, `section`) pairs that should reach the Answer Call. These are what hit@k, recall@k and MRR are scored against. Empty when nothing should be retrieved (a Company missing from the Corpus, GE today). |
| `required_facts` | What a good answer must state. Each is `{fact, filing_id, section, evidence}`: a self-contained sentence naming its Company, the Filing and Section that support it, and a quote from that Section. |
| `expected_coverage_gaps` | The Coverage Gaps the answer must state, as `{kind, companies}`. Companies are tickers, or names for Companies missing from the Corpus. |

Coverage Gap kinds follow EDA notebook section 8.6:

| Kind | When |
|---|---|
| `snapshot_trend` | A trend is asked of a Snapshot Company |
| `missing_company` | A named Company is not in the Corpus |
| `stale_filing` | The answer would rest on GE Capital's FY2014 Filing |
| `no_guidance` | An outlook question whose guidance is not in the Filings |
| `periods_differ` | The compared Companies' latest Filings cover different periods |

The generation harness checks only the gaps listed. A system that states an extra gap is not penalised by the Golden Set; Faithfulness judging covers whether it was warranted.

Section names are the Corpus seam's standard names (`Risk Factors`, `MD&A`, `Legal Proceedings`, `Market Risk`, and so on). Where a Filing has no Item heading for the text, the label names the Section the text actually sits in: JPMorgan's 10-Q financial review is `Unsectioned`, and its 10-K's financial review comes after Item 15, in `Other`.

## The split rule

Sort the case ids by the SHA-256 hex digest of each id (UTF-8). The first third, rounded to the nearest whole case, are holdout; the rest are dev. That gives 10 holdout cases and 20 dev cases.

The rule is written in the file (`split_rule`), each case records its split, and a test recomputes the split from the ids and checks it matches. Prompt and Arm choices are tuned on dev only, and the holdout is scored once per final setup and never used to choose ([the holdout rule](evaluation.md#the-holdout-rule)).

The first rule tried was a per-case threshold: holdout when the hash modulo 10 is 7, 8 or 9, about 30% of cases. On these 30 ids it put only 5 cases in the holdout, too few to score. It was replaced by ranking before any Arm or prompt had run, so no score could have influenced the change. Ranking keeps the holdout at exactly a third. The cost is that adding a case can move one other case across the boundary, so cases should not be added after the holdout has been scored.

## How the cases were drafted and reviewed

No second human was available to label, so an agent drafted every case from the Corpus and the review was made mechanical where it could be.

1. **Drafted from the Corpus, not from memory.** For each question, the agent resolved the Query Scope by the rules the spec sets: Companies and Sector phrases through the Sector table, "latest" as the latest 10-K plus later 10-Qs, "the last two years" anchored on each Company's latest Filing (assumption 6). It then searched the cleaned Sections of those Filings for the passages that answer it. Every Required Fact was written from a passage that was read, and its evidence quote was copied from that passage.
2. **Checked by tests** (`backend/tests/test_golden_set.py`):
   - the schema is valid, ids are unique, and every question type is covered;
   - every expected Filing ID exists in the Corpus and has a Section of the expected name;
   - every evidence quote is found verbatim in a Section of that name in that Filing, after collapsing runs of whitespace (flattened tables and non-breaking spaces vary only in whitespace);
   - every Required Fact is a sentence that names its Company and cites one of its case's expected sources;
   - there are about six multi-turn cases, one of which changes topic without naming any Company;
   - the six starters are present in order, include the brief's three questions, and cover a sector phrase, a Snapshot trend and a missing Company;
   - the recorded split matches the rule.
3. **Reviewed by reading.** Each case was read back against its notes: is the question one an analyst would ask, are the expected Sources the ones that answer it, and is anything the answer must say missing from Required Facts or Coverage Gaps?

The tests prove that the labels point at real text. They cannot prove that the labels are complete: an answer may cite a correct Source or state a correct fact that the case does not list. Fact Recall is therefore scored against the Required Facts, while Faithfulness is judged separately from the cited passages.
