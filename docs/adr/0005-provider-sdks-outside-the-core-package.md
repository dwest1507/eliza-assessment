---
status: accepted
---

# Provider SDKs live outside the core package, which stays on the standard library

ADR 0004 puts the Answer Call behind one protocol with one implementation per provider over its official SDK, and the spec keeps the core package (`edgar_rag`) on the standard library so the API and front-end can sit on top of it. The two meet at the answer model. We split it: the core package holds the protocol (`AnswerModel`), the `Usage` it reports and `AnswerCall`, which streams an answer and logs its model, prompt version, token usage and latency. The implementations that import an SDK (`OpenAIAnswerModel` and `AnthropicAnswerModel`) live in a second package in the backend project, `edgar_answer`, together with the `make ask` command line. A guard test checks that the core package imports only the standard library and itself, and never a web framework, the API or `edgar_answer`.

## Considered options

- **The OpenAI implementation in the core package, importing the SDK lazily.** One package fewer, but the core package would declare a third-party dependency and the guard test could no longer say "standard library only".
- **The implementations in the API package.** `make ask` runs without a server, so it would import the API package to reach them, and the generation harness would too.

## Consequences

- The `openai` and `anthropic` SDKs are dependencies of the backend project, used only by `edgar_answer`. The Anthropic implementation was added for the generator comparison.
- Retrieval, prompt rendering and the Answer Call log are testable with a fake model and no SDK installed.
