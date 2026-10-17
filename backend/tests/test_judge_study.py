"""The judge study's sample: items drawn from saved generation reports, and the blind
labelling sheet the developer fills in (ADR 0013)."""

import io
import json
import os
import re
import sys

from edgar_eval.judge import Evidence
from edgar_eval.judge_study import draw_sample, write_sheet
from edgar_rag.golden_set import GOLDEN_SET_V1, RequiredFact

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
    from edgar_rag.golden_set import GOLDEN_SET_V1, SPLIT_RULE_V2

    version_1 = json.loads(GOLDEN_SET_V1.read_text(encoding="utf-8"))["cases"]
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

    version_1 = {c.id: c for c in load_golden_set(GOLDEN_SET_V1).cases}
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


def test_the_labels_are_committed_and_the_verdicts_and_score_are_derived():
    import subprocess

    from edgar_eval.judge_study import (
        DEFAULT_SAMPLE,
        DEFAULT_SCORE,
        DEFAULT_SHEET,
        DEFAULT_VERDICTS,
    )
    from edgar_rag.paths import DATA_DIR, DERIVED_DIR, REPO_ROOT

    assert DEFAULT_SHEET.parent == DEFAULT_SAMPLE.parent == DATA_DIR / "eval" / "judge_study"
    assert DEFAULT_VERDICTS.parent == DEFAULT_SCORE.parent == DERIVED_DIR / "judge_study"
    assert (DEFAULT_SHEET.parent / "README.md").is_file()

    def ignored(path):
        check = ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", str(path)]
        return subprocess.run(check, check=False).returncode == 0

    assert not ignored(DEFAULT_SHEET) and not ignored(DEFAULT_SAMPLE)
    assert ignored(DEFAULT_VERDICTS) and ignored(DEFAULT_SCORE)


def test_the_sample_command_resumes_and_refuses_at_its_default_paths(tmp_path, monkeypatch):
    """With no `--sheet` or `--sample`, the command writes both to the labels directory,
    creating it, keeps the labels on a rerun and refuses one that would drop them."""
    from edgar_eval import judge_study

    labels_dir = tmp_path / "data" / "eval" / "judge_study"
    monkeypatch.setattr(judge_study, "DEFAULT_SHEET", labels_dir / "sheet.md")
    monkeypatch.setattr(judge_study, "DEFAULT_SAMPLE", labels_dir / "sample.json")
    reports, _, _ = _synthetic_reports()
    paths = []
    for name, data in reports:
        (tmp_path / name).write_text(json.dumps(data))
        paths.append(str(tmp_path / name))
    v2 = _v2_file(tmp_path, {})

    def run(seed):
        argv = ["sample", "--reports", *paths, "--golden-set-v2", str(v2), "--seed", str(seed)]
        return judge_study.main(argv, sources=_sources, out=io.StringIO(), err=io.StringIO())

    assert run(2) == 0
    sheet = labels_dir / "sheet.md"
    assert (labels_dir / "sample.json").is_file()
    drawn = [i["id"] for i in json.loads((labels_dir / "sample.json").read_text())["items"]]
    _label_some(sheet, dict.fromkeys(drawn, "supported"))

    assert run(2) == 0
    assert set(judge_study.read_labels(sheet).values()) == {"supported"}
    before = sheet.read_text()
    assert run(99) == 1  # another draw would drop labelled items
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

    case = next(c for c in load_golden_set(GOLDEN_SET_V1).cases if c.id == "risk-aapl-tsla-jpm")
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


# --- Judging and scoring --------------------------------------------------------------------


def _fact_item(n, model):
    from edgar_eval.judge_study import StudyItem

    return StudyItem(
        id=f"F-{n:010x}", kind="fact", case_id=f"case-{n}", model=model, answer="An answer."
    )


def _claim_item(n, model):
    from edgar_eval.judge_study import StudyItem

    return StudyItem(
        id=f"C-{n:010x}",
        kind="claim",
        case_id=f"case-{n}",
        model=model,
        answer=f"Claim {n}. [S1]",
        claim=f"Claim {n}.",
        sources=(Evidence("S1", "Source 1", "Text 1."),),
    )


