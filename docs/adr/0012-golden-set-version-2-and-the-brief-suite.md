---
status: accepted
---

# Golden Set version 2: 60 dev cases, 20 new holdout cases, one-claim Required Facts, and the brief's questions in a Brief Suite of their own

Golden Set version 1 has 30 cases, 20 dev and 10 holdout. The evaluation review of 2026-10-17 found four problems with it:

- **Too few cases.** The sign test cannot see a real difference on 20 cases (ADR 0011).
- **The brief's questions are not measured where they matter.** The hash split put the NVIDIA question in the holdout, so the question the Client is likeliest to ask was scored once, ever, and never tuned on. The two in dev are averaged with the other 18 cases. The pharmaceutical question scored 0.00 Fact Recall in 24 of 27 runs, because none of its evidence reaches the prompt, without moving a single decision.
- **Compound Required Facts.** For example: "NVIDIA's revenue for the third quarter of fiscal 2026 was $57.0 billion, up 62% from a year earlier and 22% sequentially." Jev marks a fact not stated when an answer gives most of it. The NVIDIA holdout answer states that quarter's revenue and the H20 charge, and scored 0.50.
- **An unstable split.** The ranking split rule moves an existing case across the dev/holdout boundary whenever a case is added.

We decided:

- **A Brief Suite**, outside the dev/holdout split: the brief's three example questions plus four variants of each, about 15 cases. It is a must-pass check, not an estimate, so it may be tuned on freely. Each case runs 5 times on every change that could alter an answer. It passes when every must-state Required Fact is stated in at least 4 of the 5 runs and no run has a Contradicted Claim. Its cases are reported one by one, never averaged.
- **60 dev cases and 20 holdout cases**, mixed by the kinds of question the brief gives as examples:

  | Kind of question | Dev | Holdout |
  |---|---|---|
  | Multi-Company risk comparisons | ~15 | ~5 |
  | Figure and outlook trends | ~15 | ~5 |
  | Sector questions | ~12 | ~4 |
  | Coverage Gap cases | ~10 | ~3 |
  | Follow-ups | ~8 | ~3 |

  Figure facts are labelled from the SEC company-facts reference, independently of the system's own Financial Facts.
- **Version 1's cases are reused.** Its 27 cases other than the brief's join dev, including the 10 version 1 holdout cases, which were scored once and never tuned on. The 33 new dev cases and 20 holdout cases are drafted together, and the 20 whose ids have the lowest SHA-256 digests become the holdout. Every case then records its split, and no case ever moves.
- **One-claim Required Facts, in two tiers.** Each fact states one claim and names its Company. It is either must-state (something any good answer covers) or a detail. Fact Recall gates on the must-state facts, and recall of details is reported beside it. Every fact keeps a verbatim evidence quote that the Golden Set's tests check against the Corpus.
- **Drafted from whole Sections, not from what retrieval returns.** Candidates are drafted in Claude Code, so no API spend. The developer should review every drafted fact, but because this is a quick-turn demo, it is acceptable not to (see the note of 2026-10-17 below). Drafting from whole Sections keeps the labels from inheriting the system's own Section plan: "how are they addressing them" is not answered by Risk Factors alone.
- **The holdout rule applies per Golden Set version.** Version 2's holdout is scored once, on the final version 2 setup. Version 1's holdout run stands as recorded.

## Considered options

- **Keep the brief's questions in the dev/holdout split.** The one in the holdout can never be tuned on, and the ones in dev are 3 of 60 cases, averaged away.
- **About 120 dev cases.** See ADR 0011: twice the labelling for a reversible demo choice.
- **Keep the ranking split rule.** Adding any case would move another across the boundary.
- **Reuse version 1's labels as written.** The compound facts are what made Jev misjudge the NVIDIA answer.

## Consequences

- About 65 new cases and 27 rewrites. Reviewing them would take the developer roughly 7 hours, which the developer chose not to spend (see the note below).
- Version 2 scores are not comparable with version 1's, so the shipped setup is scored afresh on version 2 before any comparison.
- The Golden Set's loader, schema and tests change: tiers, a recorded split, and the Brief Suite.
- The front-end's starter prompts still include the brief's three questions; they now come from the Brief Suite.

## Note, 2026-10-17: no developer review of drafted labels

The developer should review every drafted fact, but because this is a quick-turn demo, it is acceptable not to. The developer chose not to (decided 2026-10-17, recorded on #43). Drafting does not wait for, or ask for, the developer to accept each case or fact.

The mechanical checks stand in for the review: every evidence quote is checked verbatim against the Corpus, every figure against the SEC company-facts reference, and every new question against the others for duplicates. So does the implementer's read-back of each case against its Sections. These prove that the labels point at real text, not that they are complete, so no human has checked that a case lists everything its answer must say.

## Built (2026-10-17)

Everything decided here is built:

- **The Brief Suite**: the brief's three questions and four variants of each, 15 cases, in `data/eval/brief_suite.json`, run 5 times a case by `make eval-brief`. On the shipped setup 1 of 15 cases passes, most misses being evidence that never reaches the Answer Context ([docs/evaluation.md](../evaluation.md#the-brief-suite)).
- **One-claim, tiered Required Facts**, checked by the loader, with Fact Recall scored on the must-state facts and detail recall beside it.
- **Golden Set version 2**: 80 cases in `data/eval/golden_set_v2.json`, version 1's 27 other cases rewritten and 53 new ones, with the split frozen at 60 dev and 20 holdout cases by the lowest SHA-256 digests (issue #72). It is the harnesses' default.
- **The holdout rule per version**: version 2's holdout was scored once, on the final version 2 setup, after the comparisons on dev (issue #74). Fact Recall 0.74 and Faithfulness 0.95 against dev's 0.72 and 0.93, hit@10 0.89 against 0.93: in line with dev, and deciding nothing ([docs/evaluation.md](../evaluation.md#the-version-2-holdout-run)). Version 1's holdout run stands as recorded.
