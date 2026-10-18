"""The Arm (and generator) selection rule: the shipped choice stays unless a challenger
is ahead on Fact Recall, question by question (one-sided p < 0.10), and behind on no
guardrail (one-sided p < 0.20 on Faithfulness, Coverage Gaps or Contradicted Claims);
the cheapest qualifying challenger wins."""

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
    shipped = _candidate("fts5", [0.0] * 5 + [1.0] + [0.0] * 2)
    close = _candidate("dense", [1.0] * 5 + [0.0] * 3)  # 5 wins to 1: one-sided p = 0.109

    choice = choose(shipped, [close])

    assert choice.chosen == "fts5"
    assert choice.comparisons["dense"].fact_recall.verdict == "indistinguishable"


def test_a_challenger_better_on_fact_recall_and_no_worse_elsewhere_is_chosen():
    better = _candidate("dense", [1.0] * 6 + [0.0] * 2)  # 6 wins to 0: one-sided p = 0.016

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

    assert comparison.fact_recall.losses == 0  # c0 is not a loss
    scores = ("fact_recall", "faithfulness", "coverage_gaps")
    assert [getattr(comparison, s).paired for s in scores] == [6, 7, 0]
    assert [getattr(comparison, s).left_out for s in scores] == [2, 1, 0]


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
    assert "p ahead = 0.008" in printed and "7 cases paired, 1 left out" in printed
    assert "mean difference +0.500, 95% interval [+0.500, +0.500]" in printed
    saved = json.loads(out.read_text())["comparisons"]["dense"]["fact_recall"]
    assert (saved["paired"], saved["left_out"], saved["wins"], saved["losses"]) == (7, 1, 7, 0)
    assert saved["p_ahead"] == pytest.approx(1 / 128)
    assert saved["difference"]["mean"] == pytest.approx(0.5)


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
    challenger = report("dense-local", [0.5] * 8)
    code = main(["compare", report("fts5", [0.0] * 8), challenger, "--json", str(out)])

    assert code == 0
    printed = capsys.readouterr().out
    assert "dense-local" in printed and "Fact Recall" in printed
    assert "Chosen: dense-local" in printed
    assert json.loads(out.read_text())["chosen"] == "dense-local"


# --- The one-call rule (2026-10-17) ------------------------------------------------------
# The Answer Call is a question's only API call: an Arm that makes another at query time
# is compared and reported, unconstrained, but never chosen.


def test_a_challenger_that_makes_an_api_call_at_query_time_is_never_chosen():
    hosted = _candidate("dense", [1.0] * 8, cost=0.001)
    hosted = Candidate(**{**hosted.__dict__, "query_api_call": True})
    local = _candidate("dense-local", [1.0] * 6 + [0.0] * 2, cost=0.003)

    assert choose(SHIPPED, [hosted]).chosen == "fts5"
    choice = choose(SHIPPED, [hosted, local])
    assert choice.chosen == "dense-local"  # though the hosted Arm is cheaper and further ahead
    assert choice.comparisons["dense"].qualifies  # unconstrained, it would qualify
    assert not choice.comparisons["dense"].shippable
    assert choice.comparisons["dense-local"].shippable


def test_a_report_says_whether_its_arm_makes_an_api_call_at_query_time(tmp_path):
    cases = [{"case_id": "c0", "fact_recall": 1.0, "faithfulness": 1.0}]

    recorded = {"arm": "rerank", "query_api_call": True, "cases": cases}
    assert Candidate.from_report(recorded).query_api_call
    # A report saved before the rule: the Arm table says.
    assert Candidate.from_report({"arm": "hybrid", "cases": cases}).query_api_call
    assert not Candidate.from_report({"arm": "hybrid-local", "cases": cases}).query_api_call
    assert not Candidate.from_report({"model": "gpt-6-luna", "cases": cases}).query_api_call


