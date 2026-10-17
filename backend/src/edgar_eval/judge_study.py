"""The judge study (ADR 0013): Jev's verdicts checked against the developer's blind labels.

Three commands:

- `sample` draws the items from the saved generation reports and writes the labelling
  sheet the developer fills in with an editor. It reads saved reports only: it makes no
  Answer Call and no Jev call, and calls no provider.
- `judge` has Jev judge every sampled item `JUDGE_RUNS` (2) times and, with
  `--reference`, Claude Haiku 5.5 (`REFERENCE_MODEL`, pinned) once as a reference judge.
  With `--llm-split` it also runs the trial LLM claim split (`SPLIT_MODEL`, pinned) over
  the answers of the claim items, its output cached per answer, and Jev judges its
  statements once. It prints its estimated cost before the first request, and stores
  the verdicts in their own file, apart from the sheet. A judgment that fails is
  recorded against each item it was for; no item is dropped.
- `score` reads the developer's labels and the stored verdicts and reports, per judge:
  accuracy and Cohen's kappa for facts and for claims; the share of bad claims
  (unsupported or contradicted) the judge calls supported, with its 95% Wilson interval;
  the error by generator; for Jev, agreement at each candidate fact cut-off (`CUTOFFS`)
  and with averaged probabilities; how often Jev's two runs agree; whether ADR 0013's
  revisit trigger fired; whether the early-stopping rule is met; and, when the LLM split
  was run, which split's claims judged by Jev agree better with the labels, answer by
  answer. It refuses while
  any item is unlabelled, unless the stopping rule is met or `--partial` is given.

**Fact items** (`FACT_ITEMS`, about 150) pair a saved answer with one Required Fact in the
one-claim format of ADR 0012, never with version 1's compound facts: those of Golden Set
version 2's case of the same id, or of the Brief Suite case with that id or recording it
as the version 1 case it replaces (`rewritten_facts`). An answer whose case has no
rewritten facts gives no fact item.

**Claim items** (`CLAIM_ITEMS`, about 200) are a claim, its context (heading and table
header) and the Sources it cites, re-split from each stored answer with the current claim
split (`edgar_eval.answer_checks.claims`). A report stores its answers but not their
Sources, so each Answer Context is prepared again, through the report's Arm at its own
setting, as `make eval-rescore` does; an answer whose Sources cannot be rebuilt as it was
given them, or a claim citing none of them, gives no claim item, since Jev never judges
one.

**Over-sampling.** The items are drawn at random with a fixed seed (`SEED`, recorded in
the sheet and the sample), after quotas that over-represent what matters, each met in
full or with every eligible item when there are fewer, in this order:

- claims Jev judged contradicted (`CONTRADICTED_SHARE` of the claim items) and
  unsupported (`UNSUPPORTED_SHARE`);
- every generator in the reports, `claude-haiku-5-5` included when its report exists:
  together `GENERATOR_SHARE` of each kind's items, split evenly;
- uncertain probabilities, between `UNCERTAIN[0]` and `UNCERTAIN[1]`
  (`UNCERTAIN_SHARE`): the saved probability that a fact is stated or a claim
  supported. A rewritten fact has a saved probability only where the saved answer was
  judged on that very fact, as a Brief Suite run is.

The saved verdicts steer the draw only. The sample file (`Sample.to_dict`) records why
each item was drawn, so it is not to be read while labelling; the sheet holds no verdict,
no probability and no reason for drawing an item.

**The sheet** is Markdown: the fact items, then the claim items, each section in
shuffled order, every item under its stable id (a digest of its content, so the same
item keeps its id in every draw). Every line of an item's content is quoted, and its
label goes on its own `LABEL <id> (...):` line: `stated` or `not stated` for a fact,
`supported`, `unsupported` or `contradicted` for a claim. A blank label is still to do.
A Source's text is shown in full under the first claim item citing it, and named by the
later ones, which keeps the sheet a size an editor opens.
Writing the sheet again keeps every label already entered, and refuses to drop an item
that has one, so labelling can stop and resume across sittings.

**Judging.** Jev judges each saved answer's items together, as a harness run does: its
facts in one request, its claims in one per set of cited Sources. The reference judge is
asked Jev's own questions and criteria (`edgar_eval.judge`), one item a request, its
answer held to a verdict by a JSON schema; it gives no probability.

**The trial LLM claim split** lives in the study only: the generation harness still
splits claims by sentence, and adopting the LLM split there is a follow-up (ADR 0013).
Claude Haiku 5.5 is given the answer and its cited sentences, numbered by their place in
the sentence split, and splits each into one-claim, self-contained statements. A
statement keeps its sentence's citations (the tags it names that the sentence cites, or
all of them when it names none) and its heading and table header, so each claim item's
sentence has its own statements, judged against that item's cited Sources. That keeps
the two splits comparable on the developer's labels, which are of the sentences.

**Scoring.** Jev's first run is the study's measure, since a harness run judges once: it
decides the revisit trigger and the stopping rule, and the second run measures how often
Jev agrees with itself. A fact counts as stated at `FACT_CUTOFF`; the sweep scores each of
`CUTOFFS` instead, and "averaged" counts each fact as its probability of a stated fact
(agreement p with a `stated` label, 1 - p with `not stated`), as a Fact Recall averaging
probabilities would. An item whose judgment failed is left out of that judge's scores
and counted.

- **The revisit trigger** fires when Jev's first run calls more than one in five
  (`REVISIT_SHARE`, strictly more) of the labelled bad claims supported, or its error
  differs by generator: Fisher's exact test, two-sided, of each generator's errors on
  facts, then on claims, against every other generator's, at `GENERATOR_ALPHA` shared out
  over the tests made (Bonferroni).
- **The stopping rule** is met once every fact item and at least `STOP_AFTER_CLAIMS` (100)
  claim items are labelled and the 95% Wilson interval of that false-supported share lies
  wholly below or wholly above one in five. The claim items left unlabelled are then
  left out, and the report is not partial.
- **The splits compared**, answer by answer over the answers with a labelled claim item:
  an answer is bad when the developer labels any of its claim items unsupported or
  contradicted, and each split finds it bad when Jev calls any of those sentences (Jev's
  first run), or any of their LLM statements, unsupported or contradicted. The report
  says which split agrees with the labels on more answers and which catches more of the
  bad ones, with McNemar's exact test shown but not decided on. An answer whose split or
  any judgment failed is left out and counted.

    python -m edgar_eval.judge_study sample [--reports PATH...] [--seed N]
        [--sheet PATH] [--sample PATH] [--index PATH]
    python -m edgar_eval.judge_study judge [--sample PATH] [--verdicts PATH] [--reference]
        [--llm-split] [--split-cache PATH]
    python -m edgar_eval.judge_study score [--sheet PATH] [--sample PATH]
        [--verdicts PATH] [--json PATH] [--partial]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from statistics import fmean
from typing import Any, Literal, Protocol, TextIO

from edgar_eval.answer_checks import Claim
from edgar_eval.answer_checks import claims as split_claims
from edgar_eval.judge import (
    CLAIM_CRITERIA,
    CLAIM_QUESTION,
    CONTEXT_NOTE,
    FACT_CRITERIA,
    FACT_CUTOFF,
    FACT_QUESTION,
    JEV_KEY_ENV,
    JEV_MODEL,
    JEV_USD_PER_MILLION_INPUT_TOKENS,
    VERDICTS,
    Evidence,
    Judgments,
)
from edgar_eval.metrics import cohen_kappa, fisher_exact, mcnemar_exact, wilson_interval
from edgar_rag.golden_set import (
    DEFAULT_BRIEF_SUITE,
    DEFAULT_GOLDEN_SET,
    DEFAULT_GOLDEN_SET_V2,
    BriefSuite,
    GoldenSet,
    RequiredFact,
    Tier,
    load_brief_suite,
    load_golden_set,
)
from edgar_rag.paths import DATA_DIR

__all__ = [
    "CLAIM_ITEMS",
    "CLAIM_LABELS",
    "CONTRADICTED_SHARE",
    "CUTOFFS",
    "DEFAULT_SAMPLE",
    "DEFAULT_SCORE",
    "DEFAULT_SHEET",
    "DEFAULT_SPLIT_CACHE",
    "DEFAULT_VERDICTS",
    "FACT_ITEMS",
    "FACT_LABELS",
    "GENERATOR_ALPHA",
    "GENERATOR_SHARE",
    "JUDGE_RUNS",
    "REFERENCE_MODEL",
    "REVISIT_SHARE",
    "SEED",
    "SPLIT_MODEL",
    "SPLIT_OUTPUT_TOKENS",
    "STOP_AFTER_CLAIMS",
    "UNCERTAIN",
    "UNCERTAIN_SHARE",
    "UNSUPPORTED_SHARE",
    "Agreement",
    "AnswerComparison",
    "AnswerSplit",
    "CutoffAgreement",
    "GeneratorError",
    "JudgeCost",
    "JudgeRun",
    "JudgeScore",
    "LLMSplitter",
    "Matches",
    "ReferenceJudge",
    "ReferenceVerdict",
    "Revisit",
    "RunAgreement",
    "Sample",
    "Share",
    "SourcesFor",
    "SplitAgreement",
    "SplitClaim",
    "SplitComparison",
    "SplitItem",
    "SplitRun",
    "Stopping",
    "StudyItem",
    "StudyJudge",
    "StudyScore",
    "Unlabelled",
    "Verdict",
    "default_reports",
    "draw_sample",
    "estimate_judge_cost",
    "judge_sample",
    "load_split",
    "load_verdicts",
    "main",
    "print_score",
    "read_labels",
    "rewritten_facts",
    "save_verdicts",
    "score",
    "split_sample",
    "write_sheet",
]

SEED = 20261017
"""The sample's seed, fixed before any item is drawn."""