def _study(facts, claims):
    """A sample, its labels and Jev's two runs, from rows of (model, label, run 1, run 2):
    a fact's runs are probabilities, a claim's verdicts; None is a failed judgment."""
    from edgar_eval.judge import JEV_MODEL
    from edgar_eval.judge_study import JudgeRun, Sample, Verdict

    items, labels, verdicts = [], {}, ([], [])
    for n, (model, label, *runs) in enumerate(facts, 1):
        item = _fact_item(n, model)
        items.append(item)
        labels[item.id] = label
        for run, p in zip(verdicts, runs, strict=True):
            run.append(
                Verdict.of_fact(item.id, p) if p is not None else Verdict.failed(item.id, "x")
            )
    for n, (model, label, *runs) in enumerate(claims, 1):
        item = _claim_item(n, model)
        items.append(item)
        labels[item.id] = label
        for run, v in zip(verdicts, runs, strict=True):
            run.append(
                Verdict(item.id, v, probabilities={v: 1.0}) if v else Verdict.failed(item.id, "x")
            )
    sample = Sample(seed=1, reports=(), items=tuple(items), skipped={})
    runs = tuple(
        JudgeRun(judge=JEV_MODEL, run=r, verdicts={v.item_id: v for v in vs})
        for r, vs in enumerate(verdicts, 1)
    )
    return sample, labels, runs


GPT, HAIKU = "gpt-6-luna", "claude-haiku-5-5"

# Ten fact items: (model, label, Jev run 1, Jev run 2). At the 0.5 cut-off run 1 states
# F1, F2, F5, F7 and F10; the labels state F1, F2, F3, F7 and F8.
FACTS = [
    (GPT, "stated", 0.9, 0.9),
    (GPT, "stated", 0.6, 0.4),  # flips between the runs
    (GPT, "stated", 0.3, 0.3),
    (GPT, "not stated", 0.2, 0.2),
    (GPT, "not stated", 0.55, 0.55),
    (GPT, "not stated", 0.05, None),  # run 2 failed on it
    (HAIKU, "stated", 0.95, 0.95),
    (HAIKU, "stated", 0.45, 0.45),
    (HAIKU, "not stated", 0.1, 0.2),
    (HAIKU, "not stated", 0.7, 0.7),
]
# Ten claim items: (model, label, Jev run 1, Jev run 2).
CLAIMS = [
    (GPT, "supported", "supported", "supported"),
    (GPT, "supported", "supported", "supported"),
    (GPT, "supported", "unsupported", "supported"),  # flips
    (GPT, "unsupported", "supported", "supported"),
    (GPT, "unsupported", "unsupported", "contradicted"),  # flips
    (GPT, "contradicted", "contradicted", "contradicted"),
    (HAIKU, "supported", "supported", "supported"),
    (HAIKU, "unsupported", "supported", "supported"),
    (HAIKU, "contradicted", "supported", "supported"),
    (HAIKU, "unsupported", "unsupported", "unsupported"),
]


def test_the_score_reports_agreement_with_the_labels_against_hand_computed_values(monkeypatch):
    from pytest import approx

    from edgar_eval import judge_study
    from edgar_eval.judge_study import score

    # The values below are computed by hand at a fact cut-off of 0.5, whatever the
    # study has set `FACT_CUTOFF` to.
    monkeypatch.setattr(judge_study, "FACT_CUTOFF", 0.5)
    sample, labels, runs = _study(FACTS, CLAIMS)
    report = score(sample, labels, runs)
    first = report.judges[0]

    # Facts at 0.5: 6 of 10 agree; both sides state 5 of 10, so chance agreement is 0.5
    # and kappa (0.6 - 0.5) / (1 - 0.5) = 0.2.
    assert (first.facts.items, first.facts.accuracy, first.facts.kappa) == (10, 0.6, approx(0.2))
    # Claims: 6 of 10 agree. The labels split 4/4/2 (supported, unsupported,
    # contradicted), Jev 6/3/1: chance agreement 0.24 + 0.12 + 0.02 = 0.38, and kappa
    # 0.22 / 0.62.
    assert (first.claims.items, first.claims.accuracy) == (10, 0.6)
    assert first.claims.kappa == approx(0.22 / 0.62)
    # Of 6 bad claims, Jev calls C4, C8 and C9 supported: 3 of 6, Wilson 95% interval
    # 0.1876 to 0.8124.
    bad = first.false_supported
    assert (bad.count, bad.of, bad.share) == (3, 6, 0.5)
    assert (bad.low, bad.high) == (approx(0.1876, abs=1e-4), approx(0.8124, abs=1e-4))
    # Errors by generator: gpt-6-luna misses F3 and F5 of 6 facts and C3 and C4 of 6
    # claims; claude-haiku-5-5 misses F8 and F10 of 4 and C8 and C9 of 4. With the same
    # pattern, Fisher's exact test finds no difference (p = 1).
    by = {(g.model, g.kind): g for g in first.by_generator}
    assert (by[GPT, "fact"].items, by[GPT, "fact"].errors) == (6, 2)
    assert (by[GPT, "claim"].items, by[GPT, "claim"].errors) == (6, 2)
    assert (by[HAIKU, "fact"].items, by[HAIKU, "fact"].errors) == (4, 2)
    assert (by[HAIKU, "claim"].items, by[HAIKU, "claim"].errors) == (4, 2)
    assert by[GPT, "fact"].p_value == approx(1.0)
    assert not first.generator_differs

    # Run 2 failed on F6: it is judged on 9 facts and counts the failure.
    assert (report.judges[1].facts.items, report.judges[1].failed) == (9, 1)
    # Run to run: F2 flips of the 9 facts both runs judged; C3 and C5 flip of 10 claims.
    agreement = report.run_agreement
    assert (agreement.facts.agree, agreement.facts.of) == (8, 9)
    assert (agreement.claims.agree, agreement.claims.of) == (8, 10)


