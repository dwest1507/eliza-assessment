"""Tests for the slide deck (`docs/deck.md`): its shape, and that its numbers trace.

The deck is drafted by an agent and reviewed by the developer. These tests are the
mechanical half of that review: every figure on a slide, speaker notes included, is found
word for word in a document that slide links to, so no number reaches the panel that the
evaluation records (or the EDA findings behind them) do not hold.
"""

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

REPO = Path(__file__).resolve().parents[2]
DECK = REPO / "docs" / "deck.md"

# A figure is an amount, a share, a count or a size: "0.67", "$0.0030", "25,500", "19%",
# "98k". Not figures: numbers inside labels, names and links ("10-K", "FY2025", "v7",
# "[S3]", "hit@10", "2026-10-16", "ADR 0009", "Item 1A", "assumptions 4 to 11", a URL's
# port), years, and single-digit counts, as in the generation harness's figure check.
_FIGURE = re.compile(
    r"(?<![\w@.\-/$#])\$?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(%|k\b|M\b)?(?![\w\-/@]|\.\d)"
)
_LABEL = re.compile(
    r"\b(?:ADR|Items?|version|assumptions?|findings?)\s+\d+\w*"
    r"(?:(?:,\s*|\s+and\s+|\s+to\s+)\d+\w*)*",
    re.I,
)
_URL = re.compile(r"https?://\S+")
_CODE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_YEAR = re.compile(r"(?:19|20)\d\d")


def _slides() -> list[str]:
    text = DECK.read_text(encoding="utf-8")
    front, _, body = text.removeprefix("---\n").partition("\n---\n")
    assert "marp: true" in front, "the deck is a Marp deck with front matter"
    return [s.strip() for s in re.split(r"\n---\n", body) if s.strip()]


def _figures(slide: str) -> list[str]:
    text = _LINK.sub("]", slide)
    text = _LABEL.sub(" ", _URL.sub(" ", _CODE.sub(" ", text)))
    found = []
    for match in _FIGURE.finditer(text):
        number, unit = match.group(1), match.group(2) or ""
        if _YEAR.fullmatch(number) or (number.isdigit() and int(number) < 10):
            continue
        found.append(number + unit)
    return found


def _linked_docs(slide: str) -> list[Path]:
    docs = []
    for target in _LINK.findall(slide):
        if "://" in target:
            continue
        path = (DECK.parent / unquote(target.split("#")[0])).resolve()
        if path.suffix == ".md":
            docs.append(path)
    return docs


def _appears(figure: str, text: str) -> bool:
    pattern = rf"(?<![\d.,]){re.escape(figure)}(?![\d]|[.,]\d)"
    return re.search(pattern, text) is not None


@pytest.fixture(scope="module")
def slides():
    return _slides()


def test_the_deck_has_about_eight_slides(slides):
    assert 7 <= len(slides) <= 9


def test_the_deck_covers_the_topics_of_the_presentation(slides):
    headings = [s.splitlines()[0].lower() for s in slides]
    for topic in ("problem", "value", "demo", "holdout", "risks", "future"):
        assert any(topic in h for h in headings), f"no slide heading names {topic!r}"


def test_the_evaluation_slide_uses_the_holdout_run(slides):
    [results] = [s for s in slides if "holdout" in s.splitlines()[0].lower()]
    assert "evaluation.md#the-holdout-run" in results


def test_the_future_state_follows_the_clients_answers(slides):
    """The Client confirmed one generative call is a hard requirement (assumption 1), and
    asked for live EDGAR ingestion to be proposed as the way to fill the gaps (assumption 2)."""
    [future] = [s for s in slides if "future" in s.splitlines()[0].lower()]
    lowered = future.lower()
    for item in (
        "data room",
        "edgar",
        "earnings-call transcripts",
        "alert",
        "passage-level citations",
    ):
        assert item in lowered, f"the future state leaves out {item!r}"
    assert "multi-step" not in lowered
    # Built in #153, so no longer a future step.
    assert "financial facts for every company" not in lowered


_NOTES = re.compile(r"<!--.*?-->", re.S)


def _body(slide: str) -> str:
    """A slide as the panel sees it: without its speaker notes."""
    return _NOTES.sub(" ", slide)


def _notes(slide: str) -> str:
    return " ".join(_NOTES.findall(slide))


def test_the_value_slide_carries_the_illustrative_value_model(slides):
    """The value model is assumption 12, not confirmed: the slide shows its calculation,
    says it is illustrative and links the assumption its inputs come from."""
    [value] = [s for s in slides if "value" in s.splitlines()[0].lower()]
    body = _body(value)
    assert "illustrative" in body.lower()
    assert "assumptions.md#12" in body
    for figure in ("720k", "$150", "48"):
        assert figure in body, f"the value slide leaves out {figure!r}"
    assumptions = (REPO / "docs" / "assumptions.md").read_text(encoding="utf-8")
    [twelve] = re.findall(r"^## 12\..*?(?=^## |\Z)", assumptions, re.M | re.S)
    assert "- **Status:** not confirmed" in twelve
    assert re.search(r"^\| 12 \|.*\| not confirmed \|$", assumptions, re.M)


def test_the_choices_slide_keeps_its_statistics_in_the_speaker_notes(slides):
    [choices] = [s for s in slides if "choices" in s.splitlines()[0].lower()]
    body = _LINK.sub("]", _body(choices))
    for term in (r"\bp\s*[=<]", r"McNemar", r"Control Run", r"one-sided"):
        assert not re.search(term, body), f"the choices slide shows {term!r} outside its notes"
    assert re.search(r"\bp\s*=", _notes(choices)), "the statistics belong in the notes"


def test_the_risks_slide_reports_the_human_check(slides):
    """The developer's blind labels of 15 fact items (#152) replace "no human in the loop":
    the slide states both agreements, links the section, and says the claim labels are
    still Claude's alone."""
    [risks] = [s for s in slides if "risks" in s.splitlines()[0].lower()]
    body = _body(risks)
    assert "evaluation.md#the-human-check" in body
    assert "no human in the loop" not in body.lower()
    for figure in ("15 fact labels", "80%", "87%"):
        assert figure in body, f"the risks slide leaves out {figure!r}"
    assert re.search(r"claim labels[^.]*Claude's alone", body)


def test_no_slide_mentions_the_brief_suite(slides):
    assert not [n for n, s in enumerate(slides, start=1) if "brief suite" in s.lower()]


def test_the_figure_rule_reads_figures_not_labels():
    slide = (
        "Fact Recall 0.67 at $0.0030 per answer, 25,500 tokens, 19% growth, about 98k "
        "tokens, in 3 runs: `gpt-6-luna`, FY2025 10-K [S3], hit@10, 2026-10-16, ADR 0009, "
        "v7, Item 1A, 2025, assumptions 1, 2, 7 and 10, http://localhost:3000, "
        "[the run](evaluation.md#the-holdout-run)."
    )
    assert _figures(slide) == ["0.67", "0.0030", "25,500", "19%", "98k"]


def test_every_figure_on_a_slide_is_in_a_document_the_slide_links_to(slides):
    untraced = []
    for number, slide in enumerate(slides, start=1):
        figures = _figures(slide)
        docs = _linked_docs(slide)
        for doc in docs:
            assert doc.is_file(), f"slide {number} links to a missing document: {doc}"
        texts = [doc.read_text(encoding="utf-8") for doc in docs]
        untraced += [
            f"slide {number}: {figure}"
            for figure in figures
            if not any(_appears(figure, text) for text in texts)
        ]
    assert not untraced, "figures not found in the documents their slide links to:\n" + (
        "\n".join(untraced)
    )
