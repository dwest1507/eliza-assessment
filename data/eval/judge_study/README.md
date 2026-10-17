# Judge study labels

The judge study's hand-made labels ([ADR 0013](../../../docs/adr/0013-jev-stays-the-judge-checked-by-a-judge-study.md)), committed beside the Golden Set so they are backed up.

- `sheet.md`: the blind labelling sheet the developer fills in with an editor. `make judge-study-sample` writes it, and running it again keeps every label entered.
- `sample.json`: the drawn sample, which records why each item was drawn. It is not read while labelling.

Neither is here yet: the sample is drawn once version 1's cases are rewritten. The developer commits the labelled sheet, and the sample beside it, as the labelling goes.

Jev's verdicts and the score can be regenerated, so they stay in `data/derived/judge_study/` (gitignored). See [`docs/evaluation.md`](../../../docs/evaluation.md#the-judge-studys-sample).
