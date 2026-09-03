"""Aggregate evaluation across many runs. Kept intentionally small."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def _iter_trajectories(directory: Path):
    ledger = directory / "trajectories.jsonl"
    if not ledger.exists():
        return
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def summarize(directory: Path, domain: str | None = None) -> dict:
    trajectories = list(_iter_trajectories(directory))
    if domain:
        trajectories = [t for t in trajectories if t.get("domain") == domain]

    if not trajectories:
        return {
            "total_runs": 0, "first_pass_success": 0, "final_success": 0,
            "average_attempts": 0.0, "failure_classes": {},
        }

    total = len(trajectories)
    first_pass = sum(1 for t in trajectories if t.get("evaluation", {}).get("first_pass_success"))
    final_success = sum(1 for t in trajectories if t.get("evaluation", {}).get("final_success"))
    attempts = [t.get("evaluation", {}).get("attempt_count", 0) for t in trajectories]
    failures = Counter()
    for t in trajectories:
        for fc in t.get("evaluation", {}).get("failure_classes", []):
            failures[fc] += 1

    return {
        "total_runs": total,
        "first_pass_success": first_pass,
        "final_success": final_success,
        "average_attempts": round(sum(attempts) / len(attempts), 2) if attempts else 0.0,
        "failure_classes": dict(failures),
    }


def compare(run_dicts: list[dict]) -> list[dict]:
    """Build the compact side-by-side comparison rows for the UI."""
    rows = []
    for t in run_dicts:
        ev = t.get("evaluation", {})
        rows.append({
            "model": t.get("model"),
            "final_status": t.get("final_status"),
            "first_pass_success": ev.get("first_pass_success", False),
            "final_success": ev.get("final_success", False),
            "attempts": ev.get("attempt_count", 0),
            "repair_success": ev.get("repair_success", False),
            "total_latency_ms": ev.get("total_latency_ms", 0),
            "failure_classes": ev.get("failure_classes", []),
        })
    return rows
