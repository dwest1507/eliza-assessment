# Judge study labels

The judge study's labels ([ADR 0013](../../../docs/adr/0013-jev-stays-the-judge-checked-by-a-judge-study.md)), committed beside the Golden Set so they are backed up.

- `sheet.md`: the blind labelling sheet, written by `make judge-study-sample`, with every item labelled. Running the command again keeps every label entered.
- `sample.json`: the drawn sample (seed 20261017, 30 saved reports). It records why each item was drawn, so it is not read while labelling.
- `label-reasons.md`: each label with the one-line reason its labeller gave.

**Who labelled.** The developer delegated the labelling. Every label here is Claude's (`claude-opus-5-5`), not the developer's, made on 2026-10-17 in 46 separate sessions. Each session was given only its slice of the sheet and the label definitions, and saw no Jev verdict, probability or draw reason. The labelled sheet was committed before the judge command ran. The study therefore measures Jev's agreement with Claude, not with a human. To check Jev against a person, a human relabels the sheet: clear the `LABEL` lines, or draw a fresh sheet with another seed.

Jev's verdicts and the score can be regenerated, so they stay in `data/derived/judge_study/` (gitignored). The results are in [`docs/evaluation.md`](../../../docs/evaluation.md#the-judge-studys-results).
