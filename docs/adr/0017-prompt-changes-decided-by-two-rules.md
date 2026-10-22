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

## Note (2026-10-21, #160): two runs a side in spec #132's round

**Why.** The round's Control Run came out ahead of its shipped run under `prompts`: 241 of 334 must-state facts stated against 229, +12, p ahead = 0.081. Under the rule above, every `prompts` comparison in the round would have been inconclusive whatever the candidate scored. The developer chose to run a second shipped run and Control Run and to read the round's candidates against two runs a side, as #132's archived notes suggest for small effects.

**The method, for every comparison of spec #132's round** (v16, v17, v18, the legal proceedings route and its fallback, and the combination):

- **Every side is two runs of its setup:**
  - the shipped side: `generation-dev.json` and `generation-dev-run2.json`;
  - the Control side: `generation-control-dev.json` and `generation-control-dev-run2.json`;
  - each candidate: two runs, `make eval-generation NAME=v16` and `NAME=v16-run2`.
  
  This replaces "one run per candidate" above for this round. Each extra candidate run costs about $0.29, about $1.45 over five candidates, within the spec's $10 cap.
- **How a side is read** (`Candidate.from_reports`):
  - each case's score is the mean over the side's runs that scored it, a pass/fail score as the share of its runs passing;
  - each must-state fact counts as stated by the share of the side's runs that state it, so facts stated and figure failures are each a mean per run;
  - the runs of one side must record one setup, or `compare` refuses them. The second run may carry its own `name`; the side takes its first run's.
- **The tests, thresholds and rules are unchanged:**
  - the sign test pairs the per-case means;
  - the fact-level test resamples whole cases of mean differences, scaled to whole numbers, which leaves its p-values as they are;
  - `prompt-fix` counts the mean figure failures.
- **The Control Run check compares the Control pair with the shipped pair.**
- **Why the candidate gets two runs too.** A two-run side halves a side's run-to-run variance. One candidate run against a two-run shipped side would carry half as much variance again as the Control pair against the shipped pair, so the check would understate the noise of the comparison it guards.
- **The command.** `compare` takes a side's reports joined by `+`:

  ```sh
  python -m edgar_eval.selection compare generation-dev.json+generation-dev-run2.json \
      generation-dev-v16.json+generation-dev-v16-run2.json \
      --control generation-control-dev.json+generation-control-dev-run2.json --rule prompts
  ```

  The choice file records each side's run count (`runs`, `control_runs`) and reports (`run_reports`). One report a side reads exactly as before, and the `arms`, `settings` and `generators` commands are unchanged.

**The result** (`prompts-choice-dev-control-two-runs.json` and `prompt-fix-choice-dev-control-two-runs.json`, free):

- **The four runs of v15 state 229, 235, 241 and 229 must-state facts:** the shipped run, its second run, the Control Run and its second run.
- **Under `prompts`, the Control pair is not ahead:** 235 against 232 a run, +3, p ahead = 0.334. The round's `prompts` comparisons are conclusive when read two runs a side.
- **Under `prompt-fix`, it is not ahead either:** 4.5 cases failing the figure check a run, against 2.5.
- **Caveat: two guardrails move with noise.** The Control pair is behind the shipped pair on structure followed (3 cases higher, 13 lower, p behind = 0.011) and on Faithfulness (p behind = 0.140). Guardrails are not part of the Control Run check, so the round stands, but the same setup is blocked on both by noise alone. A candidate blocked only on structure or Faithfulness is decided by the rule as it stands, and its ticket records the margin beside the Control pair's.

## Note (2026-10-21, #165): the combination ships on the developer's decision

**What happened.** Spec #132's combination, prompt v19 (v16's rule 8, v17's word range, v18's rule 5), was run twice on dev and read two runs a side under `prompts`, every side's structure under v17's range ([evaluation notes](../evaluation.md#v19-the-combination-that-freezes-165-2026-10-21)):

- **Ahead on facts stated:** 242 must-state facts a run against v15's 232, p ahead = 0.085.
- **Behind on no guardrail but structure followed:** 6 cases higher, 12 lower, −0.048 [−0.111, +0.016], p behind = 0.119, so the rule's verdict is v15.
- **The Control pair is not ahead** (+3, p ahead = 0.334), but it is further behind the shipped pair on the same guardrail: 4 higher, 11 lower, −0.071 [−0.143, −0.008], p behind = 0.059.

**The decision.** A candidate blocked only on a guardrail that noise alone moves is the developer's call, with both margins side by side. The developer treated v19's structure margin as noise, since it is inside the Control pair's, so v19 qualifies under `prompts` and is the version that freezes (#153). The rule and its thresholds are unchanged; the choice file keeps the rule's own verdict, and the ruling is recorded here, on #165 and in the evaluation notes.

**What this amends.** The 2026-10-21 note above says a candidate blocked only on structure or Faithfulness "is decided by the rule as it stands". For v19 the developer overrode that: v19 ships on the ruling, not on the rule's verdict. The rule stays as written for any later candidate, and an override like this one is recorded as a note here.

**The other approved deviations in spec #132's round:**
- **Two runs a side:** spec #132 said "One run per candidate. A second run is for reference only." Every side was read two runs a side instead (the 2026-10-21 note above).
- **v16's structure read under v17's range:** user story 36 allows structure to be re-read under v17's word range only before the longer-answers comparison. On the developer's choice, v16 (#161) was read under it throughout, since its misses on v15's check were answers over 600 words about many Companies. v16 qualifies only under that range, so it ships only with it, as it does in v19.
