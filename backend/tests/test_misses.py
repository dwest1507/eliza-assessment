"""The Generation Miss report (`make eval-misses`): fixture reports written by the
generation harness and the Brief Suite run with a fake answer model and a fake Jev, read
back with each case's Answer Context prepared again. No provider is called."""

import io
import json
import re

import pytest

from edgar_eval.judge import JEV_MODEL, ClaimJudgment, FactJudgment, Judgments
from edgar_eval.retrieval import conversation
from edgar_rag.answer_model import Usage
from edgar_rag.golden_set import GoldenCase, RequiredFact
from edgar_rag.retrieval import prepare_answer_context

QUESTION = "What are the primary risk factors facing Apple and Tesla?"
NOT_REACHED = "a sentence no Filing contains"


def _golden(case_id, facts):
    return GoldenCase(
        id=case_id,
        question=QUESTION,
        history=(),
        question_type="risk",
        expected_sources=(),
        required_facts=tuple(facts),
        expected_coverage_gaps=(),
        split="dev",
        starter=None,
        tags=(),
        notes="",
    )


def _quote(text, start, words=12):
    """`words` words of `text` from the first word starting at or after `start`, and
    where the quote starts."""
    match = re.compile(r"(?:^|\s)(\S)").search(text, start)
    begin = match.start(1)
    quote = " ".join(text[begin:].split()[:words])
    return quote, begin


class Scene:
    """The fixture: Apple's and Tesla's risk factors, Sources prepared once to pick the
    evidence quotes from, and a case whose Apple fact the fake Jev finds stated and whose
    two Tesla facts, in one Source, it finds missing."""

    def __init__(self, index):
        probe = _golden("probe", [RequiredFact("x", "X", "Risk Factors", "x")])
        context = prepare_answer_context(conversation(probe), index)
        texts = [s for s in context.sources if s.kind == "text"]
        self.apple = next(s for s in texts if s.ticker == "AAPL")
        self.tesla = next(s for s in texts if s.ticker == "TSLA")
        best_start, best_end = self.tesla.best_chunk
        self.apple_quote, _ = _quote(self.apple.text, self.apple.best_chunk[0])
        self.in_best, self.in_best_at = _quote(self.tesla.text, best_start)
        # The second Tesla quote from outside its best chunk when the Source has more.
        outside = best_end + 1 if best_end + 200 < len(self.tesla.text) else 0
        self.other, self.other_at = _quote(self.tesla.text, outside)
        self.case = _golden(
            "apple-tesla",
            [
                RequiredFact(
                    "Apple uses partners.", self.apple.filing_id, "Risk Factors", self.apple_quote
                ),
                RequiredFact(
                    "Tesla depends on Elon Musk.",
                    self.tesla.filing_id,
                    "Risk Factors",
                    self.in_best,
                ),
                RequiredFact(
                    "Tesla faces competition.", self.tesla.filing_id, "Risk Factors", self.other
                ),
                RequiredFact(
                    "Tesla is unreached.", self.tesla.filing_id, "Risk Factors", NOT_REACHED
                ),
                RequiredFact(
                    "Tesla detail.", self.tesla.filing_id, "Risk Factors", self.other, tier="detail"
                ),
            ],
        )
        # The answer cites Apple's Source only.
        self.answer = (
            f"Apple and Tesla face supply and key-person risks.\n\n## Apple\n\n"
            f"Apple relies on partners, run {{run}} [{self.apple.tag}].\n"
        )


class Model:
    """Writes the scene's answer, naming the run it was asked in."""

    model = "gpt-6-luna"

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def stream(self, messages):
        self.calls += 1
        yield self.answer.format(run=self.calls)
        yield Usage(input_tokens=20_000, output_tokens=1_000, stop_reason="complete")


class Judge:
    """States every Apple fact, and each fact in `stated_runs` in the runs listed there."""

    def __init__(self, stated_runs=None):
        self.stated_runs = stated_runs or {}

    def judge(self, answer, required_facts, claims, sources):
        run = int(re.search(r"run (\d+)", answer).group(1))

        def probability(fact):
            if fact in self.stated_runs:
                return 0.9 if run in self.stated_runs[fact] else 0.1
            return 0.95 if "Apple" in fact else 0.2

        return Judgments(
            facts=tuple(FactJudgment(f, probability(f)) for f in required_facts),
            claims=tuple(ClaimJudgment(c.text, c.tags, "supported", {}) for c in claims),
            model=JEV_MODEL,
            requests=2,
            input_tokens=100,
        )


