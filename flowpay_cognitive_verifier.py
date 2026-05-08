from typing import Any, Dict, List, Optional


MRS_RANGES_BY_SEVERITY = {
    "Normal": (0, 24.99),
    "Guarded": (25, 49.99),
    "Defensive": (50, 74.99),
    "Critical": (75, float("inf")),
}


EXPECTED_ACTION_BY_SEVERITY = {
    "Normal": {"monitoring_bundle", "monitor_only"},
    "Guarded": {"early_warning_bundle", "increase_monitoring"},
    "Defensive": {"defensive_bundle", "liquidity_rebalancing"},
    "Critical": {
        "critical_bundle",
        "critical_protection_bundle",
        "risk_off_bundle",
        "emergency_review",
    },
}


def verify_mrs_severity_alignment(
    mrs: Optional[float],
    severity: Optional[str],
) -> tuple[bool, str]:
    if mrs is None:
        return False, "MRS is missing"

    if severity not in MRS_RANGES_BY_SEVERITY:
        return False, f"Unknown severity: {severity}"

    low, high = MRS_RANGES_BY_SEVERITY[severity]

    if low <= float(mrs) <= high:
        return True, "MRS is aligned with severity"

    return False, (
        f"MRS {mrs} is outside expected range for severity {severity}: "
        f"{low} to {high}"
    )


def verify_action_severity_alignment(
    action_bundle: Optional[str],
    severity: Optional[str],
) -> tuple[bool, str]:
    if severity not in EXPECTED_ACTION_BY_SEVERITY:
        return False, f"Unknown severity for action validation: {severity}"

    if not action_bundle:
        return False, "Action bundle is missing"

    allowed_actions = EXPECTED_ACTION_BY_SEVERITY[severity]

    if action_bundle in allowed_actions:
        return True, "Action bundle is aligned with severity"

    return False, (
        f"Action bundle '{action_bundle}' is not valid for severity '{severity}'"
    )


def verify_decision(
    mrs: Optional[float],
    severity: Optional[str],
    action_bundle: Optional[str],
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    mrs_ok, mrs_message = verify_mrs_severity_alignment(mrs, severity)
    checks.append({
        "check": "mrs_severity_alignment",
        "passed": mrs_ok,
        "message": mrs_message,
    })

    action_ok, action_message = verify_action_severity_alignment(action_bundle, severity)
    checks.append({
        "check": "action_severity_alignment",
        "passed": action_ok,
        "message": action_message,
    })

    overall_passed = all(check["passed"] for check in checks)

    return {
        "cognitive_verifier_passed": overall_passed,
        "checks": checks,
    }