def test_the_compare_command_labels_an_arm_that_cannot_ship(tmp_path, capsys):
    from edgar_eval.selection import main

    shipped = _report(tmp_path / "generation-dev.json", "fts5", [0.0] * 8)
    hosted = _report(tmp_path / "generation-arms-dev-hybrid.json", "hybrid", [1.0] * 8)
    out = tmp_path / "arm-choice-dev.json"

    main(["compare", shipped, hosted, "--json", str(out)])

    printed = capsys.readouterr().out
    assert "available if the one-call limit is lifted" in printed
    assert "Chosen: fts5" in printed
    saved = json.loads(out.read_text())
    assert saved["comparisons"]["hybrid"]["qualifies"]
    assert saved["comparisons"]["hybrid"]["shippable"] is False


# --- The one-sided thresholds (ADR 0011) -------------------------------------------------
# Ahead at one-sided p < 0.10 on an ahead metric; behind at one-sided p < 0.20 on any
# guardrail; one pair of thresholds for every rule.


def _scores(wins, losses, ties=0):
    """Challenger and shipped per-case scores with `wins` and `losses` for the challenger."""
    return [1.0] * wins + [0.0] * losses + [0.5] * ties, [0.0] * wins + [1.0] * losses + [
        0.5
    ] * ties


def _against(challenger_recall, shipped_recall, *, faithful=None, contradicted=None, cost=0.002):
    """A challenger and a shipped Candidate on the same cases."""
    n = len(challenger_recall)
    c_faith, s_faith = faithful or ([1.0] * n, [1.0] * n)
    c_clean, s_clean = contradicted or ([None] * n, [None] * n)
    cases = [f"c{i}" for i in range(n)]

    def candidate(name, recall, faith, clean, cost):
        return Candidate(
            name=name,
            fact_recall=dict(zip(cases, recall, strict=True)),
            faithfulness=dict(zip(cases, faith, strict=True)),
            coverage_gaps=dict.fromkeys(cases),
            contradicted_claims=dict(zip(cases, clean, strict=True)),
            cost_usd=cost,
        )

    return (
        candidate("challenger", challenger_recall, c_faith, c_clean, cost),
        candidate("shipped", shipped_recall, s_faith, s_clean, 0.002),
    )


@pytest.mark.parametrize("rule", ["arms", "generators", "settings"])
def test_ahead_on_fact_recall_just_under_one_sided_p_0_10_qualifies(rule):
    challenger, shipped = _against(*_scores(7, 2))  # p = 46/512 = 0.090

    comparison = choose(shipped, [challenger], rule).comparisons["challenger"]

    assert comparison.fact_recall.p_ahead == pytest.approx(0.0898, abs=1e-4)
    assert comparison.fact_recall.verdict == "ahead"
    assert comparison.qualifies


@pytest.mark.parametrize("rule", ["arms", "generators", "settings"])
def test_ahead_on_fact_recall_just_over_one_sided_p_0_10_does_not_qualify(rule):
    challenger, shipped = _against(*_scores(11, 5))  # p = 6885/65536 = 0.105

    comparison = choose(shipped, [challenger], rule).comparisons["challenger"]

    assert comparison.fact_recall.p_ahead == pytest.approx(0.1051, abs=1e-4)
    assert comparison.fact_recall.verdict == "indistinguishable"
    assert not comparison.qualifies
    assert choose(shipped, [challenger], rule).chosen == "shipped"


def _ahead_on_recall_and_faithfulness(wins, losses):
    """Fact Recall 9 wins to 0 on cases c0..c8; Faithfulness `wins` to `losses` on the
    cases after them."""
    recall = _scores(9, 0, ties=wins + losses)
    c_faith, s_faith = _scores(wins, losses)
    return _against(*recall, faithful=([0.5] * 9 + c_faith, [0.5] * 9 + s_faith))


@pytest.mark.parametrize("rule", ["arms", "generators", "settings"])
def test_behind_on_faithfulness_just_under_one_sided_p_0_20_blocks_the_challenger(rule):
    challenger, shipped = _ahead_on_recall_and_faithfulness(1, 4)  # p = 6/32 = 0.1875

    comparison = choose(shipped, [challenger], rule).comparisons["challenger"]

    assert comparison.faithfulness.p_behind == pytest.approx(0.1875)
    assert comparison.faithfulness.verdict == "behind"
    assert not comparison.qualifies


