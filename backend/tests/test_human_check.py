"""The human check (spec #136): a blind 30-item sheet drawn from the judge study's
items, which the developer labels by hand, and its score against Claude's labels and
Jev's verdicts, of each kind whose items are all labelled."""

import io
import json
import re
import sys
from collections import Counter

import pytest

from edgar_eval.judge import JEV_MODEL, Evidence
from edgar_eval.judge_study import (
    JudgeRun,
    Sample,
    StudyItem,
    Verdict,
    read_labels,
    save_verdicts,
    write_sheet,
)

GPT, HAIKU = "gpt-6-luna", "claude-haiku-5-5"


def _fact(n, model=GPT):
    return StudyItem(
        id=f"F-{n:010x}",
        kind="fact",
        case_id=f"case-{n}",
        model=model,
        answer=f"Answer {n} names the company's main finding.",
        fact=f"Fact {n} holds for the company.",
        tier="must_state",
        drawn_for="uncertain",
    )


def _claim(n, model=GPT):
    return StudyItem(
        id=f"C-{n:010x}",
        kind="claim",
        case_id=f"case-{n}",
        model=model,
        answer=f"Claim {n} holds for the company. [S1]",
        claim=f"Claim {n} holds for the company.",
        sources=(Evidence("S1", f"Source of case {n}", f"Text {n} of the filing."),),
        drawn_for="random",
    )


def _study(stated=20, not_stated=30, supported=40, unsupported=12, contradicted=6, blank=4):
    """The judge study's sample and Claude's labels on it: fact and claim items by the
    label Claude gave each, and a few items Claude left blank."""
    items, labels = [], {}
    n = 0
    for make, counts in (
        (_fact, (("stated", stated), ("not stated", not_stated))),
        (
            _claim,
            (
                ("supported", supported),
                ("unsupported", unsupported),
                ("contradicted", contradicted),
            ),
        ),
    ):
        for label, count in (*counts, (None, blank)):
            for _ in range(count):
                n += 1
                item = make(n, HAIKU if n % 3 == 0 else GPT)
                items.append(item)
                labels[item.id] = label
    return Sample(
        seed=20261017, reports=("generation-dev.json",), items=tuple(items), skipped={}
    ), labels


def _write_study(tmp_path, study, claude):
    """The judge study's committed files, with Claude's labels entered on its sheet."""
    sheet, sample = tmp_path / "sheet.md", tmp_path / "sample.json"
    write_sheet(study, sheet)
    _label(sheet, {i: label for i, label in claude.items() if label})
    sample.write_text(json.dumps(study.to_dict()))
    return sheet, sample


def _label(path, labels):
    """Fill in labels on a sheet, as an editor does."""
    text = path.read_text()
    for item_id, label in labels.items():
        text = re.sub(rf"^(LABEL {item_id} \([^)]*\):).*$", rf"\1 {label}", text, flags=re.M)
    path.write_text(text)


# --- The draw -------------------------------------------------------------------------------


def test_the_draw_holds_15_fact_and_15_claim_items_spread_across_claudes_labels():
    from edgar_eval.human_check import draw_human_check

    study, claude = _study()
    check = draw_human_check(study, claude, seed=5)

    facts = [i for i in check.items if i.kind == "fact"]
    claims = [i for i in check.items if i.kind == "claim"]
    assert len(facts) == 15 and len(claims) == 15
    assert len({i.id for i in check.items}) == 30
    # Only items Claude labelled, as many of each label as can be, the first label first.
    assert Counter(claude[i.id] for i in facts) == {"stated": 8, "not stated": 7}
    assert Counter(claude[i.id] for i in claims) == {
        "supported": 5,
        "unsupported": 5,
        "contradicted": 5,
    }
    # The fact items come first, then the claim items: the sheet's order.
    assert [i.kind for i in check.items] == ["fact"] * 15 + ["claim"] * 15
    assert check.seed == 5


def test_a_scarce_label_gives_every_item_it_has_and_the_others_fill_the_rest():
    from edgar_eval.human_check import draw_human_check

    study, claude = _study(stated=3, contradicted=2)
    check = draw_human_check(study, claude, seed=5)

    assert Counter(claude[i.id] for i in check.items if i.kind == "fact") == {
        "stated": 3,
        "not stated": 12,
    }
    assert Counter(claude[i.id] for i in check.items if i.kind == "claim") == {
        "supported": 7,
        "unsupported": 6,
        "contradicted": 2,
    }


