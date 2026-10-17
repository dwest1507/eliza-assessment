"""Repeated text, internal to the retrieval seam.

Most Filing text repeats from one period to the next (finding 17). Repetition is measured
as in the EDA (notebook section 6): a text is lower-cased and split into words, every run
of eight consecutive words is one shingle, and the share of a text's shingles found in
another text is the share of it that repeats. Eight words is long enough that common
phrases rarely match by chance and short enough that a small edit only breaks the
shingles around it.

The index uses it to find the text in each chunk that is new since the Company's previous
Filing of the same Form Type; the query uses it to drop near-duplicate chunks. The Corpus
text keeps no paragraph breaks, so new text is found sentence by sentence: a run of new
sentences is a new paragraph.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

SHINGLE_WORDS = 8

NEAR_DUPLICATE = 0.8
"""A retrieved chunk with at least this share of its shingles in more recent retrieved
chunks (or in chunks from the period the question names) is a near-duplicate."""

NEW_TEXT = 0.5
"""A sentence is new in its Filing when at least this share of its shingles is absent
from the previous Filing of the same Form Type."""

MIN_NEW_WORDS = 30
"""A chunk holds new text only if its new sentences add up to at least this many words,
so a date or a figure updated in place does not count as a new paragraph."""

GAP = "\n[…]\n"
"""What stands between two passages that are not contiguous in the Filing."""

_WORD = re.compile(r"[a-z0-9]+")


def shingles(text: str) -> set[int]:
    """The text's 8-word shingles, hashed. Hashes are only compared within one process."""
    words = _WORD.findall(text.lower())
    return {hash(tuple(words[i : i + SHINGLE_WORDS])) for i in range(len(words) - 7)}


def new_text(sentences: Sequence[str], earlier: set[int] | None) -> str | None:
    """The runs of new sentences in a chunk, joined by `GAP`, or None when the chunk has
    no earlier Filing to compare with or too little new text. A sentence too short to
    hold a shingle (a heading) joins a run only between two new sentences."""
    if earlier is None:
        return None
    runs: list[list[str]] = []
    current: list[str] = []
    pending: list[str] = []
    for sentence in sentences:
        own = shingles(sentence)
        if not own:
            pending.append(sentence)
            continue
        if sum(1 for s in own if s not in earlier) >= NEW_TEXT * len(own):
            current += (pending if current else []) + [sentence]
        elif current:
            runs.append(current)
            current = []
        pending = []
    if current:
        runs.append(current)
    if sum(len(_WORD.findall(s)) for run in runs for s in run) < MIN_NEW_WORDS:
        return None
    return GAP.join("".join(run).strip() for run in runs)