@pytest.fixture(scope="module")
def scene(index):
    return Scene(index)


def _generation_report(scene, index, judge=None):
    from edgar_eval.generation import evaluate

    report = evaluate(
        [scene.case],
        Model(scene.answer),
        judge or Judge(),
        index,
        names={"AAPL": ("AAPL", "Apple"), "TSLA": ("TSLA", "Tesla")},
        fact_values=lambda filing_id: [],
        log_path=None,
    )
    return json.loads(json.dumps(report.to_dict()))


def test_a_known_miss_yields_its_source_offset_crowding_and_citation(scene, index):
    from edgar_eval.misses import generation_misses

    saved = _generation_report(scene, index)

    misses = generation_misses(saved, [scene.case], index)

    # The two Tesla facts are missed; the unreached one and the detail are not counted.
    assert [f.fact for f in misses.facts] == [
        "Apple uses partners.",
        "Tesla depends on Elon Musk.",
        "Tesla faces competition.",
    ]
    apple, in_best, other = misses.facts
    assert [f.fact for f in misses.misses] == [in_best.fact, other.fact]
    assert not apple.missed and apple.cited and apple.probability == 0.95
    # Its Source, its tokens and its rank among Tesla's Sources.
    assert (in_best.source, in_best.source_section, in_best.ticker) == (
        scene.tesla.tag,
        "Risk Factors",
        "TSLA",
    )
    assert in_best.source_rank == 1 and in_best.company_sources >= 1
    assert in_best.source_tokens > 0
    # Where the quote stands, and whether in the best-ranked chunk.
    assert in_best.offset == scene.in_best_at
    assert in_best.relative_offset == round(scene.in_best_at / len(scene.tesla.text), 3)
    assert in_best.in_best_chunk is True
    best_start, best_end = scene.tesla.best_chunk
    assert other.offset == scene.other_at
    assert other.in_best_chunk is (best_start <= scene.other_at < best_end)
    # Crowding: both Tesla facts sit in one Source, neither stated; it is never cited.
    assert (in_best.sharing, in_best.sharing_stated) == (2, 0)
    assert (apple.sharing, apple.sharing_stated) == (1, 1)
    assert not in_best.cited and not other.cited
    # The Companies in scope and the answer's length.
    assert in_best.companies == 2
    assert in_best.words == saved["cases"][0]["structure"]["words"]


def test_the_summaries_set_the_misses_beside_the_stated_facts(scene, index):
    from edgar_eval.misses import generation_misses

    summaries = generation_misses(_generation_report(scene, index), [scene.case], index).summaries()

    assert summaries["overall"] == {"facts": 3, "missed": 2, "stated": 1, "miss_rate": 0.667}
    assert summaries["by_companies"] == {
        "2": {"facts": 3, "missed": 2, "stated": 1, "miss_rate": 0.667}
    }
    assert summaries["by_cited"] == {
        "cited": {"facts": 1, "missed": 0, "stated": 1, "miss_rate": 0.0},
        "uncited": {"facts": 2, "missed": 2, "stated": 0, "miss_rate": 1.0},
    }
    assert sum(g["facts"] for g in summaries["by_offset"].values()) == 3
    assert summaries["misses_by_section"] == {"Risk Factors": 2}
    assert summaries["means"]["missed"]["uncited"] == 1.0
    assert summaries["means"]["stated"]["uncited"] == 0.0


def test_a_truncated_answer_misses_every_fact_it_was_given(scene, index):
    from edgar_eval.misses import generation_misses

    saved = _generation_report(scene, index)
    saved["cases"][0]["truncated"] = True

    misses = generation_misses(saved, [scene.case], index)

    assert len(misses.misses) == 3


