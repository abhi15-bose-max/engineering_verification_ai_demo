import json

from backend.domains.ode.adapter import ODETaskAdapter
from backend.domains.base import MalformedCandidateError


def test_nl_extract_and_verify_pass():
    adapter = ODETaskAdapter()
    spec = "Solve y'(x) + y(x) = 0 with y(0) = 2."
    candidate = adapter.normalize_candidate(json.dumps({
        "solution": "2*exp(-x)", "method": "linear", "constants": [],
        "domain": "x real", "repair_summary": "solved",
    }))
    result = adapter.verify(candidate, spec)
    assert result.status == "PASS"


def test_verify_wrong_constant_classified_as_initial_condition_mismatch():
    adapter = ODETaskAdapter()
    spec = "Solve y'(x) + y(x) = 0 with y(0) = 2."
    candidate = adapter.normalize_candidate(json.dumps({
        "solution": "exp(-x)", "method": "linear", "constants": [],
        "domain": "x real", "repair_summary": "first try",
    }))
    result = adapter.verify(candidate, spec)
    assert result.status == "FAIL"
    assert result.failure_class == "initial_condition_mismatch"


def test_malformed_candidate_raises():
    adapter = ODETaskAdapter()
    try:
        adapter.normalize_candidate("not json at all")
        assert False, "expected MalformedCandidateError"
    except MalformedCandidateError:
        pass


def test_malformed_candidate_missing_fields():
    adapter = ODETaskAdapter()
    try:
        adapter.normalize_candidate(json.dumps({"solution": "2*exp(-x)"}))
        assert False, "expected MalformedCandidateError"
    except MalformedCandidateError:
        pass