@pytest.mark.parametrize("rule", ["arms", "generators", "settings"])
def test_behind_on_faithfulness_just_over_one_sided_p_0_20_does_not_block(rule):
    challenger, shipped = _ahead_on_recall_and_faithfulness(2, 5)  # p = 29/128 = 0.227

    comparison = choose(shipped, [challenger], rule).comparisons["challenger"]

    assert comparison.faithfulness.p_behind == pytest.approx(0.2266, abs=1e-4)
    assert comparison.faithfulness.verdict == "indistinguishable"
    assert comparison.qualifies


@pytest.mark.parametrize("rule", ["arms", "generators", "settings"])
def test_a_challenger_with_more_contradicted_answers_is_blocked(rule):
    # Ahead on Fact Recall on all 9 cases, but 4 of the challenger's answers have a
    # Contradicted Claim where the shipped answers have none, and 1 the other way round:
    # behind on "has no Contradicted Claim" at p = 6/32 = 0.1875.
    recall = _scores(9, 0)
    clean = ([True] * 4 + [False] * 4 + [True], [True] * 4 + [True] * 4 + [False])
    challenger, shipped = _against(*recall, contradicted=clean)

    comparison = choose(shipped, [challenger], rule).comparisons["challenger"]

    assert comparison.fact_recall.verdict == "ahead"
    assert comparison.contradicted_claims.verdict == "behind"
    assert (comparison.contradicted_claims.wins, comparison.contradicted_claims.losses) == (1, 4)
    assert not comparison.qualifies


def test_the_command_reads_contradicted_claims_from_generation_reports(tmp_path, capsys):
    from edgar_eval.selection import main

    def report(name, contradicted, failed=()):
        cases = [
            {
                "case_id": f"c{i}",
                "fact_recall": 1.0 if name == "dense" else 0.0,
                "faithfulness": None if i in failed else 1.0,
                "coverage_gaps": None,
                "contradictions": {"claims": ["x"] * n, "count": n, "passed": not n},
                "judgments": {
                    "failures": [{"judgment": "faithfulness"}] if i in failed else [],
                },
            }
            for i, n in enumerate(contradicted)
        ]
        path = tmp_path / f"generation-arms-dev-{name}.json"
        path.write_text(json.dumps({"arm": name, "split": "dev", "cases": cases}))
        return str(path)

    # The challenger contradicts itself in c0..c3, the shipped choice in c4; c9's claims
    # could not be judged for the challenger, so whether it has one is unknown.
    shipped = report("fts5", [0] * 4 + [1] + [0] * 5)
    challenger = report("dense", [1] * 4 + [0] * 6, failed=(9,))
    out = tmp_path / "arm-choice-dev.json"

    main(["compare", shipped, challenger, "--json", str(out)])

    saved = json.loads(out.read_text())["comparisons"]["dense"]
    clean = saved["contradicted_claims"]
    assert (clean["paired"], clean["left_out"], clean["wins"], clean["losses"]) == (9, 1, 1, 4)
    assert clean["verdict"] == "behind" and saved["fact_recall"]["verdict"] == "ahead"
    assert not saved["qualifies"]
    assert "No Contradicted Claim: behind (1 cases higher, 4 lower" in capsys.readouterr().out


def test_a_version_1_report_leaves_contradicted_claims_unscored():
    v1 = {"arm": "fts5", "cases": [{"case_id": "c0", "fact_recall": 1.0, "faithfulness": 1.0}]}

    assert Candidate.from_report(v1).contradicted_claims == {"c0": None}


def test_every_rule_shares_one_pair_of_thresholds():
    from edgar_eval import selection

    assert (selection.AHEAD_P, selection.BEHIND_P) == (0.10, 0.20)
    for name, rule in selection.RULES.items():
        guardrails = set(rule.behind_on_none)
        assert {"faithfulness", "coverage_gaps", "contradicted_claims"} <= guardrails, name


