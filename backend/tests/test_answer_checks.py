"""The generation harness's checks in code, on hand-written answers."""

import pytest

from edgar_eval.answer_checks import (
    check_citations,
    check_coverage_gaps,
    check_figures,
    check_structure,
    claims,
    figures,
)
from edgar_rag.golden_set import CoverageGapLabel

# --- Citation validity --------------------------------------------------------------------

GOOD = """\
Apple and Tesla both depend on outside manufacturing, but their exposures differ [S1][S3].

## Apple (AAPL)

- Most manufacturing is done by partners in Asia [S1].
- New U.S. tariffs were announced in fiscal 2025 [S1, S2].

| Company | Main risk |
|---|---|
| Apple | Outsourced manufacturing [S1] |
| Tesla | Dependence on Elon Musk [S3] |

Key differences:

1. Tesla's risks centre on one person [S3].

**Coverage:** JPMorgan's risk factors were not among the Sources.
"""


def test_an_answer_whose_every_paragraph_cites_a_listed_source_passes():
    check = check_citations(GOOD, source_numbers={1, 2, 3})

    assert check.passed
    assert check.unknown_tags == ()
    assert check.uncited == ()


def test_a_tag_that_is_not_among_this_turns_sources_fails():
    answer = "Apple outsources manufacturing [S1]. Tesla depends on Elon Musk [S7]."

    check = check_citations(answer, source_numbers={1, 2, 3})

    assert not check.passed
    assert check.unknown_tags == ("S7",)


def test_tags_written_together_in_one_bracket_are_each_checked():
    check = check_citations("Both face tariffs [S1, S9; S2].", source_numbers={1, 2})

    assert check.unknown_tags == ("S9",)


def test_a_range_of_tags_cites_every_source_in_it():
    check = check_citations("All five filings discuss risk [S1–S3] [S4-S6].", {1, 2, 3, 4, 5})

    assert check.uncited == ()
    assert check.unknown_tags == ("S6",)


def test_a_paragraph_list_item_or_table_row_without_a_tag_fails():
    answer = """\
Apple outsources manufacturing [S1].

Tesla depends on Elon Musk.

- Tariffs rose in 2025.

| Company | Risk |
|---|---|
| JPMorgan | Credit risk |
"""
    check = check_citations(answer, source_numbers={1})

    assert not check.passed
    assert check.uncited == (
        "Tesla depends on Elon Musk.",
        "Tariffs rose in 2025.",
        "| JPMorgan | Credit risk |",
    )


def test_headings_lead_ins_and_the_coverage_note_need_no_tag():
    answer = """\
# Risk comparison

**Apple**

Apple outsources manufacturing [S1].

The main differences:

## Coverage

The Sources do not include JPMorgan's 10-K risk factors.

Coverage: no guidance is given in the Filings.
"""
    assert check_citations(answer, source_numbers={1}).passed


# --- Figure exactness ---------------------------------------------------------------------

PASSAGES = {
    1: "Total net sales | 416,161 | 391,035 (in millions). Gross margin was 46.9%.",
    2: "Net income attributable to the Company was $1.2 billion, up 15% on the prior year.",
}
NVDA_REVENUE = 46_743_000_000  # a Financial Fact, in whole US dollars
# Each Source's Filing's Financial Facts: S1's Filing reports NVIDIA's revenue.
FACTS = {1: [NVDA_REVENUE], 2: []}


def test_figures_are_amounts_percentages_and_counts_but_not_years_dates_or_labels():
    text = (
        "In fiscal 2025 (FY2025, Q3 FY2026) Apple's 10-K Item 1A, filed as "
        "AAPL_10-K_2025-09-27 on September 27, 2025, reported net sales of $416,161 million "
        "[S1], a 46.9% gross margin, 3 segments and 166,000 employees, "
        "for 2024-09-28 to 2025-09-27."
    )

    assert [f.text for f in figures(text)] == ["$416,161 million", "46.9%", "166,000"]


