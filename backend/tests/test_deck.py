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
# The deck links the repository's documents by their public GitHub URLs on main, so a
# copy handed to someone without the repository still opens them.
GITHUB = "https://github.com/dwest1507/eliza-assessment/blob/main/"

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


def _repo_path(target: str) -> Path | None:
    """The repository file a link's GitHub URL names, or None for any other link."""
    if not target.startswith(GITHUB):
        return None
    return REPO / unquote(target.removeprefix(GITHUB).split("#")[0])


def _linked_docs(slide: str) -> list[Path]:
    docs = []
    for target in _LINK.findall(slide):
        path = _repo_path(target)
        if path is not None and path.suffix == ".md":
            docs.append(path)
    return docs


def _anchors(doc: Path) -> set[str]:
    """The heading anchors GitHub gives a Markdown file: lower case, punctuation other
    than hyphens dropped, spaces as hyphens, a repeated heading numbered from -1."""
    seen: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6} +(.+?) *$", doc.read_text(encoding="utf-8"), re.M):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        if count:
            seen[f"{slug}-{count}"] = 1
    return set(seen)


def _appears(figure: str, text: str) -> bool:
    """A figure appears word for word, or, a whole percentage, as the share the documents
    record: "74%" traces to "0.74", since the slides speak in percentages."""
    candidates = [figure]
    if re.fullmatch(r"\d{1,2}%", figure):
        candidates.append(f"0.{int(figure[:-1]):02d}")
    return any(re.search(rf"(?<![\d.,]){re.escape(c)}(?![\d]|[.,]\d)", text) for c in candidates)


@pytest.fixture(scope="module")
def slides():
    return _slides()


def test_the_deck_has_about_eight_slides(slides):
    assert 7 <= len(slides) <= 9


def _slide(slides: list[str], heading: str) -> str:
    [slide] = [s for s in slides if heading in s.splitlines()[0].lower()]
    return slide


def test_the_deck_covers_the_topics_of_the_presentation(slides):
    """Eight slides for the Client, in this order, then one appendix slide."""
    headings = [s.splitlines()[0].lower() for s in slides]
    topics = (
        "checked answer",
        "problem",
        "value",
        "demo",
        "how we know it works",
        "completeness or reliability",
        "limits",
        "next step",
        "appendix",
    )
    assert len(headings) == len(topics)
    for heading, topic in zip(headings, topics, strict=True):
        assert topic in heading, f"expected a slide on {topic!r}, found {heading!r}"


def test_the_evaluation_slide_uses_the_final_holdout_run(slides):
    results = _slide(slides, "how we know it works")
    assert "evaluation.md#the-final-all-model-round" in results
    assert "20 questions" in _body(results)


def test_the_model_slide_shows_the_trade_off_in_plain_words(slides):
    """Completeness (Fact Recall) and Reliability (Faithfulness), as percentages, for every
    model of the final round, so the Client can weigh one against the other."""
    body = _body(_slide(slides, "completeness or reliability"))
    assert "Completeness" in body and "Reliability" in body
    for model in ("gpt-6-luna", "gpt-6.1-sol", "gpt-5.6-terra", "Haiku", "Sonnet", "Opus"):
        assert model in body, f"the model slide leaves out {model!r}"


# Glossary terms the panel hasn't been taught: the slides say them in plain words, and only
# the speaker notes use them.
_JARGON = ("Fact Recall", "Faithfulness", "Query Scope", "Corpus", "Answer Call", "Golden Set")


def test_the_slides_speak_plain_language(slides):
    for number, slide in enumerate(slides, start=1):
        body = _LINK.sub("]", _body(slide))
        for term in _JARGON:
            assert term not in body, f"slide {number} shows {term!r} outside its notes"
        for stat in (r"\bp\s*[=<]", r"McNemar", r"Control Run", r"one-sided"):
            assert not re.search(stat, body), f"slide {number} shows {stat!r} outside its notes"


def test_the_future_state_follows_the_clients_answers(slides):
    """The Client confirmed one generative call is a hard requirement (assumption 1), and
    asked for live EDGAR ingestion to be proposed as the way to fill the gaps (assumption 2)."""
    future = _slide(slides, "next step")
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
    # The deck closes on a pilot, not on a list of features.
    assert "proposed next step" in _body(future).lower()
    assert "pilot" in _body(future).lower()


_NOTES = re.compile(r"<!--.*?-->", re.S)


def _body(slide: str) -> str:
    """A slide as the panel sees it: without its speaker notes."""
    return _NOTES.sub(" ", slide)


def _notes(slide: str) -> str:
    return " ".join(_NOTES.findall(slide))


def test_the_value_slide_carries_the_illustrative_value_and_cost(slides):
    """The value model is assumption 12 and the fully loaded running cost assumption 13,
    both not confirmed: the slide shows the calculation and both results, says they are
    illustrative and links the assumptions their inputs come from."""
    body = _body(_slide(slides, "value"))
    assert "illustrative" in body.lower()
    assert "assumptions.md#12" in body
    assert "assumptions.md#13" in body
    for figure in ("360k", "$150", "48", "$90k", "$46k"):
        assert figure in body, f"the value slide leaves out {figure!r}"
    assumptions = (REPO / "docs" / "assumptions.md").read_text(encoding="utf-8")
    for number in (12, 13):
        [section] = re.findall(rf"^## {number}\..*?(?=^## |\Z)", assumptions, re.M | re.S)
        assert "- **Status:** not confirmed" in section
        assert re.search(rf"^\| {number} \|.*\| not confirmed \|$", assumptions, re.M)


def test_the_choices_slide_keeps_its_statistics_in_the_speaker_notes(slides):
    choices = _slide(slides, "choices")
    assert re.search(r"\bp\s*=", _notes(choices)), "the statistics belong in the notes"


def test_the_limits_slide_reports_the_human_check(slides):
    """The developer's blind labels of 15 fact items (#152) replace "no human in the loop":
    the slide names the check and links the section, and its notes state both agreements
    and say the claim labels are still Claude's alone."""
    limits = _slide(slides, "limits")
    body = _body(limits)
    assert "evaluation.md#the-human-check" in body
    assert "15 fact labels" in body
    assert "no human in the loop" not in limits.lower()
    for figure in ("80%", "87%"):
        assert figure in limits, f"the limits slide leaves out {figure!r}"
    assert re.search(r"claim labels[^.]*Claude's alone", limits)


def test_every_link_opens_without_the_repository():
    """A link to a repository document is its GitHub URL on main, naming a file that
    exists and, when it has an anchor, a heading in it; no link is a local path."""
    for target in _LINK.findall(DECK.read_text(encoding="utf-8")):
        assert "://" in target, f"{target!r} is a local path, not a public URL"
        path = _repo_path(target)
        if path is None:
            continue
        assert path.is_file(), f"{target!r} names no file in the repository"
        _, _, anchor = target.partition("#")
        if anchor:
            assert anchor in _anchors(path), f"{target!r} names no heading of {path.name}"


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
