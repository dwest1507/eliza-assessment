# Judge study labels

The judge study's labels ([ADR 0013](../../../docs/adr/0013-jev-stays-the-judge-checked-by-a-judge-study.md)), committed beside the Golden Set so they are backed up.

- `sheet.md`: the blind labelling sheet, written by `make judge-study-sample`, with every item labelled. Running the command again keeps every label entered.
- `sample.json`: the drawn sample (seed 20261017, 30 saved reports). It records why each item was drawn, so it is not read while labelling.
- `label-reasons.md`: each label with the one-line reason its labeller gave.
- `human_check.md`: the human check's blind sheet, 15 fact items and 15 claim items drawn from this sample by `make human-check-sample` (seed 20261020) for the developer to label by hand; `make human-check-score` then scores those labels against Claude's labels here and Jev's verdicts. An agent never fills it in. See [`docs/evaluation.md`](../../../docs/evaluation.md#the-human-check).

**Who labelled.** The developer delegated the labelling. Every label here is Claude's (`claude-opus-5-5`), not the developer's, made on 2026-10-17 in 46 separate sessions. Each session was given only its slice of the sheet and the label definitions, and saw no Jev verdict, probability or draw reason. The labelled sheet was committed before the judge command ran. The study therefore measures Jev's agreement with Claude, not with a human. To check the labels and Jev against a person, the developer labels `human_check.md`.

Jev's verdicts and the score can be regenerated, so they stay in `data/derived/judge_study/` (gitignored). The results are in [`docs/evaluation.md`](../../../docs/evaluation.md#the-judge-studys-results).
