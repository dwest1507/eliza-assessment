"""The Arm (and generator) selection rule: the shipped choice stays unless a challenger
is distinguishably better on Fact Recall, question by question, and not worse on
Faithfulness or Coverage Gaps; the cheapest wins ties."""

import io
import json
from pathlib import Path

import pytest

from edgar_eval.selection import Candidate, choose, sign_test


def test_the_sign_test_counts_cases_where_one_side_scored_higher():
    result = sign_test([1.0, 1.0, 0.5, 0.5, 0.0], [0.5, 0.5, 0.5, 1.0, 0.0])

    assert (result.challenger_only, result.shipped_only) == (2, 1)
    assert result.p_value == pytest.approx(1.0)
    assert result.verdict == "indistinguishable"


def test_the_sign_test_skips_cases_either_side_could_not_score():
    result = sign_test([1.0] * 6 + [None, 1.0], [0.0] * 6 + [1.0, None])

    assert (result.challenger_only, result.shipped_only) == (6, 0)
    assert result.verdict == "ahead"


def _candidate(name, recall, faithful=None, gaps=None, cost=0.002):
    cases = [f"c{i}" for i in range(len(recall))]
    return Candidate(
        name=name,
        fact_recall=dict(zip(cases, recall, strict=True)),
        faithfulness=dict(zip(cases, faithful or [1.0] * len(recall), strict=True)),
        coverage_gaps=dict(zip(cases, gaps or [None] * len(recall), strict=True)),
        cost_usd=cost,
    )


SHIPPED = _candidate("fts5", [0.0] * 8)


def test_the_shipped_choice_stays_when_no_challenger_is_distinguishably_better():
    close = _candidate("dense", [1.0] * 5 + [0.0] * 3)  # 5 wins to 0: p = 0.0625

    choice = choose(SHIPPED, [close])

    assert choice.chosen == "fts5"
    assert choice.comparisons["dense"].fact_recall.verdict == "indistinguishable"


def test_a_challenger_better_on_fact_recall_and_no_worse_elsewhere_is_chosen():
    better = _candidate("dense", [1.0] * 6 + [0.0] * 2)  # 6 wins to 0: p = 0.031

    assert choose(SHIPPED, [better]).chosen == "dense"


def test_a_challenger_worse_on_faithfulness_or_coverage_gaps_is_not_chosen():
    unfaithful = _candidate("dense", [1.0] * 6 + [0.0] * 2, faithful=[0.0] * 6 + [1.0] * 2)
    shipped = _candidate("fts5", [0.0] * 8, gaps=[True] * 8)
    gapless = _candidate("hybrid", [1.0] * 6 + [0.0] * 2, gaps=[False] * 6 + [True] * 2)

    assert choose(SHIPPED, [unfaithful]).chosen == "fts5"
    assert choose(shipped, [gapless]).chosen == "fts5"


def test_the_cheapest_of_several_qualifying_challengers_wins():
    dear = _candidate("rerank", [1.0] * 8, cost=0.003)
    cheap = _candidate("hybrid", [1.0] * 6 + [0.0] * 2, cost=0.002)

    assert choose(SHIPPED, [dear, cheap]).chosen == "hybrid"


def test_a_case_missing_a_score_on_one_side_is_left_out_of_that_scores_pairs():
    # c0's Fact Recall judgment failed for the challenger; c7 was answered by the shipped
    # choice only. Neither counts as a zero: both are left out of Fact Recall's pairs.
    challenger = _candidate("dense", [None] + [1.0] * 6)
    shipped = _candidate("fts5", [1.0] + [0.0] * 7)

    comparison = choose(shipped, [challenger]).comparisons["dense"]

    assert comparison.fact_recall.shipped_only == 0  # c0 is not a loss
    assert comparison.paired == {"fact_recall": 6, "faithfulness": 7, "coverage_gaps": 0}
    assert comparison.left_out == {"fact_recall": 2, "faithfulness": 1, "coverage_gaps": 0}


def test_the_command_reports_the_cases_each_score_left_out(tmp_path, capsys):
    from edgar_eval.selection import main

    def report(arm, recall):
        cases = [
            {"case_id": f"c{i}", "fact_recall": r, "faithfulness": 1.0, "coverage_gaps": None}
            for i, r in enumerate(recall)
        ]
        path = tmp_path / f"generation-arms-dev-{arm}.json"
        path.write_text(json.dumps({"arm": arm, "split": "dev", "cases": cases}))
        return str(path)

    out = tmp_path / "arm-choice-dev.json"
    shipped, challenger = report("fts5", [0.0] * 8), report("dense", [None] + [0.5] * 7)
    main(["compare", shipped, challenger, "--json", str(out)])

    printed = capsys.readouterr().out
    assert "Fact Recall: ahead (7 cases higher, 0 lower" in printed
    assert "7 cases paired, 1 left out" in printed
    saved = json.loads(out.read_text())["comparisons"]["dense"]
    assert (saved["paired"]["fact_recall"], saved["left_out"]["fact_recall"]) == (7, 1)