def test_the_cut_off_sweep_and_averaged_probabilities_against_hand_computed_values():
    from pytest import approx

    from edgar_eval.judge_study import CUTOFFS, FACT_CUTOFF, score

    sample, labels, runs = _study(FACTS, CLAIMS)
    first = score(sample, labels, runs).judges[0]

    assert CUTOFFS == (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
    sweep = {c.cutoff: c for c in first.cutoffs}
    # At 0.1 every fact but F6 counts as stated: 6 of 10 agree, kappa 0.2.
    assert (sweep[0.1].accuracy, sweep[0.1].kappa) == (0.6, approx(0.2))
    # At 0.3 (F3's 0.3 counts as stated) 8 of 10 agree, Jev states 7: kappa 0.6.
    assert (sweep[0.3].accuracy, sweep[0.3].kappa) == (0.8, approx(0.6))
    # The score's own fact agreement is the sweep's at the fact cut-off.
    assert sweep[FACT_CUTOFF].accuracy == first.facts.accuracy
    # At 0.9 only F1 and F7 count: 7 of 10 agree, kappa 0.4.
    assert (sweep[0.9].accuracy, sweep[0.9].kappa) == (0.7, approx(0.4))
    # Averaged, each fact counts as its probability of a stated fact: agreement is p for
    # a stated label and 1 - p otherwise, (3.2 + 3.4) / 10.
    assert first.averaged == approx(0.66)


def _bad_claims(called_supported, bad, good=0, model=GPT):
    """Claim rows: `bad` labelled unsupported, `called_supported` of them judged
    supported, and `good` labelled and judged supported."""
    rows = [
        (model, "unsupported", v, v)
        for v in ["supported"] * called_supported + ["unsupported"] * (bad - called_supported)
    ]
    return rows + [(model, "supported", "supported", "supported")] * good


def test_the_revisit_trigger_fires_just_above_one_in_five_and_not_at_exactly_one_in_five():
    from edgar_eval.judge_study import score

    facts = [(GPT, "stated", 0.9, 0.9)]
    at = score(*_study(facts, _bad_claims(5, 25)))
    assert at.judges[0].false_supported.share == 0.2
    assert not at.revisit.fired and not at.revisit.false_supported_above

    above = score(*_study(facts, _bad_claims(6, 29)))  # 0.207
    assert above.revisit.fired and above.revisit.false_supported_above
    assert not above.revisit.generator_differs


def test_the_revisit_trigger_fires_when_the_error_differs_by_generator():
    from edgar_eval.judge_study import score

    facts = [(GPT, "stated", 0.9, 0.9)]
    # Jev errs on every gpt-6-luna claim and on no claude-haiku-5-5 claim: 2 / C(20, 10).
    claims = [(GPT, "supported", "unsupported", "unsupported")] * 10
    claims += [(HAIKU, "supported", "supported", "supported")] * 10
    report = score(*_study(facts, claims))
    assert not report.revisit.false_supported_above  # no bad claim at all
    p = {(g.model, g.kind): g.p_value for g in report.judges[0].by_generator}
    assert p[GPT, "claim"] < 1e-4
    assert report.revisit.generator_differs and report.revisit.fired


def _unlabel(labels, sample, kind, keep):
    """Labels with all but the first `keep` items of a kind left blank."""
    items = [i.id for i in sample.items if i.kind == kind]
    return {**labels, **{i: None for i in items[keep:]}}


def test_the_stopping_rule_is_met_once_every_fact_and_100_claims_are_labelled_and_decided():
    from edgar_eval.judge_study import score

    facts = [(GPT, "stated", 0.9, 0.9), (GPT, "not stated", 0.1, 0.1)]
    # Of the first 100 claims, 40 bad and 2 of them called supported: the 95% interval,
    # 0.014 to 0.165, lies wholly below one in five. 50 more claims stay unlabelled.
    claims = _bad_claims(2, 40, good=60) + _bad_claims(0, 0, good=50)
    sample, labels, runs = _study(facts, claims)
    report = score(sample, _unlabel(labels, sample, "claim", 100), runs)
    assert report.stopping.met and report.stopping.decided == "below"
    assert (report.stopping.claims_labelled, report.stopping.claims) == (100, 150)
    assert not report.partial
    assert report.judges[0].claims.items == 100

    # 20 of 40 called supported: 0.35 to 0.65, wholly above.
    sample, labels, runs = _study(facts, _bad_claims(20, 40, good=60) + _bad_claims(0, 0, good=5))
    report = score(sample, _unlabel(labels, sample, "claim", 100), runs)
    assert report.stopping.met and report.stopping.decided == "above"


def test_the_stopping_rule_is_not_met_short_of_100_claims_an_unlabelled_fact_or_an_open_interval():
    from edgar_eval.judge_study import Unlabelled, score

    facts = [(GPT, "stated", 0.9, 0.9), (GPT, "not stated", 0.1, 0.1)]
    decided = _bad_claims(2, 40, good=60) + _bad_claims(0, 0, good=50)
    sample, labels, runs = _study(facts, decided)
    short = score(sample, _unlabel(labels, sample, "claim", 99), runs, partial=True)
    assert not short.stopping.met and short.stopping.decided == "below"
    assert short.partial
    fact_left = _unlabel(_unlabel(labels, sample, "claim", 100), sample, "fact", 1)
    assert not score(sample, fact_left, runs, partial=True).stopping.met

    # 8 of 40 called supported: 0.105 to 0.348 holds one in five, so all 200 are labelled.
    open_sample, open_labels, open_runs = _study(
        facts, _bad_claims(8, 40, good=60) + _bad_claims(0, 0, good=5)
    )
    open_labels = _unlabel(open_labels, open_sample, "claim", 100)
    open_ = score(open_sample, open_labels, open_runs, partial=True)
    assert not open_.stopping.met and open_.stopping.decided is None

    # Without a partial report, each of them is refused.
    for refused in (
        (sample, _unlabel(labels, sample, "claim", 99), runs),
        (sample, fact_left, runs),
        (open_sample, open_labels, open_runs),
    ):
        try:
            score(*refused)
        except Unlabelled as error:
            assert "unlabelled" in str(error)
        else:
            raise AssertionError("scored with items unlabelled")


class FakeJevClient:
    """Jev's client, answering from tables: a fact's probability, a claim's verdict. A
    request asking about anything in `fail_on` fails, as a long input does."""

    def __init__(self, nouls=None, choices=None, fail_on=(), before_first=None):
        from edgar_eval.judge import JEV_MODEL

        self.requests = []
        self.nouls, self.choices, self.fail_on = nouls or {}, choices or {}, set(fail_on)
        self.model = JEV_MODEL
        self.before_first = before_first

    def system_one(self, state, questions, *, model=None, extra_headers=None):
        from types import SimpleNamespace

        if not self.requests and self.before_first:
            self.before_first()
        self.requests.append(questions)
        asked = {
            q.instructions.get("required_fact") or q.instructions["claim"]
            for q in questions.values()
        }
        if asked & self.fail_on:
            raise RuntimeError("max_tokens_exceeded")
        nouls, choices = {}, {}
        for qid, q in questions.items():
            if "required_fact" in q.instructions:
                nouls[qid] = SimpleNamespace(
                    noul=self.nouls.get(q.instructions["required_fact"], 0.9)
                )
            else:
                verdict = self.choices.get(q.instructions["claim"], "supported")
                choices[qid] = SimpleNamespace(choice=verdict, probabilities={verdict: 0.8})
        return SimpleNamespace(
            model=self.model,
            usage=SimpleNamespace(input_tokens=1_000),
            nouls=nouls,
            choices=choices,
        )


def _judge_command(
    tmp_path, *extra, jev=None, reference=None, splitter=None, sample=None, out=None
):
    """Draw a small sample, write its sheet, and run `judge` on it."""
    from edgar_eval.judge_study import main

    if sample is None:
        reports, facts, _ = _synthetic_reports(cases=2, sentences=3)
        sample = draw_sample(reports, facts, _sources, seed=4, fact_items=4, claim_items=6)
    write_sheet(sample, tmp_path / "sheet.md")
    (tmp_path / "sample.json").write_text(json.dumps(sample.to_dict()))
    argv = ["judge", "--sample", str(tmp_path / "sample.json")]
    argv += ["--verdicts", str(tmp_path / "verdicts.json")]
    code = main(
        [*argv, *extra], jev=jev, reference=reference, splitter=splitter, out=out or io.StringIO()
    )
    return code, sample


def test_jev_judges_every_item_twice_and_a_failure_is_recorded_against_its_item(tmp_path):
    from edgar_eval.judge import JEV_MODEL, JevJudge
    from edgar_eval.judge_study import JudgeRun

    reports, facts, _ = _synthetic_reports(cases=2, sentences=3)
    sample = draw_sample(reports, facts, _sources, seed=4, fact_items=4, claim_items=6)
    failing = next(i for i in sample.items if i.kind == "claim")
    stated = next(i for i in sample.items if i.kind == "fact")
    client = FakeJevClient(nouls={stated.fact: 0.2}, choices={}, fail_on={failing.claim})
    sheet_before = None

    code, _ = _judge_command(tmp_path, jev=JevJudge(client=client), sample=sample)
    assert code == 0
    sheet_before = (tmp_path / "sheet.md").read_text()
    saved = json.loads((tmp_path / "verdicts.json").read_text())
    runs = [JudgeRun.from_dict(r) for r in saved["runs"]]

    assert [(r.judge, r.run) for r in runs] == [(JEV_MODEL, 1), (JEV_MODEL, 2)]
    # The failed request judged every claim citing the same Sources in that answer.
    same_request = {
        i.id
        for i in sample.items
        if i.kind == "claim" and i.answer == failing.answer and i.sources == failing.sources
    }
    for run in runs:
        assert set(run.verdicts) == {i.id for i in sample.items}  # none dropped
        for item_id in same_request:
            failed = run.verdicts[item_id]
            assert failed.verdict is None and "max_tokens_exceeded" in failed.error
        assert run.verdicts[stated.id].probability == 0.2
        assert run.verdicts[stated.id].verdict == "not stated"
        others = [v for i, v in run.verdicts.items() if i not in same_request]
        assert others and all(v.verdict is not None and v.error is None for v in others)
    # Each answer is asked once per run, its facts and claims together.
    assert len(client.requests) >= 2
    # The verdicts are kept apart from the sheet, which stays blind.
    assert (tmp_path / "sheet.md").read_text() == sheet_before
    assert "0.2" not in sheet_before and "supported\n" not in sheet_before


def test_the_cost_estimate_is_printed_before_any_judge_is_called(tmp_path):
    from edgar_eval.judge import JevJudge

    out = io.StringIO()
    seen = []
    client = FakeJevClient(before_first=lambda: seen.append(out.getvalue()))
    _judge_command(tmp_path, jev=JevJudge(client=client), out=out)
    assert seen and "Estimated cost" in seen[0] and "$" in seen[0]
    assert "claude-haiku-5-5" not in seen[0]  # no reference asked for


class FakeAnthropic:
    """Anthropic's client: a JSON verdict for each request, or a refusal for an item
    whose text holds `refuse`."""

    def __init__(self, refuse=None):
        self.requests = []
        self.refuse = refuse
        self.messages = self

    def create(self, **request):
        from types import SimpleNamespace

        self.requests.append(request)
        prompt = request["messages"][0]["content"]
        schema = request["output_config"]["format"]["schema"]
        body = {"stated": False} if "stated" in schema["properties"] else {"verdict": "unsupported"}
        refused = self.refuse is not None and self.refuse in prompt
        return SimpleNamespace(
            model=request["model"],
            stop_reason="refusal" if refused else "end_turn",
            content=[] if refused else [SimpleNamespace(type="text", text=json.dumps(body))],
            usage=SimpleNamespace(input_tokens=500, output_tokens=50),
        )


def test_the_reference_judge_runs_once_pinned_and_records_its_failures(tmp_path, monkeypatch):
    from edgar_eval.judge import JevJudge
    from edgar_eval.judge_study import REFERENCE_MODEL, JudgeRun, ReferenceJudge, score

    # No provider's SDK can be imported: every client is a fake. (Jev's question types
    # come from its SDK, which the fake client answers without any request.)
    for module in ("openai", "anthropic"):
        monkeypatch.setitem(sys.modules, module, None)
    reports, facts, _ = _synthetic_reports(cases=2, sentences=3)
    sample = draw_sample(reports, facts, _sources, seed=4, fact_items=4, claim_items=6)
    refused = next(i for i in sample.items if i.kind == "claim")
    anthropic = FakeAnthropic(refuse=f"<claim>\n{refused.claim}\n</claim>")
    # Every item asking about that claim, whichever generator's answer it is from.
    refusals = {i.id for i in sample.items if i.kind == "claim" and i.claim == refused.claim}
    out = io.StringIO()

    code, _ = _judge_command(
        tmp_path,
        "--reference",
        jev=JevJudge(client=FakeJevClient()),
        reference=ReferenceJudge(client=anthropic),
        sample=sample,
        out=out,
    )
    assert code == 0
    assert REFERENCE_MODEL == "claude-haiku-5-5"
    assert f"{REFERENCE_MODEL} once" in out.getvalue()
    assert len(anthropic.requests) == len(sample.items)  # one request an item, once
    assert {r["model"] for r in anthropic.requests} == {REFERENCE_MODEL}
    runs = [
        JudgeRun.from_dict(r) for r in json.loads((tmp_path / "verdicts.json").read_text())["runs"]
    ]
    assert [r.judge for r in runs] == ["jev-1.13.0", "jev-1.13.0", REFERENCE_MODEL]
    reference = runs[2].verdicts
    for item_id in refusals:
        assert reference[item_id].verdict is None and "refusal" in reference[item_id].error
    assert all(
        v.verdict == ("not stated" if i.startswith("F-") else "unsupported")
        for i, v in reference.items()
        if i not in refusals
    )

    # The score reports it beside Jev's runs, without a cut-off sweep.
    labels = {i.id: "stated" if i.kind == "fact" else "supported" for i in sample.items}
    report = score(sample, labels, runs)
    haiku = report.judges[2]
    assert haiku.judge == REFERENCE_MODEL and haiku.failed == len(refusals)
    assert haiku.facts.accuracy == 0.0 and haiku.cutoffs == () and haiku.averaged is None


def test_the_score_command_refuses_unlabelled_items_unless_a_partial_report_is_asked_for(
    tmp_path,
):
    from edgar_eval.judge import JevJudge
    from edgar_eval.judge_study import main

    code, sample = _judge_command(tmp_path, jev=JevJudge(client=FakeJevClient()))
    fact = next(i for i in sample.items if i.kind == "fact")
    _label_some(tmp_path / "sheet.md", {fact.id: "stated"})
    argv = [
        "score",
        "--sheet",
        str(tmp_path / "sheet.md"),
        "--sample",
        str(tmp_path / "sample.json"),
    ]
    argv += ["--verdicts", str(tmp_path / "verdicts.json"), "--json", str(tmp_path / "score.json")]

    err = io.StringIO()
    assert main(argv, out=io.StringIO(), err=err) == 1
    assert "unlabelled" in err.getvalue()
    assert not (tmp_path / "score.json").exists()

    out = io.StringIO()
    assert main([*argv, "--partial"], out=out) == 0
    saved = json.loads((tmp_path / "score.json").read_text())
    assert saved["partial"] and saved["judges"][0]["facts"]["items"] == 1
    assert "partial" in out.getvalue().lower()


# --- The trial LLM claim split ----------------------------------------------------------------


class FakeSplitter:
    """Anthropic's client for the LLM claim split: it splits each numbered sentence of
    the prompt in two, the first statement giving no tags, the second only a tag the
    answer never cites, so the split's own citations are what the claims keep."""

    def __init__(self):
        self.requests = []
        self.messages = self

    def create(self, **request):
        from types import SimpleNamespace

        self.requests.append(request)
        prompt = request["messages"][0]["content"]
        statements = []
        for n, text in re.findall(r'<sentence n="(\d+)"[^>]*>(.*?)</sentence>', prompt):
            statements.append({"sentence": int(n), "claim": f"{text} (first)", "tags": []})
            statements.append({"sentence": int(n), "claim": f"{text} (second)", "tags": ["S9"]})
        return SimpleNamespace(
            model=request["model"],
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps({"statements": statements}))],
            usage=SimpleNamespace(input_tokens=800, output_tokens=300),
        )


