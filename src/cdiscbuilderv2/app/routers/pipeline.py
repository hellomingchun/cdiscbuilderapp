"""
SDTM Pipeline Execution API Router.
Coordinates the Polars transformation engine, cross-domain references,
and post-transformation verification suites.
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import polars as pl

from ...engine import CDISCEngine
from ...pipeline import SDTMPipeline
from ...verifications import VerificationEngine
from ..state import STATE

logger = logging.getLogger("cdiscbuilderv2.app.pipeline")
router = APIRouter(prefix="/api/pipeline", tags=["Pipeline Execution"])


class RunPipelineRequest(BaseModel):
    formats: Optional[List[str]] = ["csv", "parquet", "xpt"]


@router.post("/run")
async def run_pipeline(req: RunPipelineRequest):
    """Executes the full SDTM build pipeline in-memory using Polars."""
    if not STATE["specs"]:
        raise HTTPException(status_code=400, detail="No domain specifications available. Generate or upload specs in Step 2 first.")

    try:
        logger.info(f"Running pipeline for {len(STATE['specs'])} domains...")
        built_domains = {}
        logs = []

        # 1. Execute domains with ODM source or Trial Design base
        for d_name, spec in STATE["specs"].items():
            if STATE["df_long"] is not None:
                engine = CDISCEngine(spec, df_long=STATE["df_long"], built_domains=built_domains)
                built_domains[d_name] = engine.build()
                logs.append(f"Built domain: {d_name} ({built_domains[d_name].height} rows)")
            elif d_name in STATE["built_domains"]:
                built_domains[d_name] = STATE["built_domains"][d_name]
                logs.append(f"Loaded pre-built domain: {d_name}")
            else:
                # If no raw EDC loaded, create empty or schema-based dataframe
                cols = {col["name"]: pl.Series([], dtype=pl.Utf8) for col in spec.get("columns", [])}
                built_domains[d_name] = pl.DataFrame(cols) if cols else pl.DataFrame()
                logs.append(f"Created empty domain: {d_name}")

        STATE["built_domains"] = built_domains

        # 2. Run Verifications
        verif_reports = {}
        for d_name, df in built_domains.items():
            spec = STATE["specs"].get(d_name, {})
            v_rep = VerificationEngine.verify(df, spec)
            verif_reports[d_name] = v_rep.to_dict()

        STATE["verification_reports"] = verif_reports

        results = []
        for d_name, df in built_domains.items():
            rep = verif_reports.get(d_name, {})
            results.append({
                "domain": d_name,
                "status": "SUCCESS",
                "rows": df.height,
                "columns_count": len(df.columns),
                "columns": df.columns,
                "is_valid": rep.get("is_valid", True),
                "violations_count": rep.get("total_violations", 0)
            })

        return {
            "status": "SUCCESS",
            "total_domains": len(results),
            "domains_built": len(results),
            "logs": logs,
            "results": results,
            "datasets": results,
            "verifications": verif_reports
        }

    except Exception as e:
        logger.exception("Pipeline execution failed")
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")


@router.get("/status")
async def get_pipeline_status():
    """Retrieve current pipeline execution status and summary of built domains."""
    return {
        "built_domains": list(STATE["built_domains"].keys()),
        "total_built": len(STATE["built_domains"]),
        "has_verifications": bool(STATE["verification_reports"])
    }
