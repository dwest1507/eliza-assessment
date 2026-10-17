---
status: accepted
---

# FTS5 stays the Shipped Arm: no challenger beat it on paired cases

> The rule's threshold (two-sided p < 0.05) is superseded by [ADR 0011](0011-one-sided-thresholds-and-a-control-run.md) for comparisons on Golden Set version 2. The choice recorded here stands until such a comparison says otherwise.

> **2026-10-17, the one-call rule and the local Arms.** The developer set the limit at one API call of any kind per question, the Answer Call ([assumption 1](../assumptions.md#1-one-api-call-per-question)); local models inside retrieval are fine. The `dense` and `hybrid` Arms embed each question with OpenAI, a second API call, so they can't ship, whatever they score. They stay in `ARMS` and are still measured, reported as "available if the one-call limit is lifted". Every Arm now records whether it makes an API call at query time (`query_api_call`). The screen never sends such an Arm to a paid run, and the Arm rule never chooses it. Two shippable Arms join the comparison: `dense-local` and `hybrid-local`, which embed the chunks and the question with `BAAI/bge-small-en-v1.5`, pinned to a commit and run by ONNX Runtime (`make local-embeddings`, free). On version 1's dev split neither is distinguishable from FTS5 on Evidence Reached (27 and 28 of 44 facts against 30), so the screen keeps `rerank`, `hybrid-local` and `dense-local` for the version 2 comparisons ([docs/evaluation.md](../evaluation.md#the-one-call-rule-and-the-local-arms)). If a local Arm ships, its embeddings join `make index` and its ranker and packages move from `edgar_eval` into the product; until then they stay in the dev dependency group.

The spec sets three challengers against FTS5 `bm25()`: OpenAI dense embeddings searched by exact inner product, a weighted reciprocal-rank fusion hybrid (k = 1), and FTS5's top 20 re-ranked by an ONNX cross-encoder. They are chosen between by a fixed rule (user story 54): FTS5 ships unless a challenger is distinguishably better on Fact Recall and not worse on Faithfulness or Coverage Gaps, and the cheapest wins ties. We measured all four on the Golden Set's dev split in both harnesses, on 2026-10-16, and **FTS5 stays the Shipped Arm**. No challenger was distinguishably better on Fact Recall, so none qualifies.

| Arm | hit@10 | recall@10 | MRR | Fact Recall vs FTS5 (higher / lower cases, exact p) | Faithfulness vs FTS5 | Coverage Gaps vs FTS5 |
|---|---|---|---|---|---|---|
| `fts5` (shipped) | 0.88 | 0.82 | 0.73 | – | – | – |
| `dense` | 0.88 | 0.82 | 0.76 | 1 / 6, p = 0.125 | 2 / 8, p = 0.109 | 0 / 0 |
| `hybrid` | 0.88 | 0.82 | 0.80 | 3 / 2, p = 1.000 | 2 / 7, p = 0.180 | 0 / 0 |
| `rerank` | 0.88 | 0.82 | 0.68 | 2 / 2, p = 1.000 | 3 / 5, p = 0.727 | 0 / 0 |
| `fts5` again (control) | – | – | – | 1 / 1, p = 1.000 | 3 / 5, p = 0.727 | 0 / 0 |

Every challenger hits and misses the same cases at hit@10 as FTS5 (McNemar's test has no discordant case at all). On answers, every comparison is "indistinguishable". The control row reruns FTS5 against itself, so its spread is pure run-to-run noise: Faithfulness moves 3 cases up and 5 down with nothing changed, the same spread the challengers show. The full numbers and method are in [docs/evaluation.md](../evaluation.md#arm-comparison).

## How the challengers are measured

Each Arm is the shipped retrieval seam with a different ranker. `prepare_answer_context` takes an optional `Ranker`, given the question, every chunk id inside the Query Scope's hard filters (Company, time window, Section plan) and the `bm25()` ranking of them. Ids the ranker returns outside the hard filters are ignored. Budget, deduplication, change routing and the prompt are the same for every Arm, so the comparison isolates the ranking, and the generation harness can answer through any Arm (`--arm`). The rankers and their model packages live in `edgar_eval` (ADR 0006); the core package only defines the hook and stays on the standard library.

## Considered options

- **Ship the hybrid for its MRR (0.80 against 0.73).** MRR is a secondary retrieval metric, and the rule gates on Fact Recall in answers. There the hybrid was 3 cases up and 2 down, which is noise. Shipping it would add an embedding call per question, a 300 MB matrix to deploy and rebuild, and an OpenAI dependency at query time, for no measured gain.
- **Tune the hybrid's weight or the re-ranker's depth on dev.** With 17 scored retrieval cases and 19 paired answer cases, a tuned setting would mostly fit noise, and it would spend the dev split's honesty on a choice the rule already settles. The settings are the spec's defaults: equal weights, k = 1, depth 20.
- **Run each Arm several times and average per case.** It would narrow the noise, but the control row shows the effect sizes here are within one run's noise. More runs would only matter if a challenger were close to qualifying.

## Consequences

- No embeddings are built by `make index`, and the product's install stays free of numpy, ONNX Runtime, `tokenizers` and `huggingface-hub`. These packages sit in the backend's dev dependency group, and a guard test keeps them there.
- The challengers stay in `ARMS`, so `make eval-retrieval` keeps comparing them. `make embeddings` builds the dense and hybrid Arms' chunk embeddings once (about 35 cents, about 25 minutes at a 1M tokens-per-minute limit), and `make eval-arms` reruns the whole comparison and the rule.
- **Revisit when** the Golden Set grows enough for a sign test to see a two- or three-case difference, or when questions arrive that `bm25()` cannot match lexically. Paraphrases of Filing wording are where dense retrieval should help, and the dev cases have few of them. If a challenger then ships, its embeddings join `make index` and the ranker moves from `edgar_eval` into the product.
- The dense Arm lost Fact Recall on both outlook cases (1.00 → 0.00 and 0.50 → 0.00): it reached the expected MD&A Sections, but ranked general forward-looking passages above the specific ones the Required Facts quote. Exact terms such as "capital expenditures" or "2026" are where FTS5 has the edge on this Corpus.
