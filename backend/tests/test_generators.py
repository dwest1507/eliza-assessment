"""The compared generators: one table of each model with its provider and its price, which
the answer cost, the generation harness's choice of implementation and the Makefile's
key check all read."""

import pytest

from edgar_eval import generators
from edgar_eval.generators import (
    ANTHROPIC,
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
    ]
    assert [g.provider.key_env_var for g in GENERATORS] == [
        "OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
    ]


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


def test_answer_cost_is_unknown_for_a_model_without_a_price():
    assert answer_cost("some-new-model", input_tokens=1_000, output_tokens=1_000) is None
    assert answer_cost("gpt-6-luna", input_tokens=None, output_tokens=None) is None


def test_a_generator_is_built_by_its_providers_implementation(monkeypatch):
    from edgar_answer.anthropic_model import AnthropicAnswerModel
    from edgar_answer.openai_model import OpenAIAnswerModel

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    claude = answer_model("claude-opus-5-5")
    gpt = answer_model("gpt-6.1-sol")

    assert isinstance(claude, AnthropicAnswerModel) and claude.model == "claude-opus-5-5"
    assert isinstance(gpt, OpenAIAnswerModel) and gpt.model == "gpt-6.1-sol"
    assert answer_model(None).model == "gpt-6-luna"
    with pytest.raises(SystemExit):
        answer_model("gemini-9")


def test_the_provider_comes_from_the_table_not_the_model_name(monkeypatch):
    from edgar_answer.anthropic_model import AnthropicAnswerModel

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    added = Generator("gpt-lookalike", ANTHROPIC, Price(input=1.0, output=2.0))
    monkeypatch.setattr(generators, "GENERATORS", (*GENERATORS, added))

    model = answer_model("gpt-lookalike")

    assert isinstance(model, AnthropicAnswerModel) and model.model == "gpt-lookalike"
    assert answer_cost("gpt-lookalike", 1_000_000, 1_000_000) == pytest.approx(3.0)
    with pytest.raises(SystemExit):
        answer_model("claude-unlisted")


def test_the_default_generator_follows_openai_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")

    assert answer_model(None).model == "gpt-6.1-sol"


def test_the_keys_command_names_the_api_keys_a_run_needs(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    assert main(["keys", "claude-sonnet-5-5"]) == 0
    assert capsys.readouterr().out.split() == ["ANTHROPIC_API_KEY"]
    assert main(["keys"]) == 0  # the default generator
    assert capsys.readouterr().out.split() == ["OPENAI_API_KEY"]
    assert main(["keys", "--all"]) == 0  # every compared generator, each key once
    assert capsys.readouterr().out.split() == ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    with pytest.raises(SystemExit) as stopped:
        main(["keys", "gemini-9"])
    assert stopped.value.code != 0
