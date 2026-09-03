"""Safe expression parsing for the Logic/Z3 domain.

Model output is untrusted, so constraints are never passed to eval() or
exec(). Instead each constraint string is parsed with Python's `ast` module
and only a small allowlist of node types is walked to build a Z3 expression.
Anything outside the allowlist (attribute access, calls, comprehensions,
imports, ...) raises immediately.
"""
from __future__ import annotations

import ast

import z3

_ALLOWED_COMPARE = {
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}
_ALLOWED_BINOP = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}


class ConstraintParseError(ValueError):
    pass


def _build_symbols(variables: dict) -> dict:
    symbols = {}
    for name, vtype in variables.items():
        if not name.isidentifier():
            raise ConstraintParseError(f"Invalid variable name: {name}")
        vtype_norm = str(vtype).strip().lower()
        if vtype_norm == "int":
            symbols[name] = z3.Int(name)
        elif vtype_norm == "real":
            symbols[name] = z3.Real(name)
        elif vtype_norm == "bool":
            symbols[name] = z3.Bool(name)
        else:
            raise ConstraintParseError(f"Unsupported variable type '{vtype}' for '{name}'.")
    return symbols


def _eval_node(node, symbols):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, symbols)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return z3.BoolVal(node.value)
        if isinstance(node.value, (int, float)):
            return node.value
        raise ConstraintParseError(f"Unsupported constant: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id not in symbols:
            raise ConstraintParseError(f"Unknown variable: {node.id}")
        return symbols[node.id]
    if isinstance(node, ast.UnaryOp):
        val = _eval_node(node.operand, symbols)
        if isinstance(node.op, ast.USub):
            return -val
        if isinstance(node.op, ast.Not):
            return z3.Not(val)
        raise ConstraintParseError("Unsupported unary operator.")
    if isinstance(node, ast.BinOp):
        op = _ALLOWED_BINOP.get(type(node.op))
        if op is None:
            raise ConstraintParseError("Unsupported arithmetic operator.")
        return op(_eval_node(node.left, symbols), _eval_node(node.right, symbols))
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(v, symbols) for v in node.values]
        if isinstance(node.op, ast.And):
            return z3.And(*values)
        if isinstance(node.op, ast.Or):
            return z3.Or(*values)
        raise ConstraintParseError("Unsupported boolean operator.")
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ConstraintParseError("Only single comparisons are supported (e.g. 'x >= 0').")
        op = _ALLOWED_COMPARE.get(type(node.ops[0]))
        if op is None:
            raise ConstraintParseError("Unsupported comparison operator.")
        left = _eval_node(node.left, symbols)
        right = _eval_node(node.comparators[0], symbols)
        return op(left, right)
    raise ConstraintParseError(f"Unsupported syntax: {type(node).__name__}")


def parse_constraint(text: str, symbols: dict):
    if not isinstance(text, str) or len(text) > 500:
        raise ConstraintParseError("Constraint is missing or too long.")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ConstraintParseError(f"Could not parse constraint '{text}': {exc}") from exc
    return _eval_node(tree, symbols)


def build_symbols(variables: dict) -> dict:
    return _build_symbols(variables)
