"""The judge study's sample: items drawn from saved generation reports, and the blind
labelling sheet the developer fills in (ADR 0013)."""

import io
import json
import os
import re
import sys

from edgar_eval.judge import Evidence
from edgar_eval.judge_study import draw_sample, write_sheet
from edgar_rag.golden_set import RequiredFact

GENERATORS = ("gpt-6-luna", "claude-sonnet-5-5", "claude-haiku-5-5")


def _fact(text, tier="must_state"):
    return RequiredFact(text, "0000000000-26-000001", "Risk Factors", text, tier)


def _answer(case_id, n):
    """An answer of `n` cited sentences, each its own paragraph citing S1 or S2."""
    return "\n\n".join(
        f"In {case_id}, finding {i} holds for the company. [S{1 + i % 2}]" for i in range(n)
    )


def _sentences(case_id, n):
    return [f"In {case_id}, finding {i} holds for the company." for i in range(n)]


def _saved_case(case_id, model, answer, facts=(), claims=()):
    return {
        "case_id": case_id,
        "question_type": "risk",
        "answer": answer,
        "model": model,
        "sources": 2,
        "judgments": {
            "facts": [{"fact": f, "probability": p} for f, p in facts],
            "claims": [
                {
                    "claim": text,
                    "tags": [tag],
                    "verdict": verdict,
                    "probabilities": {"supported": p, "unsupported": 1 - p, "contradicted": 0.0},
                }
                for text, tag, verdict, p in claims
            ],
            "model": "jev-1.13.0",
            "requests": 2,
            "input_tokens": 100,
        },
    }


def _report(model, cases):
    return {"model": model, "arm": "fts5", "context_budget": 32000, "cases": cases}


def _sources(report, case):
    """A fake of the rebuilt Answer Context: two Sources for every saved answer."""
    return {
        f"S{n}": Evidence(f"S{n}", f"Source {n} of {case['case_id']}", f"Text {n}.") for n in (1, 2)
    }


def _synthetic_reports(cases=12, sentences=10):
    """Saved reports from three generators, each answering `cases` cases. Most claims are
    supported with a confident probability; every fifth is unsupported, every thirteenth
    contradicted, every seventh uncertain."""
    reports, facts, verdicts = [], {}, {}
    for model in GENERATORS:
        saved = []
        for c in range(cases):
            case_id = f"case-{c}"
            facts[case_id] = (_fact(f"{case_id} states fact A."), _fact(f"{case_id} states B."))
            answer = _answer(case_id, sentences)
            claims = []
            for i, text in enumerate(_sentences(case_id, sentences)):
                k = c * sentences + i
                verdict = (
                    "contradicted" if k % 13 == 0 else "unsupported" if k % 5 == 0 else "supported"
                )
                p = 0.4 if k % 7 == 0 else 0.95 if verdict == "supported" else 0.02
                claims.append((text, f"S{1 + i % 2}", verdict, p))
                verdicts[(model, text)] = (verdict, p)
            fact_p = 0.3 if c % 3 == 0 else 0.97
            saved.append(
                _saved_case(
                    case_id,
                    model,
                    answer,
                    facts=[(f.fact, fact_p) for f in facts[case_id]],
                    claims=claims,
                )
            )
        reports.append((f"generation-dev-{model}.json", _report(model, saved)))
    return reports, facts, verdicts


def test_the_same_seed_and_reports_give_the_same_sample(tmp_path):
    reports, facts, _ = _synthetic_reports()
    first = draw_sample(reports, facts, _sources, seed=7, fact_items=20, claim_items=40)
    again = draw_sample(reports, facts, _sources, seed=7, fact_items=20, claim_items=40)
    other = draw_sample(reports, facts, _sources, seed=8, fact_items=20, claim_items=40)

    assert first == again
    assert [i.id for i in first.items] != [i.id for i in other.items]
    write_sheet(first, tmp_path / "a.md")
    write_sheet(again, tmp_path / "b.md")
    assert (tmp_path / "a.md").read_text() == (tmp_path / "b.md").read_text()
    assert "Seed: 7" in (tmp_path / "a.md").read_text()
    assert json.loads(json.dumps(first.to_dict()))["seed"] == 7


def _item_blocks(sheet):
    """The sheet's items, each without its label line."""
    blocks = sheet.split("\n### ")[1:]
    return [
        "\n".join(line for line in b.splitlines() if not line.startswith("LABEL ")) for b in blocks
    ]


