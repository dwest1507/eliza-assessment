"""The human check (spec #136): a person checks the judge study's labels by hand.

Every label of the judge study (ADR 0013) is Claude's (`claude-opus-5-5`), made on the
developer's delegation, so the study measures Jev against Claude, not against a person.
The human check is a small blind sample of the same items for the developer to label:

- `sample` draws `FACT_ITEMS` (15) fact items and `CLAIM_ITEMS` (15) claim items from the
  judge study's sample (`sample.json`) with a fixed seed (`SEED`), among the items Claude
  labelled on the study's sheet. Each kind's items are spread across Claude's labels, as
  evenly as the labels allow: one item of each label in turn (in `FACT_LABELS` or
  `CLAIM_LABELS` order) until the kind's count is drawn, a label with too few items giving
  all it has. It writes them to `human_check.md` beside the study's files, in shuffled
  order within each kind, through the study's own sheet writer: no Claude label, no Jev
  verdict, no probability and no reason an item was drawn. Drawing again keeps every label
  entered and refuses, writing nothing, to drop a labelled item.
- `score` reads the developer's labels, Claude's labels from the study's sheet and Jev's
  first run from the study's verdicts (`verdicts.json`, the study's measure), and reports
  the developer's agreement with each: per kind, the count, the share and Cohen's kappa,
  and over all the items the count and share. A fact's Jev verdict is taken at
  `FACT_CUTOFF`, from its stored probability. An item whose Jev judgment failed is left
  out of Jev's agreement and counted. It refuses while any item is unlabelled.

Neither command calls a provider: the draw reads the study's committed files, and the
score its stored verdicts.

    python -m edgar_eval.human_check sample [--seed N] [--sheet PATH]
        [--study-sheet PATH] [--study-sample PATH]
    python -m edgar_eval.human_check score [--sheet PATH] [--study-sheet PATH]
        [--study-sample PATH] [--verdicts PATH] [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO

from edgar_eval.judge import FACT_CUTOFF, JEV_MODEL
from edgar_eval.judge_study import (
    CLAIM_LABELS,
    DEFAULT_SAMPLE,
    DEFAULT_VERDICTS,
    DERIVED_STUDY_DIR,
    FACT_LABELS,
    LABELLING,
    LABELS_DIR,
    JudgeRun,
    Sample,
    StudyItem,
    Unlabelled,
    load_verdicts,
    read_labels,
    write_sheet,
)
from edgar_eval.judge_study import DEFAULT_SHEET as STUDY_SHEET
from edgar_eval.metrics import cohen_kappa

__all__ = [
    "CLAIM_ITEMS",
    "DEFAULT_SCORE",
    "DEFAULT_SHEET",
    "FACT_ITEMS",
    "LABELLER",
    "SEED",
    "Agreement",
    "HumanCheckScore",
    "KindAgreement",
    "draw_human_check",
    "main",
    "print_score",
    "score_human_check",
    "write_human_sheet",
]

SEED = 20261020
"""The human check's seed, fixed before any item is drawn."""

FACT_ITEMS = 15
CLAIM_ITEMS = 15

LABELLER = "claude-opus-5-5"
"""Who labelled the judge study's sheet, on the developer's delegation."""

DEFAULT_SHEET = LABELS_DIR / "human_check.md"
"""Committed beside the study's sheet: its labels are made by hand."""

DEFAULT_SCORE = DERIVED_STUDY_DIR / "human_check_score.json"
"""Gitignored: it can be regenerated from the labels and the verdicts."""


# --- The draw -------------------------------------------------------------------------------