FACT_ITEMS = 150
CLAIM_ITEMS = 200

UNCERTAIN = (0.05, 0.65)
"""Saved probabilities in this closed range are uncertain."""

UNCERTAIN_SHARE = 1 / 3
CONTRADICTED_SHARE = 1 / 10
UNSUPPORTED_SHARE = 1 / 4
GENERATOR_SHARE = 1 / 2
"""Of each kind's items, at least this share goes to the generators, split evenly."""

FACT_LABELS = ("stated", "not stated")
CLAIM_LABELS = ("supported", "unsupported", "contradicted")

STUDY_DIR = DATA_DIR / "derived" / "judge_study"
DEFAULT_SHEET = STUDY_DIR / "sheet.md"
DEFAULT_SAMPLE = STUDY_DIR / "sample.json"
DEFAULT_VERDICTS = STUDY_DIR / "verdicts.json"
DEFAULT_SCORE = STUDY_DIR / "score.json"

Kind = Literal["fact", "claim"]

SourcesFor = Callable[[Mapping, Mapping], Mapping[str, Evidence] | None]
"""The Sources a saved answer was given, by tag, from its report and its saved case, or
None when they cannot be rebuilt."""


@dataclass(frozen=True)
class StudyItem:
    """One item to label: a saved answer and one Required Fact, or one claim of a saved
    answer and the Sources it cites."""

    id: str
    kind: Kind
    case_id: str
    model: str
    """The generator that wrote the answer."""
    answer: str
    fact: str = ""
    tier: Tier | None = None
    claim: str = ""
    heading: str = ""
    table_header: str = ""
    sources: tuple[Evidence, ...] = ()
    """The Sources the claim cites, in its order."""
    drawn_for: str = ""
    """The quota the item was drawn for (a verdict, `generator:<model>`, `uncertain`),
    or `random`. It reflects Jev's saved verdict, so it never reaches the sheet."""


@dataclass(frozen=True)
class Sample:
    seed: int
    reports: tuple[str, ...]
    items: tuple[StudyItem, ...]
    """The fact items, then the claim items, each in shuffled order: the sheet's order."""
    skipped: dict[str, int]
    """Answers or claims that could give no item, by reason."""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping) -> Sample:
        """A sample saved with `to_dict`."""
        items = tuple(
            StudyItem(**{**i, "sources": tuple(Evidence(**s) for s in i["sources"])})
            for i in data["items"]
        )
        return cls(data["seed"], tuple(data["reports"]), items, dict(data["skipped"]))


# --- Drawing the sample -------------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    item: StudyItem
    probability: float | None
    """Jev's saved probability that the fact is stated or the claim supported."""
    verdict: str | None
    """Jev's saved verdict on the claim."""


def rewritten_facts(
    golden_set: GoldenSet, brief_suite: BriefSuite
) -> dict[str, tuple[RequiredFact, ...]]:
    """The one-claim Required Facts of each case id a saved answer may carry: Golden Set
    version 2's cases by id, and the Brief Suite's by id and by the version 1 case each
    replaces. A version 2 case comes first."""
    facts: dict[str, tuple[RequiredFact, ...]] = {}
    for case in brief_suite.cases:
        facts[case.id] = case.required_facts
        if case.replaces is not None:
            facts.setdefault(case.replaces, case.required_facts)
    for case in golden_set.cases:
        facts[case.id] = case.required_facts
    return facts


def draw_sample(
    reports: Sequence[tuple[str, Mapping]],
    facts: Mapping[str, Sequence[RequiredFact]],
    sources: SourcesFor,
    *,
    seed: int = SEED,
    fact_items: int = FACT_ITEMS,
    claim_items: int = CLAIM_ITEMS,
) -> Sample:
    """Draw the study's items from saved reports, each a (name, report) pair: a
    generation report (`GenerationReport.to_dict`) or a Brief Suite report, whose runs'
    reports are read. `facts` holds the rewritten facts by case id (`rewritten_facts`);
    `sources` rebuilds the Sources of a saved answer."""
    fact_pool: dict[str, _Candidate] = {}
    claim_pool: dict[str, _Candidate] = {}
    skipped = {"answers with no rewritten facts": 0, "answers whose Sources cannot be rebuilt": 0}
    for report in (r for _, data in reports for r in _generation_reports(data)):
        for case in report.get("cases", ()):
            rewritten = facts.get(case["case_id"])
            if rewritten:
                for candidate in _fact_candidates(case, rewritten):
                    fact_pool.setdefault(candidate.item.id, candidate)
            else:
                skipped["answers with no rewritten facts"] += 1
            given = sources(report, case)
            if given is None:
                skipped["answers whose Sources cannot be rebuilt"] += 1
                continue
            for candidate in _claim_candidates(case, given):
                claim_pool.setdefault(candidate.item.id, candidate)

    rng = random.Random(seed)
    drawn_facts = _draw(fact_pool, fact_items, _fact_quotas(fact_pool, fact_items), rng)
    drawn_claims = _draw(claim_pool, claim_items, _claim_quotas(claim_pool, claim_items), rng)
    return Sample(
        seed=seed,
        reports=tuple(name for name, _ in reports),
        items=(*drawn_facts, *drawn_claims),
        skipped=skipped,
    )


def _generation_reports(data: Mapping) -> list[Mapping]:
    """The generation reports in a saved file: the file itself, or a Brief Suite run's."""
    return list(data["run_reports"]) if "run_reports" in data else [data]


def _fact_candidates(case: Mapping, facts: Sequence[RequiredFact]) -> Iterable[_Candidate]:
    saved = {f["fact"]: f["probability"] for f in case.get("judgments", {}).get("facts", ())}
    for fact in facts:
        item = StudyItem(
            id=_item_id("F", case, fact.fact),
            kind="fact",
            case_id=case["case_id"],
            model=case["model"],
            answer=case["answer"],
            fact=fact.fact,
            tier=fact.tier,
        )
        yield _Candidate(item, saved.get(fact.fact), None)


def _claim_candidates(case: Mapping, given: Mapping[str, Evidence]) -> Iterable[_Candidate]:
    saved = {(c["claim"], tuple(c["tags"])): c for c in case.get("judgments", {}).get("claims", ())}
    for claim in split_claims(case["answer"]):
        cited = tuple(given[tag] for tag in claim.tags if tag in given)
        if not cited:
            continue  # unsupported without a Jev call, so nothing of Jev's to check
        verdict = saved.get((claim.text, claim.tags))
        item = StudyItem(
            id=_item_id("C", case, "\n".join((claim.text, *claim.tags))),
            kind="claim",
            case_id=case["case_id"],
            model=case["model"],
            answer=case["answer"],
            claim=claim.text,
            heading=claim.heading,
            table_header=claim.table_header,
            sources=cited,
        )
        yield _Candidate(
            item,
            verdict["probabilities"].get("supported") if verdict else None,
            verdict["verdict"] if verdict else None,
        )


def _item_id(prefix: str, case: Mapping, text: str) -> str:
    """A digest of the item's content, so the same item has the same id in every draw."""
    content = "\x1f".join((case["case_id"], case["model"], case["answer"], text))
    return f"{prefix}-{hashlib.sha256(content.encode('utf-8')).hexdigest()[:10]}"


Quota = tuple[str, Callable[[_Candidate], bool], int]
"""What an item is drawn for, which candidates meet it, and how many items must."""


def _uncertain(candidate: _Candidate) -> bool:
    p = candidate.probability
    return p is not None and UNCERTAIN[0] <= p <= UNCERTAIN[1]


def _generator_quotas(pool: Mapping[str, _Candidate], target: int) -> list[Quota]:
    models = sorted({c.item.model for c in pool.values()})
    each = math.ceil(target * GENERATOR_SHARE / len(models)) if models else 0
    return [(f"generator:{m}", lambda c, m=m: c.item.model == m, each) for m in models]


def _fact_quotas(pool: Mapping[str, _Candidate], target: int) -> list[Quota]:
    return [
        *_generator_quotas(pool, target),
        ("uncertain", _uncertain, math.ceil(target * UNCERTAIN_SHARE)),
    ]


def _claim_quotas(pool: Mapping[str, _Candidate], target: int) -> list[Quota]:
    return [
        (
            "contradicted",
            lambda c: c.verdict == "contradicted",
            math.ceil(target * CONTRADICTED_SHARE),
        ),
        (
            "unsupported",
            lambda c: c.verdict == "unsupported",
            math.ceil(target * UNSUPPORTED_SHARE),
        ),
        *_generator_quotas(pool, target),
        ("uncertain", _uncertain, math.ceil(target * UNCERTAIN_SHARE)),
    ]


