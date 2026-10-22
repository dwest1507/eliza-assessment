"""Tests for the evaluation notes (`docs/evaluation.md`): a reader who opens them for the
results finds them first, and the history stays below."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NOTES = (REPO / "docs" / "evaluation.md").read_text(encoding="utf-8")


def _section(heading: str) -> str:
    [section] = re.findall(
        rf"^(#+) {re.escape(heading)}\n(.*?)(?=^#{{1,4}} |\Z)", NOTES, re.M | re.S
    )
    return section[1]


def test_at_a_glance_opens_the_notes():
    headings = re.findall(r"^## (.+)$", NOTES, re.M)
    assert headings[0] == "At a glance"
    lines = [line for line in _section("At a glance").splitlines() if line.strip()]
    assert 8 <= len(lines) <= 20, "At a glance is about 15 lines"


def test_at_a_glance_says_what_was_measured_the_numbers_their_meaning_and_the_limits():
    glance = _section("At a glance")
    for part in ("What was measured", "The headline numbers", "What they mean", "The main limits"):
        assert part in glance, f"At a glance leaves out {part!r}"


def test_the_full_history_stays_below():
    headings = re.findall(r"^## (.+)$", NOTES, re.M)
    for kept in ("Retrieval harness", "Generation harness", "Evaluation version 2"):
        assert kept in headings[1:], f"the history lost {kept!r}"


def test_the_holdout_rule_says_the_holdout_is_scored_once_more_only_on_the_final_setup():
    rule = _section("The holdout rule")
    assert "only on the final setup" in rule
