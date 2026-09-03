"""Restricted SymPy parsing. Adapted from the supplied DE-SLM prototype.

Only a fixed allowlist of names is available to parse_expr, and a small
denylist blocks obviously dangerous syntax before parsing. This is what
"restricted SymPy parsing" means in the security requirements - no eval(),
no import, no arbitrary Python execution reachable from model output.
"""
from __future__ import annotations

import re
import sympy as sp
from sympy.parsing.sympy_parser import (
    parse_expr, standard_transformations, implicit_multiplication_application,
)

_ALLOWED_NAMES = {
    "E": sp.E, "I": sp.I, "pi": sp.pi,
    "exp": sp.exp, "log": sp.log, "sqrt": sp.sqrt,
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
    "Abs": sp.Abs,
}

_FORBIDDEN = re.compile(r"__|import|lambda|eval|exec|open\s*\(", re.IGNORECASE)

_TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)


def _locals(variable: str, dependent: str) -> dict:
    names = dict(_ALLOWED_NAMES)
    names[variable] = sp.Symbol(variable, real=True)
    names[dependent] = sp.Function(dependent)
    return names


def safe_sympify(text: str, variable: str = "x", dependent: str = "y"):
    if not isinstance(text, str) or len(text) > 2000:
        raise ValueError("Expression is missing or too long.")
    if _FORBIDDEN.search(text):
        raise ValueError("Forbidden syntax in expression.")
    text = text.replace("^", "**")
    text = re.sub(
        rf"\b{re.escape(dependent)}\s*'\s*\(\s*{re.escape(variable)}\s*\)",
        f"Derivative({dependent}({variable}),{variable})", text,
    )
    text = re.sub(
        rf"\b{re.escape(dependent)}\s*''\s*\(\s*{re.escape(variable)}\s*\)",
        f"Derivative({dependent}({variable}),({variable},2))", text,
    )
    names = _locals(variable, dependent)
    names["Derivative"] = sp.Derivative
    names["Eq"] = sp.Eq
    return parse_expr(text, local_dict=names, transformations=_TRANSFORMATIONS, evaluate=True)


def parse_equation(equation: str, variable: str = "x", dependent: str = "y"):
    if "=" in equation:
        lhs, rhs = equation.split("=", 1)
        expr = safe_sympify(lhs, variable, dependent) - safe_sympify(rhs, variable, dependent)
    else:
        expr = safe_sympify(equation, variable, dependent)
    return sp.expand(expr)


def parse_condition(condition: str, variable: str = "x", dependent: str = "y"):
    c = condition.strip()
    if not c:
        return None
    if "=" not in c:
        raise ValueError(f"Condition must contain '=': {condition}")
    lhs, rhs = c.split("=", 1)
    return sp.Eq(safe_sympify(lhs, variable, dependent), safe_sympify(rhs, variable, dependent))


def parse_candidate(text: str, variable: str = "x", dependent: str = "y"):
    if not isinstance(text, str) or len(text) > 4000:
        raise ValueError("Candidate expression is missing or too long.")
    if _FORBIDDEN.search(text):
        raise ValueError("Forbidden syntax in candidate.")
    names = _locals(variable, dependent)
    expr = text.strip().replace("^", "**")
    return parse_expr(expr, local_dict=names, transformations=_TRANSFORMATIONS, evaluate=True)
