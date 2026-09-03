"""Logic / constraint-reasoning domain adapter.

LLM translates a natural-language rule/question into a small formal
representation (typed variables + constraints, optionally a proposed
assignment or a conclusion to check). Z3 is the ground truth: it checks
consistency (satisfiability) of the constraints and, if a query is present,
whether it actually follows.
"""
from __future__ import annotations

import json
from typing import Any

import z3

from backend.domains.base import MalformedCandidateError, TaskAdapter, VerificationResult
from backend.domains.logic.expr import ConstraintParseError, build_symbols, parse_constraint

SOLVER_TIMEOUT_MS = 5000
REQUIRED_FIELDS = {"variables", "constraints"}

GENERATE_TEMPLATE = """You are a formal-logic modeling assistant. Z3 (an SMT solver) will \
independently check whatever you produce - you must never claim it is already verified.

TASK
{task}

OUTPUT CONTRACT
Return exactly ONE JSON object, no markdown fences, no prose, with keys:
  "variables": object mapping variable name -> type, where type is one of
               "Int", "Real", or "Bool". Include every variable used.
  "constraints": array of constraint strings using only the listed variables
                 and operators + - * / and comparisons (>=, <=, >, <, ==, !=)
                 and boolean and/or/not. One constraint per array entry.
  "query": OPTIONAL object describing what to check. Either:
           {{"type": "check_assignment", "assignment": {{"varname": value, ...}}}}
           to check whether a specific proposed assignment satisfies every
           constraint, or omit "query" entirely to just check whether the
           constraints are jointly consistent (satisfiable).

Do not use function calls, comprehensions, or any Python syntax beyond basic
arithmetic and comparisons. Return ONLY the JSON object.
"""

REPAIR_TEMPLATE = """You are repairing a formal model using independent Z3 verifier evidence.

TASK
{task}

PREVIOUS MODEL JSON
{previous}

VERIFIER EVIDENCE
failure_class: {failure_class}
evidence: {evidence}

Repair the JSON model so the "variables" and "constraints" correctly capture
the task, and (if present) so the "query" is answered correctly. Return
exactly one JSON object with keys: variables, constraints, and optionally
query - same contract as before. Return ONLY the JSON object.
"""


class LogicTaskAdapter(TaskAdapter):
    domain = "logic"
    verifier_name = "Z3 (SMT)"
    example_task = (
        "Determine whether x >= 0, y >= 0, x + y <= 10 and x = 6, y = 5 are simultaneously satisfiable."
    )

    def build_generate_prompt(self, specification: str) -> str:
        return GENERATE_TEMPLATE.format(task=specification)

    def build_repair_prompt(self, specification: str, raw_candidate: str, verification: VerificationResult) -> str:
        return REPAIR_TEMPLATE.format(
            task=specification, previous=raw_candidate.strip()[:1500],
            failure_class=verification.failure_class, evidence=verification.diagnostics,
        )

    def normalize_candidate(self, raw_output: str) -> Any:
        raw = raw_output.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    obj = json.loads(raw[start:end + 1])
                except json.JSONDecodeError as exc:
                    raise MalformedCandidateError(f"Could not parse model JSON: {exc}") from exc
            else:
                raise MalformedCandidateError("Model output is not JSON.")
        missing = REQUIRED_FIELDS - set(obj)
        if missing:
            raise MalformedCandidateError(f"Model JSON missing fields: {sorted(missing)}")
        if not isinstance(obj["variables"], dict) or not obj["variables"]:
            raise MalformedCandidateError("'variables' must be a non-empty object.")
        if not isinstance(obj["constraints"], list) or not obj["constraints"]:
            raise MalformedCandidateError("'constraints' must be a non-empty array.")
        if len(obj["constraints"]) > 40:
            raise MalformedCandidateError("Too many constraints for this demo.")
        return obj

    def verify(self, candidate: dict, specification: str) -> VerificationResult:
        try:
            symbols = build_symbols(candidate["variables"])
            parsed_constraints = [
                (text, parse_constraint(text, symbols)) for text in candidate["constraints"]
            ]
        except ConstraintParseError as exc:
            return VerificationResult(status="FAIL", failure_class="malformed_constraint", diagnostics=str(exc))
        except Exception as exc:  # noqa: BLE001
            return VerificationResult(status="ERROR", failure_class="verifier_error", diagnostics=str(exc))

        solver = z3.Solver()
        solver.set("timeout", SOLVER_TIMEOUT_MS)
        for _, expr in parsed_constraints:
            solver.add(expr)

        check = solver.check()
        if check == z3.unknown:
            return VerificationResult(status="ERROR", failure_class="solver_timeout",
                                       diagnostics="Z3 could not decide within the time limit.")
        if check == z3.unsat:
            return VerificationResult(
                status="FAIL", failure_class="contradiction",
                diagnostics="The constraints are jointly unsatisfiable (contradictory).",
                evidence={"constraints": candidate["constraints"], "sat_result": "unsat"},
            )

        model = solver.model()
        witness = {str(d): str(model[d]) for d in model.decls()}
        query = candidate.get("query") or {}

        if query.get("type") == "check_assignment":
            assignment = query.get("assignment", {})
            check_solver = z3.Solver()
            check_solver.set("timeout", SOLVER_TIMEOUT_MS)
            for _, expr in parsed_constraints:
                check_solver.add(expr)
            try:
                for name, value in assignment.items():
                    if name not in symbols:
                        raise ConstraintParseError(f"Assignment references unknown variable '{name}'.")
                    check_solver.add(symbols[name] == value)
            except ConstraintParseError as exc:
                return VerificationResult(status="FAIL", failure_class="malformed_constraint", diagnostics=str(exc))

            assignment_check = check_solver.check()
            if assignment_check == z3.sat:
                return VerificationResult(
                    status="PASS",
                    evidence={"result": "satisfiable", "assignment": assignment, "witness": witness},
                )
            return VerificationResult(
                status="FAIL", failure_class="unsatisfied_constraint",
                diagnostics=f"Assignment {assignment} does not satisfy the constraints.",
                evidence={"result": "unsatisfiable", "assignment": assignment,
                          "constraints": candidate["constraints"]},
            )

        return VerificationResult(
            status="PASS",
            evidence={"result": "satisfiable", "witness": witness, "constraints": candidate["constraints"]},
        )

    def display_candidate(self, candidate: Any) -> str:
        return json.dumps(candidate, indent=2)
