"""The Generation Miss report: where a saved report's answers lost facts they were given.

A **Generation Miss** is a must-state Required Fact whose evidence reached the Answer
Context (Evidence Reached, `edgar_eval.retrieval.evidence_reached`) but which the answer
did not state: Jev's probability is below the fact cut-off the report was scored at, or
the answer was cut off at the token cap. In a Brief Suite report it is a must-state fact
reached in every run but stated in fewer runs than the pass threshold
(`edgar_eval.brief_suite.required_runs`).

The report reads one saved generation or Brief Suite report and makes no provider call.
A report stores each answer but not its Sources, so each case's Answer Context is
prepared again, as the offline re-score does (`edgar_eval.rescore`): through the report's
Arm, at the context budget it records, from an index of its chunk size. A case whose
Sources no longer match the report (another number of Sources, or Evidence Reached other
than the report recorded) is refused and listed, never read, so a miss is never put down
to the wrong Source. A report from an index of another chunk size is refused whole.

For every must-state fact whose evidence reached the Answer Context, stated or missed,
it records:

- the case, the fact, its Company and Section, and Jev's probability (in a Brief Suite
  report, the mean of the runs', with the runs that stated it);
- the Source holding its evidence quote (the first whose text holds it, one of the fact's
  own Filing and Section first), that Source's tokens and its rank among the Company's
  text Sources (1 is the Company's best-ranked Source);
- the quote's offset in the Source, in characters and as a share of its text, and whether
  it falls in the Source's best-ranked chunk (`Source.best_chunk`);
- how many of the case's must-state facts that Source holds, and how many of them the
  answer stated;
- whether the answer cites the Source (in a Brief Suite report, in how many runs);
- the number of Companies in scope (the Answer Context's coverage) and the answer's word
  count.

The summaries set the misses beside the stated facts: the miss rate (misses over facts
reached) by number of Companies, by whether the holding Source is cited and by where in
the Source the quote falls, the misses by the fact's Section, and the mean tokens,
offset and crowding of each. Reading each miss by hand (generalised, omitted, stated but
scored under the cut-off, headline dropped) is left to an agent, in the evaluation notes.

`make eval-misses` runs it on the round's shipped run, or the reports `REPORTS=` names,
prints the summaries and the misses and writes them beside each report, in
`data/derived/eval/misses-<report>.json`. Given several reports, such as a round's
shipped run and its Control Run, it also prints their summaries pooled (`pooled`), as
#132's diagnosis read them:

    python -m edgar_eval.misses [REPORT ...] [--split dev|holdout|all] [--index PATH]
        [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean
from typing import TextIO

from edgar_eval.answer_checks import source_numbers_cited
from edgar_eval.brief_suite import required_runs
from edgar_eval.retrieval import Arm, Prepare, conversation, evidence_reached
from edgar_rag.golden_set import (
    DEFAULT_BRIEF_SUITE,
    DEFAULT_GOLDEN_SET,
    GOLDEN_SET_FILES,
    GOLDEN_SET_V1,
    GOLDEN_SET_V2,
    GoldenCase,
    RequiredFact,
    load_brief_suite,
    load_golden_set,
)
from edgar_rag.retrieval import (
    CONTEXT_BUDGET_TOKENS,
    DEFAULT_INDEX,
    AnswerContext,
    Source,
    count_tokens,
    index_chunk_tokens,
    prepare_answer_context,
)

__all__ = [
    "MISSES_PREFIX",
    "MissReport",
    "ReachedFact",
    "brief_suite_misses",
    "generation_misses",
    "main",
    "misses_path",
    "pooled",
    "print_misses",
]

MISSES_PREFIX = "misses-"
"""A Generation Miss report is written beside the report it reads, its name this prefix
and the report's (`misses-generation-dev.json`), so no harness reading
`generation-*.json` or `brief-suite*.json` takes it for a report of answers."""

_LEGACY_FACT_CUTOFF = 0.5
"""The fact cut-off of a report saved before it was recorded (`GenerationReport.fact_cutoff`)."""

_OFFSET_BANDS = ((0.25, "first quarter"), (0.5, "second quarter"), (0.75, "third quarter"))


@dataclass(frozen=True)
class ReachedFact:
    """One must-state Required Fact whose evidence reached the Answer Context."""

    case_id: str
    fact: str
    ticker: str
    """The Company of the fact's Filing."""
    filing_id: str
    section: str
    probability: float | None
    """Jev's probability that the answer states it; in a Brief Suite report, the mean of
    the runs' that were judged. None when no judgment was made."""
    missed: bool
    """A Generation Miss: not stated (in a Brief Suite report, in too few runs)."""
    source: str | None
    """The tag of the Source holding the evidence quote, or None when the quote runs
    across two Sources."""
    source_section: str | None
    source_tokens: int | None
    source_rank: int | None
    """Its place among the Company's text Sources, 1 the best-ranked; None for a Facts
    Source."""
    company_sources: int
    """The Company's text Sources."""
    offset: int | None
    """Where the quote starts in the Source's text, in characters."""
    relative_offset: float | None
    """The same as a share of the Source's text: 0 at its start."""
    in_best_chunk: bool | None
    """Whether the quote overlaps the Source's best-ranked chunk; None for a Facts
    Source."""
    sharing: int
    """The case's must-state facts the Source holds, this one included."""
    sharing_stated: int
    """How many of those the answer stated."""
    cited: bool
    """Whether the answer cites the Source (in a Brief Suite report, in any run)."""
    companies: int
    """The Companies in scope: the Answer Context's coverage."""
    words: float
    """The answer's word count (in a Brief Suite report, the mean of the runs')."""
    runs: int = 1
    stated_runs: int | None = None
    """Runs that stated it, in a Brief Suite report."""
    cited_runs: int | None = None
    """Runs that cited its Source, in a Brief Suite report."""


