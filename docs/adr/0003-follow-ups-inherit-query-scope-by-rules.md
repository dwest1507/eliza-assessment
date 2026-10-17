---
status: accepted
---

# Follow-up questions inherit their Query Scope by rules, not by an LLM rewrite

The system is a chat: the browser sends the conversation, and each user message gets one Answer Call with the last 10 turns of history in its prompt. History lets the model read "them" or "that", but every claim must cite a Source retrieved for this turn, so a follow-up like "How did that change over two years?" fails unless retrieval itself knows which Companies it is about. The usual fix is an LLM call that rewrites the follow-up into a standalone question, which is a second generative call and breaks the single-call rule (assumption 1). Instead, the rules parse the latest message, and each part of the Query Scope it does not name (Companies, time window, Section hints, metric) is taken from the most recent earlier user message that named it. A part the latest message does name replaces the inherited one, so "And what about Microsoft?" switches Company and keeps the rest.

## How the rules apply

- **What counts as naming a part.** Companies are named by a name, a ticker, a Sector phrase or a Company missing from the Corpus, and the three replace the earlier Companies together: "And the oil majors?" switches to Chevron and ExxonMobil, and "What about Honeywell?" switches to a missing Company, so the stale GE Filing of the earlier question doesn't come back either. A time window and a named Fiscal Period are one part, so "over the last two years" replaces an inherited "FY2024". The metric is named by a metric word or a segment name of the Companies in scope.
- **The topic is inherited too.** Retrieval ranks chunks by the question's words, and "And what about Microsoft?" or "How did that change over the last two years?" has no word to search for once Company names, time words and change words are set aside. Such a follow-up searches with its own words plus those of the most recent earlier question that had a topic, and that question's wording also decides whether it asks about a trend, a change or the outlook (so "And what about Microsoft?" after "How has NVIDIA's revenue changed?" is a change question about Microsoft's revenue). A follow-up with words of its own ("Which of them has the most regulatory exposure?") searches with those alone.
- **History in the prompt.** The Answer Call sees the last 10 turns, dropping the oldest until they fit in about 6k tokens. An earlier answer's `[Sn]` tags pointed at that turn's Sources, so they are rewritten as the Filing IDs they cited, which the browser sends back with each earlier answer (never the passages); a tag it can't resolve is dropped. The prompt says history is not evidence, and every claim must cite a Source of the current turn.

## Considered options

- **Retrieve on the latest message alone, history in the prompt only.** An elliptical follow-up names no Company, so retrieval ranks across all 54 and the model has nothing it may cite.
- **Retrieve on the recent user messages joined together.** It can only add to the scope, never replace: a switch to Microsoft keeps the earlier Companies and splits the per-Company budget between them.
- **Carry the previous turn's Sources forward.** Context grows every turn and keeps stale Sources after a change of subject, and new retrieval still needs a Query Scope.
- **An LLM rewrite before retrieval.** Best on messy follow-ups, but it is a second generative call. The Client has confirmed the single call is a hard requirement across the whole pipeline (assumption 1), so this option is closed.

## Consequences

- A change of topic that names no Company wrongly inherits the earlier Companies. The front-end shows each answer's resolved Query Scope, and the Golden Set holds a case for this failure so it is measured.
- The backend stays stateless: the Query Scope is recomputed from the user messages the browser sends.
- Inheritance reaches back only as far as the prompt's history: the chat API accepts at most the question and the 10 messages before it, and the workspace sends no more, dropping the oldest. A part last named before that is no longer inherited.
