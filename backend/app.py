from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.core.evaluation import compare, summarize
from backend.core.models import ModelError, get_available_models, get_model
from backend.core.orchestrator import MAX_ATTEMPTS_CEILING, run_engineering_loop
from backend.domains.registry import get_task_adapter, list_domains

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
TRAJECTORY_DIR = DATA_DIR / "trajectories"
TRAJECTORY_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIR = BASE / "frontend"

app = FastAPI(title="Engineering AI Orchestration & Validation Infrastructure",
              description="Public technical demonstrator: bring your model, bring your verifier.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_state: dict[str, dict] = {}
_lock = threading.Lock()


class RunRequest(BaseModel):
    domain: str
    model: str
    task: str = Field(min_length=1, max_length=4000)
    max_attempts: int = Field(default=3, ge=1, le=MAX_ATTEMPTS_CEILING)


def _emit(run_id: str, event: dict) -> None:
    with _lock:
        if run_id not in _state:
            return
        _state[run_id].setdefault("events", []).append(event)
        _state[run_id]["latest_event"] = event


def _worker(run_id: str, domain: str, model_id: str, task: str, max_attempts: int) -> None:
    try:
        with _lock:
            _state[run_id]["status"] = "running"
        task_adapter = get_task_adapter(domain)
        model = get_model(model_id)
        trajectory = run_engineering_loop(
            task_adapter=task_adapter, model=model, specification=task,
            max_attempts=max_attempts, trajectory_dir=TRAJECTORY_DIR / domain,
            emit=lambda event: _emit(run_id, event),
        )
        with _lock:
            _state[run_id]["status"] = "done"
            _state[run_id]["trajectory"] = trajectory.to_dict()
    except ModelError as exc:
        with _lock:
            _state[run_id]["status"] = "error"
            _state[run_id]["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - the demo must never crash on bad input
        with _lock:
            _state[run_id]["status"] = "error"
            _state[run_id]["error"] = f"Unexpected server error: {exc}"


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/domains")
def domains():
    return {"domains": list_domains()}


@app.get("/api/models")
def models():
    return {"models": get_available_models()}


@app.post("/api/runs")
def create_run(req: RunRequest):
    if req.domain not in {d["id"] for d in list_domains()}:
        raise HTTPException(400, f"Unknown domain '{req.domain}'.")
    available = {m["id"]: m["available"] for m in get_available_models()}
    if req.model not in available:
        raise HTTPException(400, f"Unknown model '{req.model}'.")
    if not available[req.model]:
        raise HTTPException(400, f"Model '{req.model}' is not configured on this server (missing API key).")

    run_id = uuid.uuid4().hex
    with _lock:
        _state[run_id] = {
            "status": "queued", "events": [], "domain": req.domain,
            "model": req.model, "task": req.task, "max_attempts": req.max_attempts,
        }
    threading.Thread(
        target=_worker, args=(run_id, req.domain, req.model, req.task, req.max_attempts), daemon=True,
    ).start()
    return {"run_id": run_id}


def _get_state(run_id: str) -> dict:
    with _lock:
        if run_id not in _state:
            raise HTTPException(404, "Run not found.")
        return dict(_state[run_id])


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    return _get_state(run_id)


@app.get("/api/runs/{run_id}/trajectory")
def get_trajectory(run_id: str):
    info = _get_state(run_id)
    if "trajectory" not in info:
        raise HTTPException(404, "Trajectory not available yet.")
    return info["trajectory"]


@app.get("/api/runs/{run_id}/result")
def get_result(run_id: str):
    info = _get_state(run_id)
    if "trajectory" not in info:
        raise HTTPException(404, "Result not available yet.")
    t = info["trajectory"]
    return {
        "final_status": t["final_status"], "final_candidate": t["final_candidate"],
        "evaluation": t["evaluation"], "error": t.get("error"),
    }


@app.get("/api/compare")
def compare_runs(run_ids: str):
    ids = [r.strip() for r in run_ids.split(",") if r.strip()]
    trajectories = []
    for rid in ids:
        info = _get_state(rid)
        if "trajectory" not in info:
            raise HTTPException(409, f"Run {rid} has not finished yet.")
        trajectories.append(info["trajectory"])
    return {"rows": compare(trajectories)}


@app.get("/api/evaluation")
def evaluation(domain: Optional[str] = None):
    if domain:
        return summarize(TRAJECTORY_DIR / domain, domain=None)
    combined = {"total_runs": 0, "first_pass_success": 0, "final_success": 0, "average_attempts": 0.0,
                "failure_classes": {}}
    for d in list_domains():
        s = summarize(TRAJECTORY_DIR / d["id"])
        combined["total_runs"] += s["total_runs"]
        combined["first_pass_success"] += s["first_pass_success"]
        combined["final_success"] += s["final_success"]
        for k, v in s["failure_classes"].items():
            combined["failure_classes"][k] = combined["failure_classes"].get(k, 0) + v
    return combined


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
