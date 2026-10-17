"""Tests for both Golden Set versions and the Brief Suite: their schema, the splits, the
starter prompts, and every file's labels against the Corpus.

The labels were drafted and reviewed by an agent, not a second human, so these tests are
the mechanical half of the review: every expected Filing and Section exists in the
Corpus, and every Required Fact's evidence quote is found word for word in its Section.
Version 2 adds: no question repeated across the three files, version 2's and the Brief
Suite's figure facts against the SEC company-facts reference (skipped without its
cache), the Brief Suite's variants of the brief's questions, version 2's frozen split
(recomputed from the digests of its 53 new cases), and its mix of question kinds,
reported against ADR 0012's table but not adjusted to it, since the hash decides the
holdout's.
"""

import csv
import hashlib
import json
import re

import pytest

from edgar_rag.corpus import load_corpus, load_sector_table
from edgar_rag.golden_set import (
    COVERAGE_GAP_KINDS,
    DEFAULT_BRIEF_SUITE,
    DEFAULT_GOLDEN_SET,
    GOLDEN_SET_V1,
    GOLDEN_SET_V2,
    QUESTION_TYPES,
    SPLIT_RULE,
    SPLIT_RULE_V2,
    TIERS,
    assign_splits,
    load_brief_suite,
    load_golden_set,
    normalise_whitespace,
    starter_cases,
)
from edgar_rag.paths import DATA_DIR
from edgar_rag.sec_reference import DEFAULT_CACHE_DIR as SEC_CACHE_DIR
from edgar_rag.sec_reference import load_company_facts

BRIEF_QUESTIONS = {
    "What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?",
    "How has NVIDIA's revenue and growth outlook changed over the last two years?",
    "What regulatory risks do the major pharmaceutical companies face, and how are they "
    "addressing them?",
}


@pytest.fixture(scope="module")
def golden_set():
    return load_golden_set(GOLDEN_SET_V1)


@pytest.fixture(scope="module")
def golden_set_v2():
    return load_golden_set(GOLDEN_SET_V2)


@pytest.fixture(scope="module")
def brief_suite():
    return load_brief_suite()


@pytest.fixture(scope="module")
def labelled_cases(golden_set, golden_set_v2, brief_suite):
    """Every labelled case: both Golden Set versions' and the Brief Suite's."""
    return (*golden_set.cases, *golden_set_v2.cases, *brief_suite.cases)


@pytest.fixture(scope="module")
def filings_by_id():
    return {f.filing_id: f for f in load_corpus()}


@pytest.fixture(scope="module")
def company_names():
    """Each Corpus ticker with the words a sentence would name the Company by."""
    names = {}
    for row in load_sector_table():
        words = [w for w in re.findall(r"[A-Za-z]+", row.company) if w != "The"]
        names[row.ticker] = {row.ticker, words[0]}
    return names


def _rewrite(tmp_path, edit, source=GOLDEN_SET_V1):
    data = json.loads(source.read_text(encoding="utf-8"))
    edit(data)
    path = tmp_path / source.name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- Schema -------------------------------------------------------------------------------


def test_golden_set_holds_about_thirty_cases_with_unique_ids(golden_set):
    ids = [case.id for case in golden_set.cases]

    assert 25 <= len(ids) <= 35
    assert len(set(ids)) == len(ids)


def test_every_case_has_a_question_a_known_type_and_its_labels(golden_set):
    for case in golden_set.cases:
        assert case.question.strip(), case.id
        assert case.question_type in QUESTION_TYPES, case.id
        assert all(gap.kind in COVERAGE_GAP_KINDS for gap in case.expected_coverage_gaps)
        # A case with nothing to retrieve must at least expect a Coverage Gap.
        assert case.expected_sources or case.expected_coverage_gaps, case.id


def test_cases_cover_every_question_type(golden_set):
    assert {case.question_type for case in golden_set.cases} == set(QUESTION_TYPES)


def test_the_loader_rejects_an_unknown_question_type(tmp_path):
    path = _rewrite(tmp_path, lambda d: d["cases"][0].update(question_type="vibes"))

    with pytest.raises(ValueError, match="question_type"):
        load_golden_set(path)


def test_the_loader_rejects_a_case_missing_a_field(tmp_path):
    path = _rewrite(tmp_path, lambda d: d["cases"][0].pop("required_facts"))

    with pytest.raises(ValueError, match="required_facts"):
        load_golden_set(path)


def test_the_loader_rejects_an_unknown_coverage_gap_kind(tmp_path):
    def edit(data):
        data["cases"][0]["expected_coverage_gaps"] = [{"kind": "vibes", "companies": ["AAPL"]}]

    with pytest.raises(ValueError, match="kind"):
        load_golden_set(_rewrite(tmp_path, edit))


# --- Required Fact tiers ------------------------------------------------------------------


def test_version_1_facts_have_no_tier_and_load_as_must_state(golden_set):
    raw = json.loads(GOLDEN_SET_V1.read_text(encoding="utf-8"))
    assert golden_set.version == 1
    assert not any("tier" in f for c in raw["cases"] for f in c["required_facts"])
    assert {f.tier for c in golden_set.cases for f in c.required_facts} == {"must_state"}


def test_a_case_can_mark_each_required_fact_must_state_or_detail(tmp_path):
    def edit(data):
        case = next(c for c in data["cases"] if len(c["required_facts"]) >= 2)
        case["required_facts"][0]["tier"] = "must_state"
        case["required_facts"][1]["tier"] = "detail"

    golden = load_golden_set(_rewrite(tmp_path, edit))

    case = next(c for c in golden.cases if len(c.required_facts) >= 2)
    assert [f.tier for f in case.required_facts[:2]] == ["must_state", "detail"]
    assert set(TIERS) == {"must_state", "detail"}


def test_the_loader_rejects_an_unknown_tier(tmp_path):
    def edit(data):
        data["cases"][0]["required_facts"][0]["tier"] = "nice_to_have"

    with pytest.raises(ValueError, match="tier"):
        load_golden_set(_rewrite(tmp_path, edit))


def test_after_version_1_every_fact_must_name_its_tier(tmp_path):
    def edit(data):
        data["version"] = 2
        for case in data["cases"]:
            for fact in case["required_facts"]:
                fact["tier"] = "must_state"
        del data["cases"][0]["required_facts"][0]["tier"]

    with pytest.raises(ValueError, match="tier"):
        load_golden_set(_rewrite(tmp_path, edit))


def test_the_loader_rejects_a_case_whose_facts_are_all_details(tmp_path):
    def edit(data):
        for fact in data["cases"][0]["required_facts"]:
            fact["tier"] = "detail"

    with pytest.raises(ValueError, match="must-state"):
        load_golden_set(_rewrite(tmp_path, edit))


def test_a_case_with_no_facts_is_valid_only_when_it_expects_coverage_gaps(tmp_path, golden_set):
    gaps_only = next(c for c in golden_set.cases if not c.required_facts)
    assert gaps_only.expected_coverage_gaps  # such cases load, as version 1's do

    def edit(data):
        case = next(c for c in data["cases"] if c["id"] == gaps_only.id)
        case["expected_coverage_gaps"] = []

    with pytest.raises(ValueError, match="must-state"):
        load_golden_set(_rewrite(tmp_path, edit))


# --- Required Facts -----------------------------------------------------------------------


