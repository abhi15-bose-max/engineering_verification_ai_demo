"""ODE domain adapter. LLM proposes an explicit closed-form solution as a
small JSON object; SymPy independently checks the equation residual and
every stated condition. Runs in a subprocess with a hard timeout so a
pathological expression can't hang the server.
"""
from __future__ import annotations

import json
import multiprocessing as mp
from typing import Any

import sympy as sp

from backend.domains.base import MalformedCandidateError, TaskAdapter, VerificationResult
from backend.domains.ode.classifier import classify_failure
from backend.domains.ode.nl_extract import split_equation_and_conditions
from backend.domains.ode.symbolic_parser import parse_candidate, parse_condition, parse_equation, safe_sympify

VERIFY_TIMEOUT_S = 10
REQUIRED_FIELDS = {"solution", "method", "constants", "domain", "repair_summary"}

GENERATE_TEMPLATE = """You are a mathematical ODE candidate generator. SymPy independently \
verifies your answer; you must never claim it is already verified.

PROBLEM
Differential equation (zero form, {dependent}({variable}) is the unknown function): {equation}
Conditions: {conditions}

OUTPUT CONTRACT
Return exactly ONE JSON object with these five keys and nothing else:
  "solution": a plain JSON STRING with an explicit SymPy-compatible expression
              for {dependent}({variable}) (e.g. "2*exp(-x)"). Do not return
              Eq(...) or "{dependent}({variable}) = ...".
  "method": short string naming the solution method
  "constants": array of any free constant names used (usually empty - solve for them)
  "domain": short string describing the domain, e.g. "{variable} real"
  "repair_summary": short string describing what you did

Return ONLY the JSON object, no markdown fences, no prose.
"""

REPAIR_TEMPLATE = """You are repairing an ODE candidate using independent SymPy verifier evidence.

PROBLEM
Differential equation (zero form): {equation}
Conditions: {conditions}

PREVIOUS CANDIDATE JSON
{previous}

VERIFIER EVIDENCE
failure_class: {failure_class}
equation_residual: {residual}
evidence: {evidence}

TASK
Repair the candidate using the verifier evidence. Preserve the original
differential equation and every condition; preserve any constraint that
already passed; fix only what failed. Return an explicit SymPy-compatible
expression for {dependent}({variable}), not Eq(...) and not "{dependent}({variable}) = ...".
Return exactly one JSON object with keys: solution, method, constants, domain,
repair_summary. Return ONLY the JSON object, no markdown fences, no prose.
"""


def _domain_issues(expr, x) -> list[str]:
    issues = []
    try:
        denom = expr.as_numer_denom()[1]
        for d in denom.as_ordered_factors():
            zeros = sp.solve(sp.Eq(d, 0), x)
            if zeros:
                issues.append(f"denominator {d} vanishes at {zeros}")
    except Exception:
        pass
    for log_node in expr.atoms(sp.log):
        arg = log_node.args[0]
        if sp.ask(sp.Q.is_nonnegative(arg), sp.Q.real(x)) is False:
            issues.append(f"log argument may be non-positive: {arg}")
    for pow_node in expr.atoms(sp.Pow):
        base, exponent = pow_node.as_base_exp()
        if getattr(exponent, "is_Rational", False) and exponent.q % 2 == 0:
            issues.append(f"even root requires a domain check: {base}**({exponent})")
    return issues


def _verify_worker(problem: dict, candidate_text: str, queue) -> None:
    variable, dependent = problem["variable"], problem["dependent"]
    x = sp.Symbol(variable, real=True)
    y = sp.Function(dependent)
    try:
        candidate = parse_candidate(candidate_text, variable, dependent)
    except Exception as exc:
        queue.put({"status": "FAIL", "failure_class": "malformed_candidate",
                   "parse_error": str(exc), "equation_residual": None,
                   "condition_checks": [], "domain_issues": [], "evidence": str(exc)})
        return
    try:
        ode = safe_sympify(problem["equation"], variable, dependent)
        residual = sp.simplify(ode.subs(y(x), candidate).doit())

        def replace_y(expr):
            replacements = {}
            for node in expr.atoms(sp.Function):
                if getattr(node.func, "__name__", None) == dependent:
                    replacements[node] = candidate.subs(x, node.args[0])
            return expr.xreplace(replacements).doit()

        condition_checks = []
        for ctext in problem.get("conditions", []):
            c = safe_sympify(ctext, variable, dependent)
            if isinstance(c, sp.Equality):
                r = sp.simplify(replace_y(c.lhs) - replace_y(c.rhs))
                condition_checks.append({
                    "condition": str(c), "residual": str(r),
                    "status": "PASS" if r == 0 else "FAIL",
                    "kind": "initial" if "(0)" in str(c) else "boundary",
                })

        issues = _domain_issues(candidate, x)
        eq_pass = residual == 0
        cond_pass = all(c["status"] == "PASS" for c in condition_checks)
        status = "PASS" if eq_pass and cond_pass and not issues else "FAIL"
        out = {
            "status": status, "equation_residual": str(residual),
            "condition_checks": condition_checks, "domain_issues": issues,
            "failure_class": None, "evidence": None,
        }
        if status != "PASS":
            if issues:
                out["evidence"] = "; ".join(issues)
            elif not eq_pass:
                out["evidence"] = f"Symbolic residual is {residual}, not 0."
            else:
                bad = [c for c in condition_checks if c["status"] == "FAIL"]
                out["evidence"] = "; ".join(f"{c['condition']}: residual={c['residual']}" for c in bad)
            out["failure_class"] = classify_failure(out)
        queue.put(out)
    except Exception as exc:
        queue.put({"status": "FAIL", "failure_class": "verifier_error",
                   "equation_residual": None, "condition_checks": [],
                   "domain_issues": [], "evidence": str(exc)})


