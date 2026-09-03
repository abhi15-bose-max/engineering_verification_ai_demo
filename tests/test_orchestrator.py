import json
import tempfile
from pathlib import Path

from backend.core.models import MockAdapter
from backend.core.orchestrator import run_engineering_loop
from backend.domains.ode.adapter import ODETaskAdapter

SPEC = "Solve y'(x) + y(x) = 0 with y(0) = 2."


def _mock(script):
    m = MockAdapter(script=script)
    m.id = "mock"
    return m


def test_first_pass_success():
    model = _mock([json.dumps({
        "solution": "2*exp(-x)", "method": "m", "constants": [],
        "domain": "x real", "repair_summary": "ok",
    })])
    with tempfile.TemporaryDirectory() as tmp:
        traj = run_engineering_loop(ODETaskAdapter(), model, SPEC, 3, Path(tmp))
    assert traj.final_status == "VERIFIED"
    assert len(traj.attempts) == 1
    assert traj.evaluation["first_pass_success"] is True


def test_repair_then_success():
    model = _mock([
        json.dumps({"solution": "exp(-x)", "method": "m", "constants": [], "domain": "x real", "repair_summary": "1"}),
        json.dumps({"solution": "2*exp(-x)", "method": "m", "constants": [], "domain": "x real", "repair_summary": "2"}),
    ])
    with tempfile.TemporaryDirectory() as tmp:
        traj = run_engineering_loop(ODETaskAdapter(), model, SPEC, 3, Path(tmp))
    assert traj.final_status == "VERIFIED"
    assert len(traj.attempts) == 2
    assert traj.evaluation["repair_success"] is True


def test_exhausts_max_attempts_and_fails():
    model = _mock([json.dumps({
        "solution": "exp(-x)", "method": "m", "constants": [],
        "domain": "x real", "repair_summary": "never fixes it",
    })])
    with tempfile.TemporaryDirectory() as tmp:
        traj = run_engineering_loop(ODETaskAdapter(), model, SPEC, 2, Path(tmp))
    assert traj.final_status == "FAILED"
    assert len(traj.attempts) == 2


def test_malformed_model_output_is_recorded_not_crashed():
    model = _mock(["not json", json.dumps({
        "solution": "2*exp(-x)", "method": "m", "constants": [],
        "domain": "x real", "repair_summary": "fixed",
    })])
    with tempfile.TemporaryDirectory() as tmp:
        traj = run_engineering_loop(ODETaskAdapter(), model, SPEC, 3, Path(tmp))
    assert traj.attempts[0].verification["failure_class"] == "malformed_candidate"
    assert traj.final_status == "VERIFIED"


def test_trajectory_is_saved_to_disk():
    model = _mock([json.dumps({
        "solution": "2*exp(-x)", "method": "m", "constants": [],
        "domain": "x real", "repair_summary": "ok",
    })])
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        traj = run_engineering_loop(ODETaskAdapter(), model, SPEC, 3, tmp_path)
        assert (tmp_path / f"{traj.run_id}.json").exists()
        assert (tmp_path / "trajectories.jsonl").exists()
