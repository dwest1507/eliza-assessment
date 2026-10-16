---
status: accepted
---

# Follow-up questions inherit their Query Scope by rules, not by an LLM rewrite

The system is a chat: the browser sends the conversation, and each user message gets one Answer Call with the last 10 turns of history in its prompt. History lets the model read "them" or "that", but every claim must cite a Source retrieved for this turn, so a follow-up like "How did that change over two years?" fails unless retrieval itself knows which Companies it is about. The usual fix is an LLM call that rewrites the follow-up into a standalone question, which is a second generative call and breaks the single-call rule (assumption 1). Instead, the rules parse the latest message, and each part of the Query Scope it does not name (Companies, time window, Section hints, metric) is taken from the most recent earlier user message that named it. A part the latest message does name replaces the inherited one, so "And what about Microsoft?" switches Company and keeps the rest.

## Considered options

- **Retrieve on the latest message alone, history in the prompt only.** An elliptical follow-up names no Company, so retrieval ranks across all 54 and the model has nothing it may cite.
- **Retrieve on the recent user messages joined together.** It can only add to the scope, never replace: a switch to Microsoft keeps the earlier Companies and splits the per-Company budget between them.
- **Carry the previous turn's Sources forward.** Context grows every turn and keeps stale Sources after a change of subject, and new retrieval still needs a Query Scope.
- **An LLM rewrite before retrieval.** Best on messy follow-ups, but it is a second generative call. If the Client allows one (Client email, question 1), it replaces the inheritance rule behind the same seam.

## Consequences

- A change of topic that names no Company wrongly inherits the earlier Companies. The front-end shows each answer's resolved Query Scope, and the Golden Set holds a case for this failure so it is measured.
- The backend stays stateless: the Query Scope is recomputed from the user messages the browser sends.