def test_every_required_fact_is_a_sentence_naming_its_company(
    labelled_cases, filings_by_id, company_names
):
    for case in labelled_cases:
        for fact in case.required_facts:
            names = company_names[filings_by_id[fact.filing_id].ticker]
            # The Sector table writes "McDonalds Corporation"; a sentence writes "McDonald's".
            unquoted = re.sub(r"['’]", "", fact.fact)
            assert fact.fact.endswith("."), (case.id, fact.fact)
            assert fact.evidence.strip(), (case.id, fact.fact)
            assert any(re.search(rf"\b{re.escape(n)}", unquoted) for n in names), (
                case.id,
                fact.fact,
                names,
            )


def test_every_required_fact_cites_one_of_its_cases_expected_sources(labelled_cases):
    for case in labelled_cases:
        expected = {(s.filing_id, s.section) for s in case.expected_sources}
        for fact in case.required_facts:
            assert (fact.filing_id, fact.section) in expected, (case.id, fact.fact)


# --- Multi-turn cases ---------------------------------------------------------------------


def test_about_six_cases_are_multi_turn_with_scripted_history(golden_set):
    multi_turn = [case for case in golden_set.cases if case.history]

    assert 5 <= len(multi_turn) <= 8
    for case in multi_turn:
        roles = [message.role for message in case.history]
        assert roles[0] == "user", case.id
        assert roles[-1] == "assistant", case.id
        assert all(a != b for a, b in zip(roles, roles[1:], strict=False)), case.id
        assert all(message.content.strip() for message in case.history), case.id


def test_one_multi_turn_case_changes_topic_without_naming_a_company(golden_set, company_names):
    cases = [c for c in golden_set.cases if "topic_change_without_company" in c.tags]

    assert len(cases) == 1
    case = cases[0]
    assert case.history
    named = {
        ticker
        for ticker, names in company_names.items()
        if any(re.search(rf"\b{re.escape(n)}\b", case.question) for n in names)
    }
    assert named == set(), named


# --- Starter prompts ----------------------------------------------------------------------


def test_the_six_starter_prompts_are_cases_in_a_fixed_order(golden_set):
    starters = golden_set.starters()

    assert [case.starter.order for case in starters] == [1, 2, 3, 4, 5, 6]
    assert all(case.starter.label.strip() for case in starters)
    assert all(not case.history for case in starters)


def test_the_starters_include_the_brief_examples_and_the_hard_cases(golden_set):
    starters = golden_set.starters()
    questions = {case.question for case in starters}
    gap_kinds = {gap.kind for case in starters for gap in case.expected_coverage_gaps}

    assert BRIEF_QUESTIONS <= questions
    others = [case for case in starters if case.question not in BRIEF_QUESTIONS]
    assert "sector" in {case.question_type for case in others}
    assert {"snapshot_trend", "missing_company"} <= gap_kinds


def test_the_brief_starters_come_from_the_brief_suite_and_the_rest_from_the_golden_set(
    golden_set, brief_suite
):
    starters = starter_cases(golden_set, brief_suite)

    assert [case.starter.order for case in starters] == [1, 2, 3, 4, 5, 6]
    brief = {case.id for case in brief_suite.cases}
    for case in starters:
        assert (case.id in brief) == (case.question in BRIEF_QUESTIONS), case.id
    # The text the front-end shows is the version 1 starters', unchanged.
    assert [(c.starter.label, c.question) for c in starters] == [
        (c.starter.label, c.question) for c in golden_set.starters()
    ]


# --- The Brief Suite ----------------------------------------------------------------------

VERSION_1_SHA256 = "4127b0df5ea101918dd1b181491030ce570eec50a0d6ca9ac571ca7b6a695aa4"
"""The digest of Golden Set version 1's file, which stays unchanged as a record."""


def test_version_1s_golden_set_file_is_unchanged():
    digest = hashlib.sha256(GOLDEN_SET_V1.read_bytes()).hexdigest()

    assert digest == VERSION_1_SHA256


def test_the_brief_suite_holds_the_brief_questions_each_replacing_its_version_1_case(
    golden_set, brief_suite
):
    golden = {case.id: case for case in golden_set.cases}

    replaced = [case for case in brief_suite.cases if case.replaces]
    assert {case.question for case in replaced} == BRIEF_QUESTIONS
    assert len(replaced) == 3
    for case in replaced:
        old = golden[case.replaces]
        assert "brief_example" in old.tags, case.id
        assert case.question == old.question, case.id
        assert case.question_type == old.question_type, case.id
        assert case.split is None, case.id  # outside the dev/holdout split


def test_brief_suite_ids_are_unique_and_never_golden_set_ids(
    golden_set, golden_set_v2, brief_suite
):
    ids = [case.id for case in brief_suite.cases]

    assert len(set(ids)) == len(ids)
    assert not set(ids) & {case.id for case in golden_set.cases}
    assert not set(ids) & {case.id for case in golden_set_v2.cases}


def test_the_loader_rejects_an_id_in_both_the_brief_suite_and_golden_set_version_2(tmp_path):
    clash = _v2_case("risk-unh-cybersecurity") | {"id": "brief-risk-aapl-tsla-jpm"}
    v2 = _v2_file(tmp_path, [clash])

    with pytest.raises(ValueError, match="brief-risk-aapl-tsla-jpm"):
        load_brief_suite(DEFAULT_BRIEF_SUITE, (GOLDEN_SET_V1, v2))


def test_every_brief_suite_case_has_facts_in_both_tiers(brief_suite):
    for case in brief_suite.cases:
        tiers = {fact.tier for fact in case.required_facts}
        assert tiers == {"must_state", "detail"}, case.id


def test_the_loader_rejects_an_id_in_both_the_brief_suite_and_the_golden_set(tmp_path):
    path = _rewrite(
        tmp_path, lambda d: d["cases"][0].update(id="risk-aapl-tsla-jpm"), DEFAULT_BRIEF_SUITE
    )

    with pytest.raises(ValueError, match="risk-aapl-tsla-jpm"):
        load_brief_suite(path)


def test_the_loader_rejects_a_brief_suite_case_with_a_split(tmp_path):
    path = _rewrite(tmp_path, lambda d: d["cases"][0].update(split="dev"), DEFAULT_BRIEF_SUITE)

    with pytest.raises(ValueError, match="split"):
        load_brief_suite(path)


def test_the_loader_rejects_a_brief_suite_fact_with_no_tier(tmp_path):
    path = _rewrite(
        tmp_path, lambda d: d["cases"][0]["required_facts"][0].pop("tier"), DEFAULT_BRIEF_SUITE
    )

    with pytest.raises(ValueError, match="tier"):
        load_brief_suite(path)


def test_the_loader_rejects_a_replaced_case_the_golden_set_does_not_hold(tmp_path):
    path = _rewrite(tmp_path, lambda d: d["cases"][0].update(replaces="nope"), DEFAULT_BRIEF_SUITE)

    with pytest.raises(ValueError, match="nope"):
        load_brief_suite(path)


def test_brief_suite_cases_are_not_valid_golden_set_cases():
    with pytest.raises(ValueError):
        load_golden_set(DEFAULT_BRIEF_SUITE)


VARIANT_ANGLES = {"rephrasing", "other_companies", "other_angle", "follow_up"}
"""The four kinds of variant each brief question gets (ADR 0012): a rephrasing, other
Companies in the same shape (for the pharmaceutical question, another Health Care Sector
phrase), another time window or Section angle (for the pharmaceutical question, a single
Company), and a follow-up."""


