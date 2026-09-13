from __future__ import annotations

import pytest

from tests.integration.conftest import _missing_live_chat_llm_credential


@pytest.mark.parametrize(
    ("env", "missing"),
    [
        ({}, True),
        ({"OPENAI_API_KEY": "   "}, True),
        ({"COGNIS_TEST_LLM_MODEL": "openai/gpt-5"}, True),
        ({"COGNIS_TEST_LLM_MODEL": "chatgpt-4o-latest"}, True),
        ({"COGNIS_TEST_LLM_MODEL": "o3-mini"}, True),
        ({"COGNIS_TEST_LLM_MODEL": "o4-mini"}, True),
        ({"OPENAI_API_KEY": "test-key"}, False),
        ({"COGNIS_TEST_LLM_MODEL": "anthropic/claude-sonnet-4-5"}, False),
    ],
)
def test_missing_live_chat_llm_credential(
    env: dict[str, str],
    missing: bool,
) -> None:
    result = _missing_live_chat_llm_credential(env)

    assert (result is not None) is missing
