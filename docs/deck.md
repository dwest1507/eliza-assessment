---
marp: true
theme: default
paginate: true
size: 16:9
title: SEC Filings research assistant
description: The presentation around the demo, for a private equity firm deciding whether AI is worth it.
style: |
  section { font-size: 24px; padding: 48px 64px; }
  h1 { font-size: 40px; }
  h2 { font-size: 32px; }
  table { font-size: 19px; }
  blockquote { position: absolute; bottom: 28px; left: 64px; right: 64px; font-size: 14px; border: none; padding: 0; color: #666; }
  section.lead { justify-content: center; }
  section.dense { font-size: 21px; }
  section.lead h1 { font-size: 52px; }
---

# Hours of filing reading → a checked answer in seconds
<!-- _class: lead -->

A research assistant for your deal team: ask a business question about a public company, get an answer from its 10-K and 10-Q filings.

- **Every claim cited.** One click opens the passage it came from.
- **Honest about gaps.** It's built to answer only from the filings, and to say what they don't cover.
- **Measured, not promised.** Tested on questions it had never seen, against the facts a good answer must state.

> Sources: [the brief](https://github.com/dwest1507/eliza-assessment/blob/main/docs/AI-RAG%20Assessment.md), [assumption 1](https://github.com/dwest1507/eliza-assessment/blob/main/docs/assumptions.md#1-one-api-call-per-question)

<!--
Frame this as a client meeting. The three bullets are the promises the rest of the deck backs:
the demo shows the citations and the gaps, the scorecard shows the measurement.

Say aloud, as the "we listened" moment: as you asked, every answer comes from a single AI call
(assumption 1, which the Client confirmed as a hard requirement). Everything before it, finding
the companies, periods and passages, is plain rules and search, so it is fast, cheap and
predictable.
-->

---

# The problem: the answers are in the filings, but buried

- **Deal work runs on filings:** comps and valuation marks every quarter, take-private diligence, sector theses, portfolio benchmarking.
- **They're long and repetitive:** a median 10-K is about 70,000 words, about 5 hours to read once. A question across companies means several, and most of each filing repeats last year's.
- **AI is arriving, but trust isn't:** 90% of PE and M&A leaders already use AI to some degree, yet 59% say its outputs need significant manual validation (Deloitte, 2026).

**So the bar isn't "an answer". It's an answer you can check in one click.**

> Sources: [market context](https://github.com/dwest1507/eliza-assessment/blob/main/docs/market-context.md), [EDA findings](https://github.com/dwest1507/eliza-assessment/blob/main/docs/findings.md), [assumption 3](https://github.com/dwest1507/eliza-assessment/blob/main/docs/assumptions.md#3-every-filing-is-kept-whatever-its-date)

<!--
The reading time is our estimate: the Corpus's median 10-K word count over an average adult
reading speed of 238 words a minute. Nobody reads a whole 10-K for one question, but a question
comparing three companies' risks still reads about two hours of Risk Factors.

Deloitte's 2026 Pulse Survey asked 500 US PE, portfolio company and corporate M&A leaders. The
90% includes firms only piloting; 59% is the most cited challenge with their current tools.
It reassures an unsure firm that its peers are moving, and sets up why citations matter.

If asked about the data: the Corpus is 246 Filings from 54 Companies, about 17.2M tokens. Only
13 Companies have the two years of quarters a trend question needs; the other 41 are Snapshot
Companies. 47 Filings are from 2022, and the only GE Filing is GE Capital's FY2014 10-K, kept and
flagged as stale, as the Client agreed (assumption 3).
-->

---

# The value: hours back, at a fraction of the cost

**Illustrative numbers: ours, not yet yours. A pilot would set the real ones.**

| | A year |
|---|---|
| **Value:** 10 analysts × 5 questions a week × 1 hour saved × $150 an hour × 48 weeks | **about $360k** |
| Conservative: 15 minutes saved per question | about $90k |
| **Running cost, fully loaded on Azure:** mostly an engineer's time; the AI itself is under $10 | **about $46k** |
| **Return** | **about 8×**, about 2× conservatively |

**Beyond hours:** a first read on a target in minutes, more companies screened per thesis, and every claim one click from its source.

> Sources: [assumption 12](https://github.com/dwest1507/eliza-assessment/blob/main/docs/assumptions.md#12-an-illustrative-value-model), [assumption 13](https://github.com/dwest1507/eliza-assessment/blob/main/docs/assumptions.md#13-an-illustrative-running-cost), [market context](https://github.com/dwest1507/eliza-assessment/blob/main/docs/market-context.md#how-long-a-filing-takes-to-read)

<!--
Every input is ours (assumptions 12 and 13, not confirmed). Ask the Client for theirs: how many
analysts, how many questions each asks a week, how long one takes by hand today.

Why 1 hour saved: a question comparing three companies' risks reads about two hours of filing
text by hand; we net out the minutes spent checking citations, and stay well under that.

The cost is honest, not just the AI: production in the firm's own Azure tenant, with a web
firewall, private networking, monitoring and backups, is about $7,424 a year of computing, and
the answers' AI calls about $7.82 of that. The rest is people: 0.15 of an engineer to patch it,
re-test new models each quarter and support users, and a yearly security test. Expected $46k,
low $22k ($21,717), high $91k ($90,546).

Name the worst case before a partner finds it: at the high cost and 15 minutes saved, it about
breaks even. Which is why the pilot measures hours saved first: it is the one input that
decides everything.
-->

---

# Demo: three things to watch for
<!-- _class: dense -->

1. **Exact figures, and you see what an answer can draw on.** NVIDIA's revenue and outlook over two years, then its Calendar: every quarter, its filing and its revenue.
2. **Every claim is one click from its source.** The risks of Apple, Tesla and JPMorgan compared, then a follow-up.
3. **It says what's missing instead of filling it in.** JPMorgan and Wells Fargo, then "What's covered".

> Sources: [README: running the full stack](https://github.com/dwest1507/eliza-assessment/blob/main/README.md#running-the-full-stack), [ADR 0003](https://github.com/dwest1507/eliza-assessment/blob/main/docs/adr/0003-follow-ups-inherit-query-scope-by-rules.md), [ADR 0016](https://github.com/dwest1507/eliza-assessment/blob/main/docs/adr/0016-coverage-gaps-shown-by-the-product.md)

<!--
Run `make dev` before the meeting and open http://localhost:3000. Each question is a starter
prompt, and every starter is an evaluation case, so each one is measured. Each answer opens on its
short answer; click "Show full analysis" before pointing at a table or a figure.

1. Click "How has NVIDIA's revenue and outlook changed?". The answer leads with the finding,
   the figures come from the Financial Facts table, and the Coverage note below it says guidance
   is not in the filings. The Calendar tab opens on NVDA by itself: every fiscal quarter, the
   filing that covers it and its revenue, a derived fourth quarter marked as derived. "You can
   see at a glance which periods an answer can draw on."
2. Click "Compare the risk factors of Apple, Tesla and JPMorgan". Click a citation such as [S3]:
   the passage opens in the side panel. Open "Sources" under the answer for what the rules
   understood (the companies, periods and sections). Follow up: "Which of them has the most
   regulatory exposure?"
3. Click "Compare JPMorgan and Wells Fargo". The answer says Wells Fargo isn't in the filings,
   and a Coverage note repeats it; it doesn't fill in Wells Fargo's side. Then open "What's
   covered" and search "Wells Fargo" (listed as not covered) and "JPMorgan" (latest filing only). "This is
   exactly what live EDGAR ingestion fills in."

Take the panel's own question only if they ask.
-->

---

# How we know it works

**Tested on 20 questions it never saw until the end:**

- **Completeness:** states about 76% of the key facts a good answer needs
- **Reliability:** about 93% of claims are backed by the passage they cite
- **Figures:** every figure exact; it quotes the filing and never does its own math
- **Says what's missing:** names what the filings can't answer instead of filling it in
- **Cost and speed:** under a cent and about 7 seconds an answer

*How:* 83 questions, each written with the facts a good answer must state. An independent AI judge grades every answer, and we checked a sample of its grades by hand. Fancier search options didn't produce better answers, so we kept the simple, cheap one.

> Sources: [the final round and its holdout run](https://github.com/dwest1507/eliza-assessment/blob/main/docs/evaluation.md#the-final-all-model-round-154-2026-10-21), [the test questions](https://github.com/dwest1507/eliza-assessment/blob/main/docs/golden-set.md), [market context](https://github.com/dwest1507/eliza-assessment/blob/main/docs/market-context.md#how-well-the-best-ai-answers-filing-questions)

<!--
The holdout: the shipped setup (keyword search, `gpt-6-luna`, prompt v19) scored once on 20
holdout questions, kept apart from every choice, after the final round. Nothing changed after it.
Fact Recall (Completeness) 0.76, Faithfulness (Reliability) 0.93, citations valid 0.95, figures
exact 1.00, $0.0028 per answer and the full answer after 7.0 seconds on average. On the 63 dev
questions: Fact Recall 0.74, Faithfulness 0.97. In line, so the choices made on dev did not
overfit. The "How it works" page shows the same two holdout numbers, 76% and 93%.

Why no number for saying what's missing: only 2 of the 20 holdout questions turn on a gap the
check scores (a missing company and a stale filing), and both answers said so. On dev the shipped
run said so on 12 of 15 such questions (0.80), the Control Run on 14 (0.93). Too few for a rate,
so neither the slide nor the page gives one; the demo shows it instead.

The answers state 78 of the holdout's 106 must-state facts. Of the 28 they miss, 19 had reached
the prompt, so the misses are now mostly the model's, not the search's. On 20 questions one
question moves a share by 0.05: read the numbers as directional.

The judge is Jev, pinned to one version, from neither generator's family. If asked why measure at
all: on Vals AI's Finance Agent benchmark (October 2026, 449 analyst-grade questions over SEC
filings) the best system scores 67.85%, and only 58.87% fully right on the strict measure. Even
the best AI gets a meaningful share of filing questions wrong, so quality has to be measured on
the firm's own questions.
-->

---

# Completeness or reliability: you set the dial
<!-- _class: dense -->

Six models answered the same 63 test questions from the same sources. The rule for a win was written down first: state more key facts without backing fewer claims.

| Model | Completeness: key facts stated | Reliability: claims backed by their source | $ per answer |
|---|---|---|---|
| **`gpt-6-luna`** (today) | 74% | **97%** | **0.0030** |
| `gpt-6.1-sol` | 80% | 96% | 0.0592 |
| `gpt-5.6-terra` | 81% | 95% | 0.0622 |
| Claude Haiku 5.5 | 75% | 90% | 0.0050 |
| Claude Sonnet 5.5 | **85%** | 89% | 0.0934 |
| Claude Opus 5.5 | 82% | 81% | 0.1925 |

- **Bigger models find more facts but back fewer of their claims,** at 20 times the cost or more.
- **We default to reliability:** a number in an IC memo has to hold up without re-checking.
- **You can choose otherwise.** Switching models is one setting, and every new model gets the same test: testing all six cost $27.75.

> Sources: [the final round of model comparisons](https://github.com/dwest1507/eliza-assessment/blob/main/docs/evaluation.md#the-final-all-model-round-154-2026-10-21), [ADR 0009](https://github.com/dwest1507/eliza-assessment/blob/main/docs/adr/0009-gpt-6-luna-stays-the-generator.md), [ADR 0011](https://github.com/dwest1507/eliza-assessment/blob/main/docs/adr/0011-one-sided-thresholds-and-a-control-run.md)

<!--
Completeness is Fact Recall and Reliability is Faithfulness, both on the 63 dev questions, every
model at reasoning effort low, one run each. If asked why `gpt-6-luna`'s 74% and 97% differ from
the previous slide's 76% and 93%: those are the 20 holdout questions, kept apart from every
choice; these are the 63 the models were compared on. In facts: `gpt-6-luna` stated 245 of 334 must-state
facts, Claude Sonnet 5.5 286.

The rule: a challenger must be ahead on Fact Recall and behind on none of Faithfulness, Coverage
Gaps and Contradicted Claims. The Control Run, `gpt-6-luna` again, was not ahead (p = 0.124).
`gpt-6.1-sol` was ahead on Fact Recall (19 questions higher, 8 lower, p = 0.026) but behind on
Contradicted Claims (7 answers with one against 2, p = 0.109); terra was ahead (20 and 3) but
behind on Faithfulness (p = 0.115) and on the gaps it acknowledged (p = 0.188); Claude Sonnet
5.5 and Opus 5.5 were ahead (24 and 3; 26 and 7) and behind on Faithfulness and Contradicted
Claims; Claude Haiku 5.5 was not ahead (p = 0.229).

If asked "so Luna is the best model?": no, the best balance for reliability. What favours it:
the prompt was tuned on Luna's answers, and the Claude models run it unchanged, writing 623 to
629 words where Luna writes 513. Each model ran once, and the Control Run alone moved by 14 facts
(259 against 245), so `gpt-6.1-sol` is close to a tie, blocked only by Contradicted Claims, and
its slowest answer took 33.6 s, over the 30-second ceiling. If the firm leans toward completeness,
the pilot can tune the prompt for a larger model and test it the same way.
-->

---

# Today's limits, and what fixes each
<!-- _class: dense -->

| Today | What fixes it |
|---|---|
| **A fixed set of filings:** 54 companies, and trends for only 13. Wells Fargo, Citigroup and newer 10-Ks are missing | **Live EDGAR ingestion** of new filings and companies |
| **Guidance and outlook** mostly aren't in 10-Ks and 10-Qs | **8-K earnings releases** (free), then **earnings-call transcripts** (licensed) |
| **Exact figures** only for revenue, net income and segment revenue | **Full XBRL financials:** public comps, exported to Excel with every cell cited |
| **Answers state about 76% of key facts,** tested on 20 questions, with 15 fact labels checked by hand | **The pilot:** your analysts' own questions, graded by them, tuned on them |
| **Answers go to a hosted AI model** | **A private deployment** in your own cloud environment, or a local model |

> Sources: [EDA findings](https://github.com/dwest1507/eliza-assessment/blob/main/docs/findings.md), [the final round and its holdout run](https://github.com/dwest1507/eliza-assessment/blob/main/docs/evaluation.md#the-final-all-model-round-154-2026-10-21), [the human check](https://github.com/dwest1507/eliza-assessment/blob/main/docs/evaluation.md#the-human-check), [assumptions](https://github.com/dwest1507/eliza-assessment/blob/main/docs/assumptions.md)

<!--
Each limit is solvable, and each fix is the next piece of work. Lead with them before the panel
finds them.

The small human check: Claude drafted the evaluation's labels. The developer checked 15 fact
labels blind: 80% agreement with Claude's labels, 87% with Jev's verdicts. The claim labels
(Faithfulness, Contradicted Claims) are still Claude's alone. In the pilot, the firm's analysts
hand-check a sample of the judge's grades, which closes this.

Smaller limits, if asked: a follow-up that changes topic without naming a company inherits the
earlier companies (ADR 0003; the Sources disclosure shows what the rules understood); figures are
quoted, never computed, so a change the filings don't state is left out; the Sector table and
the missing-company list are our curation (assumptions 5 and 9).
-->

---

# Where this goes, and the next step

| Step | What | Why a PE firm cares |
|---|---|---|
| **Pilot** | Today's assistant, with **live EDGAR** for your watchlist and **passage-level citations** | Proves the value on your work, with your numbers |
| **Next** | **Public comps:** peers' exact figures from XBRL, exported to Excel with every cell linked to its filing | Recurs every quarter: valuation marks, and the peer side of portfolio benchmarking |
| **Then** | **Watchlist alerts:** what changed in risk factors and MD&A as each filing lands | Changes in filing language carry signal, and nobody reads the diffs |
| **Later** | **Your private documents:** data rooms, CIMs and portfolio company financials checked against public peers, on a private deployment; 8-K and **earnings-call transcripts** for guidance | The hardest to copy: your data beside the public filings |

**Proposed next step: a 6-week pilot.** 3–5 of your analysts and their real questions, on your watchlist. We agree up front what success means, for example: at least 1 hour saved per question, completeness and reliability on your questions at or above today's, and every figure exact. At the end: real numbers for the value model, and a decision on what to build next.

> Sources: [market context](https://github.com/dwest1507/eliza-assessment/blob/main/docs/market-context.md#changes-in-filing-language-carry-signal), [assumptions 1, 2, 7 and 13](https://github.com/dwest1507/eliza-assessment/blob/main/docs/assumptions.md), [ADR 0001](https://github.com/dwest1507/eliza-assessment/blob/main/docs/adr/0001-sqlite-financial-facts-store.md)

<!--
Every step keeps the rule the Client confirmed: one AI call per question.

The pilot's analysts also hand-check a sample of the judge's grades, so the measurement becomes
theirs too. Comps first because it recurs every quarter, where PE firms spend the hours. If
asked about benchmarking: benchmarking a portfolio company needs its own numbers, which aren't
public, so until the private-documents step they go into the Excel export by hand. Alerts
are cheaper and reuse today's index, which already finds the text that is new between periods.
For alerts: changes in 10-K and 10-Q language predicted returns, earnings and even bankruptcies
(Lazy Prices, Journal of Finance, 2020): 34–58 basis points a month overall, up to 188 on
risk-factor changes alone. Evidence that diffs carry signal, not a promise of alpha.

If asked "why not ChatGPT, Copilot or Hebbia?": chatting with a 10-K is becoming a free feature
of tools the firm may already pay for. What this gives that they don't: quality measured on your
own questions, not asked to be trusted; answers that say what's missing; a setup you own, which
can switch models as better ones arrive (the dial slide) and keep your documents in your tenant;
and a roadmap toward your data rooms and watchlist, where generic tools don't go.

After the meeting: confirm assumptions 4 to 13 with the Client, starting with the value model's
inputs.
-->

---

# Appendix: how it's built, and the choices we tested
<!-- _class: dense -->

**One question, end to end:** rules find the companies, periods and sections the question names → keyword search picks the passages, without repeats → exact figures come from a facts table → **one AI call** writes the cited answer.

- **Search: plain keyword search stays.** Embedding search, a hybrid of the two, a re-ranking model and two local embedding models were tried; none got the answers to state more of the key facts, and keyword search needs no extra model or call.
- **Passage size and reading budget: unchanged.** Smaller and larger passages, and a larger budget, reached more evidence but got no more of it into the answers than 600-token passages with a 32k budget.
- **The prompt:** a version was kept only if it stated more key facts or fixed named failures. The final one states each point in full, gives more room for more companies, and quotes figures rather than computing them.
- **The model:** see the dial slide.

> Sources: [the Arm comparison](https://github.com/dwest1507/eliza-assessment/blob/main/docs/evaluation.md#the-arm-comparison-on-the-new-retrieval-127-2026-10-18), [the settings comparison](https://github.com/dwest1507/eliza-assessment/blob/main/docs/evaluation.md#the-settings-comparison-on-the-new-retrieval-129-2026-10-18), [prompt log](https://github.com/dwest1507/eliza-assessment/blob/main/docs/prompt-iterations.md), [ADR 0008](https://github.com/dwest1507/eliza-assessment/blob/main/docs/adr/0008-fts5-stays-the-shipped-arm.md), [ADR 0011](https://github.com/dwest1507/eliza-assessment/blob/main/docs/adr/0011-one-sided-thresholds-and-a-control-run.md)

<!--
Shown only if asked about the design. The statistics, for a technical panelist: every choice was
made by a rule written before the run, with an exact one-sided test so that noise is not
declared a win (ahead at p < 0.10, behind on a guardrail at p < 0.20), and each comparison beside
a Control Run, the shipped setup run again, to show the noise.

Retrieval and the settings: embeddings, a hybrid, a re-ranker, two local embedding models, other
passage sizes and a 48k budget were each compared fact by fact on the dev questions. None got the
answers to state more must-state facts by enough to pass the rule, so keyword search, 600-token
passages and the 32k budget stay. The Answer Call's context is up to 32k tokens; the dense and
hybrid Arms also make a hosted embedding call per question, so they could not ship under the
one-call rule.

Prompt: v19, read over two runs a side: its answers state 242 of 334 must-state facts a run
against v15's 232 (p = 0.085), and fail the figure check in 0.5 cases a run against 2.5.
-->
