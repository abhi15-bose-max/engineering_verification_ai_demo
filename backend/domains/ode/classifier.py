def classify_failure(result: dict) -> str | None:
    if result.get("status") == "PASS":
        return None
    if result.get("parse_error"):
        return "malformed_candidate"
    if result.get("domain_issues"):
        return "singularity_or_branch_issue"
    checks = result.get("condition_checks", [])
    if any(c.get("status") == "FAIL" for c in checks):
        if any("initial" in c.get("kind", "") for c in checks):
            return "initial_condition_mismatch"
        if any("boundary" in c.get("kind", "") for c in checks):
            return "boundary_condition_mismatch"
        return "wrong_integration_constant"
    residual = result.get("equation_residual")
    if residual not in (None, "0", "0.0"):
        return "nonzero_symbolic_residual"
    return "unknown"
