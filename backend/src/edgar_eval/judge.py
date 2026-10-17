"""The Jev judge: Fact Recall and Faithfulness, judged by a model of another family.

Jev is TypeSafe's System One model. It returns typed judgments with probabilities, not
text, and it is neither an OpenAI nor an Anthropic model, so it judges both generators
under consideration without favouring its own family. It is pinned to an exact version
(`JEV_MODEL`), never an alias such as `jev-latest`, which moves when a new release ships
and would change scores without any change here. Every response's model is checked
against the pin.

Two judgments, each a narrow question over the state it needs:

- **Fact Recall.** One request per answer. The state is the answer; each Required Fact
  is a Noul ("does the answer state this fact?"). A fact counts as stated at a
  probability of at least `STATED_AT`. Every Required Fact is judged, whatever its tier;
  the generation harness scores Fact Recall on the must-state ones and detail recall on
  the details (`edgar_eval.generation.CaseResult`).
- **Faithfulness.** The answer's claims (`edgar_eval.answer_checks.claims`: every
  sentence but its headings, Coverage Gap wordings and lead-ins) are grouped by the
  Sources they cite. One request per group: the state is those Sources' text, and each
  claim is a Choice between supported, unsupported and contradicted. Beside the claim,
  marked as context and not judged, go its nearest heading and, for a table row, the
  table's header row, so "it" and a row of figures keep their meaning; each verdict
  records them. A claim citing no Source of the turn, an uncited sentence among them,
  is unsupported and never sent.
  Faithfulness is the share of claims supported by the Sources they cite.

The key is read from `JEV_API_KEY` (`backend/.env`). The SDK is a dev dependency and is
imported only when the judge runs; tests pass a fake client.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from edgar_eval.answer_checks import Claim
from edgar_rag.retrieval import count_tokens

__all__ = [
    "JEV_KEY_ENV",
    "JEV_MODEL",
    "JEV_USD_PER_MILLION_INPUT_TOKENS",
    "STATED_AT",
    "VERDICTS",
    "ClaimJudgment",
    "Evidence",
    "FactJudgment",
    "JevJudge",
    "Judgments",
]

JEV_MODEL = "jev-1.13.0"
"""The pinned Jev version: the stable release `jev-latest` pointed at on 2026-10-16."""

JEV_KEY_ENV = "JEV_API_KEY"

JEV_USD_PER_MILLION_INPUT_TOKENS = 0.042
"""Jev's price (docs.typesafe.ai/models, 2026-10-16). Output tokens are free."""

STATED_AT = 0.5
"""The probability from which a Required Fact counts as stated."""

VERDICTS = ("supported", "unsupported", "contradicted")

LONG_CONTEXT_TOKENS = 28_000
"""Above this many tokens of state, a request turns on Jev's long context: its default
limit is 32k tokens of state plus any one question."""
_LONG_CONTEXT_HEADER = {"TypeSafe-Danger-Zone-Long-Context": "true"}

_FACT_QUESTION = (
    "Does the `answer` state `required_fact`? It counts as stated when the answer gives "
    "the same information in other words or in more detail. It does not count when the "
    "answer states only part of it, something related but different, or the opposite."
)
_FACT_CRITERIA = {
    "true": "The answer states the required fact, in any wording.",
    "false": "The answer does not state the required fact, states only part of it, or "
    "contradicts it.",
}
_CLAIM_QUESTION = (
    "`claim` is a sentence from an answer about public companies that cites the `sources`, "
    "excerpts from SEC filings. How do the `sources` relate to `claim`?"
)
_CLAIM_CRITERIA = {
    "supported": "The sources state the claim or directly imply it, including every figure, "
    "period and company name in it.",
    "unsupported": "The sources do not say this: the claim adds information, figures or "
    "conclusions that the sources do not contain.",
    "contradicted": "The sources say something different from the claim, such as another "
    "figure, period, company or direction of change.",
}
_CONTEXT_NOTE = (
    " `context` is where `claim` sits in the answer: the heading above it and, for a table "
    'row, the table\'s header row. Use it only to read `claim`, such as what "it" refers to '
    "or what a row's figures measure; judge `claim` alone, not `context`."
)


@dataclass(frozen=True)
class Evidence:
    """A Source as the judge reads it."""

    tag: str
    label: str
    text: str


@dataclass(frozen=True)
class FactJudgment:
    fact: str
    probability: float
    """Jev's probability that the answer states the fact."""

    @property
    def stated(self) -> bool:
        return self.probability >= STATED_AT


@dataclass(frozen=True)
class ClaimJudgment:
    claim: str
    tags: tuple[str, ...]
    verdict: str
    probabilities: dict[str, float]
    heading: str = ""
    """The context the claim was judged with (`edgar_eval.answer_checks.Claim`)."""
    table_header: str = ""