def test_a_figure_found_in_a_cited_passage_is_exact():
    answer = "Net sales were $416,161 million [S1], with a 46.9% gross margin [S1]."

    check = check_figures(answer, PASSAGES, fact_values={})

    assert check.passed
    assert check.figures == 2


def test_a_figure_rounded_or_rescaled_from_a_cited_passage_is_exact():
    answer = "Net sales were $416.2 billion [S1]; net income was $1,200 million [S2]."

    assert check_figures(answer, PASSAGES, fact_values={}).passed


def test_a_figure_that_matches_a_financial_fact_of_a_cited_filing_is_exact():
    answer = "NVIDIA's revenue was $46.7 billion [S1], or $46,743 million."

    assert check_figures(answer, PASSAGES, fact_values=FACTS).passed


def test_a_figure_matching_only_an_uncited_filings_financial_fact_is_not_exact():
    # S1's Filing reports the revenue, but the answer cites only S2: a figure for the
    # wrong period, or from a Filing the answer never cites, must not pass.
    answer = "NVIDIA's revenue was $46.7 billion [S2]."

    check = check_figures(answer, PASSAGES, fact_values=FACTS)

    assert not check.passed
    assert check.unmatched == ("$46.7 billion",)


def test_a_figure_in_no_cited_passage_and_no_financial_fact_is_not_exact():
    answer = "Net sales were $420.0 billion [S1], up 6.4% [S1]; net income rose 15% [S2]."

    check = check_figures(answer, PASSAGES, fact_values=FACTS)

    assert not check.passed
    assert check.unmatched == ("$420.0 billion", "6.4%")


def test_only_passages_the_answer_cites_count():
    answer = "Net income was $1.2 billion [S1]."

    assert check_figures(answer, PASSAGES, fact_values={}).unmatched == ("$1.2 billion",)


def test_a_percentage_must_appear_as_written_not_rescaled():
    # 46.9 appears in the passage, but 0.0469% is not 46.9%.
    assert not check_figures("Margin was 0.0469% [S1].", PASSAGES, fact_values={}).passed


# --- Coverage Gaps ------------------------------------------------------------------------

NAMES = {
    "JPM": ("JPM", "JPMorgan Chase", "JPMorgan"),
    "NVDA": ("NVDA", "NVIDIA"),
    "GE": ("GE", "General Electric", "GE Capital"),
    "AAPL": ("AAPL", "Apple"),
    # Companies missing from the Corpus, so a sentence about one is not taken for another.
    "Citigroup": ("Citigroup",),
}


def gap(kind, *companies):
    return CoverageGapLabel(kind=kind, companies=companies)