def _draw(
    pool: Mapping[str, _Candidate], target: int, quotas: Sequence[Quota], rng: random.Random
) -> list[StudyItem]:
    """`target` items from the pool: each quota met in turn, counting the items already
    drawn, then the rest at random; returned in shuffled order."""
    candidates = [pool[i] for i in sorted(pool)]
    chosen: dict[str, StudyItem] = {}
    for reason, meets, wanted in quotas:
        have = sum(meets(pool[i]) for i in chosen)
        eligible = [c for c in candidates if c.item.id not in chosen and meets(c)]
        for c in rng.sample(
            eligible, max(0, min(wanted - have, len(eligible), target - len(chosen)))
        ):
            chosen[c.item.id] = replace(c.item, drawn_for=reason)
    rest = [c for c in candidates if c.item.id not in chosen]
    for c in rng.sample(rest, max(0, min(target - len(chosen), len(rest)))):
        chosen[c.item.id] = replace(c.item, drawn_for="random")
    items = list(chosen.values())
    rng.shuffle(items)
    return items


# --- The labelling sheet ------------------------------------------------------------------

_LABEL_LINE = re.compile(r"^LABEL (?P<id>[FC]-[0-9a-f]{10}) \([^)\n]*\):[ \t]*(?P<label>.*)$", re.M)


def _allowed(item_id: str) -> tuple[str, ...]:
    return FACT_LABELS if item_id.startswith("F-") else CLAIM_LABELS


def read_labels(path: str | Path) -> dict[str, str | None]:
    """The sheet's label of every item, by id: one of `FACT_LABELS` or `CLAIM_LABELS`
    (case and spacing aside), or None while it is blank. Raises ValueError on any other
    label."""
    labels: dict[str, str | None] = {}
    for match in _LABEL_LINE.finditer(Path(path).read_text(encoding="utf-8")):
        item_id = match["id"]
        label = " ".join(match["label"].split()).lower() or None
        if label is not None and label not in _allowed(item_id):
            raise ValueError(
                f"{path}: item {item_id} is labelled {match['label'].strip()!r}, not one of "
                f"{', '.join(_allowed(item_id))}"
            )
        labels[item_id] = label
    return labels


def write_sheet(sample: Sample, path: str | Path) -> int:
    """Write the sample's labelling sheet, keeping every label of a sheet already at
    `path`, and return how many were kept. Raises ValueError, writing nothing, when that
    sheet labels an item this sample does not draw, or holds a label that is not one."""
    path = Path(path)
    existing = read_labels(path) if path.exists() else {}
    ids = {item.id for item in sample.items}
    dropped = sorted(i for i, label in existing.items() if label and i not in ids)
    if dropped:
        raise ValueError(
            f"{path} holds labels for {len(dropped)} item(s) this sample does not draw "
            f"({', '.join(dropped)}); write the sheet elsewhere, or draw it with the seed "
            "and reports it was drawn with"
        )
    kept = {i: label for i, label in existing.items() if label}
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(_render(sample, kept), encoding="utf-8")
    partial.replace(path)
    return len(kept)


def _render(sample: Sample, labels: Mapping[str, str]) -> str:
    facts = [i for i in sample.items if i.kind == "fact"]
    claims = [i for i in sample.items if i.kind == "claim"]
    lines = [
        "# Judge study labelling sheet",
        "",
        f"Seed: {sample.seed}. Drawn from {len(sample.reports)} saved report(s): "
        f"{len(facts)} fact items and {len(claims)} claim items.",
        "",
        "Label each item on its `LABEL` line, after the colon. A fact item is `stated` or "
        "`not stated`: does the answer state the Required Fact, in any wording? A claim "
        "item is `supported`, `unsupported` or `contradicted`: how do the cited Sources "
        "relate to the claim? Its context (heading, table header) is there to read the "
        "claim by, not to be judged. Label every fact item, then the claim items in "
        "order. Leave a label blank to come back to it; drawing the sheet again keeps "
        "every label written here.",
        "",
        "## Fact items",
        "",
    ]
    for n, item in enumerate(facts, 1):
        lines += [
            f"### {n}. {item.id}",
            "",
            "**Required Fact**",
            "",
            *_quoted(item.fact),
            "",
            "**Answer**",
            "",
            *_quoted(item.answer),
            "",
            f"LABEL {item.id} (stated / not stated): {labels.get(item.id, '')}".rstrip(),
            "",
        ]
    lines += ["## Claim items", ""]
    # Each Source's text is shown in full once, under the first claim item citing it.
    first_shown: dict[tuple[str, str], int] = {}
    for n, item in enumerate(claims, 1):
        lines += [f"### {n}. {item.id}", "", "**Claim**", "", *_quoted(item.claim), ""]
        context = [("Heading", item.heading), ("Table header", item.table_header)]
        for name, value in (c for c in context if c[1]):
            lines += [f"**Context: {name.lower()}**", "", *_quoted(value), ""]
        for source in item.sources:
            lines += [f"**Cited Source {source.tag}**", "", *_quoted(source.label)]
            shown = first_shown.setdefault((source.label, source.text), n)
            if shown == n:
                lines += [">", *_quoted(source.text), ""]
            else:
                lines += ["", f"(The same Source: its text is under claim item {shown} above.)", ""]
        lines += [
            f"LABEL {item.id} (supported / unsupported / contradicted): "
            f"{labels.get(item.id, '')}".rstrip(),
            "",
        ]
    return "\n".join(lines)


def _quoted(text: str) -> list[str]:
    """The text as a Markdown quote, every line prefixed, so no line of it can be read as
    a label line."""
    return [f"> {line}".rstrip() for line in text.splitlines()] or [">"]


# --- Verdicts -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """One judge's verdict on one item, or the failure of its judgment, which is kept so
    no item is ever dropped."""

    item_id: str
    verdict: str | None
    """A fact item's `stated` or `not stated` (at `FACT_CUTOFF` for Jev), or a claim
    item's `supported`, `unsupported` or `contradicted`; None when the judgment failed."""
    probability: float | None = None
    """Jev's probability that the fact is stated; None for a claim, or a judge that gives
    none."""
    probabilities: dict[str, float] = field(default_factory=dict)
    """Jev's probability of each claim verdict."""
    error: str | None = None
    """Why the judgment failed."""

    @classmethod
    def of_fact(cls, item_id: str, probability: float) -> Verdict:
        return cls(item_id, _stated(probability, FACT_CUTOFF), probability)

    @classmethod
    def failed(cls, item_id: str, error: str) -> Verdict:
        return cls(item_id, None, error=error)

    def at(self, cutoff: float) -> str | None:
        """The fact verdict at another cut-off, where the judge gave a probability."""
        return self.verdict if self.probability is None else _stated(self.probability, cutoff)


def _stated(probability: float, cutoff: float) -> str:
    return "stated" if probability >= cutoff else "not stated"


@dataclass(frozen=True)
class JudgeRun:
    """One judge's pass over every sampled item."""

    judge: str
    """The judge's pinned model: `JEV_MODEL`, or `REFERENCE_MODEL` for the reference."""
    run: int
    verdicts: dict[str, Verdict]
    """A verdict, or a failure, for every item, by id."""
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_dict(cls, data: Mapping) -> JudgeRun:
        verdicts = {i: Verdict(**v) for i, v in data["verdicts"].items()}
        return cls(**{**data, "verdicts": verdicts})


# --- Judging ------------------------------------------------------------------------------

JUDGE_RUNS = 2
"""Jev judges every item this many times, so its run-to-run agreement is measured."""

REFERENCE_MODEL = "claude-haiku-5-5"
"""The reference judge, run once when asked for: a reference, not a candidate (ADR 0013).
An exact model id, never an alias."""

REFERENCE_MAX_TOKENS = 4_000
"""The reference judge's token cap, its thinking included."""
REFERENCE_OUTPUT_TOKENS = 500
"""The output tokens, thinking included, the cost estimate allows each reference request."""


class StudyJudge(Protocol):
    """What the study needs from Jev: `edgar_eval.judge.JevJudge`, or a fake."""

    model: str

    def judge(
        self,
        answer: str,
        required_facts: Sequence[str],
        claims: Sequence[Claim],
        sources: Mapping[str, Evidence],
    ) -> Judgments: ...


@dataclass(frozen=True)
class ReferenceVerdict:
    verdict: Verdict
    input_tokens: int = 0
    output_tokens: int = 0


class ReferenceJudge:
    """Claude Haiku 5.5, pinned to `REFERENCE_MODEL`, asked Jev's own questions one item at
    a time, its answer constrained to a verdict by a JSON schema. It gives a verdict, no
    probability. A request that fails, is refused, stops at the token cap or gives no
    verdict is recorded against its item."""

    def __init__(self, client: Any = None, model: str = REFERENCE_MODEL):
        self.model = model
        if client is None:
            from anthropic import Anthropic

            client = Anthropic()
        self._client = client

    def judge_item(self, item: StudyItem) -> ReferenceVerdict:
        prompt, schema = _reference_request(item)
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=REFERENCE_MAX_TOKENS,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as error:  # noqa: BLE001 - recorded against its item
            return ReferenceVerdict(Verdict.failed(item.id, f"{type(error).__name__}: {error}"))
        usage = getattr(response, "usage", None)
        tokens = (getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)
        if response.stop_reason != "end_turn":
            return ReferenceVerdict(
                Verdict.failed(item.id, f"stop_reason {response.stop_reason}"), *tokens
            )
        try:
            text = next(b.text for b in response.content if b.type == "text")
            data = json.loads(text)
            verdict = (
                ("stated" if data["stated"] else "not stated")
                if item.kind == "fact"
                else data["verdict"]
            )
        except (StopIteration, ValueError, KeyError, TypeError) as error:
            return ReferenceVerdict(Verdict.failed(item.id, f"no verdict: {error!r}"), *tokens)
        if verdict not in _allowed(item.id):
            return ReferenceVerdict(Verdict.failed(item.id, f"no verdict: {verdict!r}"), *tokens)
        return ReferenceVerdict(Verdict(item.id, verdict), *tokens)


