"""Domain-independent contracts.

Every domain (RTL, ODE, Logic, ...) implements a TaskAdapter. The orchestrator
only ever talks to this interface, never to domain internals directly. This
is the seam that lets the same orchestration loop drive Verilator/Yosys,
SymPy, and Z3 without knowing anything about hardware, calculus, or logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class VerificationResult:
    """Normalized output of any verifier, regardless of domain."""

    status: str  # "PASS" | "FAIL" | "ERROR"
    failure_class: Optional[str] = None
    diagnostics: str = ""
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "failure_class": self.failure_class,
            "diagnostics": self.diagnostics,
            "evidence": self.evidence,
        }


class MalformedCandidateError(Exception):
    """Raised by normalize_candidate when the model output cannot be used."""


class TaskAdapter(ABC):
    """Domain-specific logic. Owns prompting, parsing, and verification."""

    domain: str = "base"
    verifier_name: str = "unknown"
    example_task: str = ""

    @abstractmethod
    def build_generate_prompt(self, specification: str) -> str:
        """Prompt sent to the model for the first candidate."""

    @abstractmethod
    def build_repair_prompt(
        self,
        specification: str,
        raw_candidate: str,
        verification: VerificationResult,
    ) -> str:
        """Prompt sent to the model to repair a failed candidate."""

    @abstractmethod
    def normalize_candidate(self, raw_output: str) -> Any:
        """Parse/clean raw model text into a domain-specific candidate object.

        Raises MalformedCandidateError if the output cannot be used at all.
        """

    @abstractmethod
    def verify(self, candidate: Any, specification: str) -> VerificationResult:
        """Run the real, domain-specific verifier. This is the ground truth."""

    def display_candidate(self, candidate: Any) -> str:
        """How the candidate should be rendered to the user. Default: str()."""
        return str(candidate)
