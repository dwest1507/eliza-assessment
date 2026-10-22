"""The compared generators, for the evaluation: the table of generators
(`edgar_answer.generators.GENERATORS`, each model with its provider and its list price),
read from where the product reads it, and what the harnesses add to it.

Everything that depends on a generator reads the table: the answer cost
(`answer_cost`), the implementation the generation harness answers with
(`answer_model`), the generators `make eval-generators` runs by default (`COMPARISON`,
here), and the API key the Makefile checks for before a paid run:

    python -m edgar_eval.generators keys [MODEL...]     # the keys those models' providers need
    python -m edgar_eval.generators keys --comparison   # the default comparison's keys
    python -m edgar_eval.generators keys --all          # every compared generator's keys

With no MODEL, the default generator is `ANSWER_MODEL`, else the shipped one (the
table's first row), as for the product. A model not in the table is refused: it has no
provider and no price.
"""

from __future__ import annotations

import argparse
import sys
from typing import TextIO

from edgar_answer import generators as _table
from edgar_answer.generators import (
    ANTHROPIC,
    GENERATORS,
    OPENAI,
    Generator,
    Price,
    Provider,
    UnknownAnswerModel,
)
from edgar_rag.answer_model import AnswerModel

__all__ = [
    "ANTHROPIC",
    "COMPARISON",
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

COMPARISON: tuple[str, ...] = ("gpt-6-luna", "claude-haiku-5-5")
"""The generators the comparison runs by default, the shipped one first: Golden Set
version 2's, `gpt-6-luna` against `claude-haiku-5-5`. `python -m edgar_eval.selection
generators` (and so `make eval-generators`) runs these unless `--model` names other rows
(`MODELS="..."`) or `--all` asks for every row (`MODELS=`, empty); the shipped generator
always runs, as the shipped run and the Control Run."""


def generator(model: str | None = None) -> Generator | None:
    """The table's row for a model id, or for the default generator when None; None when
    the model is not in the table."""
    return _table.generator(model)


def answer_cost(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """One Answer Call's cost in US dollars, or None if the model has no price or the
    provider reported no usage."""
    row = generator(model) if model else None
    if row is None or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * row.price.input + output_tokens * row.price.output) / 1_000_000


def _require(model: str | None) -> Generator:
    try:
        return _table.require(model)
    except UnknownAnswerModel as error:
        raise SystemExit(f"error: {error}") from None


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
    keys.add_argument("model", nargs="*", help="the generators (default: the default one)")
    keys.add_argument("--all", action="store_true", help="every compared generator")
    keys.add_argument(
        "--comparison", action="store_true", help="the generators compared by default"
    )
    args = parser.parse_args(argv)

    if args.all:
        rows = GENERATORS
    elif args.comparison:
        rows = tuple(_require(m) for m in COMPARISON)
    else:
        rows = tuple(_require(m) for m in args.model or [None])
    print("\n".join(dict.fromkeys(g.provider.key_env_var for g in rows)), file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