@pytest.mark.parametrize(
    "brief_case",
    [
        "brief-risk-aapl-tsla-jpm",
        "brief-outlook-nvda-revenue-two-years",
        "brief-sector-pharma-regulatory",
    ],
)
def test_a_brief_question_has_four_variants_one_per_angle(brief_suite, brief_case):
    variants = [case for case in brief_suite.cases if case.variant_of == brief_case]

    assert len(variants) == 4
    angles = [set(case.tags) & VARIANT_ANGLES for case in variants]
    assert all(len(angle) == 1 for angle in angles), angles
    assert set().union(*angles) == VARIANT_ANGLES
    for case in variants:
        assert "brief_variant" in case.tags, case.id
        assert case.replaces is None and case.starter is None, case.id
        # Only the follow-up has a scripted history, which ends with an assistant answer.
        assert bool(case.history) == ("follow_up" in case.tags), case.id


def test_the_loader_rejects_a_variant_of_no_brief_question(tmp_path):
    def edit(data):
        variant = next(c for c in data["cases"] if "variant_of" in c)
        variant["variant_of"] = "brief-nope"

    path = _rewrite(tmp_path, edit, DEFAULT_BRIEF_SUITE)

    with pytest.raises(ValueError, match="brief-nope"):
        load_brief_suite(path)


def test_only_a_brief_suite_case_is_a_variant(tmp_path):
    path = _rewrite(tmp_path, lambda d: d["cases"][0].update(variant_of="brief-risk-aapl-tsla-jpm"))

    with pytest.raises(ValueError, match="variant"):
        load_golden_set(path)


# --- Split --------------------------------------------------------------------------------


def test_split_is_recorded_for_every_case_and_matches_the_hash_rule(golden_set):
    expected = assign_splits(case.id for case in golden_set.cases)

    assert {case.id: case.split for case in golden_set.cases} == expected


def test_the_split_rule_is_written_in_the_file(golden_set):
    assert golden_set.split_rule == SPLIT_RULE


def test_the_holdout_is_a_third_of_the_cases(golden_set):
    assert len(golden_set.split("holdout")) == round(len(golden_set.cases) / 3)


def test_the_split_depends_only_on_the_ids_not_their_order():
    ids = [f"case-{i}" for i in range(30)]

    splits = assign_splits(ids)

    assert splits == assign_splits(reversed(ids))
    assert list(splits.values()).count("holdout") == 10


# --- Labels against the Corpus ------------------------------------------------------------


def _source_problems(cases, filings_by_id):
    """Each expected Source whose Filing is not in the Corpus or has no such Section."""
    problems = []
    for case in cases:
        for source in case.expected_sources:
            filing = filings_by_id.get(source.filing_id)
            if filing is None or source.section not in {s.name for s in filing.sections}:
                problems.append(f"{case.id}: no Section {source.section!r} in {source.filing_id}")
    return problems


def _evidence_problems(cases, filings_by_id):
    """Each Required Fact whose evidence quote is not word for word (after collapsing
    whitespace) in a Section of its name in its Filing."""
    problems = []
    for case in cases:
        for fact in case.required_facts:
            filing = filings_by_id.get(fact.filing_id)
            sections = filing.sections if filing else ()
            texts = [normalise_whitespace(s.text) for s in sections if s.name == fact.section]
            if not any(normalise_whitespace(fact.evidence) in text for text in texts):
                problems.append(
                    f"{case.id}: not in {fact.filing_id} {fact.section}: {fact.evidence!r}"
                )
    return problems


def test_every_expected_filing_and_section_exists_in_the_corpus(labelled_cases, filings_by_id):
    assert _source_problems(labelled_cases, filings_by_id) == []


def test_every_evidence_quote_appears_verbatim_in_its_labelled_section(
    labelled_cases, filings_by_id
):
    assert _evidence_problems(labelled_cases, filings_by_id) == []


def test_whitespace_normalisation_only_collapses_whitespace():
    assert normalise_whitespace("$164.50\xa0billion,\n  up") == "$164.50 billion, up"
    assert normalise_whitespace("JPMorganChase’s") == "JPMorganChase’s"


# --- Golden Set version 2 -----------------------------------------------------------------


def _v2_case(case_id, split="dev"):
    """A version 1 case rewritten for version 2: the same id, a tier on every fact and a
    recorded split."""
    raw = json.loads(GOLDEN_SET_V1.read_text(encoding="utf-8"))
    case = next(c for c in raw["cases"] if c["id"] == case_id)
    for fact in case["required_facts"]:
        fact["tier"] = "must_state"
    return case | {"split": split}


def _v2_file(tmp_path, cases, name="golden_set_v2.json"):
    path = tmp_path / name
    data = {"version": 2, "split_rule": SPLIT_RULE_V2, "cases": cases}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_small_version_2_file_loads_with_a_split_recorded_per_case(tmp_path):
    path = _v2_file(
        tmp_path,
        [
            _v2_case("risk-unh-cybersecurity", "dev"),
            _v2_case("trend-aapl-revenue-fy2025", "holdout"),
            _v2_case("outlook-tsla-2026", "pending"),
        ],
    )

    golden = load_golden_set(path)

    assert golden.version == 2
    assert {c.id: c.split for c in golden.cases} == {
        "risk-unh-cybersecurity": "dev",
        "trend-aapl-revenue-fy2025": "holdout",
        "outlook-tsla-2026": "pending",
    }
    assert [c.id for c in golden.split("pending")] == ["outlook-tsla-2026"]


def test_version_1_has_no_pending_split(tmp_path):
    path = _rewrite(tmp_path, lambda d: d["cases"][0].update(split="pending"))

    with pytest.raises(ValueError, match="split"):
        load_golden_set(path)


def test_the_version_2_file_sits_beside_version_1_and_loads(golden_set_v2):
    assert GOLDEN_SET_V2.parent == GOLDEN_SET_V1.parent
    assert DEFAULT_GOLDEN_SET == GOLDEN_SET_V2  # the harnesses' default
    assert golden_set_v2.version == 2
    assert golden_set_v2.split_rule == SPLIT_RULE_V2
    ids = [case.id for case in golden_set_v2.cases]
    assert len(set(ids)) == len(ids)
    assert all(case.split in ("dev", "holdout", "pending") for case in golden_set_v2.cases)


def test_version_2_holds_all_27_of_version_1s_cases_other_than_the_briefs(
    golden_set, golden_set_v2
):
    """Version 1's cases other than the brief's were rewritten into version 2 in three
    batches of nine (ADR 0012); the brief's are in the Brief Suite."""
    not_brief = {case.id for case in golden_set.cases if "brief_example" not in case.tags}

    assert len(not_brief) == 27
    assert not_brief <= {case.id for case in golden_set_v2.cases}


def test_a_rewritten_version_1_case_keeps_its_question_and_history_and_is_dev(
    golden_set, golden_set_v2
):
    version_1 = {case.id: case for case in golden_set.cases}

    rewritten = [case for case in golden_set_v2.cases if case.id in version_1]
    for case in rewritten:
        old = version_1[case.id]
        assert case.split == "dev", case.id
        assert case.question == old.question, case.id
        assert case.history == old.history, case.id
        assert case.question_type == old.question_type, case.id
        assert case.starter == old.starter, case.id
        assert "brief_example" not in old.tags, case.id  # the brief's are in the Brief Suite