def _reference_request(item: StudyItem) -> tuple[str, dict]:
    """The reference judge's prompt and answer schema for an item: Jev's question and
    criteria, over the same state Jev is given."""
    if item.kind == "fact":
        criteria = "\n".join(f"- {k}: {v}" for k, v in FACT_CRITERIA.items())
        prompt = (
            f"<answer>\n{item.answer}\n</answer>\n\n<required_fact>\n{item.fact}\n"
            f"</required_fact>\n\n{FACT_QUESTION}\n\nSet `stated` by these criteria:\n{criteria}"
        )
        properties: dict = {"stated": {"type": "boolean"}}
    else:
        sources = "\n\n".join(
            f'<source tag="{s.tag}" label="{s.label}">\n{s.text}\n</source>' for s in item.sources
        )
        context = "".join(
            f"<{name}>{value}</{name}>\n"
            for name, value in (("heading", item.heading), ("table_header", item.table_header))
            if value
        )
        question = CLAIM_QUESTION + (CONTEXT_NOTE if context else "")
        criteria = "\n".join(f"- {k}: {v}" for k, v in CLAIM_CRITERIA.items())
        prompt = (
            f"<sources>\n{sources}\n</sources>\n\n<claim>\n{item.claim}\n</claim>\n\n"
            + (f"<context>\n{context}</context>\n\n" if context else "")
            + f"{question}\n\nSet `verdict` by these criteria:\n{criteria}"
        )
        properties = {"verdict": {"type": "string", "enum": list(VERDICTS)}}
    schema = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    return prompt, schema


_Group = list[StudyItem]


def _answer_groups(sample: Sample) -> list[_Group]:
    """The items of each saved answer, which Jev judges together, as a harness run does:
    its facts in one request, its claims in one per set of cited Sources."""
    groups: dict[tuple[str, str, str], _Group] = {}
    for item in sample.items:
        groups.setdefault((item.case_id, item.model, item.answer), []).append(item)
    return list(groups.values())


def _claim_of(item: StudyItem) -> Claim:
    return Claim(item.claim, tuple(s.tag for s in item.sources), item.heading, item.table_header)


def _jev_group(jev: StudyJudge, group: _Group) -> tuple[list[Verdict], Judgments]:
    facts = [i for i in group if i.kind == "fact"]
    claims = [i for i in group if i.kind == "claim"]
    sources = {s.tag: s for i in claims for s in i.sources}
    judged = jev.judge(
        group[0].answer, [i.fact for i in facts], [_claim_of(i) for i in claims], sources
    )

    def failure(kind: str, text: str) -> str:
        return next(
            (f.error for f in judged.failures if f.judgment == kind and text in f.items),
            "no verdict returned",
        )

    verdicts = []
    if judged.facts:
        verdicts += [
            Verdict.of_fact(i.id, f.probability) for i, f in zip(facts, judged.facts, strict=True)
        ]
    else:
        verdicts += [Verdict.failed(i.id, failure("fact_recall", i.fact)) for i in facts]
    by_claim = {(c.claim, c.tags): c for c in judged.claims}
    for item in claims:
        claim = _claim_of(item)
        found = by_claim.get((claim.text, claim.tags))
        verdicts.append(
            Verdict(item.id, found.verdict, probabilities=dict(found.probabilities))
            if found
            else Verdict.failed(item.id, failure("faithfulness", claim.text))
        )
    return verdicts, judged


def judge_sample(
    sample: Sample,
    jev: StudyJudge,
    *,
    runs: int = JUDGE_RUNS,
    reference: ReferenceJudge | None = None,
    workers: int = 4,
) -> tuple[JudgeRun, ...]:
    """Jev's `runs` passes over every sampled item, then the reference judge's one when
    given. Every item gets a verdict or a recorded failure in every run."""
    groups = _answer_groups(sample)
    passes: list[JudgeRun] = []
    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        for n in range(1, runs + 1):
            judged = list(pool.map(lambda g: _jev_group(jev, g), groups))
            passes.append(
                JudgeRun(
                    judge=jev.model,
                    run=n,
                    verdicts={v.item_id: v for verdicts, _ in judged for v in verdicts},
                    requests=sum(j.requests for _, j in judged),
                    input_tokens=sum(j.input_tokens for _, j in judged),
                )
            )
        if reference is not None:
            answers = list(pool.map(reference.judge_item, sample.items))
            passes.append(
                JudgeRun(
                    judge=reference.model,
                    run=1,
                    verdicts={a.verdict.item_id: a.verdict for a in answers},
                    requests=len(answers),
                    input_tokens=sum(a.input_tokens for a in answers),
                    output_tokens=sum(a.output_tokens for a in answers),
                )
            )
    return tuple(passes)


@dataclass(frozen=True)
class JudgeCost:
    """The estimated cost of judging a sample, before any request."""

    jev_requests: int
    """Per run."""
    jev_usd: float
    """Every run."""
    runs: int
    reference_usd: float | None
    split_usd: float | None = None
    """The LLM claim split of the answers not cached, and Jev once on its statements."""
    split_answers: int = 0
    split_cached: int = 0

    def line(self) -> str:
        total = self.jev_usd + (self.reference_usd or 0.0) + (self.split_usd or 0.0)
        text = (
            f"Estimated cost: about ${total:.2f}: {JEV_MODEL} {self.runs} times "
            f"({self.jev_requests} requests a run), ${self.jev_usd:.3f}"
        )
        if self.reference_usd is not None:
            text += f"; {REFERENCE_MODEL} once, ${self.reference_usd:.3f}"
        if self.split_usd is not None:
            text += (
                f"; the {SPLIT_MODEL} claim split of {self.split_answers} answers "
                f"({self.split_cached} cached) and {JEV_MODEL} once on its statements, "
                f"${self.split_usd:.3f}"
            )
        return text + "."


def estimate_judge_cost(
    sample: Sample,
    *,
    runs: int = JUDGE_RUNS,
    reference: bool,
    splitter: LLMSplitter | None = None,
) -> JudgeCost:
    """Jev's cost from the tokens of each request's state and questions, at its price;
    the reference's from each prompt's tokens and `REFERENCE_OUTPUT_TOKENS` of output, at
    its list price in `edgar_eval.generators.GENERATORS`; and, with a splitter, the LLM
    split's from each uncached answer's prompt tokens and `SPLIT_OUTPUT_TOKENS` of output
    at its list price, plus one Jev pass over the claim items' Sources and statements
    (taken as twice the claims' tokens)."""
    from edgar_eval.generators import generator
    from edgar_rag.retrieval import count_tokens

    requests, tokens, claim_tokens = 0, 0, 0
    for group in _answer_groups(sample):
        facts = [i.fact for i in group if i.kind == "fact"]
        if facts:
            requests += 1
            tokens += count_tokens("\n".join([group[0].answer, *facts]))
        by_sources: dict[tuple[str, ...], list[StudyItem]] = {}
        for item in (i for i in group if i.kind == "claim"):
            by_sources.setdefault(tuple(s.tag for s in item.sources), []).append(item)
        for members in by_sources.values():
            requests += 1
            texts = [f"{s.label}\n{s.text}" for s in members[0].sources]
            tokens += count_tokens("\n".join([*texts, *(i.claim for i in members)]))
            claim_tokens += count_tokens("\n".join([*texts, *(i.claim for i in members * 2)]))
    jev_usd = runs * tokens * JEV_USD_PER_MILLION_INPUT_TOKENS / 1_000_000
    reference_usd = None
    if reference:
        price = generator(REFERENCE_MODEL).price
        prompt_tokens = sum(count_tokens(_reference_request(i)[0]) for i in sample.items)
        output_tokens = REFERENCE_OUTPUT_TOKENS * len(sample.items)
        reference_usd = (prompt_tokens * price.input + output_tokens * price.output) / 1_000_000
    if splitter is None:
        return JudgeCost(requests, jev_usd, runs, reference_usd)
    answers = {i.answer for i in sample.items if i.kind == "claim"}
    uncached = [a for a in sorted(answers) if not splitter.cached(a)]
    price = generator(splitter.model).price
    prompt_tokens = sum(count_tokens(_split_prompt(a)) for a in uncached)
    output_tokens = SPLIT_OUTPUT_TOKENS * len(uncached)
    split_usd = (prompt_tokens * price.input + output_tokens * price.output) / 1_000_000
    split_usd += claim_tokens * JEV_USD_PER_MILLION_INPUT_TOKENS / 1_000_000
    return JudgeCost(
        requests,
        jev_usd,
        runs,
        reference_usd,
        split_usd,
        len(answers),
        len(answers) - len(uncached),
    )


def save_verdicts(
    runs: Sequence[JudgeRun], sample: Sample, path: str | Path, split: SplitRun | None = None
) -> None:
    """Write the judges' verdicts, and the LLM split's when it was run, apart from the
    sheet."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "seed": sample.seed,
        "items": len(sample.items),
        "fact_cutoff": FACT_CUTOFF,
        "runs": [asdict(r) for r in runs],
    }
    if split is not None:
        data["llm_split"] = split.to_dict()
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    partial.replace(path)


def load_verdicts(path: str | Path) -> tuple[JudgeRun, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(JudgeRun.from_dict(r) for r in data["runs"])


def load_split(path: str | Path) -> SplitRun | None:
    """The LLM split stored with the verdicts, or None when it was not run."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return SplitRun.from_dict(data["llm_split"]) if "llm_split" in data else None


