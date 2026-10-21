---
status: accepted
---

# Prompt changes are decided by two rules: `prompts` and `prompt-fix`

Decided on 2026-10-20 (spec #132) and built on 2026-10-21 (issue #157), before any run that uses either rule. It extends [ADR 0015](0015-fact-level-fact-recall-for-retrieval-comparisons.md)'s fact-level test, under [ADR 0011](0011-one-sided-thresholds-and-a-control-run.md)'s thresholds and Control Run, to prompt changes.

**Before this ADR**, a prompt version was decided by a rule written on its ticket before its run and recorded in the [prompt log](../prompt-iterations.md): v8 to v14, for example, shipped only if the share of answers following the structure rose and the sign test put them behind v7 on none of Fact Recall, Faithfulness and Coverage Gaps. Those decisions stand as recorded. From spec #132's candidates (v16 onwards), a prompt change is decided by one of the two rules below, applied offline to saved reports.

## The rules

- **`prompts`, for changes meant to raise the facts stated.** Spec #132's v16 (state each point in full), v17 (length scaled to Companies), the legal proceedings route, and their combination. It is ADR 0015's rule:
  - **ahead** on must-state Required Facts stated, summed over the paired cases, at one-sided p < 0.10 by the case-cluster bootstrap with the fixed seed;
  - **behind at p < 0.20 on none** of the guardrails: Fact Recall case by case (the sign test), Faithfulness, Coverage Gaps (as [ADR 0016](0016-coverage-gaps-shown-by-the-product.md) defines them), Contradicted Claims and, new, **structure followed** (the structure check, paired per case by the sign test).
- **`prompt-fix`, for correctness changes.** Spec #132's v18 (quote figures, never compute them).
  - It qualifies when **fewer cases fail the figure check** than in the shipped run, over the cases both reports record. It is a count, as the prompt log's rule for a correctness fix is, not a test.
  - It is **behind at p < 0.20 on none** of the `prompts` guardrails, with **facts stated** (the fact-level test's one-sided p behind) added as one, so a fix can't ship by stating less.
- **The Control Run check is unchanged.** The round's Control Run is compared with its shipped run under the same rule. If it comes out ahead on the rule's ahead metric (facts stated for `prompts`, fewer figure failures for `prompt-fix`), the comparison is inconclusive and the shipped version stands.
- **One run per candidate,** with `gpt-6-luna`. A second run is for reference only, and how it will be read is posted on its ticket before it runs.
- **Structure is reported under every rule** but is a guardrail of these two only. The Arm, settings and generator rules are unchanged.

## How it is run

- `make eval-generation NAME=v16` writes `generation-<split>-v16.json` and records `name` in the report, so a candidate never overwrites the round's shipped run, `generation-<split>.json`.
- `python -m edgar_eval.selection compare SHIPPED.json CANDIDATE.json --control CONTROL.json --rule prompts|prompt-fix --json data/derived/eval/prompt-choice-<split>.json` applies a rule, free. A candidate is named by its report's `name`, else its prompt version. A challenger whose name another already has takes its report's file name beside it.
- The choice file records the rule, the prompt and code versions each side's report records (`versions`), every comparison and the verdict (`qualifies`, `chosen`, `inconclusive` and its reason).

## Why

- **A prompt change that aims to raise the facts stated has to show a gain,** not just avoid harm, and the fact-level test is the most sensitive test this project has for one (ADR 0015). The same rule for prompt and retrieval changes means the legal route candidate and the prompt candidates are judged alike.
- **Structure is a guardrail because the prompt candidates can break it.** v16 asks for more particulars and v17 allows longer answers, so the opening, the comparison table or the per-Company headings could regress (user story 16 of #132). The Arm and settings rules never change the prompt, so they leave structure out.
- **A correctness fix is not held to a gain it doesn't aim at.** v18 targets computed figures, which fail the figure check and cause Contradicted Claims. Facts stated is added to its guardrails, since quoting instead of computing could drop facts a computed comparison stated.

## Considered options

- **One rule for every prompt change.** `prompts` would hold v18 to a facts-stated gain it doesn't aim at; `prompt-fix` would let v16 and v17 ship without a gain.
- **A test, not a count, for `prompt-fix`'s ahead metric** (the sign test on cases passing the figure check). The spec chose the count; see the caveat below.
- **Keeping the per-ticket rules of v8 to v14.** They let each ticket set its own rule before the run, but the rules drifted from ticket to ticket and were not applied by code.

## Consequences

- `edgar_eval.selection.RULES` gains `prompts` and `prompt-fix`, applied only by `compare`. Every candidate read from a report carries structure followed and the figure check per case, and every comparison prints both.
- **Caveat: the figure count moves with noise.** Read offline on #126's saved reports, none of which changed how figures are written, the Control Run failed the figure check in 6 cases against the shipped run's 6, but `hybrid-local` and the 600 / 48k and 800 / 48k settings failed it in 3 or 4. Under `prompt-fix` those three would qualify. So a `prompt-fix` verdict is read with a hand check that the cases it fixes are the computed figures it targets, as #132's spec asks ("must fix the figure failures it targets"), and the evaluation notes say so.
- **Revisit when** the system moves past the demo stage, with ADR 0011's thresholds.

## Built (2026-10-21)

Built in `edgar_eval` (issue #157). `Candidate.from_report` reads each case's structure check and figure check, and the prompt and code versions the report records. `compare` and `choose` apply both rules. The tests in `backend/tests/test_selection.py` run on hand-built reports.

Applied offline to #126's saved reports (prompt v7, `compare --rule prompts`, free): the Control Run is not ahead (226 of 316 must-state facts stated against 227), and `hybrid-local` (234, p ahead = 0.182), 600 / 48k (233, p = 0.195), 450 / 48k (229, p = 0.391) and 800 / 48k (225, p = 0.640) are not ahead fact by fact. Every fact-level verdict and count matches #127's and #129's choice files under ADR 0015, so v7 would have stood under `prompts` too.
