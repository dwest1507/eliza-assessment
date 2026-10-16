"""`make ask`: answer one question from the command line, without a server.

Prints the Query Scope and the numbered Sources, then streams the answer from the
Answer Call, then one line with the model, prompt version, token usage and latency.

    python -m edgar_answer.ask "What are the primary risk factors facing Apple?"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

from edgar_rag.answer_model import DEFAULT_ANSWER_LOG, AnswerCall, AnswerModel
from edgar_rag.retrieval import DEFAULT_INDEX, AnswerContext, Message, prepare_answer_context


def main(
    argv: list[str] | None = None,
    *,
    model: AnswerModel | None = None,
    out: TextIO = sys.stdout,
    log_path: str | Path = DEFAULT_ANSWER_LOG,
) -> int:
    parser = argparse.ArgumentParser(description="Answer a question from the Filings.")
    parser.add_argument("question", help="the business question to answer")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="the index file")
    args = parser.parse_args(argv)
    if not args.question.strip():
        parser.error('no question given: run `make ask Q="..."`')

    context = prepare_answer_context([Message("user", args.question)], args.index)
    _print_context(context, out)
    if model is None:
        from edgar_answer.openai_model import OpenAIAnswerModel

        model = OpenAIAnswerModel()

    print("\nAnswer\n", file=out)
    call = AnswerCall(context, model, log_path=log_path)
    for text in call:
        out.write(text)
        out.flush()
    record = call.record
    assert record is not None
    print(
        f"\n\n[{record.model} · prompt {record.prompt_version} · "
        f"{record.input_tokens} input / {record.output_tokens} output tokens · "
        f"{record.latency_s:.1f} s]",
        file=out,
    )
    return 0


def _print_context(context: AnswerContext, out: TextIO) -> None:
    companies = context.query_scope.companies
    print("Query Scope", file=out)
    print(
        "  Companies: "
        + (
            ", ".join(f"{c.name} ({c.ticker}, {c.coverage})" for c in companies)
            or "none named (searching every Company)"
        ),
        file=out,
    )
    print(f"\nSources ({len(context.sources)})", file=out)
    for source in context.sources:
        print(f"  [{source.tag}] {source.label}", file=out)


if __name__ == "__main__":
    sys.exit(main())
