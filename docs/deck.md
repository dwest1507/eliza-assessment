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

| | What the analyst gets | Evidence |
|---|---|---|
| **Analyst hours per question** | A 300–600 word answer (up to 1,000 for many Companies), the direct answer first, then per Company | 7.5 s per answer, first text after 1.9 s, $0.0030 per answer (dev) |
| **Stated Coverage Gaps** | Snapshot trends, missing Companies, the stale Filing, missing guidance and differing periods, shown below the answer | Every expected gap stated: 1.00 (holdout) |
| **Auditable citations** | Every `[Sn]` opens its Filing, Section, Report Period and passage | Citations valid 0.95, Faithfulness 0.93 (holdout) |

**An illustrative value model** ([assumption 12](assumptions.md#12-an-illustrative-value-model), not confirmed: the inputs are ours, for the Client to replace):

10 analysts × 5 questions a week × 2 hours saved × $150 an hour × 48 weeks = **about $720k a year**, against $9.63 a week of Answer Calls even at the most expensive model's price ($0.15 at the shipped one's).

> Sources: [the final round and its holdout run](evaluation.md#the-final-all-model-round-154-2026-10-21), [assumption 12](assumptions.md#12-an-illustrative-value-model)

<!--
The table is measured: the answer's speed and cost, and that it is checkable (every citation
opens the passage) and honest about what is missing. The speed and cost are the current setup's,
at reasoning effort low on the dev split; the citations and gaps are from the holdout run, scored once at the end. The value model is not: its inputs are
assumption 12, chosen by us and not confirmed. Say so, then ask the Client for their own
numbers: how many analysts, how many questions each asks a week, and how long one takes by
hand today. Even at a quarter of our hours saved, the value dwarfs the cost of the Answer
Calls.
-->
---

# Demo hand-off: one question, end to end

question → **rules** resolve the Query Scope (Companies, Sector phrase, time window, Section, metric) → **FTS5 retrieval** of deduplicated passages per Company → **Financial Facts** for exact figures → **one Answer Call**

1. **The brief's first question** (Apple, Tesla, JPMorgan risks): the short answer first, then "Show full analysis" for the comparison table, click `[S3]` to open the passage in the side panel (every retrieved Source numbered S1…SN there), then open "Sources" under the answer for the Query Scope chips. Follow up: "Which of them has the most regulatory exposure?"
2. **NVIDIA's revenue and outlook**: the short answer leads with the finding; the Coverage note below it says guidance is not in the Filings; then "Show full analysis" for the figures from the Financial Facts table.
3. **JPMorgan's revenue over two years**: a Snapshot Company, so the answer says it cannot show a trend.
4. **JPMorgan and Wells Fargo**: the answer says, where it matters, that Wells Fargo isn't in the Filings, and a Coverage note repeats it in its fixed wording; never answered from memory.
5. **The panel's own question**, then the "How it works" page.

> Sources: [README: running the full stack](../README.md#running-the-full-stack), [ADR 0003](adr/0003-follow-ups-inherit-query-scope-by-rules.md)

<!--
Run `make dev` before the meeting and open http://localhost:3000. Items 1 to 4 are starter
prompts, and every starter is an evaluation case, so each one is measured. Each answer
opens on its short answer, the two or three sentence direct answer; click "Show full analysis" before
pointing at a table or a figure, since they sit in the rest of the answer. Once the answer is
complete, its Coverage notes appear below it, then the "Sources" disclosure: its Query Scope chips
on top, then the cited Sources and a collapsed "Also retrieved". Every Coverage Gap is a Coverage
note, and the answer mentions one only where it leaves part of the question unanswered (ADR 0016).
The document icon on the right edge opens the side panel at the latest answer's S1, and clicking
it again closes it. For the panel's own question, open "Sources" under the answer first: its Query
Scope chips show what the rules understood.
-->

---

# Evaluation: the final holdout numbers

The shipped setup (keyword search, `gpt-6-luna`, the final prompt) was scored once on 20 holdout questions, kept apart from every choice, after the final round of model comparisons. Nothing changed after it.

| | Holdout (20 questions) | Dev (63 questions) |
|---|---|---|
| Passages found (hit@10) | 0.89 | 0.97 |
| Key facts stated (Fact Recall) | 0.76 | 0.74 |
| Claims backed by their citation (Faithfulness) | 0.93 | 0.97 |
| Citations valid | 0.95 | 0.90 |
| Figures exact | 1.00 | 1.00 |
| $ per answer, full answer | $0.0028, 7.0 s | $0.0030, 7.5 s |

The holdout is in line with dev, so the choices made on dev did not overfit. The answers state 78 of the holdout's 106 must-state facts; of the 28 they miss, 19 had reached the prompt, so the misses are now mostly the model's, not retrieval's.

> Sources: [the final round and its holdout run](evaluation.md#the-final-all-model-round-154-2026-10-21), [earlier holdout runs](evaluation.md#the-holdout-run), [Golden Set](golden-set.md)

<!--
Fact Recall: the share of a question's must-state facts the answer states. Faithfulness: the
share of cited claims the cited Source supports. Both judged by Jev, pinned to one version,
from neither generator's model family. On 20 questions one question moves a share by 0.05, so
read the numbers as directional. The one zero is a follow-up that changes topic without
naming a Company, ADR 0003's known weakness. Every figure is exact: from prompt v19 the answer
quotes figures and never computes them.
-->
---

# How the choices were made: nothing beat the simple setup

Every choice was tried against alternatives, on test questions kept apart from the final check, with the rule for a win written down before each run.

- **Retrieval: plain keyword search stays.** Embedding search, a hybrid of the two, a re-ranking model and two local embedding models were tried. None got the answers to state more of the key facts, and keyword search needs no extra model and no extra API call.
- **The model: `gpt-6-luna` stays.** In a final round, five other OpenAI and Anthropic models answered the same questions. Four stated more of the key facts, but each made more claims its sources don't back or contradict, at 20 times the cost or more. A smaller Claude model stated no more.
- **Passage size and how much text each answer reads: unchanged.** Smaller and larger passages, and a larger reading budget, reached more of the evidence but got no more of it into the answers than 600-token passages with a 32k budget.
- **The prompt: each version kept only if it fixed named failures or stated more of the key facts, without harming the rest.** v7 held through v14; v15 moves the Coverage Gaps out of the answer, into Coverage notes below it. v19, the final prompt, states each point in full, gives more room when more Companies are asked about, and quotes figures rather than computing them.

> Sources: [Arm comparison](evaluation.md#arm-comparison), [the final round of model comparisons](evaluation.md#the-final-all-model-round-154-2026-10-21), [prompt log](prompt-iterations.md), [version 2 comparisons](evaluation.md#the-version-2-comparisons-on-dev), [the Arm comparison on the new retrieval](evaluation.md#the-arm-comparison-on-the-new-retrieval-127-2026-10-18), [the settings comparison on the new retrieval](evaluation.md#the-settings-comparison-on-the-new-retrieval-129-2026-10-18), [ADR 0008](adr/0008-fts5-stays-the-shipped-arm.md), [ADR 0009](adr/0009-gpt-6-luna-stays-the-generator.md), [ADR 0011](adr/0011-one-sided-thresholds-and-a-control-run.md), [ADR 0016](adr/0016-coverage-gaps-shown-by-the-product.md)

<!--
The statistics, for a technical panelist who asks. Every choice was made by a rule written
before the run, with an exact one-sided test so that noise is not declared a win (ahead at
p < 0.10, behind on a guardrail at p < 0.20), and each comparison beside a Control Run, the
shipped setup run again, to show the noise.

Retrieval and the settings: embeddings, a hybrid, a re-ranker, two local embedding models,
other passage sizes and a 48k budget were each compared fact by fact on the dev questions. None
got the answers to state more must-state facts by enough to pass the rule, so keyword search,
600-token passages and the 32k budget stay.

Generator, the final round on the frozen code (63 dev questions, every model at reasoning
effort low): the Control Run, `gpt-6-luna` again, was not ahead (p = 0.124). `gpt-6.1-sol` was
ahead on Fact Recall (19 questions higher, 8 lower, p = 0.026) but behind on Contradicted
Claims (7 answers with one against 2, p = 0.109); terra was ahead (20 and 3) but behind on
Faithfulness (p = 0.115) and on the gaps it acknowledged (p = 0.188); Claude Sonnet 5.5 and
Opus 5.5 were ahead (24 and 3; 26 and 7) and behind on Faithfulness and Contradicted Claims;
Claude Haiku 5.5 was not ahead (p = 0.229). Per answer they cost $0.0592, $0.0622, $0.0934,
$0.1925 and $0.0050, against $0.0030.

Prompt: v19, read over two runs a side: its answers state 242 of 334 must-state facts a run
against v15's 232 (p = 0.085), and fail the figure check in 0.5 cases a run against 2.5.
-->
---

# Risks and limits

- **Small evaluation.** 20 holdout questions: one moves a share by 0.05. The numbers show the system works, not its exact rate.
- **Answers miss facts.** Fact Recall 0.76 on the holdout: the answers miss 28 of 106 must-state facts, 9 of them because their evidence never reaches the prompt and 19 although it does.
- **Follow-ups that change topic without naming a Company** inherit the earlier Companies. The Query Scope chips, at the top of each answer's "Sources", show it; the Golden Set measures it.
- **Figures are quoted, not computed.** From prompt v19 the answer quotes each figure as the Filing or the table states it, so a change the Filings don't state is left out; in the final round every figure checked was exact, on dev and on the holdout.
- **Thin coverage.** Trends only for 13 Companies; Financial Facts only revenue, net income and segment revenue; guidance mostly sits outside the Filings.
- **A small human check.** Claude drafted the evaluation's labels and labelled the judge study. The developer checked 15 fact labels blind: agreement 80% with Claude's labels and 87% with Jev's verdicts. The claim labels (Faithfulness, Contradicted Claims) are still Claude's alone. Accepted for a demo; production would use more hand-labelled data.
- **Our own inputs and a hosted model.** The Sector table and the list of missing Companies are curated and disclosed, not yet confirmed by the Client. The Answer Call goes to a hosted API, behind one interface a local model can replace.

> Sources: [the final round and its holdout run](evaluation.md#the-final-all-model-round-154-2026-10-21), [prompt v19](evaluation.md#v19-the-combination-that-freezes-165-2026-10-21), [ADR 0003](adr/0003-follow-ups-inherit-query-scope-by-rules.md), [assumptions 4, 5, 9 and 10](assumptions.md), [EDA findings](findings.md), [ADR 0013](adr/0013-jev-stays-the-judge-checked-by-a-judge-study.md), [the human check](evaluation.md#the-human-check)

<!--
Lead with the limits before the panel finds them. Each one is either measured (the
holdout misses, the follow-up case) or stated in every answer (coverage, guidance).
-->

---

# Future state: where an investment leads

- **Live EDGAR ingestion, to fill the Coverage Gaps.** The gaps are public: FY2025 10-Ks filed after the Corpus (Pfizer, AbbVie), NVIDIA's FY2026 10-K, earlier JPMorgan Filings, and Companies such as Wells Fargo and Citigroup. Added Filings would be a labelled supplement beside the Corpus.
- **Alerts on new Filings.** The index already finds text that is new between periods; run it as each Filing lands and send the new risk factors and MD&A changes for the Companies a deal team follows.
- **Earnings-call transcripts for guidance.** Guidance is published in earnings releases and calls, not in 10-Ks and 10-Qs, so outlook questions could quote it instead of stating the gap.
- **Passage-level citations.** A citation names a Section of a Filing today; pointing it at the passage that states the claim makes every check one click.
- **Private-company data rooms.** The same pipeline over a target's CIM, management accounts and contracts, with the same citations and gaps. A local model can take the Answer Call when the documents cannot leave the firm.

Every one keeps the rule the Client confirmed: one generative LLM call per question.

> Sources: [assumptions 1, 2, 4, 7 and 10](assumptions.md), [ADR 0001](adr/0001-sqlite-financial-facts-store.md)

<!--
Lead with EDGAR ingestion: the Client suggested proposing it as the way to fill the gaps
the demo states. The next step after the meeting is to confirm assumptions 4 to 11 with the
Client, starting with the Sector table and the follow-up behaviour.
-->
