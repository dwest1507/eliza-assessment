---
status: accepted
---

# CI runs no paid API, and gates retrieval on recorded Floors

CI (`.github/workflows/`) runs on every pull request and every push to main. It must cost nothing, so no job calls OpenAI, Anthropic or Jev, and no job is given a provider key: the generation harness and everything built on it (`make eval-generation`, `make eval-arms`, `make eval-generators`, `make embeddings`) run only on a developer's machine, when asked for. `scripts/backend-test.sh` and `scripts/backend-eval.sh` also blank `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and `JEV_API_KEY`, so a key exported from `backend/.env` cannot reach a paid API through `make ci-cd` either.

What CI checks:

- **Backend:** the uv lockfile, ruff, and pytest. The suite builds its own small indexes from the Corpus and fakes every answer model and the judge.
- **Retrieval:** the index is rebuilt and the Shipped Arm (FTS5) scored on the Golden Set's dev split with the retrieval harness, which makes no LLM call. The job fails if hit@10, recall@10 or MRR drops below its Floor in `data/eval/retrieval_floors.json`.
- **Front-end:** ESLint, Prettier, TypeScript, Vitest, the production build, and a Lighthouse budget on pull requests.
- **Security:** CodeQL, gitleaks, npm audit, pip-audit of the chat API's dependencies, and dependency review, also weekly.
- **Releases:** Release Please opens a release pull request from the conventional commits on main.

## The Floors

FTS5 ranks deterministically, so a Floor is the score measured when the Floors were recorded, rounded down to two decimals: losing any one of the 17 scored dev cases at hit@10 fails the gate. The record also holds the settings it was measured at (the split, the Arm, the Golden Set version, the number of scored cases, the chunk size and the context budget). A run at other settings fails as "Floors stale", since its scores cannot be compared with the Floors. A change that is meant to move them (a new Golden Set version, a new Shipped Arm, chunk size or context budget) runs `make eval-floors` and commits the new record with it, so the change is visible in review.

The gate scores the dev split only. The holdout split is scored once per final setup ([The holdout run](../evaluation.md#the-holdout-run)), and a gate that read it on every push would make it a split the configuration is tuned against.

## Consequences

- CI does not measure answer quality. A prompt or generator change can lower Fact Recall or Faithfulness without failing CI; the generation harness has to be run by hand, as before.
- The Floors gate a regression in the Shipped Arm only. A challenger Arm's scores are not gated.
