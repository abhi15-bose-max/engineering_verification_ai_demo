"""The core loop. Domain-independent by construction.

orchestrator only knows about: ModelAdapter, TaskAdapter, VerificationResult,
Trajectory. It never imports Verilator, SymPy, or Z3. That separation is the
entire architectural point of this platform.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from backend.core.models import ModelAdapter, ModelError
from backend.core.trajectory import Attempt, Trajectory, save_trajectory
from backend.domains.base import MalformedCandidateError, TaskAdapter, VerificationResult

EventCallback = Callable[[dict], None]

MAX_ATTEMPTS_CEILING = 8  # hard safety ceiling regardless of what the client requests
MAX_TASK_CHARS = 4000     # input size limit


def _noop(_event: dict) -> None:
    return None


def run_engineering_loop(
    task_adapter: TaskAdapter,
    model: ModelAdapter,
    specification: str,
    max_attempts: int,
    trajectory_dir: Path,
    emit: Optional[EventCallback] = None,
) -> Trajectory:
    emit = emit or _noop
    max_attempts = max(1, min(max_attempts, MAX_ATTEMPTS_CEILING))
    specification = specification[:MAX_TASK_CHARS]

    trajectory = Trajectory.create(
        domain=task_adapter.domain,
        verifier_name=task_adapter.verifier_name,
        model_id=getattr(model, "id", "unknown"),
        task=specification,
        max_attempts=max_attempts,
    )
    emit({"type": "run_created", "run_id": trajectory.run_id})

    try:
        emit({"type": "stage", "stage": "generate", "attempt": 1})
        started = time.perf_counter()
        gen = model.generate(task_adapter.build_generate_prompt(specification))
        raw = gen.text
        latency = gen.latency_ms
    except ModelError as exc:
        trajectory.finalize("ERROR", error=str(exc))
        emit({"type": "error", "message": str(exc)})
        save_trajectory(trajectory, trajectory_dir)
        return trajectory

    for attempt_no in range(1, max_attempts + 1):
        emit({"type": "stage", "stage": "verify", "attempt": attempt_no})

        try:
            candidate = task_adapter.normalize_candidate(raw)
            verification = task_adapter.verify(candidate, specification)
            candidate_display = task_adapter.display_candidate(candidate)
        except MalformedCandidateError as exc:
            verification = VerificationResult(
                status="FAIL", failure_class="malformed_candidate", diagnostics=str(exc),
            )
            candidate_display = raw

        emit({
            "type": "verification_result", "attempt": attempt_no,
            "status": verification.status, "failure_class": verification.failure_class,
        })

        attempt = Attempt(
            attempt_id=attempt_no,
            raw_model_output=raw,
            candidate_display=candidate_display,
            verification=verification.to_dict(),
            latency_ms=latency,
        )

        if verification.status == "PASS":
            trajectory.record_attempt(attempt)
            trajectory.finalize("VERIFIED", final_candidate=candidate_display)
            emit({"type": "final", "status": "VERIFIED", "attempts": attempt_no})
            break

        if attempt_no >= max_attempts:
            trajectory.record_attempt(attempt)
            trajectory.finalize("FAILED", final_candidate=candidate_display)
            emit({"type": "final", "status": "FAILED", "attempts": attempt_no})
            break

        emit({"type": "stage", "stage": "diagnose", "attempt": attempt_no})
        emit({"type": "stage", "stage": "repair", "attempt": attempt_no})
        try:
            repair_prompt = task_adapter.build_repair_prompt(specification, raw, verification)
            started = time.perf_counter()
            gen = model.generate(repair_prompt)
            repaired_raw = gen.text
            attempt.repair_feedback = verification.diagnostics or verification.failure_class
            trajectory.record_attempt(attempt)
            raw = repaired_raw
            latency = gen.latency_ms
        except ModelError as exc:
            attempt.repair_feedback = f"Repair request failed: {exc}"
            trajectory.record_attempt(attempt)
            trajectory.finalize("ERROR", final_candidate=candidate_display, error=str(exc))
            emit({"type": "error", "message": str(exc)})
            break
        emit({"type": "stage", "stage": "re-verify", "attempt": attempt_no + 1})

    save_trajectory(trajectory, trajectory_dir)
    return trajectory