NEW_SLICE_1 = {
    "risk-meta-amzn-legal-proceedings",
    "risk-goog-meta-ai",
    "risk-nflx-dis-streaming-competition",
    "risk-t-vz-cmcsa-regulation",
    "risk-amd-csco-supply-chain",
    "risk-nke-sbux-hd-consumer-demand",
    "risk-aapl-msft-market-risk",
    "risk-nvda-amd-competition",
    "risk-nke-tsla-amzn-tariffs",
}
"""Version 2's first slice of new cases: multi-Company risk comparisons among information
technology, communication services and consumer Companies (issue #66)."""

_SLICE_1_SECTORS = {
    "Information Technology",
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
}


def test_new_slice_1_holds_nine_multi_company_risk_comparisons(golden_set_v2, filings_by_id):
    cases = {case.id: case for case in golden_set_v2.cases if case.id in NEW_SLICE_1}
    sectors = {row.ticker: row.sector for row in load_sector_table()}

    assert set(cases) == NEW_SLICE_1
    sizes = []
    for case in cases.values():
        tickers = {filings_by_id[s.filing_id].ticker for s in case.expected_sources}
        assert case.question_type == "risk", case.id
        assert not case.history and case.starter is None, case.id
        assert {sectors[t] for t in tickers} <= _SLICE_1_SECTORS, case.id
        assert {filings_by_id[f.filing_id].ticker for f in case.required_facts} == tickers, case.id
        sizes.append(len(tickers))
    assert set(sizes) == {2, 3}  # two-Company and three-Company comparisons
    sections = {s.section for case in cases.values() for s in case.expected_sources}
    assert {"Risk Factors", "Legal Proceedings", "Market Risk"} <= sections


NEW_SLICE_2_RISK = {
    "risk-v-ma-cybersecurity",
    "risk-wmt-tgt-legal-proceedings",
    "risk-ups-market-risk",
    "risk-cvx-xom-commodity-prices",
    "risk-abbv-jnj-loss-of-exclusivity",
    "risk-ba-commercial-production",
    "risk-pg-pep-input-costs",
}
NEW_SLICE_2_FOLLOW_UPS = {"followup-cat-de-dealers", "followup-lmt-to-rtx-market-risk"}
"""Version 2's second slice of new cases: seven risk questions on financials, industrials,
energy, health care and consumer staples Companies, and two follow-ups (issue #67)."""

_SLICE_2_SECTORS = {"Financials", "Industrials", "Energy", "Health Care", "Consumer Staples"}


def test_new_slice_2_holds_seven_risk_questions_on_its_sectors(golden_set_v2, filings_by_id):
    cases = {case.id: case for case in golden_set_v2.cases if case.id in NEW_SLICE_2_RISK}
    sectors = {row.ticker: row.sector for row in load_sector_table()}

    assert set(cases) == NEW_SLICE_2_RISK
    sizes, covered = set(), set()
    for case in cases.values():
        tickers = {filings_by_id[s.filing_id].ticker for s in case.expected_sources}
        assert case.question_type == "risk", case.id
        assert not case.history and case.starter is None, case.id
        assert {sectors[t] for t in tickers} <= _SLICE_2_SECTORS, case.id
        assert {filings_by_id[f.filing_id].ticker for f in case.required_facts} == tickers, case.id
        sizes.add(1 if len(tickers) == 1 else 2)
        covered |= {sectors[t] for t in tickers}
    assert sizes == {1, 2}  # single-Company and multi-Company questions
    assert covered == _SLICE_2_SECTORS
    sections = {s.section for case in cases.values() for s in case.expected_sources}
    assert {"Legal Proceedings", "Market Risk", "Cybersecurity"} <= sections


def test_new_slice_2_holds_one_inheriting_and_one_switching_follow_up(golden_set_v2, company_names):
    cases = {c.id: c for c in golden_set_v2.cases if c.id in NEW_SLICE_2_FOLLOW_UPS}

    assert set(cases) == NEW_SLICE_2_FOLLOW_UPS
    for case in cases.values():
        assert case.history and case.history[-1].role == "assistant", case.id
        assert re.search(r"\b[A-Z]+_10-[KQ]_\d{4}-\d{2}-\d{2}\b", case.history[-1].content)
    [inherits] = [c for c in cases.values() if "inherits_companies" in c.tags]
    [switches] = [c for c in cases.values() if "switches_company" in c.tags]
    named = {
        ticker
        for ticker, names in company_names.items()
        if any(re.search(rf"\b{re.escape(n)}\b", inherits.question) for n in names)
    }
    assert named == set()  # it names no Company, so it inherits them
    earlier = {
        ticker
        for ticker, names in company_names.items()
        if any(re.search(rf"\b{re.escape(n)}\b", switches.history[0].content) for n in names)
    }
    asked = {
        ticker
        for ticker, names in company_names.items()
        if any(re.search(rf"\b{re.escape(n)}\b", switches.question) for n in names)
    }
    assert asked and not asked & earlier  # it names another Company


NEW_SLICE_3 = {
    "trend-goog-cloud-two-years": "segment revenue",
    "trend-dis-segments-fy2025": "segment revenue",
    "trend-tsla-energy-two-years": "segment revenue",
    "trend-ko-revenue-two-years": "revenue",
    "trend-amzn-net-sales-2025": "revenue",
    "trend-pfe-jnj-revenue-2024": "revenue",
    "trend-xom-net-income-2025": "net income",
    "trend-aapl-msft-net-income-fy2025": "net income",
    "trend-goog-meta-net-income-two-years": "net income",
}
"""Version 2's third slice of new cases: figure trends on Tracked Companies, each by the
Financial Facts metric it asks about (issue #68)."""


def test_new_slice_3_holds_nine_figure_trends_on_tracked_companies(golden_set_v2, filings_by_id):
    cases = {case.id: case for case in golden_set_v2.cases if case.id in NEW_SLICE_3}

    assert set(cases) == set(NEW_SLICE_3)
    sizes, windows = set(), set()
    for case in cases.values():
        filings = [filings_by_id[s.filing_id] for s in case.expected_sources]
        tickers = {f.ticker for f in filings}
        assert case.question_type == "figure_trend", case.id
        assert not case.history and case.starter is None, case.id
        assert {f.coverage for f in filings} == {"tracked"}, case.id  # no Snapshot Company
        assert {filings_by_id[f.filing_id].ticker for f in case.required_facts} == tickers, case.id
        assert not any(g.kind == "snapshot_trend" for g in case.expected_coverage_gaps), case.id
        sizes.add(len(tickers))
        windows.add("two years" if "last two years" in case.question else "named")
    assert set(NEW_SLICE_3.values()) == {"revenue", "net income", "segment revenue"}
    assert sizes == {1, 2}  # single-Company and two-Company questions
    assert windows == {"two years", "named"}  # "the last two years" and named fiscal years


NEW_SLICE_4_OUTLOOK = {
    "outlook-amzn-q1-2026-guidance": "guidance",
    "outlook-mcd-2025": "guidance",
    "outlook-intc-2026": "no_guidance",
    "outlook-nflx-growth": "no_guidance",
}
NEW_SLICE_4_SECTOR = {
    "sector-aerospace-supply-chain": ("aerospace and defense companies", "Aerospace & Defense"),
    "sector-industrials-tariffs": ("industrial companies", "Industrials"),
    "sector-energy-operational-risks": ("energy companies", "Energy"),
    "sector-banks-capital-liquidity": ("major banks", "Banks"),
    "sector-financials-digital-assets": ("financial companies", "Financials"),
}
"""Version 2's fourth slice of new cases (issue #69): four outlook questions, each by
whether its guidance is in the Filings, and five sector questions, each by its Sector
phrase and the Sector table value (sector or industry) the phrase resolves to."""