# --- The trial LLM claim split ------------------------------------------------------------

SPLIT_MODEL = "claude-haiku-5-5"
"""The trial LLM claim split's model (ADR 0013): an exact model id, never an alias. The
split lives in the study only; the generation harness splits claims by sentence."""

SPLIT_MAX_TOKENS = 8_000
"""The split's token cap, its thinking included."""
SPLIT_OUTPUT_TOKENS = 1_500
"""The output tokens, thinking included, the cost estimate allows each split request."""

DEFAULT_SPLIT_CACHE = STUDY_DIR / "llm_split"

SPLIT_INSTRUCTIONS = (
    "Split each numbered sentence of the answer above into one-claim, self-contained "
    "statements. A statement makes one claim that can be checked on its own: name what "
    'it is about instead of writing "it", "they" or "this", and keep the figures, '
    "periods and qualifiers the sentence gives it. Add nothing the sentence does not say, "
    "and leave nothing it claims out. A sentence that makes one claim gives one "
    "statement. Give each statement the number of the sentence it comes from, and the "
    "Source tags of that sentence that it rests on."
)

_SPLIT_SCHEMA = {
    "type": "object",
    "properties": {
        "statements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sentence": {"type": "integer"},
                    "claim": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["sentence", "claim", "tags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["statements"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class AnswerSplit:
    """An answer's LLM split: each statement with the index of the sentence it comes from
    in the sentence split (`edgar_eval.answer_checks.claims`), or the split's failure."""

    statements: tuple[tuple[int, Claim], ...] = ()
    error: str | None = None
    cached: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


class LLMSplitter:
    """The trial LLM claim split: Claude Haiku 5.5, pinned to `SPLIT_MODEL`, splits each
    cited sentence of an answer into one-claim, self-contained statements, one request an
    answer, its answer held to a list of statements by a JSON schema.

    A statement keeps its sentence's citations: the tags it gives that its sentence cites,
    or all of the sentence's when it gives none of them; and its sentence's heading and
    table header, the context the judge reads it by. The output is cached per answer in
    `cache_dir`, so a rerun makes no request; a split that fails is not cached."""

    def __init__(
        self,
        client: Any = None,
        model: str = SPLIT_MODEL,
        cache_dir: str | Path = DEFAULT_SPLIT_CACHE,
    ):
        self.model = model
        self.cache_dir = Path(cache_dir)
        self._client = client

    def _cache_path(self, answer: str) -> Path:
        key = "\x1f".join((self.model, _split_prompt(answer)))
        return self.cache_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()[:20]}.json"

    def cached(self, answer: str) -> bool:
        return self._cache_path(answer).exists()

    def split(self, answer: str) -> AnswerSplit:
        sentences = split_claims(answer)
        path = self._cache_path(answer)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))["statements"]
            return AnswerSplit(_statements(raw, sentences), cached=True)
        if self._client is None:
            from anthropic import Anthropic

            self._client = Anthropic()
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=SPLIT_MAX_TOKENS,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": _SPLIT_SCHEMA},
                },
                messages=[{"role": "user", "content": _split_prompt(answer)}],
            )
        except Exception as error:  # noqa: BLE001 - recorded against the answer's items
            return AnswerSplit(error=f"{type(error).__name__}: {error}")
        usage = getattr(response, "usage", None)
        tokens = {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        }
        if response.stop_reason != "end_turn":
            return AnswerSplit(error=f"stop_reason {response.stop_reason}", **tokens)
        try:
            text = next(b.text for b in response.content if b.type == "text")
            raw = json.loads(text)["statements"]
            statements = _statements(raw, sentences)
        except (StopIteration, ValueError, KeyError, TypeError) as error:
            return AnswerSplit(error=f"no statements: {error!r}", **tokens)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"model": self.model, "statements": raw}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return AnswerSplit(statements, **tokens)


def _split_prompt(answer: str) -> str:
    """The split's prompt: the answer, then its cited sentences, numbered by their index
    in the sentence split (uncited ones are unsupported whatever their split)."""
    numbered = "\n".join(
        f'<sentence n="{n}" tags="{", ".join(c.tags)}">{c.text}</sentence>'
        for n, c in enumerate(split_claims(answer))
        if c.tags
    )
    return (
        f"<answer>\n{answer}\n</answer>\n\n<sentences>\n{numbered}\n</sentences>\n\n"
        f"{SPLIT_INSTRUCTIONS}"
    )


def _statements(
    raw: Sequence[Mapping], sentences: Sequence[Claim]
) -> tuple[tuple[int, Claim], ...]:
    """The split's statements as claims, each keeping its sentence's citations and
    context; one naming no cited sentence of the answer is dropped."""
    found = []
    for statement in raw:
        n = statement["sentence"]
        if not isinstance(n, int) or not 0 <= n < len(sentences) or not sentences[n].tags:
            continue
        sentence = sentences[n]
        text = " ".join(str(statement["claim"]).split())
        if not text:
            continue
        given = [t for t in sentence.tags if t in set(statement.get("tags") or ())]
        tags = tuple(given) or sentence.tags
        found.append((n, Claim(text, tags, sentence.heading, sentence.table_header)))
    return tuple(found)


@dataclass(frozen=True)
class SplitClaim:
    """One statement of the LLM split, and Jev's verdict on it, or its failure."""

    claim: str
    tags: tuple[str, ...]
    verdict: str | None
    error: str | None = None


@dataclass(frozen=True)
class SplitItem:
    """The LLM split's statements of one claim item's sentence, each judged by Jev; or
    why there are none to judge."""

    item_id: str
    claims: tuple[SplitClaim, ...]
    error: str | None = None
    """The split of the item's answer failed."""


@dataclass(frozen=True)
class SplitRun:
    """The LLM split of every sampled answer with a claim item, its statements judged once
    by Jev with each claim item's cited Sources."""

    model: str
    judge: str
    items: dict[str, SplitItem]
    """By claim item id."""
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached: int = 0
    """Answers whose split was read from the cache."""
    judge_requests: int = 0
    judge_input_tokens: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["items"] = list(data["items"].values())
        return data

    @classmethod
    def from_dict(cls, data: Mapping) -> SplitRun:
        items = {
            i["item_id"]: SplitItem(
                i["item_id"],
                tuple(SplitClaim(**{**c, "tags": tuple(c["tags"])}) for c in i["claims"]),
                i.get("error"),
            )
            for i in data["items"]
        }
        return cls(**{**data, "items": items})


def _sentence_of(item: StudyItem, sentences: Sequence[Claim]) -> int | None:
    """The index of a claim item's sentence in its answer's sentence split."""
    cited = {s.tag for s in item.sources}
    return next(
        (
            n
            for n, c in enumerate(sentences)
            if (c.text, c.heading, c.table_header) == (item.claim, item.heading, item.table_header)
            and cited <= set(c.tags)
        ),
        None,
    )


def split_sample(
    sample: Sample, splitter: LLMSplitter, jev: StudyJudge, *, workers: int = 4
) -> SplitRun:
    """Split every sampled answer with a claim item, then have Jev judge, once, the
    statements of each claim item's sentence against that item's cited Sources: each
    answer's statements together, as a harness run judges its claims."""
    groups: dict[str, list[StudyItem]] = {}
    for item in (i for i in sample.items if i.kind == "claim"):
        groups.setdefault(item.answer, []).append(item)

    def one(answer: str) -> tuple[AnswerSplit, list[SplitItem], Judgments | None]:
        items = groups[answer]
        split = splitter.split(answer)
        if split.error is not None:
            return split, [SplitItem(i.id, (), split.error) for i in items], None
        sentences = split_claims(answer)
        of_item = {}
        for item in items:
            n = _sentence_of(item, sentences)
            of_item[item.id] = [c for m, c in split.statements if m == n]
        claims = [c for i in items for c in of_item[i.id]]
        sources = {s.tag: s for i in items for s in i.sources}
        judged = jev.judge(answer, [], claims, sources) if claims else None
        verdicts = {(c.claim, c.tags): c.verdict for c in judged.claims} if judged else {}

        def failure(text: str) -> str:
            failures = judged.failures if judged else ()
            return next(
                (f.error for f in failures if f.judgment == "faithfulness" and text in f.items),
                "no verdict returned",
            )

        judged_items = []
        for item in items:
            rows = []
            for c in of_item[item.id]:
                verdict = verdicts.get((c.text, c.tags))
                rows.append(
                    SplitClaim(c.text, c.tags, verdict, None if verdict else failure(c.text))
                )
            judged_items.append(SplitItem(item.id, tuple(rows)))
        return split, judged_items, judged

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        results = list(pool.map(one, groups))
    splits = [s for s, _, _ in results]
    judged = [j for _, _, j in results if j is not None]
    return SplitRun(
        model=splitter.model,
        judge=jev.model,
        items={i.item_id: i for _, items, _ in results for i in items},
        requests=sum(not s.cached for s in splits),
        input_tokens=sum(s.input_tokens for s in splits),
        output_tokens=sum(s.output_tokens for s in splits),
        cached=sum(s.cached for s in splits),
        judge_requests=sum(j.requests for j in judged),
        judge_input_tokens=sum(j.input_tokens for j in judged),
    )