def _split_runs(tmp_path):
    saved = json.loads((tmp_path / "verdicts.json").read_text())
    return saved["llm_split"]


def test_the_llm_split_is_cached_per_answer_reused_and_keeps_its_citations(tmp_path):
    from edgar_eval.judge import JevJudge
    from edgar_eval.judge_study import SPLIT_MODEL, LLMSplitter

    reports, facts, _ = _synthetic_reports(cases=2, sentences=3)
    sample = draw_sample(reports, facts, _sources, seed=4, fact_items=4, claim_items=6)
    claim_items = [i for i in sample.items if i.kind == "claim"]
    answers = {i.answer for i in claim_items}
    cache = tmp_path / "split-cache"

    client = FakeSplitter()
    out = io.StringIO()
    code, _ = _judge_command(
        tmp_path,
        "--llm-split",
        "--split-cache",
        str(cache),
        jev=JevJudge(client=FakeJevClient()),
        splitter=LLMSplitter(client=client, cache_dir=cache),
        sample=sample,
        out=out,
    )
    assert code == 0
    assert SPLIT_MODEL == "claude-haiku-5-5"
    assert {r["model"] for r in client.requests} == {SPLIT_MODEL}
    assert len(client.requests) == len(answers)  # one request an answer
    assert f"{SPLIT_MODEL} claim split" in out.getvalue()

    split = _split_runs(tmp_path)
    assert split["model"] == SPLIT_MODEL
    by_item = {i["item_id"]: i for i in split["items"]}
    assert set(by_item) == {i.id for i in claim_items}
    for item in claim_items:
        claims = by_item[item.id]["claims"]
        assert [c["claim"] for c in claims] == [f"{item.claim} (first)", f"{item.claim} (second)"]
        # Each statement keeps its sentence's citations: none given, or none the
        # sentence cites, is not a citation dropped.
        cited = [s.tag for s in item.sources]
        assert all(c["tags"] == cited for c in claims)
        assert all(c["verdict"] == "supported" and c["error"] is None for c in claims)

    # A rerun reads the cache: no request, the same claims.
    again = FakeSplitter()
    out = io.StringIO()
    code, _ = _judge_command(
        tmp_path,
        "--llm-split",
        "--split-cache",
        str(cache),
        jev=JevJudge(client=FakeJevClient()),
        splitter=LLMSplitter(client=again, cache_dir=cache),
        sample=sample,
        out=out,
    )
    assert code == 0 and again.requests == []
    rerun = _split_runs(tmp_path)
    assert rerun["items"] == split["items"]
    assert (rerun["requests"], rerun["cached"]) == (0, len(answers))
    assert f"of {len(answers)} answers ({len(answers)} cached)" in out.getvalue()