def test_new_slice_4_holds_two_guided_and_two_unguided_outlook_questions(
    golden_set_v2, filings_by_id
):
    cases = {c.id: c for c in golden_set_v2.cases if c.id in NEW_SLICE_4_OUTLOOK}

    assert set(cases) == set(NEW_SLICE_4_OUTLOOK)
    for case in cases.values():
        [ticker] = {filings_by_id[s.filing_id].ticker for s in case.expected_sources}
        assert case.question_type == "outlook", case.id
        assert not case.history and case.starter is None, case.id
        assert {filings_by_id[f.filing_id].ticker for f in case.required_facts} == {ticker}
        gaps = [(g.kind, tuple(g.companies)) for g in case.expected_coverage_gaps]
        if NEW_SLICE_4_OUTLOOK[case.id] == "guidance":
            assert gaps == [], case.id  # the guidance is in the Filing
        else:
            assert gaps == [("no_guidance", (ticker,))], case.id


def test_new_slice_4_holds_five_sector_questions_on_industrials_energy_and_financials(
    golden_set_v2, filings_by_id
):
    cases = {c.id: c for c in golden_set_v2.cases if c.id in NEW_SLICE_4_SECTOR}
    rows = {row.ticker: row for row in load_sector_table()}

    assert set(cases) == set(NEW_SLICE_4_SECTOR)
    covered = set()
    for case in cases.values():
        phrase, value = NEW_SLICE_4_SECTOR[case.id]
        resolved = {t for t, row in rows.items() if value in (row.sector, row.industry)}
        sources = {filings_by_id[s.filing_id].ticker for s in case.expected_sources}
        facts = {filings_by_id[f.filing_id].ticker for f in case.required_facts}
        assert case.question_type == "sector", case.id
        assert not case.history and case.starter is None, case.id
        assert phrase in case.question, case.id
        assert sources <= resolved and facts == sources, case.id
        assert len(facts) >= 2, case.id  # facts from several of the resolved Companies
        covered |= {rows[t].sector for t in facts}
    assert covered == {"Industrials", "Energy", "Financials"}


_RETAIL = ("Broadline Retail", "Specialty Retail", "Consumer Staples Distribution & Retail")
NEW_SLICE_5_SECTOR = {
    "sector-semiconductors-customer-concentration": (
        "semiconductor companies",
        ("Semiconductors & Semiconductor Equipment",),
    ),
    "sector-software-cybersecurity": ("software companies", ("Software",)),
    "sector-pharma-research-and-development": (
        "pharmaceutical companies",
        ("Pharmaceuticals", "Biotechnology"),
    ),
    "sector-health-care-liability-claims": ("health care companies", ("Health Care",)),
    "sector-consumer-staples-key-customers": ("consumer staples", ("Consumer Staples",)),
    "sector-consumer-discretionary-climate": (
        "consumer discretionary",
        ("Consumer Discretionary",),
    ),
    "sector-retailers-workforce": ("retailers", _RETAIL),
    "sector-communication-services-advertising": (
        "communication services",
        ("Communication Services",),
    ),
}
NEW_SLICE_5_GAP = "gap-aapl-nvda-research-spending-periods-differ"
"""Version 2's fifth slice of new cases (issue #70): eight sector questions on health care,
information technology, consumer and communication services Companies, each by its Sector
phrase and the Sector table values (sector or industry) the phrase resolves to, and one
Coverage Gap case, a comparison whose Companies' latest fiscal years differ."""

_SLICE_5_SECTORS = {
    "Health Care",
    "Information Technology",
    "Consumer Discretionary",
    "Consumer Staples",
    "Communication Services",
}


def test_new_slice_5_holds_eight_sector_questions_on_its_sectors(golden_set_v2, filings_by_id):
    cases = {c.id: c for c in golden_set_v2.cases if c.id in NEW_SLICE_5_SECTOR}
    rows = {row.ticker: row for row in load_sector_table()}

    assert set(cases) == set(NEW_SLICE_5_SECTOR)
    covered = set()
    for case in cases.values():
        phrase, values = NEW_SLICE_5_SECTOR[case.id]
        resolved = {t for t, row in rows.items() if {row.sector, row.industry} & set(values)}
        sources = {filings_by_id[s.filing_id].ticker for s in case.expected_sources}
        facts = {filings_by_id[f.filing_id].ticker for f in case.required_facts}
        assert case.question_type == "sector", case.id
        assert not case.history and case.starter is None, case.id
        assert phrase in case.question, case.id
        assert sources <= resolved and facts == sources, case.id
        assert len(facts) >= 2, case.id  # facts from several of the resolved Companies
        covered |= {rows[t].sector for t in facts}
    assert covered == _SLICE_5_SECTORS


def test_new_slice_5_holds_a_periods_differ_comparison_as_a_coverage_gap_case(
    golden_set_v2, filings_by_id
):
    """A comparison asked to test the periods differ gap: its Companies' latest 10-Ks end
    more than 20 days apart, the case expects that gap and no other, and the mix counts it
    as a Coverage Gap case, not as a trend."""
    [case] = [c for c in golden_set_v2.cases if c.id == NEW_SLICE_5_GAP]
    filings = [filings_by_id[s.filing_id] for s in case.expected_sources]
    ends = {f.ticker: f.report_period for f in filings if f.form_type == "10-K"}

    assert len(ends) >= 2 and not case.history
    assert (max(ends.values()) - min(ends.values())).days > 20
    gaps = [(g.kind, set(g.companies)) for g in case.expected_coverage_gaps]
    assert gaps == [("periods_differ", set(ends))]
    assert "periods_differ_comparison" in case.tags
    assert _question_kind(case) == "coverage_gap"


NEW_SLICE_6_GAPS = {
    "gap-cat-sales-snapshot": "snapshot_trend",
    "missing-broadcom-revenue": "missing_company",
    "stale-gecc-main-risks": "stale_filing",
    "gap-msft-goog-capex-periods-differ": "periods_differ",
    "missing-kroger-with-walmart": "mixed",
}
NEW_SLICE_6_FOLLOW_UPS = {
    "followup-topic-change-stock-splits": "topic_change_without_company",
    "followup-cmcsa-to-telecom-competition": "switches_company",
    "followup-aapl-buybacks-change": "inherits_companies",
}
"""Version 2's sixth and last slice of new cases (issue #71): five Coverage Gap cases, one
per kind the issue names (a trend asked of a Snapshot Company, a missing Company version 1
did not use, the stale Filing, the periods differ gap, and a covered Company asked about
beside a missing one), and three follow-ups, each by its tag: one changes topic without
naming a Company, one switches to a Sector phrase, one asks how something changed."""

_TELECOM_PHRASE = ("telecom companies", "Diversified Telecommunication Services")
_CHANGE_WORDS = re.compile(r"\bchang(?:e|ed)\b|\bgrown\b|\bgrew\b", re.I)


