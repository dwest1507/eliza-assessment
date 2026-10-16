"""The generation harness's checks in code, on hand-written answers."""

import pytest

from edgar_eval.answer_checks import (
    check_citations,
    check_coverage_gaps,
    check_figures,
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

    check = check_figures(answer, PASSAGES, fact_values=())

    assert check.passed
    assert check.figures == 2


def test_a_figure_rounded_or_rescaled_from_a_cited_passage_is_exact():
    answer = "Net sales were $416.2 billion [S1]; net income was $1,200 million [S2]."

    assert check_figures(answer, PASSAGES, fact_values=()).passed


def test_a_figure_that_matches_a_financial_fact_is_exact():
    answer = "NVIDIA's revenue was $46.7 billion [S1], or $46,743 million."

    assert check_figures(answer, PASSAGES, fact_values=[NVDA_REVENUE]).passed


def test_a_figure_in_no_cited_passage_and_no_financial_fact_is_not_exact():
    answer = "Net sales were $420.0 billion [S1], up 6.4% [S1]; net income rose 15% [S2]."

    check = check_figures(answer, PASSAGES, fact_values=[NVDA_REVENUE])

    assert not check.passed
    assert check.unmatched == ("$420.0 billion", "6.4%")


def test_only_passages_the_answer_cites_count():
    answer = "Net income was $1.2 billion [S1]."

    assert check_figures(answer, PASSAGES, fact_values=()).unmatched == ("$1.2 billion",)


def test_a_percentage_must_appear_as_written_not_rescaled():
    # 46.9 appears in the passage, but 0.0469% is not 46.9%.
    assert not check_figures("Margin was 0.0469% [S1].", PASSAGES, fact_values=()).passed


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


def test_claims_are_the_cited_sentences_with_the_sources_they_rest_on():
    answer = """\
Apple outsources most manufacturing [S1]. It also faces new tariffs [S1, S2].

## Tesla

- Tesla depends on Elon Musk. Losing him would hurt the business [S3].

| Company | Risk |
|---|---|
| JPMorgan | Credit risk [S4] |

Tariffs matter.

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
    ]


def test_a_run_of_tags_after_the_full_stop_belongs_to_the_sentence_before_it():
    answer = "Apple faces tariffs. Tesla faces incentive cuts. [S1] [S5] [S8]"

    assert [(c.text, c.tags) for c in claims(answer)] == [
        ("Apple faces tariffs.", ("S1", "S5", "S8")),
        ("Tesla faces incentive cuts.", ("S1", "S5", "S8")),
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