def test_the_command_compares_generation_reports_and_writes_the_choice(tmp_path, capsys):
    from edgar_eval.selection import main

    def report(arm, recall):
        cases = [
            {
                "case_id": f"c{i}",
                "fact_recall": r,
                "faithfulness": 1.0,
                "coverage_gaps": None,
                "cost_usd": 0.002,
            }
            for i, r in enumerate(recall)
        ]
        path = tmp_path / f"generation-arms-dev-{arm}.json"
        path.write_text(json.dumps({"arm": arm, "split": "dev", "cases": cases}))
        return str(path)

    out = tmp_path / "arm-choice-dev.json"
    code = main(
        ["compare", report("fts5", [0.0] * 8), report("dense", [0.5] * 8), "--json", str(out)]
    )

    assert code == 0
    printed = capsys.readouterr().out
    assert "dense" in printed and "Fact Recall" in printed and "Chosen: dense" in printed
    assert json.loads(out.read_text())["chosen"] == "dense"


# --- The generator rule -------------------------------------------------------------------
# A generator replaces the shipped one only if distinguishably better on Fact Recall or on
# Coverage Gaps, and worse on none of Fact Recall, Faithfulness or Coverage Gaps.

LUNA = _candidate("gpt-6-luna", [0.0] * 8, gaps=[False] * 8)


def test_a_generator_better_on_coverage_gaps_alone_is_chosen():
    gaps = _candidate("claude-sonnet-5-5", [0.0] * 8, gaps=[True] * 6 + [False] * 2)

    assert choose(LUNA, [gaps], rule="generators").chosen == "claude-sonnet-5-5"
    assert choose(LUNA, [gaps]).chosen == "gpt-6-luna"  # the Arm rule gates on Fact Recall


def test_a_generator_better_on_fact_recall_is_chosen_unless_worse_elsewhere():
    better = _candidate("gpt-6.1-sol", [1.0] * 6 + [0.0] * 2, gaps=[False] * 8)
    unfaithful = _candidate(
        "claude-opus-5-5", [1.0] * 6 + [0.0] * 2, faithful=[0.0] * 6 + [1.0] * 2
    )
    shipped = _candidate("gpt-6-luna", [0.0] * 8, gaps=[True] * 8)
    gapless = _candidate("claude-sonnet-5-5", [1.0] * 6 + [0.0] * 2, gaps=[False] * 8)

    assert choose(LUNA, [better], rule="generators").chosen == "gpt-6.1-sol"
    assert choose(LUNA, [unfaithful], rule="generators").chosen == "gpt-6-luna"
    assert choose(shipped, [gapless], rule="generators").chosen == "gpt-6-luna"


def test_generator_reports_are_named_by_model_not_by_arm(tmp_path, capsys):
    from edgar_eval.selection import main

    def report(model, recall):
        cases = [
            {
                "case_id": f"c{i}",
                "fact_recall": r,
                "faithfulness": 1.0,
                "coverage_gaps": None,
                "cost_usd": 0.002,
            }
            for i, r in enumerate(recall)
        ]
        path = tmp_path / f"generation-dev-{model}.json"
        path.write_text(json.dumps({"arm": "fts5", "model": model, "split": "dev", "cases": cases}))
        return str(path)

    out = tmp_path / "generator-choice-dev.json"
    code = main(
        [
            "compare",
            report("gpt-6-luna", [0.0] * 8),
            report("claude-opus-5-5", [0.5] * 8),
            "--rule",
            "generators",
            "--json",
            str(out),
        ]
    )

    assert code == 0
    assert "Chosen: claude-opus-5-5" in capsys.readouterr().out
    written = json.loads(out.read_text())
    assert written["chosen"] == "claude-opus-5-5" and written["rule"] == "generators"


# --- The chunk size and context budget rule (ADR 0010) -----------------------------------
# The Arm rule, with candidates named by their setting: every setting runs on the
# Shipped Arm with the shipped generator.