def _run_verify_with_timeout(problem: dict, candidate_text: str, timeout: int = VERIFY_TIMEOUT_S) -> dict:
    methods = mp.get_all_start_methods()
    method = "fork" if "fork" in methods else "spawn"
    ctx = mp.get_context(method)
    q = ctx.Queue()
    p = ctx.Process(target=_verify_worker, args=(problem, candidate_text, q))
    try:
        p.start()
    except Exception as exc:
        return {"status": "FAIL", "failure_class": "verifier_error", "evidence": f"Could not start verifier: {exc}",
                "equation_residual": None, "condition_checks": [], "domain_issues": []}
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        return {"status": "FAIL", "failure_class": "cas_timeout", "evidence": f"Verifier exceeded {timeout}s.",
                "equation_residual": None, "condition_checks": [], "domain_issues": []}
    if q.empty():
        return {"status": "FAIL", "failure_class": "verifier_error", "evidence": "Verifier exited without a result.",
                "equation_residual": None, "condition_checks": [], "domain_issues": []}
    return q.get()


class ODETaskAdapter(TaskAdapter):
    domain = "ode"
    verifier_name = "SymPy (symbolic)"
    example_task = "Solve y'(x) + y(x) = 0 with y(0) = 2."
    variable = "x"
    dependent = "y"

    def __init__(self):
        self._problem_cache: dict[str, dict] = {}

    def _get_problem(self, specification: str) -> dict:
        if specification in self._problem_cache:
            return self._problem_cache[specification]
        equation_text, condition_texts = split_equation_and_conditions(specification)
        equation_expr = parse_equation(equation_text, self.variable, self.dependent)
        conditions = []
        for ctext in condition_texts:
            parsed = parse_condition(ctext, self.variable, self.dependent)
            if parsed is not None:
                conditions.append(str(parsed))
        problem = {
            "variable": self.variable, "dependent": self.dependent,
            "equation": str(equation_expr), "conditions": conditions,
            "equation_display": equation_text, "conditions_display": condition_texts,
        }
        self._problem_cache[specification] = problem
        return problem

    def build_generate_prompt(self, specification: str) -> str:
        problem = self._get_problem(specification)
        return GENERATE_TEMPLATE.format(
            variable=self.variable, dependent=self.dependent,
            equation=problem["equation"], conditions=problem["conditions"] or "(none)",
        )

    def build_repair_prompt(self, specification: str, raw_candidate: str, verification: VerificationResult) -> str:
        problem = self._get_problem(specification)
        return REPAIR_TEMPLATE.format(
            variable=self.variable, dependent=self.dependent,
            equation=problem["equation"], conditions=problem["conditions"] or "(none)",
            previous=raw_candidate.strip()[:1500],
            failure_class=verification.failure_class,
            residual=verification.evidence.get("equation_residual"),
            evidence=verification.diagnostics,
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
                    raise MalformedCandidateError(f"Could not parse candidate JSON: {exc}") from exc
            else:
                raise MalformedCandidateError("Model output is not JSON.")
        missing = REQUIRED_FIELDS - set(obj)
        if missing:
            raise MalformedCandidateError(f"Candidate JSON missing fields: {sorted(missing)}")
        if not isinstance(obj["solution"], str) or not obj["solution"].strip():
            raise MalformedCandidateError("'solution' must be a non-empty string.")
        if len(obj["solution"]) > 4000:
            raise MalformedCandidateError("'solution' exceeds the size limit for this demo.")
        return obj

    def verify(self, candidate: dict, specification: str) -> VerificationResult:
        problem = self._get_problem(specification)
        try:
            result = _run_verify_with_timeout(problem, candidate["solution"])
        except Exception as exc:
            return VerificationResult(status="ERROR", failure_class="verifier_error", diagnostics=str(exc))

        if result["status"] == "PASS":
            return VerificationResult(status="PASS", evidence={
                "equation_residual": result["equation_residual"],
                "condition_checks": result["condition_checks"],
                "domain_issues": result["domain_issues"],
            })
        return VerificationResult(
            status="FAIL", failure_class=result.get("failure_class"),
            diagnostics=result.get("evidence") or "",
            evidence={
                "equation_residual": result.get("equation_residual"),
                "condition_checks": result.get("condition_checks", []),
                "domain_issues": result.get("domain_issues", []),
            },
        )

    def display_candidate(self, candidate: Any) -> str:
        if isinstance(candidate, dict):
            return f"{self.dependent}({self.variable}) = {candidate.get('solution')}"
        return str(candidate)
