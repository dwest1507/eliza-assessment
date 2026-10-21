"""The compared generators: one table of each model with its provider and its price, which
the answer cost, the generation harness's choice of implementation and the Makefile's
key check all read."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from edgar_eval.generators import (
    ANTHROPIC,
    COMPARISON,
    GENERATORS,
    Generator,
    Price,
    answer_cost,
    answer_model,
    main,
)


def test_the_table_lists_each_compared_generator_once_the_shipped_default_first():
    assert [g.model for g in GENERATORS] == [
        "gpt-6-luna",
        "gpt-6.1-sol",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
        "claude-haiku-5-5",
        "gpt-5.6-terra",
    ]
    assert [g.provider.key_env_var for g in GENERATORS] == [
        "OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ]


def test_terra_is_an_openai_generator_at_its_list_price(monkeypatch):
    from edgar_answer.openai_model import OpenAIAnswerModel

    monkeypatch.setenv("OPENAI_API_KEY", "test")

    # gpt-5.6-terra: $2.00 per million input tokens, $12.00 per million output tokens.
    assert answer_cost("gpt-5.6-terra", 1_000_000, 100_000) == pytest.approx(3.2)
    terra = answer_model("gpt-5.6-terra")
    assert isinstance(terra, OpenAIAnswerModel) and terra.model == "gpt-5.6-terra"


def test_the_harnesses_read_the_table_the_product_reads():
    from edgar_answer import generators as product

    assert GENERATORS is product.GENERATORS


def test_answer_cost_prices_input_and_output_tokens_per_million():
    # gpt-6-luna: $0.10 per million input tokens, $0.50 per million output tokens.
    assert answer_cost("gpt-6-luna", input_tokens=1_000_000, output_tokens=100_000) == (
        pytest.approx(0.15)
    )
    assert answer_cost("gpt-6-luna", input_tokens=26_000, output_tokens=900) == (
        pytest.approx(0.00305)
    )
    # claude-sonnet-5-5: $2 in, $10 out; claude-opus-5-5: $4 in, $20 out, per million.
    assert answer_cost("claude-sonnet-5-5", 1_000_000, 100_000) == pytest.approx(3.0)
    assert answer_cost("claude-opus-5-5", 1_000_000, 100_000) == pytest.approx(6.0)
    assert all(answer_cost(g.model, 1, 1) is not None for g in GENERATORS)


def test_claude_haiku_5_5_is_an_anthropic_generator_at_gpt_6_luna_s_price(monkeypatch):
    from edgar_answer.anthropic_model import AnthropicAnswerModel

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    # $0.10 per million input tokens, $0.50 per million output tokens (under 100k).
    assert answer_cost("claude-haiku-5-5", 1_000_000, 100_000) == pytest.approx(0.15)
    assert answer_cost("claude-haiku-5-5", 26_000, 900) == pytest.approx(0.00305)
    haiku = answer_model("claude-haiku-5-5")
    assert isinstance(haiku, AnthropicAnswerModel) and haiku.model == "claude-haiku-5-5"


def test_the_version_1_generators_keep_their_prices():
    # The version 1 reports were priced from these rows; adding a generator changes none.
    prices = {g.model: (g.price.input, g.price.output) for g in GENERATORS}

    assert {m: prices[m] for m in prices if m not in {"claude-haiku-5-5", "gpt-5.6-terra"}} == {
        "gpt-6-luna": (0.10, 0.50),
        "gpt-6.1-sol": (2.00, 10.00),
        "claude-sonnet-5-5": (2.00, 10.00),
        "claude-opus-5-5": (4.00, 20.00),
    }


def test_answer_cost_is_unknown_for_a_model_without_a_price():
    assert answer_cost("some-new-model", input_tokens=1_000, output_tokens=1_000) is None
    assert answer_cost("gpt-6-luna", input_tokens=None, output_tokens=None) is None


def test_a_generator_is_built_by_its_providers_implementation(monkeypatch):
    from edgar_answer.anthropic_model import AnthropicAnswerModel
    from edgar_answer.openai_model import OpenAIAnswerModel

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("ANSWER_MODEL", raising=False)

    claude = answer_model("claude-opus-5-5")
    gpt = answer_model("gpt-6.1-sol")

    assert isinstance(claude, AnthropicAnswerModel) and claude.model == "claude-opus-5-5"
    assert isinstance(gpt, OpenAIAnswerModel) and gpt.model == "gpt-6.1-sol"
    assert answer_model(None).model == "gpt-6-luna"
    with pytest.raises(SystemExit):
        answer_model("gemini-9")


def test_the_provider_comes_from_the_table_not_the_model_name(monkeypatch):
    from edgar_answer import generators as table
    from edgar_answer.anthropic_model import AnthropicAnswerModel

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    added = Generator("gpt-lookalike", ANTHROPIC, Price(input=1.0, output=2.0))
    monkeypatch.setattr(table, "GENERATORS", (*GENERATORS, added))

    model = answer_model("gpt-lookalike")

    assert isinstance(model, AnthropicAnswerModel) and model.model == "gpt-lookalike"
    assert answer_cost("gpt-lookalike", 1_000_000, 1_000_000) == pytest.approx(3.0)
    with pytest.raises(SystemExit):
        answer_model("claude-unlisted")


def test_the_default_generator_follows_answer_model(monkeypatch):
    from edgar_answer.anthropic_model import AnthropicAnswerModel

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("ANSWER_MODEL", "claude-opus-5-5")

    model = answer_model(None)

    assert isinstance(model, AnthropicAnswerModel) and model.model == "claude-opus-5-5"


def test_the_keys_command_names_the_key_of_the_answer_model(monkeypatch, capsys):
    monkeypatch.setenv("ANSWER_MODEL", "claude-sonnet-5-5")

    assert main(["keys"]) == 0
    assert capsys.readouterr().out.split() == ["ANTHROPIC_API_KEY"]


def test_the_keys_command_names_the_api_keys_a_run_needs(monkeypatch, capsys):
    monkeypatch.delenv("ANSWER_MODEL", raising=False)

    assert main(["keys", "claude-sonnet-5-5"]) == 0
    assert capsys.readouterr().out.split() == ["ANTHROPIC_API_KEY"]
    assert main(["keys"]) == 0  # the default generator
    assert capsys.readouterr().out.split() == ["OPENAI_API_KEY"]
    assert main(["keys", "--all"]) == 0  # every compared generator, each key once
    assert capsys.readouterr().out.split() == ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    assert main(["keys", "gpt-6-luna", "claude-haiku-5-5"]) == 0  # a list, each key once
    assert capsys.readouterr().out.split() == ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    with pytest.raises(SystemExit) as stopped:
        main(["keys", "gemini-9"])
    assert stopped.value.code != 0


def test_the_default_comparison_is_gpt_6_luna_against_claude_haiku_5_5():
    # Golden Set version 2's comparison: the shipped generator first, every one a row.
    assert COMPARISON == ("gpt-6-luna", "claude-haiku-5-5")
    assert COMPARISON[0] == GENERATORS[0].model
    assert set(COMPARISON) <= {g.model for g in GENERATORS}


def test_the_keys_command_names_the_default_comparison_s_keys(capsys):
    assert main(["keys", "--comparison"]) == 0
    assert capsys.readouterr().out.split() == ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]


# --- The Makefile reads the table ---------------------------------------------------------
# `make eval-generators` names no model: the default comparison is COMPARISON, MODELS="..."
# names rows and MODELS= (empty) runs every one.

REPO = Path(__file__).resolve().parents[2]


def test_the_makefile_names_no_compared_generator():
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    assert [g.model for g in GENERATORS if g.model in makefile] == []


def _dry_run(*assignments: str) -> list[str]:
    """The commands `make eval-generators` would run, without running them."""
    env = {k: v for k, v in os.environ.items() if k not in {"MODELS", "MAKEFLAGS", "MFLAGS"}}
    index = "data/derived/edgar_rag.sqlite"  # treated as built, so nothing is rebuilt
    printed = subprocess.run(
        ["make", "--no-print-directory", "-n", "-o", index, "eval-generators", *assignments],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return printed.splitlines()


def _line(lines: list[str], command: str) -> str:
    return next(line for line in lines if command in line)


@pytest.mark.skipif(shutil.which("make") is None, reason="needs make")
@pytest.mark.parametrize(
    ("assignments", "keys", "selection"),
    [
        ((), "keys --comparison", "generators --split dev"),
        (
            ("MODELS=claude-sonnet-5-5 claude-haiku-5-5",),
            "keys claude-sonnet-5-5 claude-haiku-5-5",
            "generators --split dev --model claude-sonnet-5-5 --model claude-haiku-5-5",
        ),
        (("MODELS=",), "keys --all", "generators --split dev --all"),
    ],
)
def test_make_eval_generators_passes_the_models_named_or_the_default(assignments, keys, selection):
    lines = _dry_run(*assignments)

    # The shipped generator's keys, then the compared ones', both from the table.
    check = _line(lines, "edgar_eval.generators keys")
    assert "edgar_eval.generators keys)" in check
    assert f"edgar_eval.generators {keys})" in check
    assert _line(lines, "edgar_eval.selection").rstrip().endswith(f"selection {selection}")
