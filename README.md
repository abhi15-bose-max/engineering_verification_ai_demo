# Engineering AI Verification — Public Technical Demonstrator

**"Bring your model. Bring your verifier. We run the engineering loop."**

This is a small, public-facing demo of an **API-first engineering AI
orchestration and validation infrastructure**. It is a research / MVP
demonstrator, not a production platform.

The idea: AI generation alone is not engineering. Real engineering requires
verification. This platform orchestrates:

```
GENERATE → VERIFY → DIAGNOSE → REPAIR → RE-VERIFY
```

against **real, independent verifiers** (not the model grading itself), and
turns every attempt into a structured trajectory plus evaluation metrics.

---

## 1. What this demo is

- Pick a model (GPT and/or Gemini — hosted APIs, no local/GPU inference).
- Pick a domain (RTL, ODE, or Formal Logic). The platform resolves the
  correct verifier automatically.
- Enter a task. Click **Run engineering loop**.
- Watch generation → verification → diagnosis → repair → re-verification.
- Get back a verified artifact, verifier evidence, a full trajectory, and
  evaluation metrics — never a claimed "pass" that the verifier didn't
  actually produce.
- Select two models and the same task/verifier/attempt-limit runs against
  both, side by side, for a fair comparison.

## 2. Architecture

```
                    FRONTEND (vanilla HTML/CSS/JS)
                              |
                          FASTAPI  (backend/app.py)
                              |
                       ORCHESTRATOR (backend/core/orchestrator.py)
                        /        |          \
                   MODEL       TASK        VERIFIER
              (ModelAdapter) (TaskAdapter)  (inside TaskAdapter.verify)
               GPT / Gemini   RTL/ODE/Logic  Verilator+Yosys / SymPy / Z3
                              \        |        /
                               TRAJECTORY (backend/core/trajectory.py)
                                        |
                               EVALUATION (backend/core/evaluation.py)
```

The orchestrator (`backend/core/orchestrator.py`) is **domain-independent**.
It only imports `ModelAdapter`, `TaskAdapter`, `VerificationResult`, and
`Trajectory`. It has never heard of Verilator, SymPy, or Z3 — that
separation is the entire architectural point of this codebase.

Each domain lives under `backend/domains/<name>/` and implements one class,
`TaskAdapter`, with five methods:

```python
class TaskAdapter:
    def build_generate_prompt(self, specification: str) -> str: ...
    def build_repair_prompt(self, specification, raw_candidate, verification) -> str: ...
    def normalize_candidate(self, raw_output: str) -> Any: ...
    def verify(self, candidate, specification: str) -> VerificationResult: ...
```

`VerificationResult` is the normalized contract every verifier returns:

```python
VerificationResult(status="PASS"|"FAIL"|"ERROR", failure_class=..., diagnostics=..., evidence={...})
```

Adding a new domain means writing one adapter file. Adding a new model
means writing one `ModelAdapter` subclass in `backend/core/models.py`.
Neither touches the orchestrator.

## 3. Relationship to the two supplied prototypes

This repository was built by auditing and generalizing two existing
prototypes rather than starting from scratch:

- **`rtl-engineering-agent`** — a working Qwen → Verilator → Yosys repair
  loop with a FastAPI + polling frontend. Its verifier logic
  (`verification/verilator.py`, `verification/yosys.py`) was reused almost
  verbatim in `backend/domains/rtl/`, including the Verilator-then-Yosys
  ordering (Yosys never runs if Verilator fails) and the fixed, backend-owned
  synthesis script template. The model layer and orchestration loop were
  generalized out into the shared `ModelAdapter`/orchestrator so the same
  repair loop now also drives GPT/Gemini and non-hardware domains.

- **`DE-SLM-MVP`** — a Qwen → SymPy repair loop for ODEs with a Streamlit UI.
  Its restricted-SymPy parsing (`ode_agent/problems/parser.py`,
  `ode_agent/verification/{parser,symbolic,classifier}.py`) and its JSON
  candidate contract (`solution/method/constants/domain/repair_summary`)
  were reused directly in `backend/domains/ode/`, including the
  subprocess-isolated, timeout-guarded verification call and the
  failure-class taxonomy. What's new is a small deterministic natural-language
  splitter (`nl_extract.py`) so the public demo can accept one free-text task
  string instead of separate equation/condition form fields.

The Logic/Z3 domain and the model-agnostic orchestrator/trajectory/
evaluation layer are new — there was no equivalent in either prototype.

## 4. Domains and verifiers

| Domain | Verifier            | What's checked |
|--------|----------------------|-----------------|
| RTL    | Verilator + Yosys    | Lint (`--lint-only`), then synthesis + cell/wire statistics. Yosys only runs if Verilator passes. |
| ODE    | SymPy (symbolic)     | Equation residual (should simplify to 0), every stated initial/boundary condition, and obvious domain issues (vanishing denominators, non-positive logs, even roots). |
| Logic  | Z3 (SMT)             | Joint satisfiability of the model's constraints, and — if a proposed assignment is given — whether it actually satisfies them. |

Failure classes surfaced per domain (used for both the trajectory and the
aggregate "failure intelligence" view):