def test_the_same_seed_gives_the_same_draw_and_another_seed_another():
    from edgar_eval.human_check import draw_human_check

    study, claude = _study()
    first = draw_human_check(study, claude, seed=5)
    assert draw_human_check(study, claude, seed=5) == first
    other = draw_human_check(study, claude, seed=6)
    assert {i.id for i in other.items} != {i.id for i in first.items}
    # The order within a kind does not follow Claude's labels.
    facts = [claude[i.id] for i in first.items if i.kind == "fact"]
    assert facts != sorted(facts) and facts != sorted(facts, reverse=True)


def _item_blocks(sheet):
    blocks = sheet.split("\n### ")[1:]
    return [
        "\n".join(line for line in b.splitlines() if not line.startswith("LABEL ")) for b in blocks
    ]


def test_the_sheet_holds_no_claude_label_jev_verdict_or_probability(tmp_path):
    from edgar_eval.human_check import draw_human_check, write_human_sheet

    study, claude = _study()
    check = draw_human_check(study, claude, seed=5)
    path = tmp_path / "human_check.md"
    write_human_sheet(check, path)
    sheet = path.read_text()

    assert sheet.count("(stated / not stated):") == 15
    assert sheet.count("(supported / unsupported / contradicted):") == 15
    # Every label line is blank: none carries Claude's label over.
    assert set(read_labels(path).values()) == {None}
    assert len(read_labels(path)) == 30
    for block in _item_blocks(sheet):
        for word in ("stated", "supported", "contradicted", "verdict", "uncertain", "random"):
            assert word not in block
    assert "Jev" not in sheet and "jev" not in sheet and "probabilit" not in sheet
    assert "drawn_for" not in sheet and "Claude" not in sheet
    assert "Seed: 5" in sheet


# --- The sample command -----------------------------------------------------------------------


def _sample_command(tmp_path, study_sheet, study_sample, *extra):
    from edgar_eval.human_check import main

    argv = [
        "sample",
        "--sheet",
        str(tmp_path / "human_check.md"),
        "--study-sheet",
        str(study_sheet),
        "--study-sample",
        str(study_sample),
        *extra,
    ]
    return main(argv, out=io.StringIO(), err=io.StringIO())


def test_the_sample_command_calls_no_provider(tmp_path, monkeypatch):
    for module in ("openai", "anthropic", "typesafe_sdk"):
        monkeypatch.setitem(sys.modules, module, None)
    study, claude = _study()
    study_sheet, study_sample = _write_study(tmp_path, study, claude)

    assert _sample_command(tmp_path, study_sheet, study_sample) == 0
    labels = read_labels(tmp_path / "human_check.md")
    assert sum(i.startswith("F-") for i in labels) == 15
    assert sum(i.startswith("C-") for i in labels) == 15


def test_drawing_again_keeps_the_labels_and_refuses_to_drop_a_labelled_item(tmp_path):
    study, claude = _study()
    study_sheet, study_sample = _write_study(tmp_path, study, claude)
    sheet = tmp_path / "human_check.md"
    assert _sample_command(tmp_path, study_sheet, study_sample, "--seed", "5") == 0
    fact = next(i for i in read_labels(sheet) if i.startswith("F-"))
    claim = next(i for i in read_labels(sheet) if i.startswith("C-"))
    _label(sheet, {fact: "Not  Stated", claim: "contradicted"})

    assert _sample_command(tmp_path, study_sheet, study_sample, "--seed", "5") == 0
    labels = read_labels(sheet)
    assert labels[fact] == "not stated" and labels[claim] == "contradicted"
    assert sum(v is not None for v in labels.values()) == 2

    # Another seed draws other items: the command refuses and leaves the sheet as it was.
    from edgar_eval.human_check import draw_human_check

    others = {i.id for i in draw_human_check(study, claude, seed=99).items}
    assert fact not in others or claim not in others
    before = sheet.read_text()
    assert _sample_command(tmp_path, study_sheet, study_sample, "--seed", "99") == 1
    assert sheet.read_text() == before


# --- Scoring --------------------------------------------------------------------------------


def _jev(rows):
    """Jev's first run: a probability for a fact, a verdict for a claim, None a failure."""
    verdicts = {}
    for item_id, value in rows.items():
        if value is None:
            verdicts[item_id] = Verdict.failed(item_id, "x")
        elif item_id.startswith("F-"):
            verdicts[item_id] = Verdict.of_fact(item_id, value)
        else:
            verdicts[item_id] = Verdict(item_id, value, probabilities={value: 1.0})
    return JudgeRun(judge=JEV_MODEL, run=1, verdicts=verdicts)