@pytest.mark.parametrize(
    ("label", "statement"),
    [
        (
            gap("snapshot_trend", "JPM"),
            "Trend unavailable: JPMorgan is a Snapshot Company. The Corpus holds four "
            "JPMorgan Filings, Q1–Q4 2025, so this answer covers 2025 only.",
        ),
        (
            gap("snapshot_trend", "JPM"),
            "The Sources only cover JPMorgan's 2025 filings, so no multi-year trend can be shown.",
        ),
        (
            gap("missing_company", "Wells Fargo"),
            "Wells Fargo is not in the Corpus, so it cannot be compared.",
        ),
        (
            gap("missing_company", "Bristol Myers Squibb"),
            "No filings for Bristol-Myers Squibb were provided.",
        ),
        (
            gap("missing_company", "Citigroup"),
            "The Sources do not provide Citigroup's own risk-factor disclosures.",
        ),
        (
            gap("missing_company", "Bristol Myers Squibb"),
            "The provided sources do not describe Bristol Myers Squibb's own regulatory risks.",
        ),
        (
            gap("missing_company", "Honeywell"),
            "The Sources provided contain no Honeywell filings, so its performance is unknown.",
        ),
        (
            gap("missing_company", "Wells Fargo"),
            "The supplied filings cover JPMorgan's risks, but do not include Wells Fargo "
            "filings, so a comparison is not possible.",
        ),
        (
            gap("missing_company", "Honeywell"),
            "I can't assess Honeywell's recent performance because no filing excerpts were "
            "provided.",
        ),
        (
            gap("missing_company", "Bristol Myers Squibb"),
            "The Sources provide no Bristol Myers Squibb filing evidence.",
        ),
        (
            gap("missing_company", "Bristol Myers Squibb"),
            "The Sources contain Merck's FY2024 Form 10-K, but no Bristol Myers Squibb filing "
            "evidence.",
        ),
        (
            gap("stale_filing", "GE"),
            "These excerpts do not establish GE's overall performance and do not provide "
            "post-2014 results.",
        ),
        (
            gap("stale_filing", "GE"),
            "The only General Electric Filing is GE Capital's 10-K for 2014; it does not "
            "describe General Electric today.",
        ),
        (
            gap("no_guidance", "NVDA"),
            "NVIDIA's own revenue guidance is not in the Filings provided; the outlook below "
            "is drawn from MD&A commentary and risk factors.",
        ),
        (
            gap("no_guidance", "NVDA"),
            "The filings do not include forward revenue guidance from NVIDIA.",
        ),
        (
            gap("periods_differ", "AAPL", "JPM"),
            "Note that the periods differ: Apple's fiscal year ended 27 September 2025, "
            "JPMorgan's on 31 December 2025.",
        ),
        (
            gap("periods_differ", "AAPL", "JPM"),
            "These filings cover different fiscal periods.",
        ),
    ],
)
def test_a_coverage_gap_stated_in_the_answer_is_found(label, statement):
    answer = f"Revenue rose [S1].\n\n## Coverage\n\n{statement}"

    check = check_coverage_gaps(answer, [label], NAMES)

    assert check.passed
    assert check.stated == (label.kind,)


@pytest.mark.parametrize(
    ("label", "answer"),
    [
        # A trend answered as if JPMorgan were tracked over years.
        (gap("snapshot_trend", "JPM"), "JPMorgan's revenue grew in 2025 [S1]."),
        # The gap is stated, but for another Company.
        (gap("missing_company", "Wells Fargo"), "Citigroup is not in the Corpus."),
        (gap("stale_filing", "GE"), "GE Capital reported net earnings in 2014 [S1]."),
        # Outlook words without saying guidance is missing.
        (gap("no_guidance", "NVDA"), "NVIDIA's outlook depends on data center demand [S1]."),
        (gap("periods_differ", "AAPL", "JPM"), "Apple and JPMorgan both list risks [S1]."),
    ],
)
def test_a_coverage_gap_left_unstated_is_missing(label, answer):
    check = check_coverage_gaps(answer, [label], NAMES)

    assert not check.passed
    assert check.missing == (label.kind,)


def test_a_gap_about_several_companies_must_be_stated_for_each():
    answer = "Wells Fargo is not in the Corpus [S1]. Citigroup reported strong results."

    check = check_coverage_gaps(answer, [gap("missing_company", "Wells Fargo", "Citigroup")], {})

    assert check.missing == ("missing_company",)


def test_an_answer_with_no_expected_gap_passes():
    assert check_coverage_gaps("Revenue rose [S1].", [], NAMES).passed


# --- Claims for the Faithfulness judgment -------------------------------------------------


def test_claims_are_every_sentence_with_the_sources_it_rests_on():
    answer = """\
Apple outsources most manufacturing [S1]. It also faces new tariffs [S1, S2].

## Tesla

- Tesla depends on Elon Musk. Losing him would hurt the business [S3].

| Company | Risk |
|---|---|
| JPMorgan | Credit risk [S4] |

Tariffs matter. Tesla's margins fell in 2025.

## Coverage

No guidance is in the Filings.
"""
    assert [(c.text, c.tags) for c in claims(answer)] == [
        ("Apple outsources most manufacturing.", ("S1",)),
        ("It also faces new tariffs.", ("S1", "S2")),
        # A sentence without its own tag rests on the tags of its paragraph.
        ("Tesla depends on Elon Musk.", ("S3",)),
        ("Losing him would hurt the business.", ("S3",)),
        ("| JPMorgan | Credit risk |", ("S4",)),
        # A paragraph that cites nothing still makes claims: each rests on no Source.
        ("Tariffs matter.", ()),
        ("Tesla's margins fell in 2025.", ()),
    ]


