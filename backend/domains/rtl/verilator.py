"""Controlled Verilator wrapper. Adapted from the supplied RTL prototype.

The model never constructs this command - only the RTL text is model-derived,
and it is passed as a fixed file argument, never interpolated into shell.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def run_verilator(rtl_path: Path, timeout: int = 60) -> dict:
    if not rtl_path.exists():
        raise FileNotFoundError(f"RTL file not found: {rtl_path}")
    command = ["verilator", "--lint-only", "--language", "1800-2012", str(rtl_path)]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            cwd=str(rtl_path.parent), check=False,
        )
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": "lint", "tool": "verilator",
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "exit_code": result.returncode,
            "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:],
            "diagnostics": _extract_diagnostics(result.stderr),
        }
    except subprocess.TimeoutExpired:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(), "stage": "lint",
            "tool": "verilator", "status": "FAIL", "exit_code": None,
            "stdout": "", "stderr": f"Verilator timed out after {timeout}s.",
            "diagnostics": [], "timed_out": True,
        }
    except FileNotFoundError:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(), "stage": "lint",
            "tool": "verilator", "status": "FAIL", "exit_code": None,
            "stdout": "", "stderr": "Verilator is not installed in this environment.",
            "diagnostics": [], "tool_missing": True,
        }


def _extract_diagnostics(stderr: str) -> list[dict]:
    diagnostics = []
    pattern = re.compile(r"([^:\n]+):(\d+):(\d+):\s*(.*)")
    for match in pattern.finditer(stderr):
        diagnostics.append({
            "file": match.group(1), "line": int(match.group(2)),
            "column": int(match.group(3)), "message": match.group(4).strip(),
        })
    return diagnostics