# --- Scoring ------------------------------------------------------------------------------

CUTOFFS = tuple(round(0.1 * n, 1) for n in range(1, 10))
"""The candidate fact cut-offs the score sweeps."""

STOP_AFTER_CLAIMS = 100
"""Claim labelling may stop once this many claim items are labelled (ADR 0013)."""

REVISIT_SHARE = Fraction(1, 5)
"""ADR 0013 is revisited if Jev calls more than this share of bad claims supported."""

GENERATOR_ALPHA = 0.05
"""The significance level, shared out over the tests made (Bonferroni), at which Jev's
error differs by generator."""

BAD_CLAIMS = ("unsupported", "contradicted")


@dataclass(frozen=True)
class Agreement:
    """A judge's verdicts against the labels, over the labelled items it judged."""

    items: int
    accuracy: float | None
    kappa: float | None
    """Cohen's kappa; None when undefined (no item, or one category on both sides)."""


@dataclass(frozen=True)
class CutoffAgreement:
    cutoff: float
    accuracy: float | None
    kappa: float | None


@dataclass(frozen=True)
class Share:
    """A count of `of`, its share and the share's 95% Wilson interval."""

    count: int
    of: int
    share: float | None
    low: float | None
    high: float | None

    @classmethod
    def of_counts(cls, count: int, of: int) -> Share:
        interval = wilson_interval(count, of)
        low, high = interval if interval else (None, None)
        return cls(count, of, count / of if of else None, low, high)


@dataclass(frozen=True)
class GeneratorError:
    """A judge's errors on one generator's items of one kind, and Fisher's exact test of
    them against every other generator's."""

    model: str
    kind: Kind
    items: int
    errors: int
    error_rate: float | None
    p_value: float | None
    """None when there is no other generator to compare with."""


@dataclass(frozen=True)
class JudgeScore:
    judge: str
    run: int
    facts: Agreement
    """At `FACT_CUTOFF`."""
    claims: Agreement
    false_supported: Share
    """Of the claims labelled unsupported or contradicted, those the judge calls
    supported."""
    by_generator: tuple[GeneratorError, ...]
    generator_differs: bool
    """Whether any generator's error rate differs from the others' at `GENERATOR_ALPHA`."""
    cutoffs: tuple[CutoffAgreement, ...]
    """The facts at each of `CUTOFFS`, for a judge that gives probabilities."""
    averaged: float | None
    """The facts' agreement with the labels when each counts as its probability of a
    stated fact, as a Fact Recall averaging probabilities would: p for a fact labelled
    stated, 1 - p for one not. None for a judge with no probabilities."""
    failed: int
    """Labelled items whose judgment failed, left out of the scores above."""


@dataclass(frozen=True)
class Matches:
    agree: int
    of: int
    share: float | None


@dataclass(frozen=True)
class RunAgreement:
    """How often Jev's two runs give the same verdict, over every item both judged."""

    facts: Matches
    claims: Matches


@dataclass(frozen=True)
class Revisit:
    """ADR 0013's revisit trigger, on Jev's first run."""

    fired: bool
    false_supported_above: bool
    """More than one in five bad claims called supported."""
    generator_differs: bool


@dataclass(frozen=True)
class Stopping:
    """The early-stopping rule, fixed before labelling (ADR 0013): every fact item and at
    least `STOP_AFTER_CLAIMS` claim items labelled, and the 95% interval of Jev's
    false-supported share wholly below or wholly above one in five."""

    met: bool
    facts_labelled: int
    facts: int
    claims_labelled: int
    claims: int
    decided: Literal["below", "above"] | None
    """Which side of one in five the interval lies wholly on, if either."""


Better = Literal["sentence", "llm", "both", "neither"]


@dataclass(frozen=True)
class AnswerComparison:
    """One answer's labelled claim items: whether the developer labelled any of them
    unsupported or contradicted, and whether Jev's first run on the sentences, and Jev on
    the LLM split's statements of those sentences, finds any."""

    case_id: str
    model: str
    items: int
    labelled_bad: bool
    sentence_bad: bool
    llm_bad: bool
    better: Better
    """Which split's verdict on the answer agrees with the labels."""


@dataclass(frozen=True)
class SplitAgreement:
    """One split's per-answer verdicts against the labels."""

    agree: int
    of: int
    caught: int
    """Answers labelled with a bad claim in which this split's verdicts find one."""
    bad: int
    false_alarms: int
    """Answers labelled with no bad claim in which this split's verdicts find one."""
    clean: int


@dataclass(frozen=True)
class SplitComparison:
    """The trial LLM claim split against the sentence split, answer by answer, over the
    answers with a labelled claim item."""

    answers: tuple[AnswerComparison, ...]
    left_out: int
    """Answers left out: their split failed, or a judgment of either split did."""
    sentence: SplitAgreement
    llm: SplitAgreement
    agrees_better: Literal["sentence", "llm", "tie"]
    catches_more: Literal["sentence", "llm", "tie"]
    p_value: float
    """McNemar's exact test, two-sided, of the answers only one split agrees on: shown,
    not decided on."""


@dataclass(frozen=True)
class StudyScore:
    fact_cutoff: float
    partial: bool
    """Scored with items still unlabelled and the stopping rule not met."""
    stopping: Stopping
    judges: tuple[JudgeScore, ...]
    """Jev's runs, then the reference judge's, when run."""
    run_agreement: RunAgreement | None
    revisit: Revisit
    split: SplitComparison | None = None
    """The LLM claim split against the sentence split, when it was run."""

    def to_dict(self) -> dict:
        return asdict(self)


class Unlabelled(ValueError):
    """Items remain unlabelled, the stopping rule is not met and no partial report was
    asked for."""


def score(
    sample: Sample,
    labels: Mapping[str, str | None],
    runs: Sequence[JudgeRun],
    *,
    split: SplitRun | None = None,
    partial: bool = False,
) -> StudyScore:
    """Score the judges' verdicts against the developer's labels (`read_labels`). Jev's
    first run is the study's measure, as one harness run judges once: it decides the
    revisit trigger and the stopping rule; its second run measures how often Jev agrees
    with itself. Raises `Unlabelled` while any item is unlabelled, unless the stopping
    rule is met or `partial` is set; raises ValueError on labels or verdicts of items not
    in the sample, or verdicts missing one. With the LLM split's run, it also compares
    that split with the sentence split (`SplitComparison`)."""
    ids = {item.id for item in sample.items}
    unknown = sorted(set(labels) - ids)
    if unknown:
        raise ValueError(f"labels for {len(unknown)} item(s) not in the sample: {unknown[:5]}")
    for run in runs:
        if set(run.verdicts) != ids:
            raise ValueError(
                f"the verdicts of {run.judge} run {run.run} are not of this sample: draw "
                "and judge it again"
            )
    jev = [r for r in runs if r.judge == JEV_MODEL]
    if not jev:
        raise ValueError(f"no {JEV_MODEL} run among the verdicts")

    labelled = [item for item in sample.items if labels.get(item.id)]
    judges = tuple(_judge_score(run, labelled, labels) for run in (*jev, *_others(runs)))
    first = judges[0]
    stopping = _stopping(sample, labelled, first.false_supported)
    remaining = len(sample.items) - len(labelled)
    if remaining and not stopping.met and not partial:
        raise Unlabelled(
            f"{remaining} item(s) unlabelled ({stopping.facts - stopping.facts_labelled} "
            f"fact, {stopping.claims - stopping.claims_labelled} claim) and the stopping rule "
            "is not met: label them, or ask for a partial report"
        )
    above = first.false_supported.of > 0 and (
        Fraction(first.false_supported.count, first.false_supported.of) > REVISIT_SHARE
    )
    return StudyScore(
        fact_cutoff=FACT_CUTOFF,
        partial=bool(remaining) and not stopping.met,
        stopping=stopping,
        judges=judges,
        run_agreement=_run_agreement(sample, jev[0], jev[1]) if len(jev) > 1 else None,
        revisit=Revisit(
            fired=above or first.generator_differs,
            false_supported_above=above,
            generator_differs=first.generator_differs,
        ),
        split=_compare_splits(labelled, labels, jev[0], split) if split is not None else None,
    )