@pytest.mark.parametrize(
    "exempt",
    [
        pytest.param("## Apple's risks", id="heading"),
        pytest.param("**Apple (AAPL)**", id="bold label"),
        pytest.param("| Company | Main risk |\n|---|---|", id="table header"),
        pytest.param("Three risks stand out:", id="colon lead-in"),
        pytest.param("The Sources do not include Honeywell's filings.", id="missing company"),
        pytest.param("Tesla gives no 2026 revenue guidance in its Filings.", id="no guidance"),
        pytest.param("Apple's and Tesla's fiscal years end on different dates.", id="periods"),
        pytest.param("GE Capital's FY2014 10-K is a decade old.", id="stale filing"),
        pytest.param("Only Moderna's 2025 10-K is in the Corpus.", id="snapshot trend"),
        pytest.param("I can't determine Microsoft's revenue trend.", id="absence"),
        pytest.param("**Coverage:** Apple's FY2025 10-K only.", id="coverage note"),
    ],
)
def test_headings_coverage_gap_wordings_and_colon_lead_ins_make_no_claim(exempt):
    answer = f"Apple outsources manufacturing [S1].\n\nApple sells iPhones.\n\n{exempt}"

    assert [(c.text, c.tags) for c in claims(answer)] == [
        ("Apple outsources manufacturing.", ("S1",)),
        ("Apple sells iPhones.", ()),
    ]


def test_only_the_lead_in_sentence_of_a_paragraph_ending_in_a_colon_is_exempt():
    answer = "Apple names three risks. They are:\n\n- Tariffs [S1].\n\nApple sells iPhones [S2]:"

    assert [(c.text, c.tags) for c in claims(answer)] == [
        ("Apple names three risks.", ()),
        ("Tariffs.", ("S1",)),
        # A cited sentence is judged whatever it ends with.
        ("Apple sells iPhones:", ("S2",)),
    ]


def test_each_claim_carries_its_nearest_heading_and_a_table_row_its_header_row():
    answer = """\
Apple outsources most manufacturing [S1].

## Apple's risks

It faces new tariffs [S1].

**Tesla (TSLA)**

It depends on its CEO [S2].

| Company | FY2025 revenue [S3] |
|---|---|
| Apple | $416.2 billion [S3] |

## Outlook

Revenue may grow [S4].
"""

    assert [(c.text, c.heading, c.table_header) for c in claims(answer)] == [
        ("Apple outsources most manufacturing.", "", ""),  # above any heading
        ("It faces new tariffs.", "Apple's risks", ""),
        ("It depends on its CEO.", "Tesla (TSLA)", ""),  # a bold label heads what follows
        ("| Apple | $416.2 billion |", "Tesla (TSLA)", "| Company | FY2025 revenue |"),
        ("Revenue may grow.", "Outlook", ""),  # a heading ends the table before it
    ]


def test_a_run_of_tags_after_the_full_stop_belongs_to_the_sentence_before_it():
    answer = "Apple faces tariffs. Tesla faces incentive cuts. [S1] [S5] [S8]"

    assert [(c.text, c.tags) for c in claims(answer)] == [
        ("Apple faces tariffs.", ("S1", "S5", "S8")),
        ("Tesla faces incentive cuts.", ("S1", "S5", "S8")),
    ]


def test_a_sentence_with_u_s_before_a_capital_is_one_claim():
    answer = "Apple relies on the U.S. Government for X [S1]. Tesla sells cars [S2]."

    assert [(c.text, c.tags) for c in claims(answer)] == [
        ("Apple relies on the U.S. Government for X.", ("S1",)),
        ("Tesla sells cars.", ("S2",)),
    ]