def test_a_statement_keeps_the_citations_it_names_of_its_sentence_and_its_context(tmp_path):
    from types import SimpleNamespace

    from edgar_eval.judge_study import LLMSplitter

    answer = "## Apple\n\nRevenue rose and margins fell. [S1, S2]\n\nNo tag here."
    reply = {
        "statements": [
            {"sentence": 0, "claim": "Apple's revenue rose.", "tags": ["S1"]},
            {"sentence": 0, "claim": "Apple's margins fell.", "tags": ["S2", "S7"]},
            {"sentence": 1, "claim": "Not a cited sentence.", "tags": []},
        ]
    }

    class Client:
        requests = []

        class messages:  # noqa: N801 - the SDK's attribute
            @staticmethod
            def create(**request):
                Client.requests.append(request)
                return SimpleNamespace(
                    stop_reason="end_turn",
                    content=[SimpleNamespace(type="text", text=json.dumps(reply))],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                )

    split = LLMSplitter(client=Client, cache_dir=tmp_path).split(answer)
    assert split.error is None
    prompt = Client.requests[0]["messages"][0]["content"]
    assert "No tag here" not in prompt.split("<sentences>")[1]  # uncited: not split
    assert [(n, c.text, c.tags, c.heading) for n, c in split.statements] == [
        (0, "Apple's revenue rose.", ("S1",), "Apple"),
        (0, "Apple's margins fell.", ("S2",), "Apple"),
    ]


