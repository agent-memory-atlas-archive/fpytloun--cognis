"""Typed rejection reasons must remain fail-closed and content-free."""

import copy

import pytest

from cognis.providers.llm.inference_errors import safe_inference_error
from cognis.providers.llm.systemone import (
    SystemOneRequest,
    SystemOneResponseError,
    validate_systemone_response,
)


def request():
    return SystemOneRequest.model_validate(
        {
            "model": "typesafe/jev-1.13",
            "state": "PRIVATE_PROMPT",
            "questions": {
                "risk": {
                    "type": "choice",
                    "instructions": "classify",
                    "criteria": {"low": "low", "high": "high"},
                }
            },
        }
    )


def answer():
    return {
        "model": "typesafe/jev-1.13",
        "answers": {
            "risk": {
                "type": "choice",
                "choice": "low",
                "confidence": 0.9,
                "probabilities": {"low": 0.9, "high": 0.1},
            }
        },
        "private_completion": "PRIVATE_PROVIDER_BODY",
    }


@pytest.mark.parametrize(
    "case,code",
    [
        ("schema", "systemone_response_schema"),
        ("set", "systemone_answer_set"),
        ("sum", "systemone_probability_sum"),
        ("choice", "systemone_choice_criteria"),
        ("type", "systemone_answer_type"),
    ],
)
def test_rejected_response_has_safe_categorical_diagnostic(case, code):
    payload = answer()
    if case == "schema":
        payload["answers"]["risk"]["confidence"] = "PRIVATE_PROVIDER_BODY"
    elif case == "set":
        payload["answers"] = {}
    elif case == "sum":
        payload["answers"]["risk"]["probabilities"] = {"low": 0.5, "high": 0.1}
    elif case == "choice":
        payload["answers"]["risk"]["choice"] = "PRIVATE_PROVIDER_BODY"
    else:
        payload["answers"]["risk"] = {"type": "noul", "noul": 0.8}
    with pytest.raises(SystemOneResponseError) as caught:
        validate_systemone_response(payload, request())
    fields = safe_inference_error(caught.value)
    assert fields["exception_class"] == "SystemOneResponseError"
    assert fields["error_category"] == "response_validation"
    assert fields["upstream_code"] == code
    assert "PRIVATE_" not in str(caught.value) + str(fields)


def test_valid_response_never_rewritten_or_probabilities_normalized():
    payload = answer()
    before = copy.deepcopy(payload)
    assert validate_systemone_response(payload, request()) == before
    assert payload == before


@pytest.mark.parametrize("low", [0.8996, 0.91, 0.89])
def test_approximate_distribution_matches_supported_client_tolerance(low):
    payload = answer()
    payload["answers"]["risk"]["probabilities"] = {"low": low, "high": 0.1}
    before = copy.deepcopy(payload)
    validate_systemone_response(payload, request())
    assert payload == before


@pytest.mark.parametrize("low", [0.93, 0.85])
def test_materially_unnormalized_distribution_still_rejected(low):
    payload = answer()
    payload["answers"]["risk"]["probabilities"] = {"low": low, "high": 0.1}
    with pytest.raises(SystemOneResponseError) as caught:
        validate_systemone_response(payload, request())
    assert safe_inference_error(caught.value)["upstream_code"] == "systemone_probability_sum"


def test_invalid_score_uses_typed_code_without_accepting_it():
    req = SystemOneRequest.model_validate(
        {
            "model": "typesafe/jev-1.13",
            "state": "PRIVATE_PROMPT",
            "questions": {
                "risk": {"type": "score", "instructions": "classify", "criteria": ["low", "high"]}
            },
        }
    )
    with pytest.raises(SystemOneResponseError) as caught:
        validate_systemone_response(
            {
                "model": "typesafe/jev-1.13",
                "answers": {
                    "risk": {
                        "type": "score",
                        "score": 9.0,
                        "confidence": 0.9,
                        "probabilities": {"0": 0.9, "1": 0.1},
                    }
                },
            },
            req,
        )
    assert safe_inference_error(caught.value)["upstream_code"] == "systemone_score_criteria"
