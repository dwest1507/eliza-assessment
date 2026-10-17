---
status: accepted
---

# No LLM framework: the Answer Call goes through a thin interface over the official SDKs

The Answer Call runs on OpenAI (`gpt-6-luna`) first, and a comparison run later measures Anthropic models against it, so it needs one interface over more than one provider. We write that interface ourselves: one protocol that streams an answer's tokens and reports its token usage, with one small implementation per provider over the official `openai` and `anthropic` SDKs. Retrieval is already custom (FTS5 with hard metadata filters, Query Scope inheritance, Coverage Gaps computed by code), so a framework would only ever wrap the model call. Doing it ourselves keeps the single generative call in one short file anyone can read, which is how we show the single-call rule is kept, and keeps each provider's own settings (OpenAI's reasoning effort and completion-token cap, Anthropic's thinking budget and prompt caching) under our control, which a fair model comparison needs.

## Considered options

- **LangChain.** Swapping providers is one line, and LangGraph is a credible path for agentic research. But its standard chat-RAG pattern (a history-aware retriever) makes the LLM question rewrite that ADR 0003 rejects, none of its retrievers fit FTS5 with hard filters, and reasoning settings pass through provider-specific arguments anyway. The Client has confirmed the single-call rule is a hard requirement (assumption 1), so the agentic path it offers is not open here.
- **LiteLLM.** The least code for the comparison, with cost lookup built in, but it translates every provider into OpenAI's request format, so a comparison would partly measure the translation, and new provider settings arrive late.
- **LlamaIndex.** A full RAG framework whose indexing and retrieval we have already built more precisely.

## Consequences

- We get no framework tracing, so every Answer Call logs its model, prompt version, token usage and latency itself. The evaluation's cost and latency figures come from that log.
- Adding a provider means writing one more implementation of the protocol.