# Six answers of two claim items each: the labels, Jev's run 1 verdicts on the sentences,
# and its verdicts on the LLM split's statements of each sentence (None: the split of
# that answer failed).
S, U, X = "supported", "unsupported", "contradicted"
SPLIT_ANSWERS = [
    # labels        sentence split   LLM split
    ((S, U), (S, S), ([S], [S, U])),  # bad: the LLM split catches it, the sentences miss
    ((S, X), (S, X), ([S], [X])),  # bad: both catch it
    ((S, S), (S, S), ([S, U], [S])),  # clean: the LLM split raises a false alarm
    ((S, S), (U, S), ([S], [S, S])),  # clean: the sentences raise a false alarm
    ((U, S), (U, S), None),  # the split failed: left out
    ((S, U), (S, S), ([S], [S, U])),  # bad: the LLM split catches it
]


def _split_study():
    from edgar_eval.judge import JEV_MODEL
    from edgar_eval.judge_study import (
        JudgeRun,
        Sample,
        SplitClaim,
        SplitItem,
        SplitRun,
        StudyItem,
        Verdict,
    )

    items, labels, verdicts, split = [], {}, {}, {}
    for a, (labelled, sentence, llm) in enumerate(SPLIT_ANSWERS):
        answer = f"Answer {a} claim 0. [S1]\n\nAnswer {a} claim 1. [S1]"
        for n in range(2):
            item = StudyItem(
                id=f"C-{a * 2 + n:010x}",
                kind="claim",
                case_id=f"case-{a}",
                model=GPT,
                answer=answer,
                claim=f"Answer {a} claim {n}.",
                sources=(Evidence("S1", "Source 1", "Text 1."),),
            )
            items.append(item)
            labels[item.id] = labelled[n]
            verdicts[item.id] = Verdict(item.id, sentence[n], probabilities={sentence[n]: 1.0})
            split[item.id] = (
                SplitItem(item.id, (), "stop_reason max_tokens")
                if llm is None
                else SplitItem(
                    item.id, tuple(SplitClaim(f"{item.claim} {v}", ("S1",), v) for v in llm[n])
                )
            )
    sample = Sample(seed=1, reports=(), items=tuple(items), skipped={})
    runs = (JudgeRun(judge=JEV_MODEL, run=1, verdicts=verdicts),)
    return sample, labels, runs, SplitRun("claude-haiku-5-5", JEV_MODEL, split)


