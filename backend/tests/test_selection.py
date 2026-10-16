"""The Arm (and generator) selection rule: the shipped choice stays unless a challenger
is distinguishably better on Fact Recall, question by question, and not worse on
Faithfulness or Coverage Gaps; the cheapest wins ties."""

import json

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