def _compare_splits(
    labelled: Sequence[StudyItem],
    labels: Mapping[str, str | None],
    sentences: JudgeRun,
    split: SplitRun,
) -> SplitComparison:
    groups: dict[tuple[str, str, str], list[StudyItem]] = {}
    for item in (i for i in labelled if i.kind == "claim"):
        groups.setdefault((item.case_id, item.model, item.answer), []).append(item)
    rows, left_out = [], 0
    for (case_id, model, _), items in groups.items():
        llm = [split.items.get(i.id) for i in items]
        if (
            any(sentences.verdicts[i.id].verdict is None for i in items)
            or any(s is None or s.error is not None for s in llm)
            or any(c.verdict is None for s in llm for c in s.claims)
        ):
            left_out += 1
            continue
        labelled_bad = any(labels[i.id] in BAD_CLAIMS for i in items)
        sentence_bad = any(sentences.verdicts[i.id].verdict in BAD_CLAIMS for i in items)
        llm_bad = any(c.verdict in BAD_CLAIMS for s in llm for c in s.claims)
        right = (sentence_bad == labelled_bad, llm_bad == labelled_bad)
        better: Better = {
            (True, True): "both",
            (True, False): "sentence",
            (False, True): "llm",
            (False, False): "neither",
        }[right]
        rows.append(
            AnswerComparison(
                case_id, model, len(items), labelled_bad, sentence_bad, llm_bad, better
            )
        )

    def agreement(flagged: Callable[[AnswerComparison], bool]) -> SplitAgreement:
        return SplitAgreement(
            agree=sum(flagged(r) == r.labelled_bad for r in rows),
            of=len(rows),
            caught=sum(flagged(r) and r.labelled_bad for r in rows),
            bad=sum(r.labelled_bad for r in rows),
            false_alarms=sum(flagged(r) and not r.labelled_bad for r in rows),
            clean=sum(not r.labelled_bad for r in rows),
        )

    def ahead(sentence: int, llm: int) -> Literal["sentence", "llm", "tie"]:
        return "llm" if llm > sentence else "sentence" if sentence > llm else "tie"

    by_sentence = agreement(lambda r: r.sentence_bad)
    by_llm = agreement(lambda r: r.llm_bad)
    test = mcnemar_exact(
        [r.llm_bad == r.labelled_bad for r in rows],
        [r.sentence_bad == r.labelled_bad for r in rows],
    )
    return SplitComparison(
        answers=tuple(rows),
        left_out=left_out,
        sentence=by_sentence,
        llm=by_llm,
        agrees_better=ahead(by_sentence.agree, by_llm.agree),
        catches_more=ahead(by_sentence.caught, by_llm.caught),
        p_value=test.p_value,
    )


def _others(runs: Sequence[JudgeRun]) -> list[JudgeRun]:
    return [r for r in runs if r.judge != JEV_MODEL]


def _judge_score(
    run: JudgeRun, labelled: Sequence[StudyItem], labels: Mapping[str, str | None]
) -> JudgeScore:
    judged = [i for i in labelled if run.verdicts[i.id].verdict is not None]
    facts = [i for i in judged if i.kind == "fact"]
    claims = [i for i in judged if i.kind == "claim"]

    def pairs(items: Sequence[StudyItem], cutoff: float = FACT_CUTOFF) -> list[tuple[str, str]]:
        return [(labels[i.id], run.verdicts[i.id].at(cutoff)) for i in items]

    with_probability = [i for i in facts if run.verdicts[i.id].probability is not None]
    bad = [i for i in claims if labels[i.id] in BAD_CLAIMS]
    by_generator = _by_generator(judged, lambda i: run.verdicts[i.id].verdict != labels[i.id])
    tests = sum(g.p_value is not None for g in by_generator)
    return JudgeScore(
        judge=run.judge,
        run=run.run,
        facts=_agreement(pairs(facts)),
        claims=_agreement(pairs(claims)),
        false_supported=Share.of_counts(
            sum(run.verdicts[i.id].verdict == "supported" for i in bad), len(bad)
        ),
        by_generator=by_generator,
        generator_differs=any(
            g.p_value is not None and g.p_value < GENERATOR_ALPHA / tests for g in by_generator
        ),
        cutoffs=tuple(
            CutoffAgreement(c, a.accuracy, a.kappa)
            for c in CUTOFFS
            for a in [_agreement(pairs(with_probability, c))]
        )
        if with_probability
        else (),
        averaged=fmean(
            p if labels[i.id] == "stated" else 1 - p
            for i in with_probability
            for p in [run.verdicts[i.id].probability]
        )
        if with_probability
        else None,
        failed=len(labelled) - len(judged),
    )


def _agreement(pairs: Sequence[tuple[str, str]]) -> Agreement:
    agree = sum(a == b for a, b in pairs)
    return Agreement(len(pairs), agree / len(pairs) if pairs else None, cohen_kappa(pairs))


def _by_generator(
    items: Sequence[StudyItem], wrong: Callable[[StudyItem], bool]
) -> tuple[GeneratorError, ...]:
    rows = []
    for kind in ("fact", "claim"):
        of_kind = [i for i in items if i.kind == kind]
        models = sorted({i.model for i in of_kind})
        counts = {
            m: (sum(i.model == m for i in of_kind), sum(i.model == m and wrong(i) for i in of_kind))
            for m in models
        }
        total, total_errors = len(of_kind), sum(e for _, e in counts.values())
        for model, (n, errors) in counts.items():
            rest, rest_errors = total - n, total_errors - errors
            p = (
                fisher_exact(errors, n - errors, rest_errors, rest - rest_errors)
                if len(models) > 1
                else None
            )
            rows.append(GeneratorError(model, kind, n, errors, errors / n, p))
    return tuple(rows)


def _stopping(sample: Sample, labelled: Sequence[StudyItem], false_supported: Share) -> Stopping:
    facts = sum(i.kind == "fact" for i in sample.items)
    facts_labelled = sum(i.kind == "fact" for i in labelled)
    claims_labelled = len(labelled) - facts_labelled
    low, high = false_supported.low, false_supported.high
    decided = (
        "below"
        if high is not None and high < REVISIT_SHARE
        else "above"
        if low is not None and low > REVISIT_SHARE
        else None
    )
    return Stopping(
        met=facts_labelled == facts
        and claims_labelled >= STOP_AFTER_CLAIMS
        and decided is not None,
        facts_labelled=facts_labelled,
        facts=facts,
        claims_labelled=claims_labelled,
        claims=len(sample.items) - facts,
        decided=decided,
    )


def _run_agreement(sample: Sample, first: JudgeRun, second: JudgeRun) -> RunAgreement:
    def matches(kind: Kind) -> Matches:
        both = [
            (first.verdicts[i.id].verdict, second.verdicts[i.id].verdict)
            for i in sample.items
            if i.kind == kind
        ]
        both = [(a, b) for a, b in both if a is not None and b is not None]
        agree = sum(a == b for a, b in both)
        return Matches(agree, len(both), agree / len(both) if both else None)

    return RunAgreement(matches("fact"), matches("claim"))


# --- Inputs the sample reads from the repository ------------------------------------------

EVAL_DIR = DATA_DIR / "derived" / "eval"

PROVIDER_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", JEV_KEY_ENV)
"""Removed from the environment before any Source is rebuilt, so nothing the sample runs
can reach a provider: a Source that would need one is not rebuilt."""


def default_reports(directory: str | Path = EVAL_DIR) -> list[Path]:
    """Every saved generation report and Brief Suite report under `directory`, the
    prompt iterations and settings sweep included, in name order."""
    directory = Path(directory)
    found = {*directory.rglob("generation-*.json"), *directory.rglob("brief-suite*.json")}
    return sorted(found)


def _rebuilt_sources(cases: Mapping, index: Path) -> SourcesFor:
    """Rebuilds a saved answer's Sources by preparing its Answer Context again through
    the report's Arm, at the report's context budget, from the index of its chunk size;
    None when the case, the Arm or the index is unknown, preparing fails, or the Sources
    number differently from those the answer was given."""
    from edgar_eval.arms import ARMS
    from edgar_eval.retrieval import conversation
    from edgar_rag.retrieval import CONTEXT_BUDGET_TOKENS, index_chunk_tokens

    arms = {a.name: a for a in ARMS}
    shipped = next(a for a in ARMS if a.shipped)
    rebuilt: dict[tuple, Mapping[str, Evidence] | None] = {}

    def index_for(chunk_tokens: int | None) -> Path | None:
        if not index.exists():
            return None
        if chunk_tokens is None or chunk_tokens == index_chunk_tokens(index):
            return index
        other = index.with_name(f"{index.stem}-chunks{chunk_tokens}{index.suffix}")
        return other if other.exists() else None

    def sources(report: Mapping, case: Mapping) -> Mapping[str, Evidence] | None:
        golden = cases.get(case["case_id"])
        arm = arms.get(report["arm"]) if report.get("arm") else shipped
        path = index_for(report.get("chunk_tokens"))
        if golden is None or arm is None or arm.prepare is None or path is None:
            return None
        budget = report.get("context_budget", CONTEXT_BUDGET_TOKENS)
        key = (arm.name, path, budget, golden.id)
        if key not in rebuilt:
            try:
                context = arm.prepare(conversation(golden), path, context_budget=budget)
            except Exception:  # noqa: BLE001 - a Source that cannot be rebuilt offline
                rebuilt[key] = None
            else:
                rebuilt[key] = {s.tag: Evidence(s.tag, s.label, s.text) for s in context.sources}
        given = rebuilt[key]
        return given if given is not None and len(given) == case.get("sources") else None

    return sources


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def print_score(report: StudyScore, out: TextIO) -> None:
    """The score, judge by judge, then the trigger and the stopping rule."""
    stop = report.stopping
    print(
        f"Judge study: {stop.facts_labelled} of {stop.facts} fact items and "
        f"{stop.claims_labelled} of {stop.claims} claim items labelled; fact cut-off "
        f"{report.fact_cutoff}.",
        file=out,
    )
    if report.partial:
        print("PARTIAL REPORT: items remain unlabelled and the stopping rule is not met.", file=out)
    rows = [
        [
            "judge",
            "facts",
            "acc",
            "kappa",
            "claims",
            "acc",
            "kappa",
            "bad called supported",
            "failed",
        ]
    ]
    for j in report.judges:
        bad = j.false_supported
        interval = f" ({_pct(bad.low)} to {_pct(bad.high)})" if bad.of else ""
        rows.append(
            [
                f"{j.judge} run {j.run}",
                str(j.facts.items),
                _pct(j.facts.accuracy),
                _num(j.facts.kappa),
                str(j.claims.items),
                _pct(j.claims.accuracy),
                _num(j.claims.kappa),
                f"{bad.count} of {bad.of}, {_pct(bad.share)}{interval}",
                str(j.failed),
            ]
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip(), file=out)
    if report.run_agreement is not None:
        a = report.run_agreement
        print(
            f"Jev's two runs agree on {a.facts.agree} of {a.facts.of} facts "
            f"({_pct(a.facts.share)}) and {a.claims.agree} of {a.claims.of} claims "
            f"({_pct(a.claims.share)}).",
            file=out,
        )
    for j in (j for j in report.judges if j.cutoffs):
        sweep = ", ".join(f"{c.cutoff}: {_pct(c.accuracy)} / {_num(c.kappa)}" for c in j.cutoffs)
        print(
            f"{j.judge} run {j.run}, facts at each cut-off (accuracy / kappa): {sweep}; "
            f"averaged probabilities: {_pct(j.averaged)}.",
            file=out,
        )
    first = report.judges[0]
    for g in first.by_generator:
        p = "" if g.p_value is None else f", Fisher p = {g.p_value:.3f}"
        print(
            f"{first.judge} run {first.run} on {g.model}'s {g.kind}s: {g.errors} of "
            f"{g.items} wrong ({_pct(g.error_rate)}){p}",
            file=out,
        )
    if report.split is not None:
        _print_split(report.split, out)
    r = report.revisit
    reasons = [
        *(["more than one in five bad claims called supported"] if r.false_supported_above else []),
        *(["its error differs by generator"] if r.generator_differs else []),
    ]
    print(
        "ADR 0013's revisit trigger "
        + (f"FIRED: {'; '.join(reasons)}." if r.fired else "did not fire."),
        file=out,
    )
    print(
        "Stopping rule "
        + (
            f"met: the false-supported interval lies wholly {stop.decided} one in five."
            if stop.met
            else f"not met (it needs every fact item and {STOP_AFTER_CLAIMS} claim items "
            "labelled, and the false-supported interval wholly below or above one in five)."
        ),
        file=out,
    )


