"""The SEC company-facts fetch refuses to run without a User-Agent, as the SEC requires."""

import pytest

from edgar_rag.sec_reference import USER_AGENT_ENV, UserAgentMissing, fetch_company_facts


def test_fetch_without_a_user_agent_refuses_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(USER_AGENT_ENV, raising=False)
    cache_dir = tmp_path / "sec"

    with pytest.raises(UserAgentMissing, match="SEC_USER_AGENT is not set"):
        fetch_company_facts(["0000320193"], cache_dir)

    assert not cache_dir.exists()


def test_a_blank_user_agent_counts_as_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(USER_AGENT_ENV, "   ")

    with pytest.raises(UserAgentMissing):
        fetch_company_facts(["0000320193"], tmp_path)
