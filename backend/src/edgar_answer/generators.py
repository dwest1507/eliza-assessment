"""The generators: one table (`GENERATORS`) of every model an Answer Call can be made
with, its provider and its list price, and the one setting that picks the product's
answer model from it.

`ANSWER_MODEL` (an environment variable, `backend/.env`) names the model; the table says
which provider answers with it (OpenAI or Anthropic) and so which API key it needs. It
defaults to the table's first row, `gpt-6-luna`. A model not in the table is refused with
`UnknownAnswerModel`: it has no provider and no price. So the generator that wins the
comparison ships by configuration alone, and adding or repricing a generator is one edit
to the table.

Every provider answers at the same settings, `REASONING_EFFORT` and `TOKEN_CAP`, which
the implementations (`edgar_answer.openai_model`, `edgar_answer.anthropic_model`) read
from here, so the comparison measures the models rather than their settings.

The evaluation harnesses read the same table through `edgar_eval.generators`, which adds
the answer cost, the default comparison and the key check the Makefile runs.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from edgar_rag.answer_model import AnswerModel

__all__ = [
    "ANSWER_MODEL_ENV_VAR",
    "ANTHROPIC",
    "GENERATORS",
    "OPENAI",
    "REASONING_EFFORT",
    "TOKEN_CAP",
    "Generator",
    "Price",
    "Provider",
    "UnknownAnswerModel",
    "answer_model",
    "generator",
    "require",
]

ANSWER_MODEL_ENV_VAR = "ANSWER_MODEL"
"""The environment variable that names the answer model, a row of `GENERATORS`."""

REASONING_EFFORT = "medium"
"""Every provider's reasoning effort: OpenAI's `reasoning_effort`, Anthropic's adaptive
thinking `effort`."""

TOKEN_CAP = 32_000
"""Every provider's cap on an answer's output tokens, reasoning or thinking included:
OpenAI's `max_completion_tokens`, Anthropic's `max_tokens`. An answer that reaches it
stops with the stop reason `token_cap` and is cut off: the API logs a warning and the
harnesses list it and score it as truncated."""


@dataclass(frozen=True)
class Price:
    """A model's list price in US dollars per million tokens."""

    input: float
    output: float


def _openai(model: str) -> AnswerModel:
    from edgar_answer.openai_model import OpenAIAnswerModel

    return OpenAIAnswerModel(model)


def _anthropic(model: str) -> AnswerModel:
    from edgar_answer.anthropic_model import AnthropicAnswerModel

    return AnthropicAnswerModel(model)


@dataclass(frozen=True)
class Provider:
    """A generator's provider: the environment variable its SDK reads the key from, and
    the answer model implementation over that SDK (imported only when built)."""

    name: str
    key_env_var: str
    build: Callable[[str], AnswerModel]


OPENAI = Provider("OpenAI", "OPENAI_API_KEY", _openai)
ANTHROPIC = Provider("Anthropic", "ANTHROPIC_API_KEY", _anthropic)


@dataclass(frozen=True)
class Generator:
    model: str
    provider: Provider
    price: Price


GENERATORS: tuple[Generator, ...] = (
    Generator("gpt-6-luna", OPENAI, Price(input=0.10, output=0.50)),
    Generator("gpt-6.1-sol", OPENAI, Price(input=2.00, output=10.00)),
    Generator("claude-sonnet-5-5", ANTHROPIC, Price(input=2.00, output=10.00)),
    Generator("claude-opus-5-5", ANTHROPIC, Price(input=4.00, output=20.00)),
    Generator("claude-haiku-5-5", ANTHROPIC, Price(input=0.10, output=0.50)),
    Generator("gpt-5.6-terra", OPENAI, Price(input=2.00, output=12.00)),
)
"""Every generator an Answer Call can be made with, the default first.

Prices are list prices per million tokens: OpenAI's standard tier
(developers.openai.com/api/docs/pricing) and Anthropic's first-party API
(platform.claude.com/docs/en/about-claude/pricing), listed on 2026-10-16;
`claude-haiku-5-5` on 2026-10-17 at its rate for prompts under 100k tokens (an Answer
Context stays within the 32k context budget); and terra, `gpt-5.6-terra`, the only terra
model on OpenAI's pricing page, its id and price confirmed there on 2026-10-20 at the
standard tier's short-context rate (up to 272k input tokens). Reasoning and thinking
tokens are billed as output and are already counted in the output tokens. Every input
token is priced at the full rate, ignoring cached input, so a cost is an upper bound.

Golden Set version 1 compared the first four, version 2 `gpt-6-luna` and
`claude-haiku-5-5`; terra joined for the final round. The version 1 rows stay at their
prices, so a version 1 run is still accepted and priced as its saved reports were."""


class UnknownAnswerModel(ValueError):
    """A model that is not a row of `GENERATORS`."""


def generator(model: str | None = None) -> Generator | None:
    """The table's row for a model id, or for the answer model (`ANSWER_MODEL`, else the
    first row) when None; None when the model is not in the table."""
    model = model or os.environ.get(ANSWER_MODEL_ENV_VAR) or GENERATORS[0].model
    return next((g for g in GENERATORS if g.model == model), None)


def require(model: str | None = None) -> Generator:
    """`generator`, refusing a model not in the table with `UnknownAnswerModel`."""
    row = generator(model)
    if row is None:
        name = model or os.environ.get(ANSWER_MODEL_ENV_VAR)
        listed = ", ".join(g.model for g in GENERATORS)
        source = "" if model else f" ({ANSWER_MODEL_ENV_VAR})"
        raise UnknownAnswerModel(
            f"{name!r}{source} is not in the generator table (one of {listed}); "
            "add it to GENERATORS in edgar_answer/generators.py"
        )
    return row


def answer_model(model: str | None = None) -> AnswerModel:
    """The answer model for a model id (None for `ANSWER_MODEL`, else the default),
    built by its provider's implementation, whose SDK reads the provider's key."""
    row = require(model)
    return row.provider.build(row.model)