def draw_human_check(
    study: Sample,
    claude: Mapping[str, str | None],
    *,
    seed: int = SEED,
    fact_items: int = FACT_ITEMS,
    claim_items: int = CLAIM_ITEMS,
) -> Sample:
    """The human check's items from the judge study's sample, among those Claude labelled
    (`claude`, the study sheet's labels): each kind spread across Claude's labels, then
    shuffled; the fact items first, then the claim items."""
    rng = random.Random(seed)
    drawn: list[StudyItem] = []
    for kind, labels, count in (
        ("fact", FACT_LABELS, fact_items),
        ("claim", CLAIM_LABELS, claim_items),
    ):
        by_label = {
            label: sorted(
                (i for i in study.items if i.kind == kind and claude.get(i.id) == label),
                key=lambda i: i.id,
            )
            for label in labels
        }
        wanted = _spread([len(by_label[label]) for label in labels], count)
        items = [
            item
            for label, n in zip(labels, wanted, strict=True)
            for item in rng.sample(by_label[label], n)
        ]
        rng.shuffle(items)
        drawn += items
    return Sample(seed=seed, reports=study.reports, items=tuple(drawn), skipped={})


def _spread(available: Sequence[int], target: int) -> list[int]:
    """How many items to take of each label: one of each in turn, in order, skipping a
    label once it has none left, until `target` are taken or none are left."""
    taken = [0] * len(available)
    while sum(taken) < target and any(t < a for t, a in zip(taken, available, strict=True)):
        for n, have in enumerate(available):
            if sum(taken) < target and taken[n] < have:
                taken[n] += 1
    return taken


def _preamble(check: Sample) -> list[str]:
    facts = sum(i.kind == "fact" for i in check.items)
    return [
        "# Human check labelling sheet",
        "",
        (
            f"Seed: {check.seed}. Drawn from the judge study's sample: {facts} fact items "
            f"and {len(check.items) - facts} claim items, for a person to label by hand."
        ),
        "",
        LABELLING,
        "",
        (
            "Label from each item alone. Until every item here is labelled, don't open the "
            "judge study's `sheet.md`, `label-reasons.md` or `sample.json`, or its verdicts "
            "or score: they hold the labels this sheet checks."
        ),
    ]


def write_human_sheet(check: Sample, path: str | Path) -> int:
    """Write the human check's blind sheet, keeping every label of a sheet already at
    `path`, and return how many were kept; raises ValueError, writing nothing, when that
    sheet labels an item this draw does not hold (`write_sheet`)."""
    return write_sheet(check, path, _preamble(check))


# --- Scoring --------------------------------------------------------------------------------


@dataclass(frozen=True)
class KindAgreement:
    """The developer's labels against another's, over one kind's items."""

    items: int
    agree: int
    share: float | None
    kappa: float | None
    """Cohen's kappa; None when undefined (no item, or one category on both sides)."""


@dataclass(frozen=True)
class Agreement:
    """The developer's labels against one reference: Claude's labels, or Jev's verdicts."""

    reference: str
    facts: KindAgreement
    claims: KindAgreement
    items: int
    """Every item compared, both kinds."""
    agree: int
    share: float | None
    failed: int
    """Items whose judgment failed, left out above."""


@dataclass(frozen=True)
class HumanCheckScore:
    items: int
    facts: int
    claims: int
    fact_cutoff: float
    claude: Agreement
    jev: Agreement

    def to_dict(self) -> dict:
        return asdict(self)


def score_human_check(
    ids: Sequence[str],
    human: Mapping[str, str | None],
    claude: Mapping[str, str | None],
    jev: JudgeRun,
) -> HumanCheckScore:
    """Score the developer's labels (`human`) of the human check's items (`ids`) against
    Claude's labels and Jev's verdicts (its first run). Raises `Unlabelled` while any
    item is unlabelled, and ValueError on an item Claude did not label or Jev did not
    judge."""
    missing = [i for i in ids if i not in claude or claude[i] is None or i not in jev.verdicts]
    if missing:
        raise ValueError(
            f"{len(missing)} item(s) not labelled by the judge study's sheet or not judged in "
            f"its verdicts: {', '.join(missing[:5])}"
        )
    unlabelled = [i for i in ids if not human.get(i)]
    if unlabelled:
        raise Unlabelled(f"{len(unlabelled)} item(s) unlabelled: label every item before scoring")

    def jev_verdict(item_id: str) -> str | None:
        return jev.verdicts[item_id].at(FACT_CUTOFF)

    facts = sum(i.startswith("F-") for i in ids)
    return HumanCheckScore(
        items=len(ids),
        facts=facts,
        claims=len(ids) - facts,
        fact_cutoff=FACT_CUTOFF,
        claude=_agreement(f"{LABELLER} labels", ids, human, claude.get),
        jev=_agreement(f"{jev.judge} run {jev.run}", ids, human, jev_verdict),
    )


