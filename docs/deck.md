---
marp: true
theme: default
paginate: true
size: 16:9
title: SEC Filings research workspace
description: The presentation around the demo, from the Client's problem to the future state.
style: |
  section { font-size: 24px; padding: 48px 64px; }
  h1 { font-size: 40px; }
  h2 { font-size: 32px; }
  table { font-size: 19px; }
  blockquote { position: absolute; bottom: 28px; left: 64px; right: 64px; font-size: 14px; border: none; padding: 0; color: #666; }
  section.lead { justify-content: center; }
  section.lead h1 { font-size: 52px; }
---

# Answers from the Filings, in seconds, with every claim cited
<!-- _class: lead -->

A research workspace for the Client's analysts: ask a business question about a public Company, get a structured answer grounded in its 10-K and 10-Q Filings.

- One LLM request per question, the Answer Call; everything before it is deterministic
- Every claim cites the passage it came from
- Every gap in the data is stated, never filled from memory

> The brief: [AI-RAG Assessment](AI-RAG%20Assessment.md)

<!--
Speaker notes. Frame this as a client meeting, not a code review. The three bullets are the
promises the rest of the deck backs with evidence: one call (the Client confirmed it is a
hard requirement), citations, and stated gaps.
-->

---

# The Client's problem: Filings are long, repetitive and uneven

- **Too long to read per question.** A median 10-K is about 98k tokens and a median 10-Q 44k; JPMorgan's FY2025 10-K alone is 323k. The Corpus is about 17.2M tokens.
- **Mostly repeated.** Most text repeats from one period to the next, so the new risk or the changed outlook is buried.
- **Uneven coverage.** 246 Filings from 54 Companies, but only 13 Companies have the two years of quarters a trend question needs. The other 41 are Snapshot Companies.
- **Outside the stated range, kept and called out.** 47 Filings are from 2022, and the only GE Filing is GE Capital's FY2014 10-K. The Client agreed we keep them and call them out: every citation shows its Report Period, and the GE Capital Filing is flagged as stale.

> Sources: [EDA findings](findings.md), [assumptions 3 and 4](assumptions.md)

<!--
The brief's example questions span three Companies and two years. An analyst answering
"How has NVIDIA's revenue and growth outlook changed over the last two years?" by hand reads
eight quarterly Filings. The 2022 Filings and the GE Capital Filing are the Client-confirmed
answer to question 3 of the email.
-->

---

# The value case: hours of reading become a checked answer

| | What the analyst gets | Evidence (holdout run) |
|---|---|---|
| **Analyst hours per question** | A 300–600 word answer, the direct answer first, then per Company | 9.5 s per answer, first text after 3.1 s, $0.0030 per answer |
| **Stated Coverage Gaps** | Snapshot trends, missing Companies, the stale Filing, missing guidance and differing periods, in fixed words | Every expected gap stated: 1.00 |
| **Auditable citations** | Every `[Sn]` opens its Filing, Section, Report Period and passage | Citations valid 1.00, Faithfulness 0.95 |

The Answer Call reads about 25,500 tokens chosen from the Filings, where one median 10-K is about 98k.

**To agree with the Client:** questions asked per week and hours per question today. Hours saved = questions × (hours reading today − minutes checking the cited Sources).

> Sources: [the holdout run](evaluation.md#the-holdout-run), [EDA findings](findings.md)

<!--
Do not quote an hours-saved figure we have not measured: the inputs are the Client's.
The defensible numbers are the measured ones: the answer's speed and cost, and that the
answer is checkable (every citation opens the passage) and honest about what is missing.
-->

---

# Demo hand-off: one question, end to end

question → **rules** resolve the Query Scope (Companies, Sector phrase, time window, Section, metric) → **FTS5 retrieval** of deduplicated passages per Company → **Financial Facts** for exact figures → **one Answer Call**

1. **The brief's first question** (Apple, Tesla, JPMorgan risks): the Query Scope chips, a comparison table, click `[S3]` to open the passage. Follow up: "Which of them has the most regulatory exposure?"
2. **NVIDIA's revenue and outlook**: figures from the Financial Facts table, and the gap that guidance is not in the Filings.
3. **JPMorgan's revenue over two years**: a Snapshot Company, so the answer says it cannot show a trend.
4. **JPMorgan and Wells Fargo**: Wells Fargo is named as missing, never answered from memory.
5. **The panel's own question**, then the "How it works" page.

> Sources: [README: running the full stack](../README.md#running-the-full-stack), [ADR 0003](adr/0003-follow-ups-inherit-query-scope-by-rules.md)

<!--
Run `make dev` before the meeting and open http://localhost:3000. Items 1 to 4 are starter
prompts, and every starter is a Golden Set case, so each one is measured. For the panel's
own question, point at the Query Scope chips first: they show what the rules understood.
-->

---

# Evaluation: the final holdout numbers

The final configuration (FTS5, `gpt-6-luna`, prompt v7) was scored once on the holdout split, after every choice was made on dev. The Golden Set has 30 labelled questions: 20 dev, 10 holdout.

| Retrieval | | Answers | |
|---|---|---|---|
| hit@10 | 0.90 | Fact Recall (Jev) | 0.67 |
| recall@10 | 0.88 | Faithfulness (Jev) | 0.95 |
| MRR | 0.72 | Citations valid | 1.00 |
| | | Figures exact | 0.90 |
| | | Coverage Gaps stated | 1.00 |
| | | $ per answer, latency | $0.0030, 9.5 s |

In line with dev (Fact Recall 0.62 to 0.65, Faithfulness 0.90 to 0.95, hit@10 0.88): the dev choices did not overfit badly.

> Sources: [the holdout run](evaluation.md#the-holdout-run), [Golden Set](golden-set.md)

<!--
Fact Recall: the share of a question's Required Facts the answer states. Faithfulness: the
share of cited claims the cited Source supports. Both judged by Jev, pinned to one version,
from neither generator's model family. The one figure failure is a growth rate the answer
computed and labelled as derived, which the check fails by design.
-->

---

# How the choices were made: fixed rules, measured on dev

- **Retrieval: FTS5 stays.** Dense embeddings, a hybrid and a cross-encoder re-ranker all reach hit@10 0.88, the same as FTS5, on the same cases (p = 1.000). None was ahead on Fact Recall, and FTS5 adds no model, no embedding call and no 300 MB matrix.
- **Generator: `gpt-6-luna` stays.** `gpt-6.1-sol`, Claude Sonnet and Claude Opus state more Required Facts (0.73 to 0.75 against 0.62), but on too few cases (p = 0.062), at 20 to 65 times the cost: $0.049, $0.081 and $0.164 per answer against $0.0025.
- **Prompt: v1 to v14, v7 kept.** Each version was written for named failing dev cases and kept only if it fixed them and fell behind on nothing. From v1 to v7: Fact Recall 0.45 to 0.65, Coverage Gaps stated 0.67 to 1.00, citations valid 0.75 to 0.90. v11 to v14 tried to keep comparisons within 600 words: the structure was followed by 0.79 of dev answers against v7's 0.80, so v7 stays.

> Sources: [Arm comparison](evaluation.md#arm-comparison), [generator comparison](evaluation.md#generator-comparison), [prompt log](prompt-iterations.md), [ADR 0008](adr/0008-fts5-stays-the-shipped-arm.md), [ADR 0009](adr/0009-gpt-6-luna-stays-the-generator.md)

<!--
The point for the panel: every choice was made by a rule written before the run, with an
exact sign test so that noise is not declared a win. Rerunning FTS5 against itself moved
scores as much as the hybrid and the re-ranker did.
-->

---

# Risks and limits

- **Small evaluation.** 10 holdout cases: one case moves a share by 0.10. The numbers show the system works, not its exact rate.
- **Answers miss facts.** Fact Recall 0.67: outlook and trend answers leave out specifics, mostly when retrieval ranks the right MD&A passage too low.
- **Follow-ups that change topic without naming a Company** inherit the earlier Companies. The Query Scope chips show it; the Golden Set measures it.
- **Computed figures.** The model sometimes computes a growth rate rather than quoting the Filing; it labels it as derived.
- **Thin coverage.** Trends only for 13 Companies; Financial Facts only revenue, net income and segment revenue; guidance mostly sits outside the Filings.
- **Our own inputs and a hosted model.** The Sector table and the list of missing Companies are curated and disclosed, not yet confirmed by the Client. The Answer Call goes to a hosted API, behind one interface a local model can replace.

> Sources: [the holdout run](evaluation.md#the-holdout-run), [ADR 0003](adr/0003-follow-ups-inherit-query-scope-by-rules.md), [assumptions 4, 5, 9 and 10](assumptions.md), [EDA findings](findings.md)

<!--
Lead with the limits before the panel finds them. Each one is either measured (the
holdout misses, the follow-up case) or stated in every answer (coverage, guidance).
-->

---

# Future state: where an investment leads

- **Live EDGAR ingestion, to fill the Coverage Gaps.** The gaps are public: FY2025 10-Ks filed after the Corpus (Pfizer, AbbVie), NVIDIA's FY2026 10-K, earlier JPMorgan Filings, and Companies such as Wells Fargo and Citigroup. Added Filings would be a labelled supplement beside the Corpus.
- **Alerts on new Filings.** The index already finds text that is new between periods; run it as each Filing lands and send the new risk factors and MD&A changes for the Companies a deal team follows.
- **Earnings-call transcripts for guidance.** Guidance is published in earnings releases and calls, not in 10-Ks and 10-Qs, so outlook questions could quote it instead of stating the gap.
- **Private-company data rooms.** The same pipeline over a target's CIM, management accounts and contracts, with the same citations and gaps. A local model can take the Answer Call when the documents cannot leave the firm.

Every one keeps the rule the Client confirmed: one generative LLM call per question.

> Sources: [assumptions 1, 2, 7 and 10](assumptions.md)

<!--
Lead with EDGAR ingestion: the Client suggested proposing it as the way to fill the gaps
the demo states. The next step after the meeting is to confirm assumptions 4 to 11 with the
Client, starting with the Sector table and the follow-up behaviour.
-->
