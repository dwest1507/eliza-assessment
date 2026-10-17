"""Tests for the Golden Set and the Brief Suite: their schema, the Golden Set's split, the
starter prompts, and both files' labels against the Corpus.

The labels were drafted and reviewed by an agent, not a second human, so these tests are
the mechanical half of the review: every expected Filing and Section exists in the
Corpus, and every Required Fact's evidence quote is found word for word in its Section.
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
    QUESTION_TYPES,
    SPLIT_RULE,
    TIERS,
    assign_splits,
    load_brief_suite,
    load_golden_set,
    normalise_whitespace,
    starter_cases,
)

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
def brief_suite():
    return load_brief_suite()


@pytest.fixture(scope="module")
def labelled_cases(golden_set, brief_suite):
    """Every labelled case: the Golden Set's and the Brief Suite's."""
    return (*golden_set.cases, *brief_suite.cases)


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


def test_brief_suite_ids_are_unique_and_never_golden_set_ids(golden_set, brief_suite):
    ids = [case.id for case in brief_suite.cases]

    assert len(set(ids)) == len(ids)
    assert not set(ids) & {case.id for case in golden_set.cases}


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


def test_every_expected_filing_and_section_exists_in_the_corpus(labelled_cases, filings_by_id):
    for case in labelled_cases:
        for source in case.expected_sources:
            assert source.filing_id in filings_by_id, (case.id, source.filing_id)
            names = {s.name for s in filings_by_id[source.filing_id].sections}
            assert source.section in names, (case.id, source)


def test_every_evidence_quote_appears_verbatim_in_its_labelled_section(
    labelled_cases, filings_by_id
):
    for case in labelled_cases:
        for fact in case.required_facts:
            sections = filings_by_id[fact.filing_id].sections
            texts = [normalise_whitespace(s.text) for s in sections if s.name == fact.section]
            quote = normalise_whitespace(fact.evidence)
            assert any(quote in text for text in texts), (case.id, fact.filing_id, fact.evidence)


def test_whitespace_normalisation_only_collapses_whitespace():
    assert normalise_whitespace("$164.50\xa0billion,\n  up") == "$164.50 billion, up"
    assert normalise_whitespace("JPMorganChase’s") == "JPMorganChase’s"