@dataclass(frozen=True)
class Judgments:
    facts: tuple[FactJudgment, ...]
    claims: tuple[ClaimJudgment, ...]
    model: str
    requests: int
    input_tokens: int

    @property
    def fact_recall(self) -> float | None:
        """The share of the facts judged that are stated, or None if none was. Tier-blind:
        the harness's `CaseResult.fact_recall` counts the must-state facts only."""
        if not self.facts:
            return None
        return sum(f.stated for f in self.facts) / len(self.facts)

    @property
    def faithfulness(self) -> float | None:
        """The share of claims their cited Sources support, or None if there is no claim."""
        if not self.claims:
            return None
        return sum(c.verdict == "supported" for c in self.claims) / len(self.claims)

    @property
    def cost_usd(self) -> float:
        return self.input_tokens * JEV_USD_PER_MILLION_INPUT_TOKENS / 1_000_000


class JevJudge:
    """Judges answers with Jev, pinned to `JEV_MODEL`."""

    def __init__(self, client: Any = None, model: str = JEV_MODEL):
        self.model = model
        if client is None:
            from typesafe_sdk import TypeSafeClient

            key = os.environ.get(JEV_KEY_ENV)
            if not key:
                raise RuntimeError(
                    f"{JEV_KEY_ENV} is not set: copy backend/.env.example to backend/.env "
                    "and fill it in"
                )
            client = TypeSafeClient(api_key=key, model=model, timeout=120.0)
        self._client = client

    def judge(
        self,
        answer: str,
        required_facts: Sequence[str],
        claims: Sequence[Claim],
        sources: Mapping[str, Evidence],
    ) -> Judgments:
        """Judge one answer: whether it states each Required Fact, and whether the
        Sources each claim cites support it. `sources` maps this turn's tags to their
        Sources."""
        responses: list[Any] = []
        facts = self._fact_recall(answer, required_facts, responses)
        verdicts = self._faithfulness(claims, sources, responses)
        return Judgments(
            facts=facts,
            claims=verdicts,
            model=self.model,
            requests=len(responses),
            input_tokens=sum(r.usage.input_tokens for r in responses),
        )

    def _fact_recall(
        self, answer: str, facts: Sequence[str], responses: list[Any]
    ) -> tuple[FactJudgment, ...]:
        if not facts:
            return ()
        from typesafe_sdk import Noul

        questions = {
            f"fact_{i}": Noul(
                instructions={"required_fact": fact, "question": _FACT_QUESTION},
                criteria=_FACT_CRITERIA,
            )
            for i, fact in enumerate(facts)
        }
        response = self._ask({"answer": answer}, questions, responses)
        return tuple(
            FactJudgment(fact=fact, probability=response.nouls[f"fact_{i}"].noul)
            for i, fact in enumerate(facts)
        )

    def _faithfulness(
        self, claims: Sequence[Claim], sources: Mapping[str, Evidence], responses: list[Any]
    ) -> tuple[ClaimJudgment, ...]:
        verdicts: dict[int, ClaimJudgment] = {}
        groups: dict[tuple[str, ...], list[int]] = {}
        for i, claim in enumerate(claims):
            known = tuple(tag for tag in claim.tags if tag in sources)
            if known:
                groups.setdefault(known, []).append(i)
            else:
                verdicts[i] = _verdict(claim, "unsupported", {})
        from typesafe_sdk import Choice

        for tags, members in groups.items():
            state = {
                "sources": [
                    {"tag": tag, "label": sources[tag].label, "text": sources[tag].text}
                    for tag in tags
                ]
            }
            questions = {
                f"claim_{i}": Choice(
                    instructions=_claim_instructions(claims[i]), criteria=_CLAIM_CRITERIA
                )
                for i in members
            }
            response = self._ask(state, questions, responses)
            for i in members:
                answer = response.choices[f"claim_{i}"]
                verdicts[i] = _verdict(claims[i], answer.choice, dict(answer.probabilities))
        return tuple(verdicts[i] for i in range(len(claims)))

    def _ask(self, state: dict, questions: dict, responses: list[Any]) -> Any:
        """One Jev request. Its response is appended to `responses`, for the usage."""
        text = " ".join(str(v) for v in _strings(state))
        headers = _LONG_CONTEXT_HEADER if count_tokens(text) > LONG_CONTEXT_TOKENS else None
        response = self._client.system_one(
            state, questions, model=self.model, extra_headers=headers
        )
        if response.model != self.model:
            raise RuntimeError(
                f"Jev answered as {response.model}, not the pinned {self.model}: "
                "scores from another version are not comparable"
            )
        responses.append(response)
        return response


def _claim_instructions(claim: Claim) -> dict[str, Any]:
    """A claim's question: the claim, and beside it, marked as context, its heading and
    table header when it has them. A claim with neither is asked exactly as before claims
    carried context."""
    context = {
        key: value
        for key, value in (("heading", claim.heading), ("table_header", claim.table_header))
        if value
    }
    if not context:
        return {"claim": claim.text, "question": _CLAIM_QUESTION}
    return {"claim": claim.text, "context": context, "question": _CLAIM_QUESTION + _CONTEXT_NOTE}


def _verdict(claim: Claim, verdict: str, probabilities: dict[str, float]) -> ClaimJudgment:
    return ClaimJudgment(
        claim.text, claim.tags, verdict, probabilities, claim.heading, claim.table_header
    )


def _strings(value: object):
    if isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    else:
        yield value