def test_setting_reports_are_named_by_their_setting_and_judged_by_the_arm_rule(tmp_path, capsys):
    from edgar_eval.selection import main

    def report(settings, recall, gaps, cost):
        cases = [
            {
                "case_id": f"c{i}",
                "fact_recall": r,
                "faithfulness": 1.0,
                "coverage_gaps": None if g is None else {"missing": [] if g else ["x"]},
                "cost_usd": cost,
            }
            for i, (r, g) in enumerate(zip(recall, gaps, strict=True))
        ]
        data = {"arm": "fts5", "model": "gpt-6-luna", "settings": settings, "cases": cases}
        path = tmp_path / f"generation-dev-{settings}.json"
        path.write_text(json.dumps(data | {"split": "dev"}))
        return str(path)

    shipped = report("chunks-600-budget-32000", [0.0] * 8, [True] * 8, 0.0025)
    bigger = report("chunks-600-budget-48000", [1.0] * 6 + [0.0] * 2, [True] * 8, 0.0035)
    smaller = report("chunks-450-budget-32000", [1.0] * 6 + [0.0] * 2, [True] * 8, 0.0024)
    gapless = report("chunks-300-budget-24000", [1.0] * 8, [False] * 6 + [True] * 2, 0.0020)
    out = tmp_path / "settings-choice-dev.json"

    code = main(
        ["compare", shipped, bigger, smaller, gapless, "--rule", "settings", "--json", str(out)]
    )

    assert code == 0
    choice = json.loads(out.read_text())
    assert choice["shipped"] == "chunks-600-budget-32000"
    assert set(choice["comparisons"]) == {
        "chunks-600-budget-48000",
        "chunks-450-budget-32000",
        "chunks-300-budget-24000",
    }
    assert not choice["comparisons"]["chunks-300-budget-24000"]["qualifies"]  # behind on gaps
    assert choice["chosen"] == "chunks-450-budget-32000"  # the cheaper of the two qualifying
    assert "Chosen: chunks-450-budget-32000" in capsys.readouterr().out


# --- Limiting the generator comparison ----------------------------------------------------
# Golden Set version 2 compares gpt-6-luna with claude-haiku-5-5 only; the other rows stay
# in the table so version 1's reports still price.


def _fake_generation_runs(monkeypatch, tmp_path):
    from edgar_eval import generation, selection

    ran = []

    def fake_main(argv, *, out=None):
        model, target = argv[argv.index("--model") + 1], Path(argv[argv.index("--json") + 1])
        ran.append(model)
        cases = [{"case_id": "c0", "fact_recall": 0.5, "faithfulness": 1.0, "coverage_gaps": None}]
        target.write_text(json.dumps({"model": model, "split": "dev", "cases": cases}))
        return 0

    monkeypatch.setattr(generation, "main", fake_main)
    monkeypatch.setattr(selection, "_EVAL_DIR", tmp_path)
    return ran


def test_the_generator_comparison_can_be_limited_to_named_generators(monkeypatch, tmp_path):
    from edgar_eval.selection import main

    ran = _fake_generation_runs(monkeypatch, tmp_path)
    out = tmp_path / "generator-choice-dev.json"

    main(["generators", "--model", "claude-haiku-5-5", "--json", str(out)], out=io.StringIO())

    assert ran == ["gpt-6-luna", "claude-haiku-5-5"]  # the shipped generator always first
    written = json.loads(out.read_text())
    assert written["reports"] == [
        str(tmp_path / "generation-dev.json"),
        str(tmp_path / "generation-dev-claude-haiku-5-5.json"),
    ]
    assert list(written["comparisons"]) == ["claude-haiku-5-5"]


def test_naming_the_shipped_generator_runs_it_once(monkeypatch, tmp_path):
    from edgar_eval.selection import main

    ran = _fake_generation_runs(monkeypatch, tmp_path)
    argv = ["generators", "--model", "gpt-6-luna", "--model", "claude-haiku-5-5"]

    main([*argv, "--json", str(tmp_path / "c.json")], out=io.StringIO())

    assert ran == ["gpt-6-luna", "claude-haiku-5-5"]


def test_with_no_generator_named_every_generator_in_the_table_runs(monkeypatch, tmp_path):
    from edgar_eval.generators import GENERATORS
    from edgar_eval.selection import main

    ran = _fake_generation_runs(monkeypatch, tmp_path)

    main(["generators", "--json", str(tmp_path / "c.json")], out=io.StringIO())

    assert ran == [g.model for g in GENERATORS]


def test_a_generator_not_in_the_table_is_refused_before_any_run(monkeypatch, tmp_path):
    from edgar_eval.selection import main

    ran = _fake_generation_runs(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as stopped:
        main(["generators", "--model", "gemini-9"], out=io.StringIO())

    assert stopped.value.code != 0 and ran == []