def _missing_companies():
    """The names on the curated list of notable Companies missing from the Corpus."""
    path = DATA_DIR / "reference" / "missing_companies.csv"
    with path.open(encoding="utf-8", newline="") as f:
        return {row["name"] for row in csv.DictReader(f)}


def _named_tickers(text, company_names):
    return {
        ticker
        for ticker, names in company_names.items()
        if any(re.search(rf"\b{re.escape(n)}\b", text) for n in names)
    }


def test_new_slice_6_holds_one_coverage_gap_case_of_each_kind(
    golden_set, golden_set_v2, filings_by_id
):
    cases = {c.id: c for c in golden_set_v2.cases if c.id in NEW_SLICE_6_GAPS}
    missing = _missing_companies()
    used_by_version_1 = {
        name
        for case in golden_set.cases
        for gap in case.expected_coverage_gaps
        if gap.kind == "missing_company"
        for name in gap.companies
    }

    assert set(cases) == set(NEW_SLICE_6_GAPS)
    for case in cases.values():
        assert not case.history and case.starter is None, case.id
        assert _question_kind(case) == "coverage_gap", case.id
        gaps = [(g.kind, set(g.companies)) for g in case.expected_coverage_gaps]
        filings = [filings_by_id[s.filing_id] for s in case.expected_sources]
        tickers = {f.ticker for f in filings}
        kind = NEW_SLICE_6_GAPS[case.id]
        if kind == "snapshot_trend":
            assert gaps == [("snapshot_trend", tickers)], case.id
            assert {f.coverage for f in filings} == {"snapshot"}, case.id
        elif kind == "missing_company":
            [(gap_kind, names)] = gaps
            assert gap_kind == "missing_company" and names <= missing, case.id
            assert not names & used_by_version_1, case.id
            assert not case.expected_sources and not case.required_facts, case.id
        elif kind == "stale_filing":
            assert gaps == [("stale_filing", {"GE"})], case.id
            assert {s.filing_id for s in case.expected_sources} == {"GE_10-K_2014-12-31"}
        elif kind == "periods_differ":
            ends = {f.ticker: f.report_period for f in filings if f.form_type == "10-K"}
            assert gaps == [("periods_differ", set(ends))], case.id
            assert (max(ends.values()) - min(ends.values())).days > 20, case.id
            assert "periods_differ_comparison" in case.tags, case.id
        else:  # a covered Company asked about beside a missing one
            [(gap_kind, names)] = gaps
            assert gap_kind == "missing_company" and names <= missing, case.id
            assert tickers and case.required_facts, case.id
            assert {filings_by_id[f.filing_id].ticker for f in case.required_facts} == tickers


def test_new_slice_6_holds_three_follow_ups_of_different_kinds(
    golden_set_v2, filings_by_id, company_names
):
    cases = {c.id: c for c in golden_set_v2.cases if c.id in NEW_SLICE_6_FOLLOW_UPS}
    rows = {row.ticker: row for row in load_sector_table()}

    assert set(cases) == set(NEW_SLICE_6_FOLLOW_UPS)
    for case_id, case in cases.items():
        assert case.history and case.history[-1].role == "assistant", case_id
        assert re.search(r"\b[A-Z]+_10-[KQ]_\d{4}-\d{2}-\d{2}\b", case.history[-1].content)
        assert NEW_SLICE_6_FOLLOW_UPS[case_id] in case.tags, case_id
        assert _question_kind(case) == "follow_up", case_id
        earlier = _named_tickers(case.history[0].content, company_names)
        facts = {filings_by_id[f.filing_id].ticker for f in case.required_facts}
        asked = _named_tickers(case.question, company_names)
        kind = NEW_SLICE_6_FOLLOW_UPS[case_id]
        if kind == "topic_change_without_company":
            # It names no Company, and the Companies that answer it are not the earlier ones.
            assert not asked and earlier and not facts & earlier, case_id
            assert len(facts) >= 2, case_id
        elif kind == "switches_company":
            phrase, industry = _TELECOM_PHRASE
            resolved = {t for t, row in rows.items() if row.industry == industry}
            assert phrase in case.question and not asked, case_id
            assert facts == resolved and not resolved & earlier, case_id
        else:  # it inherits its Company and asks how the topic changed over time
            assert not asked and facts == earlier, case_id
            assert _CHANGE_WORDS.search(case.question), case_id
            periods = {filings_by_id[f.filing_id].report_period for f in case.required_facts}
            assert len(periods) >= 3, case_id


def test_version_2_holds_all_53_new_cases(golden_set, golden_set_v2):
    """The six slices complete the 53 new cases ADR 0012 sets, beside the 27 rewrites: 80
    cases, so the split can be frozen."""
    version_1 = {case.id for case in golden_set.cases}

    new = [case for case in golden_set_v2.cases if case.id not in version_1]

    assert len(new) == 53
    assert len(golden_set_v2.cases) == 80


NEW_CASES = {
    *NEW_SLICE_1,
    *NEW_SLICE_2_RISK,
    *NEW_SLICE_2_FOLLOW_UPS,
    *NEW_SLICE_3,
    *NEW_SLICE_4_OUTLOOK,
    *NEW_SLICE_4_SECTOR,
    *NEW_SLICE_5_SECTOR,
    NEW_SLICE_5_GAP,
    *NEW_SLICE_6_GAPS,
    *NEW_SLICE_6_FOLLOW_UPS,
}
"""The 53 new cases the split was frozen over (issue #72), named by their slices, so a
case added later never enters the recomputation."""


def _lowest_digests(case_ids, n):
    return sorted(case_ids, key=lambda i: hashlib.sha256(i.encode("utf-8")).hexdigest())[:n]


def test_version_2s_split_is_frozen_with_60_dev_and_20_holdout_cases(golden_set_v2):
    golden_set_v2.require_frozen()

    assert len(golden_set_v2.split("dev")) == 60
    assert len(golden_set_v2.split("holdout")) == 20
    assert golden_set_v2.split("pending") == []


def test_the_frozen_holdout_is_the_20_new_cases_with_the_lowest_digests(golden_set_v2):
    """Recomputed over the 53 new cases: a holdout id removed from the frozen list, or a
    recorded split changed, fails here or in the loader."""
    assert len(NEW_CASES) == 53

    expected = _lowest_digests(NEW_CASES, 20)

    assert golden_set_v2.holdout_ids == tuple(sorted(expected))
    assert {c.id for c in golden_set_v2.split("holdout")} == set(expected)
    assert all(c.split == "dev" for c in golden_set_v2.cases if c.id not in expected)


def test_the_split_rule_says_a_later_case_is_dev(golden_set_v2):
    assert "added later" in golden_set_v2.split_rule


def _frozen_file(tmp_path, splits, holdout_ids):
    cases = [_v2_case(case_id, split) for case_id, split in splits.items()]
    path = _v2_file(tmp_path, cases)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["holdout_ids"] = holdout_ids
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_frozen_file_loads_its_holdout_list(tmp_path):
    path = _frozen_file(
        tmp_path,
        {"risk-unh-cybersecurity": "dev", "trend-aapl-revenue-fy2025": "holdout"},
        ["trend-aapl-revenue-fy2025"],
    )

    golden = load_golden_set(path)

    assert golden.holdout_ids == ("trend-aapl-revenue-fy2025",)
    golden.require_frozen()