def test_a_brief_suite_miss_is_a_fact_reached_in_every_run_stated_in_too_few(scene, index):
    from edgar_eval.brief_suite import evaluate_brief_suite
    from edgar_eval.misses import brief_suite_misses

    # Of 5 runs, a must-state fact must be stated in 4: Elon Musk in 3 misses, the
    # competition fact in 4 passes, Apple in every run.
    judge = Judge(
        stated_runs={
            "Tesla depends on Elon Musk.": {1, 2, 3},
            "Tesla faces competition.": {1, 2, 3, 4},
        }
    )
    report = evaluate_brief_suite(
        [scene.case],
        Model(scene.answer),
        judge,
        index,
        runs=5,
        names={"AAPL": ("AAPL", "Apple"), "TSLA": ("TSLA", "Tesla")},
        fact_values=lambda filing_id: [],
        log_path=None,
        workers=1,
    )
    saved = json.loads(json.dumps(report.to_dict()))

    misses = brief_suite_misses(saved, [scene.case], index)

    assert misses.pass_runs == 4
    assert [(f.fact, f.stated_runs, f.runs) for f in misses.facts] == [
        ("Apple uses partners.", 5, 5),
        ("Tesla depends on Elon Musk.", 3, 5),
        ("Tesla faces competition.", 4, 5),
    ]
    [miss] = misses.misses
    assert miss.fact == "Tesla depends on Elon Musk."
    assert miss.probability == pytest.approx((0.9 * 3 + 0.1 * 2) / 5)
    assert (miss.source, miss.sharing, miss.sharing_stated) == (scene.tesla.tag, 2, 1)
    assert miss.cited_runs == 0 and not miss.cited
    assert misses.facts[0].cited_runs == 5


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (lambda case: case.update(sources=case["sources"] + 1), "Sources, not the"),
        (
            lambda case: case.update(evidence_reached=[not r for r in case["evidence_reached"]]),
            "no longer reach the evidence",
        ),
    ],
)
def test_a_case_whose_sources_no_longer_match_is_refused(scene, index, change, why):
    from edgar_eval.misses import generation_misses

    saved = _generation_report(scene, index)
    change(saved["cases"][0])

    misses = generation_misses(saved, [scene.case], index)

    assert misses.facts == ()
    assert why in misses.refused["apple-tesla"]


def test_a_brief_suite_case_whose_sources_no_longer_match_in_any_run_is_refused(scene, index):
    from edgar_eval.brief_suite import evaluate_brief_suite
    from edgar_eval.misses import brief_suite_misses

    report = evaluate_brief_suite(
        [scene.case],
        Model(scene.answer),
        Judge(),
        index,
        runs=2,
        names={},
        fact_values=lambda filing_id: [],
        log_path=None,
        workers=1,
    )
    saved = json.loads(json.dumps(report.to_dict()))
    saved["run_reports"][1]["cases"][0]["sources"] += 1

    misses = brief_suite_misses(saved, [scene.case], index)

    assert misses.facts == () and "apple-tesla" in misses.refused


def test_a_report_of_another_chunk_size_is_refused_whole(scene, index):
    from edgar_eval.misses import generation_misses

    saved = _generation_report(scene, index)
    saved["chunk_tokens"] = 450

    with pytest.raises(ValueError, match="450-token chunks"):
        generation_misses(saved, [scene.case], index)


def test_the_command_prints_the_misses_and_writes_them_beside_the_report(
    scene, index, tmp_path, monkeypatch
):
    from edgar_eval import misses as misses_module
    from edgar_eval.rescore import saved_reports

    saved = _generation_report(scene, index)
    for name in ("generation-dev.json", "generation-control-dev.json"):
        (tmp_path / name).write_text(json.dumps(saved))

    class Golden:
        version = 1
        cases = (scene.case,)

    monkeypatch.setattr(misses_module, "load_golden_set", lambda path: Golden)
    out = io.StringIO()
    code = misses_module.main(["--dir", str(tmp_path), "--index", str(index)], out=out)

    assert code == 0
    printed = out.getvalue()
    assert "Generation Misses in generation-dev.json" in printed
    assert "2 of 3 must-state facts reached" in printed
    assert "Tesla depends on Elon Musk." in printed
    written = json.loads((tmp_path / "misses-generation-dev.json").read_text())
    assert [m["fact"] for m in written["misses"]] == [
        "Tesla depends on Elon Musk.",
        "Tesla faces competition.",
    ]
    assert written["summaries"]["overall"]["missed"] == 2
    # A miss report is never read as a report of answers.
    assert tmp_path / "misses-generation-dev.json" not in saved_reports(tmp_path)

    # Several reports, such as a round's shipped run and Control Run, are also pooled.
    out = io.StringIO()
    misses_module.main(
        [
            "generation-dev.json",
            "generation-control-dev.json",
            "--dir",
            str(tmp_path),
            "--index",
            str(index),
        ],
        out=out,
    )
    assert (tmp_path / "misses-generation-control-dev.json").exists()
    assert (
        "Generation Misses in generation-dev.json + generation-control-dev.json (prompt "
        in out.getvalue()
    )
    assert "4 of 6 must-state facts reached" in out.getvalue()