def test_the_sheet_holds_no_jev_verdict_or_probability(tmp_path):
    reports, facts, verdicts = _synthetic_reports()
    sample = draw_sample(reports, facts, _sources, seed=1, fact_items=20, claim_items=40)
    write_sheet(sample, tmp_path / "sheet.md")
    sheet = (tmp_path / "sheet.md").read_text()

    for block in _item_blocks(sheet):
        for word in ("supported", "contradicted", "verdict", "probability", "Jev"):
            assert word not in block
        for number in ("0.4", "0.95", "0.02", "0.3", "0.97", "40%", "95%"):
            assert number not in block
        assert "drawn" not in block and "uncertain" not in block and "random" not in block
    assert "Jev" not in sheet and "probabilit" not in sheet
    # Every item asks for its label, with the labels of its kind.
    assert sheet.count("(stated / not stated):") == 20
    assert sheet.count("(supported / unsupported / contradicted):") == 40


def test_the_over_sampling_quotas_are_met_on_a_synthetic_report_set():
    from edgar_eval.judge_study import (
        CONTRADICTED_SHARE,
        GENERATOR_SHARE,
        UNCERTAIN_SHARE,
        UNSUPPORTED_SHARE,
    )

    reports, facts, verdicts = _synthetic_reports(cases=20, sentences=10)
    sample = draw_sample(reports, facts, _sources, seed=3, fact_items=30, claim_items=60)
    fact_items = [i for i in sample.items if i.kind == "fact"]
    claim_items = [i for i in sample.items if i.kind == "claim"]
    assert (len(fact_items), len(claim_items)) == (30, 60)

    # Of 600 claims, 47 contradicted, 111 unsupported and 86 uncertain: uniform
    # sampling would give about 5, 11 and 9 of 60.
    claimed = [verdicts[(i.model, i.claim)] for i in claim_items]
    assert sum(v == "contradicted" for v, _ in claimed) >= 60 * CONTRADICTED_SHARE == 6
    assert sum(v == "unsupported" for v, _ in claimed) >= 60 * UNSUPPORTED_SHARE == 15
    assert sum(0.05 <= p <= 0.65 for _, p in claimed) >= 60 * UNCERTAIN_SHARE == 20
    for model in GENERATORS:
        assert sum(i.model == model for i in claim_items) >= 60 * GENERATOR_SHARE / 3 == 10
        assert sum(i.model == model for i in fact_items) >= 30 * GENERATOR_SHARE / 3 == 5
    # A third of the cases' facts were judged at 0.3, uncertain.
    uncertain_cases = {f"case-{c}" for c in range(0, 20, 3)}
    assert sum(i.case_id in uncertain_cases for i in fact_items) >= 30 * UNCERTAIN_SHARE == 10


def test_every_generator_is_sampled_even_when_one_wrote_few_answers():
    reports, facts, _ = _synthetic_reports(cases=30)
    haiku = _report("claude-haiku-5-5", reports[2][1]["cases"][:1])
    reports = [*reports[:2], ("generation-dev-claude-haiku-5-5.json", haiku)]
    sample = draw_sample(reports, facts, _sources, seed=5, fact_items=40, claim_items=60)
    haiku_items = [i for i in sample.items if i.model == "claude-haiku-5-5"]
    # Its one answer: 2 facts and 10 claims, every one of them drawn.
    assert sum(i.kind == "fact" for i in haiku_items) == 2
    assert sum(i.kind == "claim" for i in haiku_items) == 10


def test_a_claim_item_carries_its_context_and_only_the_sources_it_cites():
    answer = "## Apple\n\nApple depends on outsourcing partners in Asia. [S2]\n\nNo tag here."
    case = _saved_case("case-0", "gpt-6-luna", answer)
    sample = draw_sample(
        [("r.json", _report("gpt-6-luna", [case]))], {}, _sources, fact_items=0, claim_items=10
    )
    (item,) = sample.items  # the uncited sentence is never judged by Jev, so no item
    assert (item.claim, item.heading) == ("Apple depends on outsourcing partners in Asia.", "Apple")
    assert [s.tag for s in item.sources] == ["S2"]
    assert sample.skipped["answers with no rewritten facts"] == 1


def test_an_answer_whose_sources_cannot_be_rebuilt_gives_no_claim_item():
    reports, facts, _ = _synthetic_reports(cases=2)
    sample = draw_sample(reports, facts, lambda report, case: None, claim_items=50)
    assert all(i.kind == "fact" for i in sample.items)
    assert sample.skipped["answers whose Sources cannot be rebuilt"] == 6


