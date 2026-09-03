from __future__ import annotations

from backend.domains.base import TaskAdapter
from backend.domains.logic.adapter import LogicTaskAdapter
from backend.domains.ode.adapter import ODETaskAdapter
from backend.domains.rtl.adapter import RTLTaskAdapter

_ADAPTER_CLASSES: dict[str, type[TaskAdapter]] = {
    "rtl": RTLTaskAdapter,
    "ode": ODETaskAdapter,
    "logic": LogicTaskAdapter,
}


def get_task_adapter(domain: str) -> TaskAdapter:
    if domain not in _ADAPTER_CLASSES:
        raise ValueError(f"Unknown domain '{domain}'.")
    return _ADAPTER_CLASSES[domain]()


def list_domains() -> list[dict]:
    out = []
    for domain_id, cls in _ADAPTER_CLASSES.items():
        adapter = cls()
        out.append({
            "id": domain_id,
            "verifier": adapter.verifier_name,
            "example_task": adapter.example_task,
        })
    return out
