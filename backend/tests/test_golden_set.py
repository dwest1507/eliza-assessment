"""Tests for both Golden Set versions and the Brief Suite: their schema, the splits, the
starter prompts, and every file's labels against the Corpus.

The labels were drafted and reviewed by an agent, not a second human, so these tests are
the mechanical half of the review: every expected Filing and Section exists in the
Corpus, and every Required Fact's evidence quote is found word for word in its Section.
Version 2 adds: no question repeated across the three files, version 2's and the Brief
Suite's figure facts against the SEC company-facts reference (skipped without its
cache), the Brief Suite's variants of the brief's questions, and version 2's mix of
question kinds, reported against ADR 0012's table but not yet enforced.
"""

import hashlib
import json
import re

import pytest

from edgar_rag.corpus import load_corpus, load_sector_table
from edgar_rag.golden_set import (
    COVERAGE_GAP_KINDS,
    DEFAULT_BRIEF_SUITE,
    DEFAULT_GOLDEN_SET,
    DEFAULT_GOLDEN_SET_V2,
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
    return load_golden_set()


@pytest.fixture(scope="module")
def golden_set_v2():
    return load_golden_set(DEFAULT_GOLDEN_SET_V2)


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


def _rewrite(tmp_path, edit, source=DEFAULT_GOLDEN_SET):
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
    raw = json.loads(DEFAULT_GOLDEN_SET.read_text(encoding="utf-8"))
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
            assert fact.fact.endswith("."), (case.id, fact.fact)
            assert fact.evidence.strip(), (case.id, fact.fact)
            assert any(re.search(rf"\b{re.escape(n)}", fact.fact) for n in names), (
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
    digest = hashlib.sha256(DEFAULT_GOLDEN_SET.read_bytes()).hexdigest()

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
        load_brief_suite(DEFAULT_BRIEF_SUITE, (DEFAULT_GOLDEN_SET, v2))


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
    raw = json.loads(DEFAULT_GOLDEN_SET.read_text(encoding="utf-8"))
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
    assert DEFAULT_GOLDEN_SET_V2.parent == DEFAULT_GOLDEN_SET.parent
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


def test_new_version_2_cases_are_pending_until_the_split_is_frozen(golden_set, golden_set_v2):
    """A case version 1 does not hold is new, and stays pending until every new case is
    drafted and the split is frozen (ADR 0012)."""
    version_1 = {case.id for case in golden_set.cases}

    new = [case for case in golden_set_v2.cases if case.id not in version_1]

    assert all(case.split == "pending" for case in new), [c.id for c in new]


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


def _question_kind(case):
    """The case's kind in `MIX_TARGET`. A follow-up is one whatever it asks. A Coverage Gap
    case asks about a missing Company or a stale Filing, or for a trend or outlook the
    Filings cannot give; a gap that only qualifies the answer (`periods_differ`) leaves the
    case in its question type's kind."""
    if case.history:
        return "follow_up"
    gap_kinds = {gap.kind for gap in case.expected_coverage_gaps}
    if case.question_type in _GAP_QUESTION_TYPES or gap_kinds & _GAP_KINDS:
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
        "risk": {"dev": 1},
        "trend": {"dev": 1, "holdout": 1},
        "sector": {"dev": 1},
        "coverage_gap": {"dev": 1, "holdout": 1, "pending": 1},
        "follow_up": {"dev": 1},
    }


def test_the_version_2_mix_is_reported_against_adr_0012s_table(golden_set_v2, capsys):
    """Reported, not yet enforced: the set is still being drafted."""
    mix = _question_mix(golden_set_v2.cases)

    assert set(mix) <= set(MIX_TARGET)
    with capsys.disabled():
        print(f"\nGolden Set version 2 mix ({len(golden_set_v2.cases)} cases), against ADR 0012:")
        for kind, (dev, holdout) in MIX_TARGET.items():
            counts = mix.get(kind, {})
            pending = f", {counts['pending']} pending" if counts.get("pending") else ""
            print(
                f"  {kind:<13} dev {counts.get('dev', 0)}/~{dev}, "
                f"holdout {counts.get('holdout', 0)}/~{holdout}{pending}"
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