def _v2_file(tmp_path, rewritten):
    """A Golden Set version 2 file of version 1 cases rewritten with these one-claim
    facts, by case id."""
    from edgar_rag.golden_set import DEFAULT_GOLDEN_SET, SPLIT_RULE_V2

    version_1 = json.loads(DEFAULT_GOLDEN_SET.read_text(encoding="utf-8"))["cases"]
    cases = []
    for case in (c for c in version_1 if c["id"] in rewritten):
        facts = [
            {**case["required_facts"][0], "fact": text, "tier": tier}
            for text, tier in rewritten[case["id"]]
        ]
        cases.append(case | {"split": "dev", "required_facts": facts})
    path = tmp_path / "golden_set_v2.json"
    path.write_text(json.dumps({"version": 2, "split_rule": SPLIT_RULE_V2, "cases": cases}))
    return path


def _sample_command(tmp_path, reports, v2, *extra, sources=_sources):
    from edgar_eval.judge_study import main

    paths = []
    for name, data in reports:
        path = tmp_path / name
        path.write_text(json.dumps(data))
        paths.append(str(path))
    argv = ["sample", "--reports", *paths, "--golden-set-v2", str(v2)]
    argv += ["--sheet", str(tmp_path / "sheet.md"), "--sample", str(tmp_path / "sample.json")]
    return main([*argv, *extra], sources=sources, out=io.StringIO())


def test_fact_items_use_the_rewritten_facts_never_a_version_1_compound_fact(tmp_path):
    from edgar_rag.golden_set import load_brief_suite, load_golden_set

    version_1 = {c.id: c for c in load_golden_set().cases}
    brief = {c.replaces: c for c in load_brief_suite().cases if c.replaces}
    rewritten = {
        "risk-unh-cybersecurity": [
            ("UnitedHealth says Change Healthcare was subject to a cyberattack.", "must_state"),
            ("UnitedHealth says the cyberattack disrupted claims processing.", "detail"),
        ]
    }
    # Saved answers of three version 1 cases, each judged on its compound facts: one
    # rewritten in version 2, one the Brief Suite replaces, one not rewritten yet.
    saved = [
        _saved_case(
            case_id,
            "gpt-6-luna",
            _answer(case_id, 2),
            facts=[(f.fact, 0.3) for f in version_1[case_id].required_facts],
        )
        for case_id in ("risk-unh-cybersecurity", "risk-aapl-tsla-jpm", "trend-amzn-aws-two-years")
    ]
    v2 = _v2_file(tmp_path, rewritten)
    assert (
        _sample_command(tmp_path, [("generation-dev.json", _report("gpt-6-luna", saved))], v2) == 0
    )

    items = json.loads((tmp_path / "sample.json").read_text())["items"]
    sheet = (tmp_path / "sheet.md").read_text()
    sampled = {(i["case_id"], i["fact"]) for i in items if i["kind"] == "fact"}
    expected = {("risk-unh-cybersecurity", text) for text, _ in rewritten["risk-unh-cybersecurity"]}
    expected |= {("risk-aapl-tsla-jpm", f.fact) for f in brief["risk-aapl-tsla-jpm"].required_facts}
    assert sampled == expected
    for case_id in ("risk-unh-cybersecurity", "trend-amzn-aws-two-years"):
        for fact in version_1[case_id].required_facts:
            assert fact.fact not in sheet
            assert all(i["fact"] != fact.fact for i in items)
    assert not any(
        i["case_id"] == "trend-amzn-aws-two-years" and i["kind"] == "fact" for i in items
    )


def _label_some(path, labels):
    """Fill in the given labels on the sheet, as the developer does in an editor."""
    text = path.read_text()
    for item_id, label in labels.items():
        text = re.sub(rf"^(LABEL {item_id} \([^)]*\):).*$", rf"\1 {label}", text, flags=re.M)
    path.write_text(text)


def test_resuming_a_partly_labelled_sheet_keeps_every_existing_label(tmp_path):
    from edgar_eval.judge_study import read_labels

    reports, facts, _ = _synthetic_reports()
    sheet = tmp_path / "sheet.md"
    sample = draw_sample(reports, facts, _sources, seed=2, fact_items=10, claim_items=20)
    write_sheet(sample, sheet)
    facts_drawn = [i.id for i in sample.items if i.kind == "fact"]
    claims_drawn = [i.id for i in sample.items if i.kind == "claim"]
    entered = {
        facts_drawn[0]: "stated",
        facts_drawn[3]: "Not  Stated",
        claims_drawn[0]: "contradicted",
        claims_drawn[5]: "unsupported",
    }
    _label_some(sheet, entered)

    # Drawn again from the same seed and reports, twice: the labels stay where they were.
    again = draw_sample(reports, facts, _sources, seed=2, fact_items=10, claim_items=20)
    assert write_sheet(again, sheet) == 4
    assert write_sheet(again, sheet) == 4

    labels = read_labels(sheet)
    assert {i: labels[i] for i in entered} == {
        facts_drawn[0]: "stated",
        facts_drawn[3]: "not stated",
        claims_drawn[0]: "contradicted",
        claims_drawn[5]: "unsupported",
    }
    assert sum(label is not None for label in labels.values()) == 4