def test_the_cheapest_qualifying_challenger_wins_under_the_one_sided_rule():
    shipped_recall = [0.0] * 7 + [1.0] * 2

    def challenger(name, recall, cost):
        return Candidate(**{**vars(_against(recall, shipped_recall, cost=cost)[0]), "name": name})

    shipped = _against(shipped_recall, shipped_recall)[1]
    dear = challenger("dear", [1.0] * 9, 0.003)  # 7 wins to 0: p = 0.008
    cheap = challenger("cheap", [1.0] * 7 + [0.0] * 2, 0.001)  # 7 to 2: p = 0.090
    cheapest = challenger("cheapest", [1.0] * 5 + [0.0] * 4, 0.0005)  # 5 to 2: p = 0.227

    choice = choose(shipped, [dear, cheap, cheapest])

    assert [n for n, c in choice.comparisons.items() if c.qualifies] == ["dear", "cheap"]
    assert choice.chosen == "cheap"


def test_each_score_reports_its_pairs_wins_losses_p_values_and_a_bootstrap_interval():
    challenger, shipped = _against([1.0, 1.0, 0.5, 0.0, None], [0.0, 0.5, 0.5, 0.5, 1.0])

    first = choose(shipped, [challenger]).comparisons["challenger"].fact_recall
    again = choose(shipped, [challenger]).comparisons["challenger"].fact_recall

    assert (first.paired, first.left_out, first.wins, first.losses) == (4, 1, 2, 1)
    assert first.p_ahead == pytest.approx(0.5)  # P(X >= 2), X ~ Binomial(3, 1/2)
    assert first.p_behind == pytest.approx(0.875)
    assert first.difference.mean == pytest.approx(0.25)  # (1 + 0.5 + 0 - 0.5) / 4
    assert first.difference.low <= 0.25 <= first.difference.high
    assert (first.difference.resamples, first.difference.confidence) == (10_000, 0.95)
    assert again.difference == first.difference  # a fixed seed


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

    # The shipped generator first, as the shipped run and the Control Run.
    assert ran == ["gpt-6-luna", "gpt-6-luna", "claude-haiku-5-5"]
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

    assert ran == ["gpt-6-luna", "gpt-6-luna", "claude-haiku-5-5"]  # no third shipped run


def test_with_no_generator_named_the_default_comparison_runs(monkeypatch, tmp_path):
    from edgar_eval import generators
    from edgar_eval.selection import main

    ran = _fake_generation_runs(monkeypatch, tmp_path)
    monkeypatch.setattr(generators, "COMPARISON", ("gpt-6-luna", "claude-opus-5-5"))

    main(["generators", "--json", str(tmp_path / "c.json")], out=io.StringIO())

    assert ran == ["gpt-6-luna", "gpt-6-luna", "claude-opus-5-5"]  # read from the table


def test_with_all_every_generator_in_the_table_runs(monkeypatch, tmp_path):
    from edgar_eval.generators import GENERATORS
    from edgar_eval.selection import main

    ran = _fake_generation_runs(monkeypatch, tmp_path)

    main(["generators", "--all", "--json", str(tmp_path / "c.json")], out=io.StringIO())

    assert ran == [GENERATORS[0].model] + [g.model for g in GENERATORS]


