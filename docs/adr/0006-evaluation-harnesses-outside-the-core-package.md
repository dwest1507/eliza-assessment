---
status: accepted
---

# The evaluation harnesses live in their own package, outside the core package

The retrieval harness scores retrieval Arms on the Golden Set, and the generation harness will score answers. Their own code needs only the standard library, but what they run does not: the challenger Arms of the spec use OpenAI embeddings and an ONNX cross-encoder, and the generation harness calls the answer models and the Jev judge through their SDKs. The core package (`edgar_rag`) stays on the standard library (ADR 0005). We put the harnesses, their pure metrics and the Arm definitions in a third package in the backend project, `edgar_eval`, which imports the core package and never the reverse. The guard test lists it with `edgar_answer` and the API as packages the core package must not import.

## Considered options

- **The harness in the core package, with model-dependent Arms elsewhere.** Arms would no longer be defined in one place, and the core package would carry measurement code the API never runs.
- **The harnesses as scripts outside any package.** They could not be imported by tests, and the pure parts (metrics, the sign test) would have no tested home.

## Consequences

- `make eval-retrieval` runs `python -m edgar_eval.retrieval`. Arms are listed in `edgar_eval.arms.ARMS`, exactly one marked shipped.
- An Arm sees only the conversation and the index and returns ranked (Filing ID, Section) pairs, so a challenger can be measured before it is wired into the retrieval seam. Only the Arm that wins the comparison is moved into the shipped seam. (Amended by [ADR 0008](0008-fts5-stays-the-shipped-arm.md): an Arm is now the shipped seam with its own ranker, passed through an optional `Ranker` hook of `prepare_answer_context`. The ranker's code and model packages stay in `edgar_eval`.)
- Model-dependent Arms and their packages go into a dev dependency group, so the product's install does not pull them in.