def _agreement(reference: str, ids: Sequence[str], human: Mapping, other) -> Agreement:
    pairs = {i: (human[i], other(i)) for i in ids}
    compared = {i: p for i, p in pairs.items() if p[1] is not None}

    def of_kind(prefix: str) -> KindAgreement:
        rows = [p for i, p in compared.items() if i.startswith(prefix)]
        agree = sum(a == b for a, b in rows)
        return KindAgreement(
            len(rows), agree, agree / len(rows) if rows else None, cohen_kappa(rows)
        )

    agree = sum(a == b for a, b in compared.values())
    return Agreement(
        reference=reference,
        facts=of_kind("F-"),
        claims=of_kind("C-"),
        items=len(compared),
        agree=agree,
        share=agree / len(compared) if compared else None,
        failed=len(pairs) - len(compared),
    )


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def print_score(report: HumanCheckScore, out: TextIO) -> None:
    print(
        f"Human check: {report.items} items labelled by hand ({report.facts} fact, "
        f"{report.claims} claim); Jev's facts at the cut-off {report.fact_cutoff}.",
        file=out,
    )
    for name, a in (("Claude's labels", report.claude), ("Jev's verdicts", report.jev)):
        failed = f"; {a.failed} failed judgment(s) left out" if a.failed else ""
        print(
            f"Against {name} ({a.reference}): {a.agree} of {a.items} agree ({_pct(a.share)}); "
            f"facts {a.facts.agree} of {a.facts.items} ({_pct(a.facts.share)}, kappa "
            f"{_num(a.facts.kappa)}); claims {a.claims.agree} of {a.claims.items} "
            f"({_pct(a.claims.share)}, kappa {_num(a.claims.kappa)}){failed}.",
            file=out,
        )


# --- Command line -------------------------------------------------------------------------


def main(
    argv: list[str] | None = None, *, out: TextIO | None = None, err: TextIO | None = None
) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    parser = argparse.ArgumentParser(description="The human check of the judge study's labels.")
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample", help="draw the items and write the blind sheet")
    sample.add_argument("--seed", type=int, default=SEED)
    score = commands.add_parser("score", help="score the labels against Claude's and Jev's")
    score.add_argument("--verdicts", type=Path, default=DEFAULT_VERDICTS)
    score.add_argument("--json", type=Path, default=DEFAULT_SCORE)
    for command in (sample, score):
        command.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
        command.add_argument("--study-sheet", type=Path, default=STUDY_SHEET)
        command.add_argument("--study-sample", type=Path, default=DEFAULT_SAMPLE)
    args = parser.parse_args(argv)

    study = Sample.from_dict(json.loads(args.study_sample.read_text(encoding="utf-8")))
    claude = read_labels(args.study_sheet)
    if args.command == "sample":
        check = draw_human_check(study, claude, seed=args.seed)
        try:
            kept = write_human_sheet(check, args.sheet)
        except ValueError as error:
            print(f"error: {error}", file=err)
            return 1
        facts = sum(i.kind == "fact" for i in check.items)
        print(
            f"Drew {facts} fact items and {len(check.items) - facts} claim items from the "
            f"judge study's sample with seed {check.seed}; {kept} label(s) kept.\n"
            f"Sheet: {args.sheet.resolve()}",
            file=out,
        )
        return 0

    human = read_labels(args.sheet)
    jev = next((r for r in load_verdicts(args.verdicts) if r.judge == JEV_MODEL), None)
    if jev is None:
        print(f"error: no {JEV_MODEL} run in {args.verdicts}", file=err)
        return 1
    try:
        report = score_human_check(list(human), human, claude, jev)
    except ValueError as error:  # Unlabelled among them
        print(f"error: {error}", file=err)
        return 1
    print_score(report, out)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(f"Score: {args.json.resolve()}", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
