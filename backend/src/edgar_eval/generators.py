"""The compared generators: one table (`GENERATORS`) of every model the generator
comparison measures, with its provider and its list price. Adding or repricing a
generator is one edit to that table.

Everything that depends on a generator reads the table: the answer cost
(`answer_cost`), the implementation the generation harness answers with
(`answer_model`), the list `make eval-generators` runs, and the API key the Makefile
checks for before a paid run:

    python -m edgar_eval.generators keys [MODEL]   # the key MODEL's provider needs
    python -m edgar_eval.generators keys --all     # every compared generator's keys

With no MODEL, the default generator is `OPENAI_MODEL`, else the shipped one (the
table's first row). A model not in the table is refused: it has no provider and no
price.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

from edgar_answer.openai_model import MODEL_ENV_VAR
from edgar_rag.answer_model import AnswerModel

__all__ = [
    "ANTHROPIC",
    "GENERATORS",
    "OPENAI",
    "Generator",
    "Price",
    "Provider",
    "answer_cost",
    "answer_model",
    "generator",
    "main",
]


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
)
"""The generators the comparison measures, the shipped default first.

Prices are list prices per million tokens on 2026-10-16: OpenAI's standard tier
(developers.openai.com/api/docs/pricing) and Anthropic's first-party API
(platform.claude.com/docs/en/about-claude/pricing). Reasoning and thinking tokens are
billed as output and are already counted in the output tokens. Every input token is
priced at the full rate, ignoring cached input, so a cost is an upper bound."""


def generator(model: str | None = None) -> Generator | None:
    """The table's row for a model id, or for the default generator when None; None when
    the model is not in the table."""
    model = model or os.environ.get(MODEL_ENV_VAR) or GENERATORS[0].model
    return next((g for g in GENERATORS if g.model == model), None)


def answer_cost(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """One Answer Call's cost in US dollars, or None if the model has no price or the
    provider reported no usage."""
    row = generator(model) if model else None
    if row is None or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * row.price.input + output_tokens * row.price.output) / 1_000_000


def _require(model: str | None) -> Generator:
    row = generator(model)
    if row is None:
        listed = ", ".join(g.model for g in GENERATORS)
        name = model or os.environ.get(MODEL_ENV_VAR)
        raise SystemExit(
            f"error: {name!r} is not a compared generator (one of {listed}); "
            "add it to GENERATORS in edgar_eval/generators.py"
        )
    return row


def answer_model(model: str | None) -> AnswerModel:
    """The generator to test, by model id (None for the default), built by its
    provider's implementation."""
    row = _require(model)
    return row.provider.build(row.model)


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description="The compared generators.")
    commands = parser.add_subparsers(dest="command", required=True)
    keys = commands.add_parser("keys", help="print the API key variables a run needs")
    keys.add_argument("model", nargs="?", help="the generator (default: the default one)")
    keys.add_argument("--all", action="store_true", help="every compared generator")
    args = parser.parse_args(argv)

    rows = GENERATORS if args.all else (_require(args.model),)
    print("\n".join(dict.fromkeys(g.provider.key_env_var for g in rows)), file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
