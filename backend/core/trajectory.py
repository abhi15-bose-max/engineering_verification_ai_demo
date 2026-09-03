"""Trajectory is a first-class object, not a log.

Every run produces exactly one Trajectory. Every attempt within a run
(generation, verification, repair) is a structured record inside it. This
is what lets the frontend render "AI tried -> verifier rejected -> system
diagnosed -> AI repaired -> verifier accepted" directly from data.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Attempt:
    attempt_id: int
    raw_model_output: str
    candidate_display: str
    verification: dict
    repair_feedback: Optional[str] = None
    latency_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "attempt_id": self.attempt_id,
            "raw_model_output": self.raw_model_output,
            "candidate": self.candidate_display,
            "verification": self.verification,
            "repair_feedback": self.repair_feedback,
            "latency_ms": self.latency_ms,
        }


@dataclass
class Trajectory:
    run_id: str
    domain: str
    verifier_name: str
    model_id: str
    task: str
    max_attempts: int
    created_at: str = field(default_factory=_now_iso)
    attempts: list[Attempt] = field(default_factory=list)
    final_status: str = "RUNNING"  # RUNNING | VERIFIED | FAILED | ERROR
    final_candidate: Optional[str] = None
    error: Optional[str] = None
    evaluation: dict = field(default_factory=dict)

    @classmethod
    def create(cls, domain: str, verifier_name: str, model_id: str, task: str, max_attempts: int) -> "Trajectory":
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        return cls(run_id=run_id, domain=domain, verifier_name=verifier_name,
                    model_id=model_id, task=task, max_attempts=max_attempts)

    def record_attempt(self, attempt: Attempt) -> None:
        self.attempts.append(attempt)

    def finalize(self, status: str, final_candidate: Optional[str] = None, error: Optional[str] = None) -> None:
        self.final_status = status
        self.final_candidate = final_candidate
        self.error = error
        self.evaluation = self._compute_evaluation()

    def _compute_evaluation(self) -> dict:
        attempts = self.attempts
        first_pass = bool(attempts) and attempts[0].verification.get("status") == "PASS"
        final_success = self.final_status == "VERIFIED"
        repair_success = final_success and len(attempts) > 1
        total_latency = sum(a.latency_ms for a in attempts)
        failure_classes = [
            a.verification.get("failure_class")
            for a in attempts
            if a.verification.get("status") != "PASS" and a.verification.get("failure_class")
        ]
        return {
            "first_pass_success": first_pass,
            "final_success": final_success,
            "attempt_count": len(attempts),
            "repair_success": repair_success,
            "total_latency_ms": total_latency,
            "model": self.model_id,
            "domain": self.domain,
            "failure_classes": failure_classes,
        }

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "domain": self.domain,
            "verifier": self.verifier_name,
            "model": self.model_id,
            "task": self.task,
            "max_attempts": self.max_attempts,
            "created_at": self.created_at,
            "attempts": [a.to_dict() for a in self.attempts],
            "final_status": self.final_status,
            "final_candidate": self.final_candidate,
            "error": self.error,
            "evaluation": self.evaluation,
        }


def save_trajectory(trajectory: Trajectory, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{trajectory.run_id}.json"
    path.write_text(json.dumps(trajectory.to_dict(), indent=2), encoding="utf-8")
    # Append-only ledger, one line per run, for cheap aggregate evaluation.
    with (directory / "trajectories.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(trajectory.to_dict(), separators=(",", ":")) + "\n")
    return path