- **RTL**: `lint_error`, `synthesis_error`, `verifier_timeout`
- **ODE**: `malformed_candidate`, `nonzero_symbolic_residual`,
  `initial_condition_mismatch`, `boundary_condition_mismatch`,
  `wrong_integration_constant`, `singularity_or_branch_issue`,
  `verifier_error`, `cas_timeout`
- **Logic**: `malformed_constraint`, `contradiction`,
  `unsatisfied_constraint`, `solver_timeout`, `verifier_error`

## 5. Trajectory format

Every run produces exactly one trajectory (`backend/core/trajectory.py`),
saved as JSON under `data/trajectories/<domain>/<run_id>.json` and appended
to a `trajectories.jsonl` ledger for cheap aggregation:

```json
{
  "run_id": "...", "domain": "ode", "verifier": "SymPy (symbolic)",
  "model": "gpt", "task": "...", "max_attempts": 3,
  "attempts": [
    {
      "attempt_id": 1, "raw_model_output": "...", "candidate": "y(x) = exp(-x)",
      "verification": {"status": "FAIL", "failure_class": "initial_condition_mismatch",
                        "diagnostics": "...", "evidence": {...}},
      "repair_feedback": "...", "latency_ms": 812
    }
  ],
  "final_status": "VERIFIED", "final_candidate": "y(x) = 2*exp(-x)",
  "evaluation": {"first_pass_success": false, "final_success": true,
                 "attempt_count": 2, "repair_success": true,
                 "total_latency_ms": 1590, "failure_classes": [...]}
}
```

## 6. Running locally

```bash
cp .env.example .env         # fill in OPENAI_API_KEY and/or GEMINI_API_KEY
pip install -r requirements.txt

# RTL domain needs Verilator + Yosys on PATH (skip if you only care about ODE/Logic):
#   apt-get install verilator yosys      (Debian/Ubuntu)
#   brew install verilator yosys         (macOS)

uvicorn backend.app:app --reload --port 8000
```

Open `http://localhost:8000`. If a model's API key isn't set, its chip is
greyed out in the UI instead of erroring at request time.

### Running the tests

```bash
pytest tests/
```

The orchestrator, ODE, RTL-parsing, and Logic tests all run against a
`MockAdapter` and don't need API keys. The RTL *verifier* tests that
actually invoke Verilator/Yosys will skip/fail if those binaries aren't
installed; everything else (candidate extraction, statistics parsing,
top-module discovery) is tested independent of the tools being present.

## 7. Deploying

```bash
docker build -t engineering-ai-demo .
docker run -p 8000:8000 --env-file .env engineering-ai-demo
```

Works in GitHub Codespaces or any small container host. No GPU, no local
model weights — all inference goes through the hosted OpenAI/Gemini APIs.
Storage is JSON trajectory files (see `data/trajectories/`); there is no
database to provision.

## 8. Security

This is a **public-facing** application, so all model output is treated as
untrusted:

- The model never constructs a shell command. RTL verification passes the
  generated file as a fixed argument to a hardcoded `verilator`/`yosys`
  invocation (`backend/domains/rtl/verilator.py`, `yosys.py`); the model
  cannot inject flags or additional commands.
- ODE candidates are parsed with `sympy.parsing.sympy_parser.parse_expr`
  against a fixed name allowlist, with a denylist for `__`, `import`,
  `lambda`, `eval`, `exec`, `open(` (`backend/domains/ode/symbolic_parser.py`).
  No `eval()`/`exec()` is ever called on model output.
- Logic constraints are parsed with Python's `ast` module and walked
  through a small allowlisted node set (`Compare`, `BoolOp`, `BinOp`,
  `UnaryOp`, `Name`, `Constant`) before being converted to Z3 expressions
  (`backend/domains/logic/expr.py`). Anything else — function calls,
  attribute access, comprehensions — raises immediately.
- All verifier subprocesses run with explicit timeouts, in per-run
  temporary directories (`tempfile.TemporaryDirectory`) that are cleaned up
  automatically.
- Task/candidate size limits are enforced (`MAX_TASK_CHARS`,
  `MAX_RTL_CHARS`, JSON field length checks) and a hard ceiling on repair
  attempts (`MAX_ATTEMPTS_CEILING = 8`) applies regardless of what the
  client requests.
- API keys are read from environment variables server-side only and are
  never sent to the frontend; `GET /api/models` reports only availability
  booleans.

## 9. What this intentionally is **not**

- Not a chatbot, not a generic coding assistant, not an LLM observability
  dashboard.
- No authentication, billing, multi-tenancy, or SOC2 controls.
- No Kubernetes, message queues, or microservices — one FastAPI process,
  background threads, JSON files.
- No GPU or local foundation model — inference is entirely hosted API calls.
- The natural-language → structured-problem extraction for ODE
  (`nl_extract.py`) is a small deterministic splitter, not a general NLU
  system; it's tuned to the demo's example shape ("Solve `<equation>` with
  `<conditions>`.").
- The Logic domain supports a genuinely small slice of formal reasoning
  (typed Int/Real/Bool variables, arithmetic comparisons, and/or/not) —
  not general first-order logic or a legal-reasoning system.
- Verification is real and is the platform's actual claim to correctness;
  everything else here (UI polish, comparison view, evaluation dashboard) is
  in service of making that one idea legible, not a claim of production
  readiness.