def test_version_1_and_a_file_still_being_drafted_have_no_holdout_list(golden_set, tmp_path):
    drafting = load_golden_set(_v2_file(tmp_path, [_v2_case("outlook-tsla-2026", "pending")]))

    assert golden_set.holdout_ids is None
    assert drafting.holdout_ids is None


@pytest.mark.parametrize(
    ("splits", "holdout_ids", "problem"),
    [
        # A dev case moved to the holdout, or a case added later recorded as holdout.
        ({"risk-unh-cybersecurity": "holdout", "outlook-tsla-2026": "holdout"},
         ["outlook-tsla-2026"], "risk-unh-cybersecurity"),
        # A holdout case moved to dev.
        ({"risk-unh-cybersecurity": "dev", "outlook-tsla-2026": "dev"},
         ["outlook-tsla-2026"], "outlook-tsla-2026"),
        # A holdout case removed from the file.
        ({"risk-unh-cybersecurity": "dev"}, ["outlook-tsla-2026"], "outlook-tsla-2026"),
        # A pending case once the split is frozen.
        ({"risk-unh-cybersecurity": "pending", "outlook-tsla-2026": "holdout"},
         ["outlook-tsla-2026"], "risk-unh-cybersecurity"),
    ],
)  # fmt: skip
def test_the_loader_rejects_a_recorded_split_that_disagrees_with_the_frozen_list(
    tmp_path, splits, holdout_ids, problem
):
    path = _frozen_file(tmp_path, splits, holdout_ids)

    with pytest.raises(ValueError, match=problem):
        load_golden_set(path)


def test_only_version_2_and_later_freeze_a_holdout_list(tmp_path):
    path = _rewrite(tmp_path, lambda d: d.update(holdout_ids=[]))

    with pytest.raises(ValueError, match="holdout_ids"):
        load_golden_set(path)


def test_a_missing_evidence_quote_or_section_fails_the_label_checks(tmp_path, filings_by_id):
    case = _v2_case("risk-unh-cybersecurity")
    case["required_facts"][0]["evidence"] = "UnitedHealth sells ice cream on the moon."
    case["expected_sources"].append({"filing_id": "UNH_10-K_2024-12-31", "section": "Nope"})
    golden = load_golden_set(_v2_file(tmp_path, [case]))

    [missing_quote] = _evidence_problems(golden.cases, filings_by_id)
    [missing_section] = _source_problems(golden.cases, filings_by_id)

    assert "ice cream" in missing_quote
    assert "Nope" in missing_section


def _repeated_questions(version_1, version_2, brief_suite):
    """Each question asked by more than one case across the three files, once case and
    whitespace are normalised. A version 1 case may share its question with the version 2
    case that rewrites it (the same id) and with the Brief Suite case that replaces it."""

    def allowed(a, b):
        order = ("v1", "v2", "brief")
        (file_a, case_a), (file_b, case_b) = sorted((a, b), key=lambda x: order.index(x[0]))
        if file_a != "v1":
            return False
        if file_b == "v2":
            return case_b.id == case_a.id
        return file_b == "brief" and case_b.replaces == case_a.id

    by_question = {}
    for file, cases in (("v1", version_1), ("v2", version_2), ("brief", brief_suite)):
        for case in cases:
            key = normalise_whitespace(case.question).casefold()
            by_question.setdefault(key, []).append((file, case))
    problems = []
    for question, asked in by_question.items():
        pairs = [(a, b) for i, a in enumerate(asked) for b in asked[i + 1 :]]
        if not all(allowed(a, b) for a, b in pairs):
            where = ", ".join(f"{file} {case.id}" for file, case in asked)
            problems.append(f"{where} all ask {question!r}")
    return problems


def test_no_question_repeats_across_both_golden_set_versions_and_the_brief_suite(
    golden_set, golden_set_v2, brief_suite
):
    assert _repeated_questions(golden_set.cases, golden_set_v2.cases, brief_suite.cases) == []


def test_a_repeated_question_fails_unless_it_is_a_rewrite_keeping_its_id(
    tmp_path, golden_set, brief_suite
):
    rewritten = _v2_case("risk-unh-cybersecurity")
    respaced = _v2_case("trend-aapl-revenue-fy2025") | {"id": "trend-aapl-again"}
    respaced["question"] = "  " + respaced["question"].upper().replace(" ", "\n ")
    brief_question = _v2_case("outlook-tsla-2026") | {"id": "outlook-nvda-again"}
    brief_question["question"] = brief_suite.cases[1].question
    v2 = load_golden_set(_v2_file(tmp_path, [rewritten, respaced, brief_question]))

    problems = _repeated_questions(golden_set.cases, v2.cases, brief_suite.cases)

    assert len(problems) == 2
    assert any("trend-aapl-again" in p and "trend-aapl-revenue-fy2025" in p for p in problems)
    assert any("outlook-nvda-again" in p for p in problems)
    assert not any("risk-unh-cybersecurity" in p for p in problems)


_AMOUNT = re.compile(r"\$(\d[\d,]*(?:\.(\d+))?)(?:\s+(thousand|million|billion|trillion)\b)?")
_SCALE = {None: 1, "thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}


def _figure_problems(cases, filings_by_id, company_facts):
    """Each dollar amount stated in a Required Fact that no USD value in the SEC
    company-facts reference matches at the amount's printed precision ($60.9 billion is
    60.85 to 60.95 billion), among the values reported in the fact's own Filing (matched
    on the accession number in its source URL). `company_facts` maps a CIK to that
    Company's company-facts JSON."""
    problems = []
    for case in cases:
        for fact in case.required_facts:
            amounts = list(_AMOUNT.finditer(fact.fact))
            if not amounts:
                continue
            filing = filings_by_id[fact.filing_id]
            accn = "-".join(re.search(r"/(\d{10})(\d{2})(\d{6})/", filing.source_url).groups())
            try:
                reference = company_facts(filing.cik)
            except FileNotFoundError:
                problems.append(f"{case.id}: no SEC reference for {filing.ticker}: {fact.fact}")
                continue
            values = [
                v["val"]
                for concepts in reference["facts"].values()
                for concept in concepts.values()
                for unit, reported in concept["units"].items()
                if unit.startswith("USD")
                for v in reported
                if v["accn"] == accn
            ]
            for amount in amounts:
                digits, decimals, scale = amount.groups()
                stated = float(digits.replace(",", "")) * _SCALE[scale]
                half_unit = _SCALE[scale] * 10 ** -len(decimals or "") / 2
                if not any(abs(v - stated) <= half_unit for v in values):
                    problems.append(
                        f"{case.id}: {amount[0]} matches no SEC value in {fact.filing_id}"
                    )
    return problems


NVIDIA_FY2024 = "NVDA_10-K_2024-01-28"
NVIDIA_FY2024_REVENUE = 60_922_000_000
"""NVIDIA's FY2024 Revenues in the SEC company-facts reference, in USD."""


def _nvidia_figure_case(tmp_path, amount):
    case = _v2_case("risk-unh-cybersecurity")
    case["id"] = "trend-nvda-revenue-fy2024"
    case["expected_sources"] = [{"filing_id": NVIDIA_FY2024, "section": "MD&A"}]
    case["required_facts"] = [
        {
            "fact": f"NVIDIA's revenue for fiscal year 2024 was {amount}.",
            "filing_id": NVIDIA_FY2024,
            "section": "MD&A",
            "evidence": "Revenue for fiscal year 2024 was $60.9 billion, up 126% from a year ago.",
            "tier": "must_state",
        }
    ]
    return load_golden_set(_v2_file(tmp_path, [case])).cases


def _fake_company_facts(filing, value):
    """A company-facts reference holding one USD value, reported in `filing`."""
    accn = re.search(r"/(\d{10})(\d{2})(\d{6})/", filing.source_url).groups()
    fact = {"val": value, "accn": "-".join(accn), "end": filing.report_period.isoformat()}
    reference = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [fact]}}}}}
    return lambda cik: reference


