"""Controlled Yosys wrapper. Adapted from the supplied RTL prototype.

The synthesis script is a fixed, backend-owned template. Only the RTL path
and discovered top-module name (extracted with a regex, not executed) are
substituted in.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def discover_top(rtl: str) -> str | None:
    match = re.search(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)", rtl)
    return match.group(1) if match else None


def run_yosys(rtl_path: Path, work_dir: Path, timeout: int = 90) -> dict:
    rtl = rtl_path.read_text(encoding="utf-8")
    top = discover_top(rtl)
    if not top:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(), "status": "FAIL",
            "exit_code": None, "top_module": None, "stdout": "",
            "stderr": "Could not determine top-level module from the RTL.",
            "statistics": {}, "netlist": None,
        }

    work_dir.mkdir(parents=True, exist_ok=True)
    script = work_dir / "verification.ys"
    netlist = work_dir / "synthesized_netlist.v"
    script.write_text(
        "\n".join([
            f"read_verilog -sv {rtl_path}",
            f"hierarchy -check -top {top}",
            "proc", "opt", "check", f"synth -top {top}",
            "stat", f"write_verilog -noattr {netlist}", "",
        ]), encoding="utf-8",
    )
    command = ["yosys", "-s", str(script)]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            cwd=str(work_dir), check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(), "status": "FAIL",
            "exit_code": None, "top_module": top, "stdout": "",
            "stderr": f"Yosys timed out after {timeout}s.",
            "statistics": {}, "netlist": None, "timed_out": True,
        }
    except FileNotFoundError:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(), "status": "FAIL",
            "exit_code": None, "top_module": top, "stdout": "",
            "stderr": "Yosys is not installed in this environment.",
            "statistics": {}, "netlist": None, "tool_missing": True,
        }

    output = result.stdout + "\n" + result.stderr
    passed = result.returncode == 0 and "found and reported 0 problems" in output
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if passed else "FAIL",
        "exit_code": result.returncode, "top_module": top,
        "statistics": _extract_statistics(output),
        "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:],
        "netlist": str(netlist) if netlist.exists() else None,
    }


def _number(pattern: str, text: str):
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _extract_statistics(text: str) -> dict:
    stats = {
        "wires": _number(r"Number of wires:\s+(\d+)", text),
        "wire_bits": _number(r"Number of wire bits:\s+(\d+)", text),
        "processes": _number(r"Number of processes:\s+(\d+)", text),
        "cells": _number(r"Number of cells:\s+(\d+)", text),
        "cell_types": {},
    }
    for cell_type, count in re.compile(
        r"^\s+(\$_[A-Za-z0-9_]+)\s+(\d+)\s*$", re.MULTILINE
    ).findall(text):
        stats["cell_types"][cell_type] = int(count)
    return stats