@dataclass(frozen=True)
class MissReport:
    report: str
    """The report read."""
    kind: str
    """"generation" or "brief_suite"."""
    prompt_version: str | None
    fact_cutoff: float | None
    """The cut-off a generation report was scored at; None for a Brief Suite report,
    whose verdicts record each fact's runs stated."""
    pass_runs: int | None
    """Of a Brief Suite report's runs, how many must state a must-state fact."""
    facts: tuple[ReachedFact, ...]
    """Every must-state fact whose evidence reached the Answer Context."""
    refused: dict[str, str]
    """The cases whose Sources no longer match the report, with why: left out."""
    unscored: tuple[str, ...]
    """The cases left out because their Fact Recall judgment failed."""

    @property
    def misses(self) -> tuple[ReachedFact, ...]:
        return tuple(f for f in self.facts if f.missed)

    def summaries(self) -> dict:
        """The misses beside the stated facts, by each reading of the diagnosis."""

        def by(key: Callable[[ReachedFact], str], order: Iterable[str] = ()) -> dict:
            groups: dict[str, list[ReachedFact]] = {k: [] for k in order}
            for fact in self.facts:
                groups.setdefault(key(fact), []).append(fact)
            return {k: _rate(group) for k, group in groups.items() if group}

        def means(facts: Sequence[ReachedFact]) -> dict:
            def mean(values: Iterable[float | int | None]) -> float | None:
                present = [v for v in values if v is not None]
                return round(fmean(present), 3) if present else None

            return {
                "facts": len(facts),
                "source_tokens": mean(f.source_tokens for f in facts),
                "relative_offset": mean(f.relative_offset for f in facts),
                "outside_best_chunk": mean(
                    None if f.in_best_chunk is None else not f.in_best_chunk for f in facts
                ),
                "sharing": mean(f.sharing for f in facts),
                "uncited": mean(not f.cited for f in facts),
                "words": mean(f.words for f in facts),
            }

        misses = self.misses
        stated = [f for f in self.facts if not f.missed]
        return {
            "overall": _rate(self.facts),
            "by_companies": by(_companies_band, ("1", "2", "3", "4", "5+")),
            "by_cited": by(lambda f: "cited" if f.cited else "uncited", ("cited", "uncited")),
            "by_offset": by(_offset_band, [b for _, b in _OFFSET_BANDS] + ["last quarter"]),
            "by_best_chunk": by(
                lambda f: {True: "in best chunk", False: "outside", None: "facts source"}[
                    f.in_best_chunk
                ],
                ("in best chunk", "outside"),
            ),
            "misses_by_section": dict(
                sorted(
                    _count(f.section for f in misses).items(), key=lambda item: (-item[1], item[0])
                )
            ),
            "means": {"missed": means(misses), "stated": means(stated)},
        }

    def to_dict(self) -> dict:
        return {
            "report": self.report,
            "kind": self.kind,
            "prompt_version": self.prompt_version,
            "fact_cutoff": self.fact_cutoff,
            "pass_runs": self.pass_runs,
            "summaries": self.summaries(),
            "misses": [asdict(f) for f in self.misses],
            "facts": [asdict(f) for f in self.facts],
            "refused": self.refused,
            "unscored": list(self.unscored),
        }


