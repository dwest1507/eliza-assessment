"""The judge study (ADR 0013): Jev's verdicts checked against the developer's blind labels.

Its first command, `sample`, draws the items from the saved generation reports and writes
the labelling sheet the developer fills in with an editor. It reads saved reports only:
it makes no Answer Call and no Jev call, and calls no provider.

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

    python -m edgar_eval.judge_study sample [--reports PATH...] [--seed N]
        [--sheet PATH] [--sample PATH] [--index PATH]
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
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal, TextIO

from edgar_eval.answer_checks import claims as split_claims
from edgar_eval.judge import JEV_KEY_ENV, Evidence
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
    "DEFAULT_SAMPLE",
    "DEFAULT_SHEET",
    "FACT_ITEMS",
    "FACT_LABELS",
    "GENERATOR_SHARE",
    "SEED",
    "UNCERTAIN",
    "UNCERTAIN_SHARE",
    "UNSUPPORTED_SHARE",
    "Sample",
    "SourcesFor",
    "StudyItem",
    "default_reports",
    "draw_sample",
    "main",
    "read_labels",
    "rewritten_facts",
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


# --- Command line -------------------------------------------------------------------------


def main(
    argv: list[str] | None = None, *, sources: SourcesFor | None = None, out: TextIO | None = None
) -> int:
    from edgar_rag.retrieval import DEFAULT_INDEX

    out = out or sys.stdout
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
    args = parser.parse_args(argv)

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
        print(f"error: {error}", file=sys.stderr)
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


if __name__ == "__main__":
    raise SystemExit(main())
