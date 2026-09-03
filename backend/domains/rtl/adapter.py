"""RTL domain adapter. LLM -> SystemVerilog -> Verilator -> Yosys.

Verilator runs first; if it fails, Yosys is never invoked (matches the
supplied prototype's ordering and avoids wasting a synthesis pass on RTL
that doesn't even lint clean).
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from backend.domains.base import MalformedCandidateError, TaskAdapter, VerificationResult
from backend.domains.rtl.verilator import run_verilator
from backend.domains.rtl.yosys import run_yosys

MAX_RTL_CHARS = 20000


def extract_sv(text: str) -> str:
    """Pull SystemVerilog out of a raw model response: fenced code first,
    then fall back to the first `module` keyword onward."""
    text = text.strip()
    fence = "```"
    pattern = re.escape(fence) + r"(?:systemverilog|verilog|sv)?\s*(.*?)" + re.escape(fence)
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    module_index = text.find("module ")
    if module_index >= 0:
        return text[module_index:].strip()
    return text


GENERATE_TEMPLATE = """You are an expert digital hardware designer.

Convert the following specification into synthesizable SystemVerilog.

Requirements:
- Follow the specification exactly.
- Produce one complete module.
- Use synthesizable SystemVerilog only (no delays, no testbench constructs).
- Do not add a testbench or an initial block unless explicitly required.
- Return ONLY the SystemVerilog source code, no explanation.

SPECIFICATION:
{specification}
"""

REPAIR_TEMPLATE = """You are repairing SystemVerilog RTL that failed verification.

ORIGINAL SPECIFICATION
{specification}

CURRENT RTL
{rtl}

FAILED STAGE: {failed_stage}

VERIFIER FEEDBACK
{feedback}

TASK
Repair the RTL so it satisfies the original specification and passes the
failed verification stage.

RULES
1. Preserve the intended behavior and module interface.
2. Do not add a testbench or an unrequested initial block.
3. Do not change the specification.
4. Return ONLY the complete corrected SystemVerilog module, no explanation.
"""


class RTLTaskAdapter(TaskAdapter):
    domain = "rtl"
    verifier_name = "Verilator + Yosys"
    example_task = "Create a synthesizable 4-bit counter with clk, reset and enable."

    def build_generate_prompt(self, specification: str) -> str:
        return GENERATE_TEMPLATE.format(specification=specification)

    def build_repair_prompt(self, specification: str, raw_candidate: str, verification: VerificationResult) -> str:
        rtl = extract_sv(raw_candidate)
        failed_stage = verification.evidence.get("failed_stage", "verification")
        return REPAIR_TEMPLATE.format(
            specification=specification, rtl=rtl,
            failed_stage=failed_stage, feedback=verification.diagnostics or "(no feedback)",
        )

    def normalize_candidate(self, raw_output: str) -> Any:
        rtl = extract_sv(raw_output)
        if not rtl or "module" not in rtl:
            raise MalformedCandidateError("Model output does not contain a SystemVerilog module.")
        if len(rtl) > MAX_RTL_CHARS:
            raise MalformedCandidateError("Generated RTL exceeds the size limit for this demo.")
        return rtl

    def verify(self, candidate: str, specification: str) -> VerificationResult:
        with tempfile.TemporaryDirectory(prefix="rtl_run_") as tmp:
            work_dir = Path(tmp)
            candidate_path = work_dir / "candidate.sv"
            candidate_path.write_text(candidate, encoding="utf-8")

            verilator = run_verilator(candidate_path)
            if verilator["status"] != "PASS":
                return VerificationResult(
                    status="FAIL",
                    failure_class="lint_error" if not verilator.get("timed_out") else "verifier_timeout",
                    diagnostics=verilator.get("stderr", ""),
                    evidence={"failed_stage": "verilator", "verilator": verilator},
                )

            synthesis = run_yosys(candidate_path, work_dir / "synthesis")
            # Persist netlist bytes into evidence (small demo circuits only) so the
            # orchestrator/tempdir lifecycle doesn't matter to callers.
            netlist_text = None
            netlist_path = synthesis.get("netlist")
            if netlist_path and Path(netlist_path).exists():
                netlist_text = Path(netlist_path).read_text(encoding="utf-8")[:8000]

            if synthesis["status"] != "PASS":
                return VerificationResult(
                    status="FAIL",
                    failure_class="verifier_timeout" if synthesis.get("timed_out") else "synthesis_error",
                    diagnostics=synthesis.get("stderr", "") or synthesis.get("stdout", ""),
                    evidence={"failed_stage": "synthesis", "verilator": verilator, "synthesis": synthesis},
                )

            return VerificationResult(
                status="PASS",
                evidence={
                    "verilator": {"status": "PASS"},
                    "synthesis": {
                        "status": "PASS",
                        "top_module": synthesis.get("top_module"),
                        "statistics": synthesis.get("statistics", {}),
                    },
                    "netlist_preview": netlist_text,
                },
            )

    def display_candidate(self, candidate: Any) -> str:
        return candidate
