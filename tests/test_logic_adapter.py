import json

import pytest

z3 = pytest.importorskip("z3")

from backend.domains.logic.adapter import LogicTaskAdapter
from backend.domains.logic.expr import ConstraintParseError, build_symbols, parse_constraint


def test_parse_constraint_rejects_forbidden_syntax():
    symbols = build_symbols({"x": "Int"})
    with pytest.raises(ConstraintParseError):
        parse_constraint("__import__('os').system('rm -rf /')", symbols)


def test_satisfiable_assignment_passes():
    adapter = LogicTaskAdapter()
    candidate = adapter.normalize_candidate(json.dumps({
        "variables": {"x": "Int", "y": "Int"},
        "constraints": ["x >= 0", "y >= 0", "x + y <= 10"],
        "query": {"type": "check_assignment", "assignment": {"x": 6, "y": 5}},
    }))
    result = adapter.verify(candidate, "irrelevant task text")
    assert result.status == "FAIL"
    assert result.failure_class == "unsatisfied_constraint"


def test_valid_assignment_passes():
    adapter = LogicTaskAdapter()
    candidate = adapter.normalize_candidate(json.dumps({
        "variables": {"x": "Int", "y": "Int"},
        "constraints": ["x >= 0", "y >= 0", "x + y <= 10"],
        "query": {"type": "check_assignment", "assignment": {"x": 3, "y": 5}},
    }))
    result = adapter.verify(candidate, "irrelevant task text")
    assert result.status == "PASS"


def test_contradictory_constraints_are_unsat():
    adapter = LogicTaskAdapter()
    candidate = adapter.normalize_candidate(json.dumps({
        "variables": {"x": "Int"},
        "constraints": ["x >= 5", "x <= 2"],
    }))
    result = adapter.verify(candidate, "irrelevant task text")
    assert result.status == "FAIL"
    assert result.failure_class == "contradiction"