def test_all_and_named_generators_are_not_both_accepted(monkeypatch, tmp_path):
    from edgar_eval.selection import main

    ran = _fake_generation_runs(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as stopped:
        main(["generators", "--all", "--model", "claude-haiku-5-5"], out=io.StringIO())

    assert stopped.value.code != 0 and ran == []


def test_a_generator_not_in_the_table_is_refused_before_any_run(monkeypatch, tmp_path):
    from edgar_eval.selection import main

    ran = _fake_generation_runs(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as stopped:
        main(["generators", "--model", "gemini-9"], out=io.StringIO())

    assert stopped.value.code != 0 and ran == []


# --- The Control Run (ADR 0011) ----------------------------------------------------------
# Every comparison reruns the shipped choice as a Control Run. If it comes out ahead of
# the shipped run on any of the rule's ahead metrics, the noise is larger than the
# thresholds assume: the choice is inconclusive and the shipped choice stands.


def _control(recall, *, gaps=None):
    """A Control Run on cases c0..c<n>, named as the shipped choice is."""
    return _candidate("fts5", recall, gaps=gaps)


@pytest.mark.parametrize("rule", ["arms", "generators", "settings"])
def test_a_control_run_ahead_of_the_shipped_run_makes_the_choice_inconclusive(rule):
    better = _candidate("dense", [1.0] * 6 + [0.0] * 2)  # ahead: 6 wins to 0
    control = _control([1.0] * 5 + [0.0] * 3)  # the shipped choice again, 5 wins to 0

    choice = choose(SHIPPED, [better], rule, control=control)

    assert choice.comparisons["dense"].qualifies  # the challenger is ahead on its own
    assert choice.control is not None and choice.control.fact_recall.verdict == "ahead"
    assert choice.inconclusive
    assert choice.chosen == "fts5"
    assert "Control Run" in choice.reason and "Fact Recall" in choice.reason


def test_a_control_run_ahead_on_coverage_gaps_is_inconclusive_only_where_gaps_can_win():
    # Coverage Gaps are an ahead metric under the generator rule only; under the Arm
    # rule they are a guardrail, so a Control Run ahead on them alone decides nothing.
    shipped = _candidate("gpt-6-luna", [0.0] * 8, gaps=[False] * 8)
    better = _candidate("claude-haiku-5-5", [1.0] * 6 + [0.0] * 2, gaps=[True] * 8)
    control = _candidate("gpt-6-luna", [0.0] * 8, gaps=[True] * 6 + [False] * 2)

    assert choose(shipped, [better], "generators", control=control).inconclusive
    by_arms = choose(shipped, [better], "arms", control=control)
    assert not by_arms.inconclusive and by_arms.chosen == "claude-haiku-5-5"


@pytest.mark.parametrize("rule", ["arms", "generators", "settings"])
def test_a_control_run_within_noise_leaves_the_choice_to_the_challengers(rule):
    better = _candidate("dense", [1.0] * 6 + [0.0] * 2)
    control = _control([1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # 2 wins to 0: p = 0.25

    choice = choose(SHIPPED, [better], rule, control=control)

    assert choice.control.fact_recall.verdict == "indistinguishable"
    assert not choice.inconclusive and choice.reason is None
    assert choice.chosen == "dense"


def test_a_control_run_within_noise_keeps_the_shipped_choice_with_no_challenger_ahead():
    close = _candidate("dense", [1.0] * 2 + [0.0] * 6)

    choice = choose(SHIPPED, [close], control=_control([0.0] * 8))

    assert not choice.inconclusive and choice.chosen == "fts5"


def _report(path, name, recall, *, key="arm", **fields):
    cases = [
        {"case_id": f"c{i}", "fact_recall": r, "faithfulness": 1.0, "coverage_gaps": None}
        for i, r in enumerate(recall)
    ]
    path.write_text(json.dumps({key: name, "split": "dev", "cases": cases} | fields))
    return str(path)


def test_the_compare_command_takes_a_control_run_and_says_why_it_is_inconclusive(tmp_path, capsys):
    from edgar_eval.selection import main

    shipped = _report(tmp_path / "generation-dev.json", "fts5", [0.0] * 8)
    control = _report(tmp_path / "generation-control-dev.json", "fts5", [1.0] * 5 + [0.0] * 3)
    challenger = _report(tmp_path / "generation-arms-dev-dense.json", "dense", [1.0] * 8)
    out = tmp_path / "arm-choice-dev.json"

    main(["compare", shipped, challenger, "--control", control, "--json", str(out)])

    printed = capsys.readouterr().out
    assert "Control Run" in printed
    assert "Inconclusive:" in printed and "Chosen: fts5" in printed
    saved = json.loads(out.read_text())
    assert saved["control_report"] == control
    assert saved["inconclusive"] is True and saved["chosen"] == "fts5"
    assert saved["control"]["fact_recall"]["verdict"] == "ahead"
    assert saved["comparisons"]["dense"]["qualifies"]


# --- One shipped run and one Control Run per round (ADR 0011) ------------------------------
# A round is the same code, prompt and Golden Set version on one split. The Arm, settings
# and generator commands of a round share its shipped run and Control Run, reusing them
# when they exist for that round and running them again when any of the three differs.


def _level_retrieval(argv, *, arms=None, out=None):
    """A fake retrieval harness whose every candidate reaches the shipped choice's
    evidence, so the screen keeps them all."""
    from edgar_eval.arms import ARMS

    chunks = 600
    if "--index" in argv:
        chunks = int(argv[argv.index("--index") + 1].rsplit("chunks", 1)[1].split(".")[0])
    budget = int(argv[argv.index("--context-budget") + 1]) if "--context-budget" in argv else 32000
    challengers = [a.name for a in ARMS if not a.shipped]
    _retrieval_report(
        Path(argv[argv.index("--json") + 1]), [[True]], 9_000, chunks, budget, kept=challengers
    )
    return 0


@pytest.fixture
def harness_runs(monkeypatch, tmp_path, request):
    """A fake generation harness that records each run (its report's name, and its
    arguments in `request.node.argvs`) and writes a report stamped with the current
    round, a dict the test can change; an index of another chunk size is recorded in
    `request.node.built` instead of built. The screen's retrieval runs keep every
    candidate."""
    from edgar_eval import generation, retrieval, selection

    current = {"code_version": "code-1", "prompt_version": "v7", "golden_set_version": 1}
    runs, argvs = [], {}

    def fake_main(argv, *, out=None):
        target = Path(argv[argv.index("--json") + 1])
        runs.append(target.name)
        argvs[target.name] = argv
        model = argv[argv.index("--model") + 1] if "--model" in argv else "gpt-6-luna"
        arm = argv[argv.index("--arm") + 1] if "--arm" in argv else "fts5"
        budget = argv[argv.index("--context-budget") + 1] if "--context-budget" in argv else 32000
        chunks = 600
        if "--index" in argv:
            chunks = int(argv[argv.index("--index") + 1].rsplit("chunks", 1)[1].split(".")[0])
        cases = [{"case_id": "c0", "fact_recall": 0.5, "faithfulness": 1.0, "coverage_gaps": None}]
        report = {
            "model": model,
            "arm": arm,
            "settings": f"chunks-{chunks}-budget-{budget}",
            "split": "dev",
            "cases": cases,
        }
        target.write_text(json.dumps(report | current))
        return 0

    monkeypatch.setattr(generation, "main", fake_main)
    monkeypatch.setattr(retrieval, "main", _level_retrieval)
    monkeypatch.setattr(generation, "current_round", lambda golden_set=None: dict(current))
    monkeypatch.setattr(selection, "_EVAL_DIR", tmp_path)
    monkeypatch.setattr(selection, "_INDEX_DIR", tmp_path)
    built = []
    monkeypatch.setattr(
        selection, "_build_index", lambda chunks, path: built.append((chunks, path.name))
    )
    request.node.argvs, request.node.built = argvs, built
    return runs, current


def _command(*argv, tmp_path):
    from edgar_eval.selection import main

    out = io.StringIO()
    main([*argv, "--json", str(tmp_path / "choice.json")], out=out)
    return out.getvalue(), json.loads((tmp_path / "choice.json").read_text())


def test_a_command_runs_the_rounds_shipped_run_and_control_run_once(harness_runs, tmp_path):
    runs, _ = harness_runs

    _, choice = _command("arms", tmp_path=tmp_path)

    assert runs[:2] == ["generation-dev.json", "generation-control-dev.json"]
    assert "generation-arms-dev-fts5.json" not in runs  # the shipped run is the Shipped Arm's
    assert choice["reports"][0] == str(tmp_path / "generation-dev.json")
    assert choice["control_report"] == str(tmp_path / "generation-control-dev.json")
    assert "fts5" not in choice["comparisons"] and choice["control"] is not None


def test_the_arm_settings_and_generator_commands_of_one_round_share_its_runs(
    harness_runs, tmp_path
):
    runs, _ = harness_runs

    _command("arms", tmp_path=tmp_path)
    runs.clear()
    printed, _ = _command("generators", "--model", "claude-haiku-5-5", tmp_path=tmp_path)
    assert runs == ["generation-dev-claude-haiku-5-5.json"]
    assert "Reusing the shipped run" in printed and "Reusing the Control Run" in printed
    runs.clear()
    _, choice = _command("settings", "--setting", "450:32000", tmp_path=tmp_path)
    assert runs == ["generation-dev-chunks450-budget32000.json"]
    assert list(choice["comparisons"]) == ["chunks-450-budget-32000"]


@pytest.mark.parametrize("changed", ["code_version", "prompt_version", "golden_set_version"])
def test_a_new_code_prompt_or_golden_set_version_starts_a_new_round(
    harness_runs, tmp_path, changed
):
    runs, current = harness_runs

    _command("generators", "--model", "claude-haiku-5-5", tmp_path=tmp_path)
    current[changed] = "changed"
    runs.clear()
    _command("generators", "--model", "claude-haiku-5-5", tmp_path=tmp_path)

    assert runs[:2] == ["generation-dev.json", "generation-control-dev.json"]


def test_a_report_of_another_setup_is_not_taken_as_the_shipped_run(harness_runs, tmp_path):
    runs, current = harness_runs
    # `make eval-generation MODEL=...` with OPENAI_MODEL set, say: the right name, the
    # right round, another generator.
    _report(tmp_path / "generation-dev.json", "gpt-6.1-sol", [0.5], key="model", arm="fts5")
    data = json.loads((tmp_path / "generation-dev.json").read_text())
    (tmp_path / "generation-dev.json").write_text(json.dumps(data | current))

    _command("generators", "--model", "claude-haiku-5-5", tmp_path=tmp_path)

    assert runs[0] == "generation-dev.json"


def test_the_settings_command_answers_each_named_setting_from_its_own_index(
    harness_runs, tmp_path, request
):
    _command("settings", "--setting", "450:32000", "--setting", "600:48000", tmp_path=tmp_path)

    argvs = request.node.argvs
    small = argvs["generation-dev-chunks450-budget32000.json"]
    assert small[small.index("--index") + 1] == str(tmp_path / "edgar_rag-chunks450.sqlite")
    assert small[small.index("--context-budget") + 1] == "32000"
    bigger = argvs["generation-dev-chunks600-budget48000.json"]
    assert "--index" not in bigger  # the shipped chunk size reads the shipped index
    assert bigger[bigger.index("--context-budget") + 1] == "48000"
    assert request.node.built == [
        (450, "edgar_rag-chunks450.sqlite")
    ]  # built once, as it was missing


def test_the_settings_command_needs_a_named_setting(harness_runs, tmp_path):
    from edgar_eval.selection import main

    runs, _ = harness_runs

    with pytest.raises(SystemExit) as stopped:
        main(["settings"], out=io.StringIO())

    assert stopped.value.code != 0 and runs == []


# --- The screen on Evidence Reached (ADR 0011) ---------------------------------------------
# Every candidate Arm and setting is scored by the retrieval harness first, for free; only
# those the screen keeps go on to paid Answer Calls.


def _retrieval_report(path, evidence, tokens, chunks=600, budget=32_000, kept=None):
    """A saved retrieval report whose Shipped Arm reached `evidence` (per case, per fact)."""
    cases = [
        {"case_id": f"c{i}", "evidence_reached": list(reached)}
        for i, reached in enumerate(evidence)
    ]
    arm = {"name": "fts5", "shipped": True, "cases": cases}
    arm["overall"] = {"mean_source_tokens": tokens}
    data = {"split": "dev", "chunk_tokens": chunks, "context_budget": budget, "arms": {"fts5": arm}}
    if kept is not None:
        data["screen"] = {"shipped": "fts5", "limit": 3, "kept": kept, "candidates": []}
    path.write_text(json.dumps(data))
    return str(path)


def test_the_arm_comparison_answers_only_the_arms_the_screen_keeps(
    harness_runs, monkeypatch, tmp_path
):
    from edgar_eval import retrieval

    runs, _ = harness_runs
    screened = []

    def fake_retrieval(argv, *, arms=None, out=None):
        screened.append(argv)
        path = Path(argv[argv.index("--json") + 1])
        _retrieval_report(path, [[True]], 9_000, kept=["hybrid-local"])
        return 0

    monkeypatch.setattr(retrieval, "main", fake_retrieval)

    _, choice = _command("arms", tmp_path=tmp_path)

    assert len(screened) == 1 and "--arm" not in screened[0]  # every Arm, for free
    assert runs == [  # then the round's two runs and the one Arm the screen kept
        "generation-dev.json",
        "generation-control-dev.json",
        "generation-arms-dev-hybrid-local.json",
    ]
    assert list(choice["comparisons"]) == ["hybrid-local"]
    assert choice["screen"]["kept"] == ["hybrid-local"]


def test_the_arm_comparison_never_answers_through_an_arm_that_makes_an_api_call(
    harness_runs, monkeypatch, tmp_path
):
    """Even a screen saved before the one-call rule, which kept the hosted Arms, sends
    none of them to a paid run."""
    from edgar_eval import retrieval

    runs, _ = harness_runs

    def fake_retrieval(argv, *, arms=None, out=None):
        path = Path(argv[argv.index("--json") + 1])
        _retrieval_report(path, [[True]], 9_000, kept=["dense", "hybrid", "rerank"])
        return 0

    monkeypatch.setattr(retrieval, "main", fake_retrieval)

    _, choice = _command("arms", tmp_path=tmp_path)

    assert runs[2:] == ["generation-arms-dev-rerank.json"]
    assert list(choice["comparisons"]) == ["rerank"]


def test_the_settings_command_answers_only_the_settings_the_screen_keeps(
    harness_runs, monkeypatch, tmp_path
):
    from edgar_eval import retrieval

    runs, _ = harness_runs
    evidence = {  # per context budget: the shipped one, one 3 facts behind, one ahead
        "32000": [[True, False]] * 6,
        "24000": [[False, False]] * 3 + [[True, False]] * 3,
        "48000": [[True, True]] * 6,
    }

    def fake_retrieval(argv, *, arms=None, out=None):
        assert argv[argv.index("--arm") + 1] == "fts5"  # the Shipped Arm only
        budget = argv[argv.index("--context-budget") + 1]
        path = Path(argv[argv.index("--json") + 1])
        _retrieval_report(path, evidence[budget], int(budget) / 4, budget=int(budget))
        return 0

    monkeypatch.setattr(retrieval, "main", fake_retrieval)

    printed, choice = _command(
        "settings", "--setting", "600:24000", "--setting", "600:48000", tmp_path=tmp_path
    )

    assert "generation-dev-chunks600-budget24000.json" not in runs
    assert runs[-1] == "generation-dev-chunks600-budget48000.json"
    assert choice["screen"]["shipped"] == "chunks-600-budget-32000"
    assert choice["screen"]["kept"] == ["chunks-600-budget-48000"]
    reasons = {c["name"]: c["reason"] for c in choice["screen"]["candidates"]}
    assert reasons["chunks-600-budget-24000"].startswith("dropped: behind")
    assert "chunks-600-budget-24000: " in printed and "Go on: chunks-600-budget-48000" in printed