@pytest.mark.parametrize(
    "sentence",
    [
        pytest.param("Lockheed depends on U.S. Government contracts [S1].", id="U.S."),
        pytest.param("Sales to the U.K. National Health Service grew [S1].", id="U.K."),
        pytest.param("Apple Inc. Services revenue grew [S1].", id="Inc."),
        pytest.param("Lockheed Martin Corp. Aeronautics leads its sales [S1].", id="Corp."),
        pytest.param("JPMorgan Chase & Co. Consumer banking grew [S1].", id="Co."),
        pytest.param("Arm Holdings Ltd. Licensing revenue rose [S1].", id="Ltd."),
        pytest.param("**U.S. Government** contracts drive sales [S1].", id="bold U.S."),
    ],
)
def test_common_abbreviations_before_a_capital_do_not_end_a_sentence(sentence):
    answer = f"{sentence} Tesla sells cars [S2]."

    assert [c.text for c in claims(answer)] == [
        sentence.replace(" [S1]", ""),
        "Tesla sells cars.",
    ]


def test_a_tag_after_an_abbreviation_still_ends_the_sentence():
    answer = "Apple sells in the U.S. [S1] Tesla sells cars [S2]."

    assert [(c.text, c.tags) for c in claims(answer)] == [
        ("Apple sells in the U.S.", ("S1",)),
        ("Tesla sells cars.", ("S2",)),
    ]


def test_a_coverage_note_that_starts_mid_paragraph_makes_no_claim():
    answer = (
        "Apple and Tesla differ [S1] [S2]. **Coverage:** The Sources do not include "
        "JPMorgan's risk factors. They do not support a ranking.\n\n"
        "Nor do they give guidance."
    )

    assert [c.text for c in claims(answer)] == ["Apple and Tesla differ."]
    assert check_citations(answer, source_numbers={1, 2}).passed


def test_a_gap_sentence_that_names_no_company_counts_for_the_company_its_paragraph_names():
    answer = (
        "Tesla's 10-K discusses capital spending [S1]. The Sources do not give a 2026 "
        "forecast for revenue or deliveries."
    )

    assert check_coverage_gaps(answer, [gap("no_guidance", "TSLA")], {"TSLA": ("Tesla",)}).passed
    # But not when the sentence is about another Company.
    other = "Tesla's 10-K discusses capital spending [S1]. NVIDIA gives no revenue guidance."
    names = {"TSLA": ("Tesla",), "NVDA": ("NVIDIA",)}
    assert not check_coverage_gaps(other, [gap("no_guidance", "TSLA")], names).passed


def test_a_paragraph_that_only_says_what_the_sources_lack_needs_no_tag():
    answer = """\
The Sources provided contain no Honeywell filings.

| Company | Exposure |
|---|---|
| Apple | No Apple filing is included in the Sources. |
| Tesla | Heavy regulation of autonomous driving. |

I can't determine Microsoft's revenue trend: no SEC filing excerpts were supplied for \
Microsoft. The earlier conversation concerns NVIDIA and is not evidence about Microsoft. \
**Coverage:** Microsoft's figures are not available in the Sources.
"""
    check = check_citations(answer, source_numbers={1})

    assert check.uncited == ("| Tesla | Heavy regulation of autonomous driving. |",)


def test_saying_that_the_earlier_answer_is_not_evidence_needs_no_tag():
    answer = (
        "The provided Sources do not establish how Tesla's risks changed. The prior answer is "
        "context only and is not supported by a Tesla risk-factor excerpt in this turn.\n\n"
        "The earlier discussion concerns NVIDIA and does not provide evidence about Microsoft."
    )

    assert check_citations(answer, source_numbers={1}).passed


def test_a_gap_about_one_company_may_be_stated_without_naming_it_again():
    answer = (
        "Tesla expects capital expenditures above $20 billion [S1].\n\n"
        "**Coverage:** The excerpts do not provide a 2026 forecast for revenue."
    )

    assert check_coverage_gaps(answer, [gap("no_guidance", "TSLA")], {"TSLA": ("Tesla",)}).passed


# --- Answer structure (assumption 8) ------------------------------------------------------

COMPANIES = {"AAPL": ("Apple Inc", "Apple"), "TSLA": ("Tesla Inc", "Tesla")}
FILLER = " ".join(["Apple relies on partners in Asia for most of its manufacturing [S1]."] * 30)