# Six items: (id, the developer's label, Claude's label, Jev run 1).
ROWS = [
    ("F-0000000001", "stated", "stated", 0.9),
    ("F-0000000002", "stated", "not stated", 0.95),
    ("F-0000000003", "not stated", "not stated", 0.1),
    ("F-0000000004", "not stated", "not stated", 0.7),
    ("C-0000000005", "supported", "supported", "supported"),
    ("C-0000000006", "unsupported", "unsupported", "supported"),
    ("C-0000000007", "contradicted", "unsupported", "contradicted"),
    ("C-0000000008", "supported", "supported", None),  # Jev's judgment failed
]


def test_the_score_reports_agreement_with_claude_and_with_jev_against_hand_computed_values(
    monkeypatch,
):
    from edgar_eval import human_check
    from edgar_eval.human_check import score_human_check

    monkeypatch.setattr(human_check, "FACT_CUTOFF", 0.6)
    human = {i: h for i, h, _, _ in ROWS}
    claude = {i: c for i, _, c, _ in ROWS}
    jev = _jev({i: j for i, _, _, j in ROWS})
    report = score_human_check(list(human), human, claude, jev)

    # Against Claude: facts agree on 3 of 4; kappa = (0.75 - 0.5) / 0.5.
    assert (report.claude.facts.agree, report.claude.facts.items) == (3, 4)
    assert report.claude.facts.share == 0.75
    assert report.claude.facts.kappa == pytest.approx(0.5)
    # Claims agree on 3 of 4: observed 0.75, chance 0.5 * 0.5 + 0.25 * 0.5 = 0.375.
    assert (report.claude.claims.agree, report.claude.claims.items) == (3, 4)
    assert report.claude.claims.kappa == pytest.approx((0.75 - 0.375) / 0.625)
    assert (report.claude.agree, report.claude.items) == (6, 8)
    assert report.claude.failed == 0

    # Against Jev at the 0.6 cut-off: F4 (0.7) is stated, so facts agree on 3 of 4.
    assert (report.jev.facts.agree, report.jev.facts.items) == (3, 4)
    assert report.jev.facts.kappa == pytest.approx(0.5)
    # C8's judgment failed, so it is left out and counted: claims agree on 2 of 3.
    assert (report.jev.claims.agree, report.jev.claims.items) == (2, 3)
    observed, chance = 2 / 3, (1 / 3) * (2 / 3) + (1 / 3) * 0 + (1 / 3) * (1 / 3)
    assert report.jev.claims.kappa == pytest.approx((observed - chance) / (1 - chance))
    assert (report.jev.agree, report.jev.items) == (5, 7)
    assert report.jev.failed == 1
    assert report.jev.reference == f"{JEV_MODEL} run 1"
    assert report.fact_cutoff == 0.6


def test_a_kind_with_an_unlabelled_item_is_left_out_and_the_other_kind_is_scored():
    from edgar_eval.human_check import LeftOut, score_human_check

    # The developer labelled every fact item and three of the four claim items.
    human = {i: h for i, h, _, _ in ROWS} | {"C-0000000006": None}
    claude = {i: c for i, _, c, _ in ROWS}
    jev = _jev({i: j for i, _, _, j in ROWS})
    report = score_human_check(list(human), human, claude, jev)

    assert (report.items, report.facts, report.claims) == (4, 4, 0)
    assert report.left_out == (LeftOut(kind="claim", items=4, labelled=3),)
    assert (report.claude.facts.agree, report.claude.facts.items) == (3, 4)
    assert (report.claude.claims.items, report.claude.claims.share) == (0, None)
    assert report.claude.claims.kappa is None
    assert (report.claude.agree, report.claude.items) == (3, 4)
    # C8's failed Jev judgment is a claim item, left out with its kind.
    assert (report.jev.agree, report.jev.items, report.jev.failed) == (3, 4, 0)


def test_the_score_refuses_while_no_kind_is_fully_labelled():
    from edgar_eval.human_check import score_human_check
    from edgar_eval.judge_study import Unlabelled

    human = {i: h for i, h, _, _ in ROWS} | {"F-0000000002": None, "C-0000000006": None}
    claude = {i: c for i, _, c, _ in ROWS}
    jev = _jev({i: j for i, _, _, j in ROWS})
    with pytest.raises(Unlabelled, match="no kind"):
        score_human_check(list(human), human, claude, jev)