def test_a_rerun_that_would_drop_a_labelled_item_refuses_and_leaves_the_sheet(tmp_path):
    reports, facts, _ = _synthetic_reports()
    sheet = tmp_path / "sheet.md"
    sample = draw_sample(reports, facts, _sources, seed=2, fact_items=10, claim_items=20)
    write_sheet(sample, sheet)
    other = draw_sample(reports, facts, _sources, seed=99, fact_items=10, claim_items=20)
    others = {i.id for i in other.items}
    dropped = next(i for i in sample.items if i.kind == "fact" and i.id not in others)
    _label_some(sheet, {dropped.id: "stated"})
    before = sheet.read_text()

    try:
        write_sheet(other, sheet)
    except ValueError as error:
        assert dropped.id in str(error)
    else:
        raise AssertionError("the rerun overwrote a label")
    assert sheet.read_text() == before
    # The command says so and fails, writing nothing.
    v2 = _v2_file(tmp_path, {})
    assert _sample_command(tmp_path, reports, v2, "--seed", "99") == 1
    assert sheet.read_text() == before


def test_a_label_that_is_not_one_is_refused_rather_than_lost(tmp_path):
    from edgar_eval.judge_study import read_labels

    reports, facts, _ = _synthetic_reports()
    sheet = tmp_path / "sheet.md"
    sample = draw_sample(reports, facts, _sources, seed=2, fact_items=4, claim_items=4)
    write_sheet(sample, sheet)
    fact = next(i for i in sample.items if i.kind == "fact")
    _label_some(sheet, {fact.id: "supported"})  # a claim's label on a fact item
    try:
        read_labels(sheet)
    except ValueError as error:
        assert fact.id in str(error)
    else:
        raise AssertionError("a wrong label was read")


def test_the_sample_command_calls_no_provider_and_rebuilds_sources_offline(
    index, tmp_path, monkeypatch
):
    """The command draws through the real Source rebuild, with every provider's SDK
    unimportable and its key removed before any Source is rebuilt."""
    from edgar_eval.arms import ARMS
    from edgar_eval.retrieval import conversation
    from edgar_rag.golden_set import load_golden_set

    for module in ("openai", "anthropic", "typesafe_sdk"):
        monkeypatch.setitem(sys.modules, module, None)
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JEV_API_KEY"):
        monkeypatch.setenv(key, "placeholder")

    case = next(c for c in load_golden_set().cases if c.id == "risk-aapl-tsla-jpm")
    shipped = next(a for a in ARMS if a.shipped)
    given = shipped.prepare(conversation(case), index).sources
    answer = "Apple relies on outsourcing partners. [S1]\n\nTesla depends on Elon Musk. [S2]"
    saved = _saved_case(case.id, "gpt-6-luna", answer) | {"sources": len(given)}
    reports = [
        ("generation-dev.json", _report("gpt-6-luna", [saved])),
        # The dense Arm needs embeddings this index has none of, so its Sources are not rebuilt.
        ("generation-arms-dev-dense.json", _report("gpt-6-luna", [saved]) | {"arm": "dense"}),
    ]
    v2 = _v2_file(tmp_path, {})
    assert _sample_command(tmp_path, reports, v2, "--index", str(index), sources=None) == 0

    sample = json.loads((tmp_path / "sample.json").read_text())
    claims = [i for i in sample["items"] if i["kind"] == "claim"]
    cited = {c["claim"]: [(s["tag"], s["text"]) for s in c["sources"]] for c in claims}
    assert cited == {
        "Apple relies on outsourcing partners.": [("S1", given[0].text)],
        "Tesla depends on Elon Musk.": [("S2", given[1].text)],
    }
    assert sample["skipped"]["answers whose Sources cannot be rebuilt"] == 1
    assert any(i["kind"] == "fact" for i in sample["items"])
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JEV_API_KEY"):
        assert key not in os.environ


def test_a_source_cited_by_several_claim_items_is_shown_in_full_once(tmp_path):
    answer = "Apple sells phones. [S1]\n\nApple sells watches. [S1]\n\nApple sells laptops. [S1]"
    case = _saved_case("case-0", "gpt-6-luna", answer)
    sample = draw_sample(
        [("r.json", _report("gpt-6-luna", [case]))], {}, _sources, fact_items=0, claim_items=3
    )
    write_sheet(sample, tmp_path / "sheet.md")
    sheet = (tmp_path / "sheet.md").read_text()

    assert sheet.count("> Text 1.") == 1
    assert sheet.count("> Source 1 of case-0") == 3  # every item still names its Source
    assert sheet.count("its text is under claim item 1 above") == 2
