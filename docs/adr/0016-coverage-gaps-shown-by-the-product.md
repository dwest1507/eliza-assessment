---
status: accepted
---

# Coverage Gaps are shown by the product, not stated by the model

Since prompt v3, every Coverage Gap has been computed by code, sent in the prompt, and stated by the model "in the words given, near the start of the answer" and again in a closing "Coverage" note, and the generation harness scored the answer on stating each one. The workspace also showed them, as a callout above the answer. So the reader saw each gap two or three times, and the answer's opening, the part shown before "Show full analysis", spent itself on gap wordings: on the brief's first question, half the direct answer repeated the "periods differ" callout word for word. Decided on 2026-10-20, in the review of the demo before the final evaluation round.

## The decision

- **The product shows every Coverage Gap.** The workspace renders the gaps, in their fixed wordings, as Coverage notes after the answer, once it is complete. `make ask` prints them, and the chat API streams them as its `data-coverage-gaps` part, as before. Which gaps a question has is decided by code alone, unchanged, including the "periods differ" rule (latest 10-Ks more than 20 days apart), so no Golden Set label changes.
- **The model no longer states gaps for their own sake.** Prompt v15 drops "state every gap … near the start" and the closing Coverage note. When a gap leaves part of the question unanswered (a Company not in the Corpus, a trend asked of a Snapshot Company, the stale Filing, guidance the Filings don't contain), the answer says so briefly, in its own words, where it matters. It never mentions "periods differ" for its own sake. Rule 7's "never fill a gap from general knowledge" stays.
- **The harness scores what the model is still asked to do.** The Coverage Gap check scores only the gaps that leave part of the question unanswered, by the same paraphrase markers, anywhere in the answer; "periods differ" leaves the check. The structure check no longer requires a closing Coverage note. Faithfulness keeps exempting sentences that say what the Filings lack. Reports scored before stand as recorded; the round that ships prompt v15 is the new baseline.

## Considered options

- **Keep the model stating every gap (prompt v3 to v14).** Measured (Coverage Gaps stated 1.00), but it repeats what the product already shows and crowds the direct answer.
- **The model never mentions any gap.** Simplest, but "Compare JPMorgan and Wells Fargo" would then answer about JPMorgan alone with no word on why until the footnote, and a Snapshot trend question's honest answer is the gap itself.

## Consequences

"Coverage Gaps stated" now measures that the answer acknowledges what it cannot answer, not that it recites the wordings, so its numbers before and after prompt v15 are not compared. `CONTEXT.md`'s Coverage Gap entry says the same. Part of issue #132's item 6 (a Coverage Gap sentence scored as an unsupported claim) goes away with the recited wordings.
