"""`make ask`: answer one question from the command line, without a server.

Prints the Query Scope, the Financial Facts table, the numbered Sources and the
Coverage Gaps, then streams the answer from the Answer Call, then one line with the
model, prompt version, token usage and latency. The model is the one `ANSWER_MODEL` names
(`edgar_answer.generators`), `gpt-6-luna` by default.

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
        from edgar_answer.generators import UnknownAnswerModel, answer_model

        try:
            model = answer_model()
        except UnknownAnswerModel as error:
            parser.error(str(error))

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
    if record.stop_reason == "token_cap":
        print("Warning: the answer stopped at the token cap and is cut off.", file=out)
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
    scope = context.query_scope
    for phrase in scope.sector_phrases:
        kind = "Company Group" if phrase.is_company_group else "Sector phrase"
        print(
            f'  {kind}: "{phrase.phrase}" → {", ".join(phrase.tickers) or "none"} '
            f"({phrase.column}: {', '.join(phrase.values)})",
            file=out,
        )
    print(f"  Time window: {scope.time_window.label}", file=out)
    print(f"  Sections: {', '.join(scope.sections) or 'whole Filings'}", file=out)
    if scope.periods:
        print(f"  Named periods: {', '.join(scope.periods)}", file=out)
    if scope.change:
        print("  Change question: new paragraphs first", file=out)
    metrics = ", ".join(m.replace("_", " ") for m in scope.metrics)
    print(f"  Metrics: {metrics or 'none'}", file=out)
    if scope.segments:
        print(f"  Segments: {', '.join(scope.segments)}", file=out)
    for company in companies:
        filings = [f for f in scope.filings if f.ticker == company.ticker]
        print(
            f"  {company.ticker}: "
            + ", ".join(f"{f.filing_id} ({f.fiscal_period})" for f in filings),
            file=out,
        )
    if scope.metrics:
        print(f"\nFinancial Facts ({len(context.financial_facts)} rows)", file=out)
        for row in context.financial_facts:
            basis = f"derived: {row.derived}" if row.derived else f'reported as "{row.label}"'
            print(
                f"  {row.ticker} {row.metric_name} {row.fiscal_period} ({row.months} months "
                f"ended {row.report_period}): {row.value_text}, {basis} "
                + " ".join(f"[{t}]" for t in row.sources),
                file=out,
            )
        for note in context.fact_notes:
            print(f"  Note: {note.text}", file=out)
    print(f"\nSources ({len(context.sources)})", file=out)
    for source in context.sources:
        print(f"  [{source.tag}] {source.label}", file=out)
    print(f"\nCoverage Gaps ({len(context.coverage_gaps)})", file=out)
    for gap in context.coverage_gaps:
        print(f"  {gap.text}", file=out)
    if not context.coverage_gaps:
        print("  none", file=out)


if __name__ == "__main__":
    sys.exit(main())