def _print_split(split: SplitComparison, out: TextIO) -> None:
    def side(name: str, a: SplitAgreement) -> str:
        return (
            f"{name} agrees with the labels on {a.agree} of {a.of} answers, catches "
            f"{a.caught} of {a.bad} answers labelled with a bad claim and raises "
            f"{a.false_alarms} false alarm(s) on {a.clean} clean ones"
        )

    verdict = {
        "tie": "agrees with the labels as often as the sentence split",
        "llm": "agrees with the labels better than the sentence split",
        "sentence": "agrees with the labels less well than the sentence split",
    }[split.agrees_better]
    catches = {
        "tie": "catches as many bad answers",
        "llm": "catches more bad answers",
        "sentence": "catches fewer bad answers",
    }[split.catches_more]
    print(
        f"LLM claim split, answer by answer ({split.left_out} answer(s) left out): "
        f"{side('the sentence split', split.sentence)}; {side('the LLM split', split.llm)}. "
        f"The LLM split {verdict} and {catches} (McNemar p = {split.p_value:.3f}, shown, "
        "not decided on).",
        file=out,
    )
    for a in split.answers:
        print(
            f"  {a.case_id} ({a.model}, {a.items} items): labelled "
            f"{'bad' if a.labelled_bad else 'clean'}, sentence split "
            f"{'bad' if a.sentence_bad else 'clean'}, LLM split "
            f"{'bad' if a.llm_bad else 'clean'}: {a.better} right",
            file=out,
        )


# --- Command line -------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    sources: SourcesFor | None = None,
    jev: StudyJudge | None = None,
    reference: ReferenceJudge | None = None,
    splitter: LLMSplitter | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    from edgar_rag.retrieval import DEFAULT_INDEX

    out, err = out or sys.stdout, err or sys.stderr
    parser = argparse.ArgumentParser(description="The judge study (ADR 0013).")
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser(
        "sample", help="draw the items from saved reports and write the labelling sheet"
    )
    sample.add_argument("--reports", type=Path, nargs="+", help="default: every saved report")
    sample.add_argument("--seed", type=int, default=SEED)
    sample.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    sample.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    sample.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    sample.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    sample.add_argument("--golden-set-v2", type=Path, default=DEFAULT_GOLDEN_SET_V2)
    sample.add_argument("--brief-suite", type=Path, default=DEFAULT_BRIEF_SUITE)
    judge = commands.add_parser(
        "judge", help=f"judge every sampled item: Jev {JUDGE_RUNS} times (costs money)"
    )
    judge.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    judge.add_argument("--verdicts", type=Path, default=DEFAULT_VERDICTS)
    judge.add_argument(
        "--reference", action="store_true", help=f"also run {REFERENCE_MODEL} once, as a reference"
    )
    judge.add_argument(
        "--llm-split",
        action="store_true",
        help=f"also split the answers with {SPLIT_MODEL} and judge the statements once",
    )
    judge.add_argument("--split-cache", type=Path, default=DEFAULT_SPLIT_CACHE)
    scoring = commands.add_parser("score", help="score the stored verdicts against the labels")
    scoring.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    scoring.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    scoring.add_argument("--verdicts", type=Path, default=DEFAULT_VERDICTS)
    scoring.add_argument("--json", type=Path, default=DEFAULT_SCORE)
    scoring.add_argument(
        "--partial", action="store_true", help="score the labelled items, with some unlabelled"
    )
    args = parser.parse_args(argv)

    if args.command == "judge":
        return _judge(args, jev, reference, splitter, out)
    if args.command == "score":
        return _score(args, out, err)
    return _sample(args, parser, sources, out, err)


def _sample(args, parser, sources: SourcesFor | None, out: TextIO, err: TextIO) -> int:
    paths = args.reports or default_reports()
    if not paths:
        parser.error(f"no saved generation report in {EVAL_DIR}")
    reports = [(str(p), json.loads(p.read_text(encoding="utf-8"))) for p in paths]
    version_1 = load_golden_set(args.golden_set)
    version_2 = load_golden_set(args.golden_set_v2)
    brief = load_brief_suite(args.brief_suite, (args.golden_set, args.golden_set_v2))
    if sources is None:
        for key in PROVIDER_KEYS:
            os.environ.pop(key, None)
        cases = {c.id: c for s in (version_1, version_2, brief) for c in s.cases}
        sources = _rebuilt_sources(cases, args.index)

    drawn = draw_sample(reports, rewritten_facts(version_2, brief), sources, seed=args.seed)
    try:
        kept = write_sheet(drawn, args.sheet)
    except ValueError as error:
        print(f"error: {error}", file=err)
        return 1
    args.sample.parent.mkdir(parents=True, exist_ok=True)
    args.sample.write_text(json.dumps(drawn.to_dict(), indent=2) + "\n", encoding="utf-8")

    facts = sum(i.kind == "fact" for i in drawn.items)
    print(
        f"Drew {facts} fact items and {len(drawn.items) - facts} claim items from "
        f"{len(reports)} report(s) with seed {drawn.seed}; {kept} label(s) kept.",
        file=out,
    )
    for reason, count in drawn.skipped.items():
        print(f"Skipped {count} {reason}.", file=out)
    print(f"Sheet: {args.sheet.resolve()}\nSample: {args.sample.resolve()}", file=out)
    return 0


def _judge(
    args,
    jev: StudyJudge | None,
    reference: ReferenceJudge | None,
    splitter: LLMSplitter | None,
    out: TextIO,
) -> int:
    drawn = Sample.from_dict(json.loads(args.sample.read_text(encoding="utf-8")))
    if args.llm_split and splitter is None:
        splitter = LLMSplitter(cache_dir=args.split_cache)
    if not args.llm_split:
        splitter = None
    cost = estimate_judge_cost(drawn, reference=args.reference, splitter=splitter)
    print(cost.line(), file=out, flush=True)
    if jev is None:
        from edgar_eval.judge import JevJudge

        jev = JevJudge()
    if args.reference and reference is None:
        reference = ReferenceJudge()
    runs = judge_sample(drawn, jev, reference=reference if args.reference else None)
    split = split_sample(drawn, splitter, jev) if splitter is not None else None
    save_verdicts(runs, drawn, args.verdicts, split)
    for run in runs:
        failed = sum(v.verdict is None for v in run.verdicts.values())
        print(
            f"{run.judge} run {run.run}: {len(run.verdicts)} items judged in {run.requests} "
            f"requests, {failed} failed.",
            file=out,
        )
    if split is not None:
        failed = sum(i.error is not None for i in split.items.values())
        statements = sum(len(i.claims) for i in split.items.values())
        print(
            f"{split.model} claim split: {len(split.items)} claim items split into "
            f"{statements} statements in {split.requests} requests ({split.cached} answers "
            f"cached), {failed} failed; {split.judge} judged them once.",
            file=out,
        )
    print(f"Verdicts: {args.verdicts.resolve()}", file=out)
    return 0


def _score(args, out: TextIO, err: TextIO) -> int:
    drawn = Sample.from_dict(json.loads(args.sample.read_text(encoding="utf-8")))
    try:
        report = score(
            drawn,
            read_labels(args.sheet),
            load_verdicts(args.verdicts),
            split=load_split(args.verdicts),
            partial=args.partial,
        )
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
