"""
Tool: calc — Milestone 32 (deterministic arithmetic).

Models confidently get basic math wrong and then double down on their own prior
answer. This tool computes arithmetic in code so the assistant never has to guess a
number. Safe by construction: an AST walk over a whitelisted grammar — no `eval`, no
names, attributes, comprehensions, or calls other than a few numeric helpers.
"""

import ast
import math
import operator
import re

from assistant_core.tools.base_tool import BaseTool, ToolResult

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "sqrt": math.sqrt, "floor": math.floor, "ceil": math.ceil,
}
_MAX_POW = 1000   # guard against 2**10**9 style resource bombs


def safe_eval(expr: str):
    """Evaluate a pure arithmetic expression. Raises ValueError on anything unsafe."""
    tree = ast.parse(expr, mode="eval")
    return _ev(tree.body)


def _ev(n):
    if isinstance(n, ast.Constant):
        if isinstance(n.value, bool) or not isinstance(n.value, (int, float)):
            raise ValueError("only numbers are allowed")
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _BINOPS:
        left, right = _ev(n.left), _ev(n.right)
        if isinstance(n.op, ast.Pow) and (abs(right) > _MAX_POW or abs(left) > _MAX_POW):
            raise ValueError("exponent too large")
        return _BINOPS[type(n.op)](left, right)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _UNARY:
        return _UNARY[type(n.op)](_ev(n.operand))
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS:
        return _FUNCS[n.func.id](*[_ev(a) for a in n.args])
    if isinstance(n, (ast.Tuple, ast.List)):      # e.g. max(1, 2, 3) or sum([1, 2, 3])
        return [_ev(e) for e in n.elts]
    raise ValueError("unsupported expression")


def _fmt(value) -> str:
    if isinstance(value, list):
        return ", ".join(_fmt(v) for v in value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.10g}"
    return str(value)


_ARITH_RE = re.compile(r"^[0-9\s.+\-*/()%]+$")
_PREFIXES = ("what is", "what's", "whats", "calculate", "compute", "evaluate",
             "solve", "how much is", "how many is")


def maybe_answer_arithmetic(message: str) -> "str | None":
    """
    If `message` is a plain arithmetic query ("4 + 6 =", "what is 3*7?"), compute it
    deterministically and return "expr = result". Else None. This runs BEFORE the model
    so basic math is always right and can never be argued into a wrong answer.
    """
    s = (message or "").strip().rstrip("?").strip()
    low = s.lower()
    for p in _PREFIXES:
        if low.startswith(p):
            s = s[len(p):].strip()
            break
    s = s.rstrip("=").strip()
    if not s or not _ARITH_RE.match(s):
        return None
    if not any(op in s for op in "+-*/%") or not any(c.isdigit() for c in s):
        return None                     # need a real operation on numbers
    try:
        value = safe_eval(s)
    except Exception:
        return None
    return f"{s} = {_fmt(value)}"


class CalcTool(BaseTool):
    """Evaluate an arithmetic expression deterministically (never guesses)."""

    @property
    def name(self) -> str:
        return "calc"

    @property
    def description(self) -> str:
        return "Evaluate an arithmetic expression exactly (e.g. '4 + 6', '(3/2)*8', 'sqrt(144)')."

    def run(self, input_data: str) -> ToolResult:
        expr = (input_data or "").strip().rstrip("=").strip()
        if not expr:
            return ToolResult(success=False, output="No expression provided. Usage: vault:calc <expression>")
        try:
            value = safe_eval(expr)
        except ZeroDivisionError:
            return ToolResult(success=False, output=f"{expr} = undefined (division by zero)")
        except Exception as exc:
            return ToolResult(success=False, output=f"Could not evaluate {expr!r}: {exc}")
        out = _fmt(value)
        return ToolResult(success=True, output=f"{expr} = {out}", metadata={"expression": expr, "result": out})
