---
status: accepted
---

# `gpt-6-luna` stays the generator: no challenger beat it on paired cases

> The rule's threshold (two-sided p < 0.05) is superseded by [ADR 0011](0011-one-sided-thresholds-and-a-control-run.md) for comparisons on Golden Set version 2. The choice recorded here stands until such a comparison says otherwise.

> **2026-10-17, confirmed on Golden Set version 2.** The version 2 comparison on dev (60 cases, issue #73), `claude-haiku-5-5` against `gpt-6-luna` on FTS5 at 600-token chunks and the 32k budget, under ADR 0011's rule, keeps `gpt-6-luna`. The verdicts are directional: one-sided p < 0.10, fixed before running. Claude Haiku 5.5 is behind on Fact Recall (5 cases higher, 35 lower, p behind < 0.001; mean difference −0.337, 95% interval −0.436 to −0.241) and on Faithfulness (11 and 37, p behind < 0.001; −0.099, −0.153 to −0.048), and costs $0.0047 per answer against $0.0028. The Control Run, `gpt-6-luna` again, was not ahead, so the comparison is conclusive. 27 of Haiku's 60 answers stopped at the 2,500-token cap, which includes thinking, and fail with Fact Recall 0. On the 30 cases where it was not cut off it states 0.72 against Luna's 0.77, so a second look at a Claude model would need a higher cap or its own prompt pass, as the consequences below say for Sonnet and Opus. See [docs/evaluation.md](../evaluation.md#the-generator-comparison).

> **2026-10-20, the product can call either provider (issue #138).** The answer model is now chosen by one setting, `ANSWER_MODEL`, read against the generator table (`GENERATORS`, moved to `backend/src/edgar_answer/generators.py` so the product and the harnesses read the same rows) for its provider (OpenAI or Anthropic) and the key it needs. It defaults to `gpt-6-luna` and replaces the OpenAI-only `OPENAI_MODEL`; a model not in the table is refused. So whichever generator wins spec #136's final round ships by configuration alone, and if a Claude model wins, this ADR is superseded. The settings below changed with it: every provider now answers at reasoning effort `medium` with a 32,000-token cap that includes reasoning, so the "nearest equivalent settings" are the same for both. A capped answer still stops with the stop reason `token_cap` and scores as truncated; the API logs a warning for it, and each generation report and `make eval-generators` list it. Terra (`gpt-5.6-terra`) joined the table at its list price. The comparisons recorded here and in the 2026-10-17 note ran at effort `low` with the 2,500-token cap, and stand as recorded.

The spec compares four generators for the Answer Call (user story 55): OpenAI's `gpt-6-luna` and `gpt-6.1-sol`, and Anthropic's Claude Sonnet 5.5 (`claude-sonnet-5-5`) and Claude Opus 5.5 (`claude-opus-5-5`), chosen between by the same kind of rule as the Arms (ADR 0008). `gpt-6-luna` ships unless a challenger is **distinguishably better on Fact Recall or on Coverage Gaps** and **worse on none of Fact Recall, Faithfulness and Coverage Gaps**, and the cheapest qualifying challenger wins. We ran all four on the Golden Set's dev split on 2026-10-16, and **`gpt-6-luna` stays the generator**. Every challenger stated more Required Facts, but none did so on enough cases for the paired sign test to tell it from noise, and each costs 20 to 65 times as much per answer.

| Generator | cases | citations valid | structure followed | words | Fact Recall | Faithfulness | $ per answer | latency s | first text s | Fact Recall vs Luna (higher / lower, exact p) | Faithfulness vs Luna | Coverage Gaps vs Luna |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **`gpt-6-luna`** (shipped) | 19 | 0.95 | 0.79 | 395 | 0.62 | 0.90 | 0.0025 | 7.9 | 2.8 | – | – | – |
| `gpt-6.1-sol` | 19 | 0.79 | 0.95 | 406 | 0.73 | 0.95 | 0.0492 | 13.2 | 1.4 | 4 / 1, p = 0.375 | 8 / 4, p = 0.388 | 0 / 0 |
| `claude-sonnet-5-5` | 20 | 0.60 | 0.80 | 479 | 0.74 | 0.92 | 0.0805 | 9.3 | 1.3 | 5 / 0, p = 0.062 | 8 / 6, p = 0.791 | 0 / 0 |
| `claude-opus-5-5` | 19 | 0.37 | 0.47 | 535 | 0.75 | 0.93 | 0.1641 | 15.8 | 3.7 | 5 / 0, p = 0.062 | 8 / 6, p = 0.791 | 0 / 0 |

Every model stated every expected Coverage Gap, so the Coverage Gaps test has no discordant case and only Fact Recall could qualify a challenger. Its tests are all "indistinguishable". The full numbers and method are in [docs/evaluation.md](../evaluation.md#generator-comparison).

## How the comparison was kept fair

- **Same inputs.** Every model answers the same 20 dev cases with prompt v7, on the Shipped Arm (`fts5`), with the same Sources, and is judged by the same pinned Jev version (`jev-1.13.0`), which is from neither model family.
- **Nearest equivalent settings.** OpenAI's reasoning effort `low` with a 2,500-token completion cap; Anthropic's adaptive thinking at effort `low` with a 2,500-token cap. Thinking counts in both caps. The Anthropic implementation sits behind the same `AnswerModel` protocol (ADR 0004) and has no refusal fallback, since a fallback would answer with a different model than the one measured.
- **List prices, full rate.** Every input token is priced at the model's list price with no cache discount, so each cost is an upper bound. Anthropic's tokenizer counts the same prompts as about 1.6 times as many input tokens (about 33,000 against 21,000), which is part of the Claude models' price.
- **Prompt v7 was tuned on `gpt-6-luna`'s failures.** That favours Luna on the checks the tuning targeted (structure and citations), not on Fact Recall or Faithfulness, which the rule gates on.

## Considered options

- **Ship a Claude model for its Fact Recall (0.74 and 0.75 against 0.62).** Both were ahead on 5 cases and behind on none, one case short of significance (6 / 0 gives p = 0.031). Under the rule that is not a measured win, and Luna's own v7 runs moved Fact Recall between 0.62 and 0.65 with nothing changed. Shipping either would multiply the cost per answer by 32 (Sonnet) or 65 (Opus) for a difference the Golden Set cannot yet confirm.
- **Ship `gpt-6.1-sol` for its Faithfulness (0.95) and structure (0.95).** Faithfulness was 8 cases up and 4 down (p = 0.388), the same order as the 3 up, 5 down that the Arm comparison's control row showed with nothing changed. It costs 20 times as much and takes 13 seconds per answer against 8.
- **A looser rule: ahead on one score, behind on neither Faithfulness nor Coverage Gaps.** The spec's wording allows it, but it lets a challenger replace Luna while losing on the other of Fact Recall and Coverage Gaps. We kept the stricter reading, which the developer confirmed. Here it changes nothing, since no challenger is ahead on anything.
- **Run each generator several times and average per case.** It would narrow the noise, at about $5.70 per round of the three challengers. It matters only if the Golden Set's size, not the noise, is what keeps Claude's 5 / 0 from qualifying, and a larger Golden Set answers that better.

## Consequences

- `gpt-6-luna` stays the default (`OPENAI_MODEL` overrode it then; `ANSWER_MODEL` does now, for either provider: see the 2026-10-20 note), at about a quarter of a cent per answer.
- The Anthropic implementation stays, so `make eval-generation MODEL=claude-sonnet-5-5` and `make eval-generators` keep working; the `anthropic` SDK stays in the backend's dependencies beside `openai`. The product never calls it.
- The Claude models' answers fail the code checks that v7 was tuned for: they are longer (480 and 535 words against 395), open with four to seven sentences rather than two or three, and add uncited paragraphs, such as what a missing Company's 10-K would usually contain. Citation validity is 0.60 and 0.37 against 0.95. A switch to Claude would need its own prompt pass on those checks first.
- **Revisit when** the Golden Set grows enough for a sign test to see a five-case difference reliably, or when the Client weighs Fact Recall above cost: Claude Sonnet 5.5 is then the first candidate, the cheaper of the two Claude models with the same paired record.
- The holdout split was run once after this choice, on the final configuration (`fts5`, `gpt-6-luna`, prompt v7): Fact Recall 0.67, Faithfulness 0.95 ([docs/evaluation.md](../evaluation.md#the-holdout-run)).
