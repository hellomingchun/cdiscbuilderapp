"""
CDISC Conformance & Verification Quality Suite API Router.
Evaluates and reports declarative quality rules and FDA/PMDA submission checks.
"""

import logging
from fastapi import APIRouter, HTTPException
from ..state import STATE
from ...verifications import VerificationEngine

logger = logging.getLogger("cdiscbuilderv2.app.verifications")
router = APIRouter(prefix="/api/verifications", tags=["Conformance & Verifications"])


@router.post("/run")
async def run_verifications():
    """Run verification checks for all built domains and cache results."""
    if not STATE["built_domains"]:
        raise HTTPException(status_code=400, detail="No built domains available. Run the pipeline first.")

    reports = {}
    for d_name, df in STATE["built_domains"].items():
        spec = STATE["specs"].get(d_name, {})
        v_rep = VerificationEngine.verify(df, spec)
        reports[d_name] = v_rep.to_dict()

    STATE["verification_reports"] = reports
    return {"status": "SUCCESS", "domains": list(reports.keys()), "reports": reports}


@router.get("/list")
async def list_verification_domains():
    """Return list of domains that have verification reports."""
    return {"domains": list(STATE["verification_reports"].keys())}


@router.get("/report")
async def get_verification_reports():
    """Retrieve full verification and conformance reports for all built domains."""
    return {
        "status": "SUCCESS",
        "total_domains": len(STATE["verification_reports"]),
        "reports": STATE["verification_reports"]
    }


@router.get("/summary")
async def get_verification_summary():
    """Retrieve high-level pass/fail summary of conformance rules."""
    total_checked = 0
    total_passed = 0
    total_failed = 0

    for _, rep in STATE["verification_reports"].items():
        total_checked += rep.get("total_rules", 0)
        total_passed += rep.get("passed_rules", 0)
        total_failed += rep.get("failed_rules", 0)

    return {
        "total_checked": total_checked,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "all_valid": total_failed == 0 and total_checked > 0
    }


@router.get("/{domain}")
async def get_domain_verification(domain: str):
    """Retrieve verification report for a specific domain."""
    if domain not in STATE["verification_reports"]:
        raise HTTPException(status_code=404, detail=f"No verification report for domain '{domain}'")
    return STATE["verification_reports"][domain]