def _rate(facts: Sequence[ReachedFact]) -> dict:
    missed = sum(f.missed for f in facts)
    return {
        "facts": len(facts),
        "missed": missed,
        "stated": len(facts) - missed,
        "miss_rate": round(missed / len(facts), 3) if facts else None,
    }


def _count(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _companies_band(fact: ReachedFact) -> str:
    return "5+" if fact.companies >= 5 else str(fact.companies)


def _offset_band(fact: ReachedFact) -> str:
    if fact.relative_offset is None:
        return "across Sources"
    return next((b for top, b in _OFFSET_BANDS if fact.relative_offset < top), "last quarter")


# --- Where a quote stands ---------------------------------------------------------------


def _find(quote: str, text: str) -> tuple[int, int] | None:
    """Where `quote` stands in `text`, both compared with every run of whitespace
    collapsed to one space (as Evidence Reached compares them): its start and end in
    `text`, or None when it is not there."""
    words = list(re.finditer(r"\S+", text))
    flat = " ".join(w.group() for w in words)
    needle = " ".join(quote.split())
    at = flat.find(needle) if needle else -1
    if at < 0:
        return None
    # Each word's start in `flat`, to map the match back to `text`.
    starts, position = [], 0
    for w in words:
        starts.append(position)
        position += len(w.group()) + 1
    first = max(i for i, s in enumerate(starts) if s <= at)
    last = max(i for i, s in enumerate(starts) if s < at + len(needle))
    begin = words[first].start() + (at - starts[first])
    end = words[last].start() + (at + len(needle) - starts[last])
    return begin, end


def _holding(
    fact: RequiredFact, sources: Sequence[Source]
) -> tuple[Source, tuple[int, int]] | None:
    """The Source holding the fact's evidence quote, and where: one of the fact's own
    Filing and Section first, else the first in number order."""
    own = [s for s in sources if (s.filing_id, s.section) == (fact.filing_id, fact.section)]
    for source in [*own, *(s for s in sources if s not in own)]:
        if (span := _find(fact.evidence, source.text)) is not None:
            return source, span
    return None


@dataclass(frozen=True)
class _Place:
    """Where one fact's evidence stands in an Answer Context."""

    source: Source | None
    span: tuple[int, int] | None
    rank: int | None
    company_sources: int


def _places(context: AnswerContext, facts: Sequence[RequiredFact]) -> list[_Place]:
    places = []
    for fact in facts:
        held = _holding(fact, context.sources)
        ticker = held[0].ticker if held else fact.filing_id.split("_")[0]
        own = [s for s in context.sources if s.kind == "text" and s.ticker == ticker]
        source, span = held if held else (None, None)
        rank = own.index(source) + 1 if source in own else None
        places.append(_Place(source, span, rank, len(own)))
    return places


def _reached_fact(
    case_id: str,
    fact: RequiredFact,
    place: _Place,
    places: Sequence[_Place],
    musts: Sequence[int],
    stated: Callable[[int], bool],
    *,
    probability: float | None,
    missed: bool,
    cited: bool,
    companies: int,
    words: float,
    **runs: int | None,
) -> ReachedFact:
    source, span = place.source, place.span
    sharing = [j for j in musts if source is not None and places[j].source == source]
    return ReachedFact(
        case_id=case_id,
        fact=fact.fact,
        ticker=fact.filing_id.split("_")[0],
        filing_id=fact.filing_id,
        section=fact.section,
        probability=probability,
        missed=missed,
        source=source.tag if source else None,
        source_section=source.section if source else None,
        source_tokens=count_tokens(source.text) if source else None,
        source_rank=place.rank,
        company_sources=place.company_sources,
        offset=span[0] if span else None,
        relative_offset=round(span[0] / max(len(source.text), 1), 3) if source and span else None,
        in_best_chunk=None
        if source is None or source.best_chunk is None or span is None
        else span[0] < source.best_chunk[1] and span[1] > source.best_chunk[0],
        sharing=len(sharing) or 1,
        sharing_stated=sum(stated(j) for j in sharing) if sharing else int(not missed),
        cited=cited,
        companies=companies,
        words=words,
        **runs,
    )


# --- Reading reports ----------------------------------------------------------------------


def _context(case: GoldenCase, index: Path, prepare: Prepare, budget: int) -> AnswerContext:
    return prepare(conversation(case), index, context_budget=budget)


def _mismatch(context: AnswerContext, case: GoldenCase, saved: dict) -> str | None:
    """Why a saved case's Sources no longer match its Answer Context prepared again, or
    None when they do."""
    if len(context.sources) != saved["sources"]:
        return (
            f"the Answer Context now has {len(context.sources)} Sources, not the "
            f"{saved['sources']} the answer was given"
        )
    recorded = saved.get("evidence_reached") or ()
    if recorded and tuple(recorded) != evidence_reached(context, case.required_facts):
        return "its Sources no longer reach the evidence the report recorded"
    return None


def _check_chunks(report: dict, index: Path) -> None:
    chunk_tokens = report.get("chunk_tokens")
    if chunk_tokens is not None and chunk_tokens != index_chunk_tokens(index):
        raise ValueError(
            f"the report was answered from {chunk_tokens}-token chunks, and {index} holds "
            f"{index_chunk_tokens(index)}-token chunks"
        )


def _musts(case: GoldenCase) -> list[int]:
    return [i for i, f in enumerate(case.required_facts) if f.tier == "must_state"]


def generation_misses(
    report: dict,
    cases: Iterable[GoldenCase],
    index: str | Path,
    *,
    prepare: Prepare = prepare_answer_context,
    name: str = "",
) -> MissReport:
    """The Generation Misses of a saved generation report, every case's Answer Context
    prepared again through `prepare` (the report's Arm) at the budget it records."""
    index = Path(index)
    _check_chunks(report, index)
    budget = report.get("context_budget", CONTEXT_BUDGET_TOKENS)
    cutoff = report.get("fact_cutoff", _LEGACY_FACT_CUTOFF)
    by_id = {c.id: c for c in cases}
    facts: list[ReachedFact] = []
    refused: dict[str, str] = {}
    unscored: list[str] = []
    for saved in report["cases"]:
        case = by_id[saved["case_id"]]
        musts = _musts(case)
        if not musts:
            continue
        context = _context(case, index, prepare, budget)
        if (why := _mismatch(context, case, saved)) is not None:
            refused[case.id] = why
            continue
        judged = saved["judgments"]["facts"]
        truncated = saved.get("truncated", saved.get("stop_reason") == "token_cap")
        failed = any(f["judgment"] == "fact_recall" for f in saved["judgments"].get("failures", ()))
        if failed and not truncated:
            unscored.append(case.id)
            continue
        probabilities = (
            [None] * len(case.required_facts) if failed else [f["probability"] for f in judged]
        )

        def stated(j: int, probabilities=probabilities, truncated=truncated) -> bool:
            p = probabilities[j]
            return not truncated and p is not None and p >= cutoff

        reached = evidence_reached(context, case.required_facts)
        places = _places(context, case.required_facts)
        cited = source_numbers_cited(saved["answer"])
        companies = len(context.coverage)
        words = saved["structure"]["words"]
        for i in musts:
            if not reached[i]:
                continue
            place = places[i]
            facts.append(
                _reached_fact(
                    case.id,
                    case.required_facts[i],
                    place,
                    places,
                    [j for j in musts if reached[j]],
                    stated,
                    probability=probabilities[i],
                    missed=not stated(i),
                    cited=place.source is not None and place.source.number in cited,
                    companies=companies,
                    words=words,
                )
            )
    return MissReport(
        report=name,
        kind="generation",
        prompt_version=report.get("prompt_version"),
        fact_cutoff=cutoff,
        pass_runs=None,
        facts=tuple(facts),
        refused=refused,
        unscored=tuple(unscored),
    )


def brief_suite_misses(
    report: dict,
    cases: Iterable[GoldenCase],
    index: str | Path,
    *,
    prepare: Prepare = prepare_answer_context,
    name: str = "",
) -> MissReport:
    """The Generation Misses of a saved Brief Suite report: the must-state facts reached
    in every run and stated in fewer than the pass threshold. Each case's Answer Context
    is prepared once (it is the same in every run) and checked against every run."""
    index = Path(index)
    runs = report["runs"]
    pass_runs = report.get("pass_runs", required_runs(runs))
    first = report["run_reports"][0] if report["run_reports"] else {}
    _check_chunks(first, index)
    budget = first.get("context_budget", CONTEXT_BUDGET_TOKENS)
    by_id = {c.id: c for c in cases}
    facts: list[ReachedFact] = []
    refused: dict[str, str] = {}
    for verdict in report["cases"]:
        case = by_id[verdict["case_id"]]
        musts = _musts(case)
        if not musts:
            continue
        results = [
            r for run in report["run_reports"] for r in run["cases"] if r["case_id"] == case.id
        ]
        context = _context(case, index, prepare, budget)
        why = next((w for r in results if (w := _mismatch(context, case, r)) is not None), None)
        if why is not None:
            refused[case.id] = why
            continue
        fact_verdicts = verdict["facts"]
        places = _places(context, case.required_facts)
        reached = [fact_verdicts[j]["evidence_reached_runs"] == runs for j in musts]
        reached_musts = [j for j, hit in zip(musts, reached, strict=True) if hit]

        def stated(j: int, fact_verdicts=fact_verdicts) -> bool:
            return fact_verdicts[j]["stated_runs"] >= pass_runs

        cited_by_run = [source_numbers_cited(r["answer"]) for r in results]
        words = fmean(r["structure"]["words"] for r in results) if results else 0.0
        for i in reached_musts:
            place = places[i]
            probabilities = [
                r["judgments"]["facts"][i]["probability"]
                for r in results
                if len(r["judgments"]["facts"]) == len(case.required_facts)
            ]
            cited_runs = sum(
                place.source is not None and place.source.number in cited for cited in cited_by_run
            )
            facts.append(
                _reached_fact(
                    case.id,
                    case.required_facts[i],
                    place,
                    places,
                    reached_musts,
                    stated,
                    probability=round(fmean(probabilities), 3) if probabilities else None,
                    missed=not stated(i),
                    cited=cited_runs > 0,
                    companies=len(context.coverage),
                    words=round(words, 1),
                    runs=runs,
                    stated_runs=fact_verdicts[i]["stated_runs"],
                    cited_runs=cited_runs,
                )
            )
    return MissReport(
        report=name,
        kind="brief_suite",
        prompt_version=report.get("prompt_version"),
        fact_cutoff=None,
        pass_runs=pass_runs,
        facts=tuple(facts),
        refused=refused,
        unscored=(),
    )


def pooled(reports: Sequence[MissReport]) -> MissReport:
    """Several reports' facts read as one, as the diagnosis of #132 pooled a round's
    shipped run and Control Run: reports of one kind, each case refused or left out in
    any of them listed under the report's name."""
    kinds = {r.kind for r in reports}
    if len(kinds) != 1:
        raise ValueError("pool reports of one kind: generation reports or Brief Suite reports")
    versions = {r.prompt_version for r in reports}
    return MissReport(
        report=" + ".join(r.report for r in reports),
        kind=kinds.pop(),
        prompt_version=versions.pop()
        if len(versions) == 1
        else ", ".join(sorted(map(str, versions))),
        fact_cutoff=reports[0].fact_cutoff,
        pass_runs=reports[0].pass_runs,
        facts=tuple(f for r in reports for f in r.facts),
        refused={f"{r.report}: {case}": why for r in reports for case, why in r.refused.items()},
        unscored=tuple(f"{r.report}: {case}" for r in reports for case in r.unscored),
    )


def misses_path(report: Path) -> Path:
    """Where the Generation Miss report of `report` is written: beside it."""
    return report.with_name(MISSES_PREFIX + report.name)


# --- Printing -------------------------------------------------------------------------------


def print_misses(misses: MissReport, out: TextIO, *, list_misses: bool = True) -> None:
    """Print the summaries and, with `list_misses`, every miss."""
    summaries = misses.summaries()
    overall = summaries["overall"]
    unit = (
        f"stated in fewer than {misses.pass_runs} runs"
        if misses.kind == "brief_suite"
        else f"under the fact cut-off {misses.fact_cutoff}"
    )
    print(
        f"Generation Misses in {misses.report} (prompt {misses.prompt_version}): "
        f"{overall['missed']} of {overall['facts']} must-state facts reached, {unit}",
        file=out,
    )
    if misses.refused:
        print(f"Refused, their Sources no longer match: {len(misses.refused)} cases", file=out)
        for case_id, why in misses.refused.items():
            print(f"  {case_id}: {why}", file=out)
    if misses.unscored:
        print(f"Left out, Fact Recall judgment failed: {', '.join(misses.unscored)}", file=out)

    def table(title: str, groups: dict) -> None:
        print(f"\n{title}", file=out)
        print(f"  {'':16} {'reached':>7} {'missed':>7} {'stated':>7} {'miss rate':>9}", file=out)
        for key, g in groups.items():
            rate = "–" if g["miss_rate"] is None else f"{g['miss_rate']:.2f}"
            print(
                f"  {key:16} {g['facts']:>7} {g['missed']:>7} {g['stated']:>7} {rate:>9}",
                file=out,
            )

    table("By Companies in scope", summaries["by_companies"])
    table("By whether the holding Source is cited", summaries["by_cited"])
    table("By where in the Source the quote starts", summaries["by_offset"])
    table("By the Source's best-ranked chunk", summaries["by_best_chunk"])
    print("\nMisses by Section", file=out)
    for section, n in summaries["misses_by_section"].items():
        print(f"  {section:40} {n:>3}", file=out)
    print("\nMeans, missed beside stated", file=out)
    missed, stated = summaries["means"]["missed"], summaries["means"]["stated"]
    print(f"  {'':20} {'missed':>9} {'stated':>9}", file=out)
    for key in (
        "source_tokens",
        "relative_offset",
        "outside_best_chunk",
        "sharing",
        "uncited",
        "words",
    ):
        print(f"  {key:20} {_show(missed[key]):>9} {_show(stated[key]):>9}", file=out)
    if not list_misses:
        return
    print("\nMisses", file=out)
    for f in misses.misses:
        p = "–" if f.probability is None else f"{f.probability:.2f}"
        where = (
            "across Sources"
            if f.source is None
            else f"{f.source} {f.source_section}, {f.source_tokens} tokens, rank "
            f"{f.source_rank or '–'} of {f.company_sources}, at {f.relative_offset:.0%}"
            f"{_best_chunk(f)}"
            f", {f.sharing_stated} of {f.sharing} stated, {'cited' if f.cited else 'uncited'}"
        )
        runs = f", stated {f.stated_runs} of {f.runs} runs" if f.stated_runs is not None else ""
        print(
            f"  {f.case_id} [{f.ticker} {f.section}] p={p}{runs}; {where}; "
            f"{f.companies} Companies, {f.words:g} words\n    {f.fact}",
            file=out,
        )


def _best_chunk(fact: ReachedFact) -> str:
    if fact.in_best_chunk is None:
        return ""
    return " in best chunk" if fact.in_best_chunk else " outside best chunk"


def _show(value: float | None) -> str:
    return "–" if value is None else f"{value:g}"


# --- Command line -------------------------------------------------------------------------


def main(
    argv: list[str] | None = None, *, arms: Sequence[Arm] | None = None, out: TextIO | None = None
) -> int:
    from edgar_eval.rescore import DEFAULT_EVAL_DIR, index_for, named_report

    out = out or sys.stdout
    parser = argparse.ArgumentParser(
        description="List the Generation Misses of a saved generation or Brief Suite "
        "report, with no Answer Call and no Jev call."
    )
    parser.add_argument(
        "reports",
        nargs="*",
        metavar="REPORT",
        help="reports to read: a path, or a name in --dir (default: the round's shipped "
        "run, generation-<split>.json); with several, their pooled summaries are printed too",
    )
    parser.add_argument(
        "--split",
        choices=("dev", "holdout", "all"),
        default="dev",
        help="the split whose shipped run is read when no REPORT is named",
    )
    parser.add_argument(
        "--dir", type=Path, default=DEFAULT_EVAL_DIR, help="where the reports are saved"
    )
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="the shipped index")
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=DEFAULT_GOLDEN_SET,
        help="a Golden Set file (default: version 2); a generation report is read against "
        "the version it records",
    )
    parser.add_argument(
        "--brief-suite",
        type=Path,
        default=DEFAULT_BRIEF_SUITE,
        metavar="PATH",
        help="the Brief Suite file a Brief Suite report was answered from",
    )
    parser.add_argument(
        "--json", type=Path, help="where to write it (default: misses-<report> beside it)"
    )
    args = parser.parse_args(argv)
    names = args.reports or [f"generation-{args.split}.json"]
    if args.json and len(names) > 1:
        parser.error("--json names the file of one report; several are each written beside it")
    found = {name: named_report(name, args.dir) for name in names}
    missing = [name for name, path in found.items() if path is None]
    if missing:
        parser.error(f"no such report: {', '.join(missing)}")
    if arms is None:
        from edgar_eval.arms import ARMS

        arms = ARMS
    by_name = {a.name: a for a in arms}
    shipped = next(a for a in arms if a.shipped)
    read: list[MissReport] = []
    for path in (p for p in found.values() if p is not None):
        report = json.loads(path.read_text(encoding="utf-8"))
        if "run_reports" in report:
            golden_sets = dict.fromkeys((GOLDEN_SET_V1, GOLDEN_SET_V2, args.golden_set))
            cases = load_brief_suite(args.brief_suite, golden_sets).cases
            first = report["run_reports"][0] if report["run_reports"] else {}
            arm = by_name[first["arm"]] if first.get("arm") else shipped
            misses = brief_suite_misses(
                report,
                cases,
                index_for(args.index, first.get("chunk_tokens")),
                prepare=arm.prepare or prepare_answer_context,
                name=path.name,
            )
        else:
            version = report.get("golden_set_version", 1)
            golden = load_golden_set(args.golden_set)
            own = (
                golden if golden.version == version else load_golden_set(GOLDEN_SET_FILES[version])
            )
            arm = by_name[report["arm"]] if report.get("arm") else shipped
            misses = generation_misses(
                report,
                own.cases,
                index_for(args.index, report.get("chunk_tokens")),
                prepare=arm.prepare or prepare_answer_context,
                name=path.name,
            )
        print_misses(misses, out)
        target = args.json or misses_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(misses.to_dict(), indent=2) + "\n", encoding="utf-8")
        print(f"\nWritten to {target}\n", file=out)
        read.append(misses)
    if len(read) > 1:
        print_misses(pooled(read), out, list_misses=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