def test_the_score_compares_the_llm_split_with_the_sentence_split_against_the_labels():
    from edgar_eval.judge_study import print_score, score

    sample, labels, runs, split = _split_study()
    assert score(sample, labels, runs).split is None  # not run, not compared

    compared = score(sample, labels, runs, split=split).split
    # Five answers compared; the one whose split failed is left out and counted.
    assert [a.case_id for a in compared.answers] == [f"case-{n}" for n in (0, 1, 2, 3, 5)]
    assert compared.left_out == 1
    assert [a.better for a in compared.answers] == ["llm", "both", "sentence", "llm", "llm"]
    first = compared.answers[0]
    assert (first.labelled_bad, first.sentence_bad, first.llm_bad) == (True, False, True)
    # Of the 3 answers labelled with a bad claim, the sentence split's verdicts catch 1
    # and the LLM split's 3; of the 2 clean answers each raises 1 false alarm.
    s, llm = compared.sentence, compared.llm
    assert (s.caught, s.bad, s.false_alarms, s.clean, s.agree, s.of) == (1, 3, 1, 2, 2, 5)
    assert (llm.caught, llm.bad, llm.false_alarms, llm.clean, llm.agree, llm.of) == (
        3,
        3,
        1,
        2,
        4,
        5,
    )
    assert (compared.agrees_better, compared.catches_more) == ("llm", "llm")
    # The LLM split alone agrees on 3 answers, the sentence split alone on 1: McNemar's
    # exact test, two-sided, 2 * 5/16.
    assert compared.p_value == 0.625

    out = io.StringIO()
    print_score(score(sample, labels, runs, split=split), out)
    assert "LLM claim split" in out.getvalue() and "3 of 3" in out.getvalue()