def structured(opening: str = "", body: str = "", coverage: str = "") -> str:
    """An answer in the shape of assumption 8, with any part replaced."""
    return "\n\n".join(
        (
            opening
            or "Apple and Tesla both depend on outside suppliers [S1][S3]. Tesla's risks also "
            "centre on one person [S3].",
            body
            or f"## Apple (AAPL)\n\n{FILLER}\n\n## Tesla (TSLA)\n\n"
            "- Tesla depends on Elon Musk [S3].",
            coverage or "**Coverage:** JPMorgan's risk factors were not among the Sources.",
        )
    )


def test_an_answer_in_the_analyst_structure_passes():
    check = check_structure(structured(), COMPANIES)

    assert check.passed, check.problems
    assert 300 <= check.words <= 600


@pytest.mark.parametrize(
    "opening",
    [
        "## Apple (AAPL)",
        "| Company | Main risk |\n|---|---|\n| Apple | Outsourcing [S1] |",
        "- Apple outsources manufacturing [S1].",
        (
            "Apple outsources [S1]. Tesla depends on Elon Musk [S3]. Both face tariffs [S1]. "
            "Apple sells abroad [S1]. Tesla builds factories [S3]."
        ),
    ],
)
def test_an_answer_that_does_not_open_with_a_short_direct_answer_fails(opening):
    check = check_structure(structured(opening=opening), COMPANIES)

    assert not check.passed
    assert any("direct answer" in p for p in check.problems)


def test_several_companies_need_a_heading_each_or_a_comparison_table():
    no_tesla_heading = f"## Apple (AAPL)\n\n{FILLER} Tesla depends on Elon Musk [S3]."
    table = (
        f"{FILLER}\n\n| Company | Main risk |\n|---|---|\n"
        "| Apple | Outsourcing [S1] |\n| Tesla | Elon Musk [S3] |"
    )

    failing = check_structure(structured(body=no_tesla_heading), COMPANIES)
    assert any("per Company" in p for p in failing.problems)
    assert check_structure(structured(body=table), COMPANIES).passed
    single = check_structure(structured(body=FILLER), {"AAPL": COMPANIES["AAPL"]})
    assert single.passed, single.problems


@pytest.mark.parametrize(
    "coverage",
    [
        "### Coverage\n\nJPMorgan's risk factors were not among the Sources.",
        (
            "Tesla also faces tariffs [S3]. **Coverage:** JPMorgan's risk factors were not "
            "among the Sources."
        ),
    ],
)
def test_a_closing_coverage_note_may_be_a_heading_or_a_bold_label(coverage):
    check = check_structure(structured(coverage=coverage), COMPANIES)

    assert check.passed, check.problems


@pytest.mark.parametrize(
    "coverage",
    [
        "Tesla also faces tariffs [S3].",
        (
            "**Coverage:** JPMorgan's risk factors were not among the Sources.\n\n"
            "## Tesla (TSLA)\n\nTesla also faces tariffs [S3]."
        ),
    ],
)
def test_an_answer_that_does_not_end_with_a_coverage_note_fails(coverage):
    check = check_structure(structured(coverage=coverage), COMPANIES)

    assert any("Coverage note" in p for p in check.problems)


@pytest.mark.parametrize(("repeats", "verdict"), [(4, "under 300"), (110, "over 600")])
def test_an_answer_outside_300_to_600_words_fails(repeats, verdict):
    body = " ".join(["Apple relies on partners in Asia [S1]."] * repeats)
    check = check_structure(
        structured(body=f"{body}\n\n| A | B |\n|---|---|\n| x | y |"), COMPANIES
    )

    assert [p for p in check.problems if "words" in p] == [f"{check.words} words, {verdict}"]


def test_an_answer_with_no_sources_need_only_open_with_its_direct_answer():
    answer = "Honeywell is not in the Filings provided, so I can't assess its performance."

    check = check_structure(answer, {})

    assert check.passed, check.problems