def test_a_wrong_figure_fails_the_check_against_the_sec_reference(tmp_path, filings_by_id):
    filing = filings_by_id[NVIDIA_FY2024]
    company_facts = _fake_company_facts(filing, NVIDIA_FY2024_REVENUE)

    right = _nvidia_figure_case(tmp_path, "$60.9 billion")
    exact = _nvidia_figure_case(tmp_path, "$60,922 million")
    [wrong] = _figure_problems(
        _nvidia_figure_case(tmp_path, "$61.9 billion"), filings_by_id, company_facts
    )

    assert _figure_problems(right, filings_by_id, company_facts) == []
    assert _figure_problems(exact, filings_by_id, company_facts) == []
    assert "$61.9 billion" in wrong


def test_a_figure_reported_in_another_filing_fails_the_check(tmp_path, filings_by_id):
    other = filings_by_id["NVDA_10-K_2025-01-26"]
    company_facts = _fake_company_facts(other, NVIDIA_FY2024_REVENUE)

    problems = _figure_problems(
        _nvidia_figure_case(tmp_path, "$60.9 billion"), filings_by_id, company_facts
    )

    assert len(problems) == 1


def test_every_version_2_figure_fact_matches_the_sec_reference(golden_set_v2, filings_by_id):
    if not (SEC_CACHE_DIR / "index.json").exists():
        pytest.skip("no SEC company-facts cache: run `make sec-facts`")

    problems = _figure_problems(golden_set_v2.cases, filings_by_id, load_company_facts)

    assert problems == []


def test_every_brief_suite_figure_fact_matches_the_sec_reference(brief_suite, filings_by_id):
    if not (SEC_CACHE_DIR / "index.json").exists():
        pytest.skip("no SEC company-facts cache: run `make sec-facts`")

    problems = _figure_problems(brief_suite.cases, filings_by_id, load_company_facts)

    assert problems == []


MIX_TARGET = {
    "risk": (15, 5),
    "trend": (15, 5),
    "sector": (12, 4),
    "coverage_gap": (10, 3),
    "follow_up": (8, 3),
}
"""ADR 0012's mix of Golden Set version 2, (dev, holdout) cases by kind of question:
multi-Company risk comparisons, figure and outlook trends, sector questions, Coverage Gap
cases and follow-ups."""

_GAP_QUESTION_TYPES = {"missing_company", "stale_filing"}
_GAP_KINDS = {"snapshot_trend", "no_guidance"}
_GAP_TAGS = {"periods_differ_comparison"}


def _question_kind(case):
    """The case's kind in `MIX_TARGET`. A follow-up is one whatever it asks. A Coverage Gap
    case asks about a missing Company or a stale Filing, or for a trend or outlook the
    Filings cannot give, or is a comparison asked to test the periods differ gap (tagged
    `periods_differ_comparison`); elsewhere that gap only qualifies the answer and leaves
    the case in its question type's kind."""
    if case.history:
        return "follow_up"
    gap_kinds = {gap.kind for gap in case.expected_coverage_gaps}
    if (
        case.question_type in _GAP_QUESTION_TYPES
        or gap_kinds & _GAP_KINDS
        or _GAP_TAGS & set(case.tags)
    ):
        return "coverage_gap"
    return {"risk": "risk", "sector": "sector"}.get(case.question_type, "trend")


def _question_mix(cases):
    """Cases counted by kind of question, then by split."""
    mix = {}
    for case in cases:
        counts = mix.setdefault(_question_kind(case), {})
        counts[case.split] = counts.get(case.split, 0) + 1
    return mix


def test_the_mix_counts_each_case_once_by_its_kind_of_question(tmp_path):
    golden = load_golden_set(
        _v2_file(
            tmp_path,
            [
                _v2_case("risk-unh-cybersecurity", "dev"),
                _v2_case("risk-aapl-nvda-supply-chain", "holdout"),  # periods differ: a risk
                _v2_case("sector-banks-risks", "pending")
                | {"tags": ["periods_differ_comparison"]},  # asked to test the gap: a gap
                _v2_case("trend-aapl-revenue-fy2025", "dev"),
                _v2_case("outlook-meta-capex-2026", "holdout"),
                _v2_case("outlook-msft-cloud", "holdout"),  # no guidance: a gap
                _v2_case("sector-aerospace-government", "dev"),
                _v2_case("trend-jpm-revenue-snapshot", "dev"),  # a Snapshot trend: a gap
                _v2_case("missing-citigroup", "pending"),
                _v2_case("followup-tsla-risk-change", "dev"),  # a follow-up, not a risk case
            ],
        )
    )

    mix = _question_mix(golden.cases)

    assert mix == {
        "risk": {"dev": 1, "holdout": 1},
        "trend": {"dev": 1, "holdout": 1},
        "sector": {"dev": 1},
        "coverage_gap": {"dev": 1, "holdout": 1, "pending": 2},
        "follow_up": {"dev": 1},
    }


FROZEN_MIX = {
    "risk": {"dev": 14, "holdout": 6},
    "trend": {"dev": 12, "holdout": 4},
    "sector": {"dev": 13, "holdout": 3},
    "coverage_gap": {"dev": 15, "holdout": 2},
    "follow_up": {"dev": 6, "holdout": 5},
}
"""Version 2's mix once its split was frozen (issue #72), as `docs/golden-set.md` records
it. The hash decided the holdout's, so it is reported against `MIX_TARGET`, not adjusted
to it."""


def test_the_version_2_mix_is_reported_against_adr_0012s_table(golden_set_v2, capsys):
    """Reported, not enforced against the table: the hash decides the holdout mix. It is
    pinned as recorded in the docs, so a case that changes kind or split shows here."""
    mix = _question_mix(golden_set_v2.cases)

    assert mix == FROZEN_MIX
    assert set(MIX_TARGET) == set(FROZEN_MIX)
    with capsys.disabled():
        print(f"\nGolden Set version 2 mix ({len(golden_set_v2.cases)} cases), against ADR 0012:")
        for kind, (dev, holdout) in MIX_TARGET.items():
            counts = mix.get(kind, {})
            print(
                f"  {kind:<13} dev {counts.get('dev', 0)}/~{dev}, "
                f"holdout {counts.get('holdout', 0)}/~{holdout}"
            )


def test_a_small_version_2_file_passes_every_label_check(
    tmp_path, golden_set, brief_suite, filings_by_id
):
    v2 = load_golden_set(
        _v2_file(
            tmp_path,
            [_v2_case("risk-unh-cybersecurity"), _v2_case("trend-aapl-revenue-fy2025", "pending")],
        )
    )

    assert _source_problems(v2.cases, filings_by_id) == []
    assert _evidence_problems(v2.cases, filings_by_id) == []
    assert _repeated_questions(golden_set.cases, v2.cases, brief_suite.cases) == []
    assert set(_question_mix(v2.cases)) == {"risk", "trend"}