def test_the_score_command_scores_each_fully_labelled_kind_and_writes_json(tmp_path):
    from edgar_eval.human_check import main

    study, claude = _study()
    study_sheet, study_sample = _write_study(tmp_path, study, claude)
    assert _sample_command(tmp_path, study_sheet, study_sample, "--seed", "5") == 0
    sheet = tmp_path / "human_check.md"
    drawn = list(read_labels(sheet))
    verdicts = tmp_path / "verdicts.json"
    probabilities = {i.id: 0.9 if n % 2 else 0.1 for n, i in enumerate(study.items)}
    rows = {i: probabilities[i] if i.startswith("F-") else "supported" for i in probabilities}
    runs = [_jev(rows), JudgeRun(judge=JEV_MODEL, run=2, verdicts=_jev(rows).verdicts)]
    save_verdicts(runs, study, verdicts)
    argv = [
        "score",
        "--sheet",
        str(sheet),
        "--study-sheet",
        str(study_sheet),
        "--study-sample",
        str(study_sample),
        "--verdicts",
        str(verdicts),
        "--json",
        str(tmp_path / "score.json"),
    ]

    _label(sheet, {drawn[0]: claude[drawn[0]]})
    err = io.StringIO()
    assert main(argv, out=io.StringIO(), err=err) == 1
    assert "unlabelled" in err.getvalue()
    assert not (tmp_path / "score.json").exists()

    # Every fact item labelled, no claim item: the facts are scored, the claims left out.
    _label(sheet, {i: claude[i] for i in drawn if i.startswith("F-")})
    out = io.StringIO()
    assert main(argv, out=out, err=io.StringIO()) == 0
    saved = json.loads((tmp_path / "score.json").read_text())
    assert (saved["items"], saved["facts"], saved["claims"]) == (15, 15, 0)
    assert saved["left_out"] == [{"kind": "claim", "items": 15, "labelled": 0}]
    assert saved["claude"]["agree"] == saved["claude"]["items"] == 15
    assert "Claim items not scored: 0 of 15 labelled" in out.getvalue()

    # The developer labels every item as Claude did: full agreement with Claude.
    _label(sheet, {i: claude[i] for i in drawn})
    out = io.StringIO()
    assert main(argv, out=out, err=io.StringIO()) == 0
    saved = json.loads((tmp_path / "score.json").read_text())
    assert saved["claude"]["agree"] == saved["claude"]["items"] == 30
    assert saved["left_out"] == []
    assert saved["claude"]["facts"]["kappa"] == pytest.approx(1.0)
    assert saved["jev"]["items"] == 30
    printed = out.getvalue()
    assert "30 of 30" in printed and "Claude" in printed and JEV_MODEL in printed


def test_the_score_refuses_an_item_not_in_the_judge_study(tmp_path):
    from edgar_eval.human_check import score_human_check

    human = {"F-00000000ff": "stated"}
    with pytest.raises(ValueError, match="F-00000000ff"):
        score_human_check(list(human), human, {}, _jev({}))


# --- Where the files live and how they are reached ---------------------------------------------


def test_the_sheet_is_committed_beside_the_study_and_the_score_is_derived():
    import subprocess

    from edgar_eval.human_check import DEFAULT_SCORE, DEFAULT_SHEET
    from edgar_eval.judge_study import DEFAULT_SHEET as STUDY_SHEET
    from edgar_eval.judge_study import DEFAULT_VERDICTS
    from edgar_rag.paths import REPO_ROOT

    assert DEFAULT_SHEET.parent == STUDY_SHEET.parent
    assert DEFAULT_SCORE.parent == DEFAULT_VERDICTS.parent

    def ignored(path):
        check = ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", str(path)]
        return subprocess.run(check, check=False).returncode == 0

    assert not ignored(DEFAULT_SHEET) and ignored(DEFAULT_SCORE)


def test_both_commands_are_in_the_makefile_and_described_in_the_docs():
    from edgar_rag.paths import REPO_ROOT

    makefile = (REPO_ROOT / "Makefile").read_text()
    assert re.search(r"^human-check-sample:.*\n\t.*edgar_eval\.human_check sample", makefile, re.M)
    assert re.search(r"^human-check-score:.*\n\t.*edgar_eval\.human_check score", makefile, re.M)
    for doc in ("docs/evaluation.md", "AGENTS.md"):
        text = (REPO_ROOT / doc).read_text()
        assert "make human-check-sample" in text and "make human-check-score" in text