def test_the_score_command_reads_the_stored_split_and_ties_when_both_agree_alike(tmp_path):
    from dataclasses import replace

    from edgar_eval.judge_study import load_split, main, save_verdicts

    sample, labels, runs, split = _split_study()
    # Only case-1, whose bad claim both splits catch.
    keep = {i.id for i in sample.items if i.case_id == "case-1"}
    sample = replace(sample, items=tuple(i for i in sample.items if i.id in keep))
    runs = tuple(
        replace(r, verdicts={k: v for k, v in r.verdicts.items() if k in keep}) for r in runs
    )
    split = replace(split, items={k: v for k, v in split.items.items() if k in keep})
    save_verdicts(runs, sample, tmp_path / "verdicts.json", split)
    assert load_split(tmp_path / "verdicts.json") == split
    write_sheet(sample, tmp_path / "sheet.md")
    _label_some(tmp_path / "sheet.md", {k: labels[k] for k in keep})
    (tmp_path / "sample.json").write_text(json.dumps(sample.to_dict()))
    argv = ["score", "--sheet", str(tmp_path / "sheet.md"), "--sample"]
    argv += [str(tmp_path / "sample.json"), "--verdicts", str(tmp_path / "verdicts.json")]
    argv += ["--json", str(tmp_path / "score.json")]

    assert main(argv, out=io.StringIO()) == 0
    saved = json.loads((tmp_path / "score.json").read_text())["split"]
    assert (saved["agrees_better"], saved["catches_more"]) == ("tie", "tie")
    assert saved["answers"][0]["better"] == "both"


def test_the_llm_split_lives_in_the_study_only_and_the_harness_still_splits_by_sentence():
    import inspect

    import edgar_eval.answer_checks as answer_checks
    import edgar_eval.brief_suite as brief_suite
    import edgar_eval.generation as generation
    from edgar_eval.answer_checks import claims

    for module in (generation, brief_suite, answer_checks):
        source = inspect.getsource(module)
        assert "judge_study" not in source and "LLMSplitter" not in source
    # The harness's claims are still the answer's sentences.
    answer = "## Apple\n\nRevenue rose and margins fell. [S1, S2] Costs grew. [S1]"
    assert [(c.text, c.tags) for c in claims(answer)] == [
        ("Revenue rose and margins fell.", ("S1", "S2")),
        ("Costs grew.", ("S1",)),
    ]
