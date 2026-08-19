"""
Clinical Study Design & Biostatistics API Router.
Handles clinical trial archetypes catalog, sample size & power calculations,
and automated CDISC Trial Design Model (TS, TA, TE, TV) synthesis.
"""

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import yaml

from ...study_designs import (
    CLINICAL_STUDY_CATALOG,
    SampleSizeRequest,
    calculate_sample_size,
    get_catalog_summary,
    get_design_by_id
)
from ...trial_design_builder import TrialDesignBuilder
from ..state import STATE

logger = logging.getLogger("cdiscbuilderv2.app.study_design")
router = APIRouter(prefix="/api/designs", tags=["Study Design & Biostatistics"])


class SynthesizeTDMRequest(BaseModel):
    design_id: str
    study_id: Optional[str] = None
    protocol_id: Optional[str] = None
    custom_params: Optional[Dict[str, Any]] = None


@router.get("/catalog")
async def get_study_designs_catalog():
    """Retrieve full catalog of industry clinical trial designs."""
    return {
        "status": "SUCCESS",
        "total_designs": len(CLINICAL_STUDY_CATALOG),
        "catalog": CLINICAL_STUDY_CATALOG,
        "designs": CLINICAL_STUDY_CATALOG
    }


@router.get("/{design_id}")
async def get_study_design(design_id: str):
    """Retrieve a specific clinical study design archetype."""
    design = get_design_by_id(design_id)
    if not design:
        raise HTTPException(status_code=404, detail=f"Study design '{design_id}' not found")
    return {"status": "SUCCESS", "design": design}


@router.post("/calculate_sample_size")
async def api_calculate_sample_size(req: SampleSizeRequest):
    """Calculate biostatistical sample size, statistical power, and event requirements."""
    try:
        res = calculate_sample_size(req)
        return {"status": "SUCCESS", "result": res, **res}
    except Exception as e:
        logger.exception("Sample size calculation error")
        raise HTTPException(status_code=400, detail=f"Calculation error: {str(e)}")


@router.post("/synthesize_tdm")
async def api_synthesize_tdm(req: SynthesizeTDMRequest):
    """Synthesizes CDISC SDTM Trial Design Model (TS, TA, TE, TV) schemas and datasets."""
    sid = req.protocol_id or req.study_id or "ST-001"
    builder = TrialDesignBuilder(
        design_id=req.design_id,
        study_id=sid,
        custom_config=req.custom_params
    )
    schemas = builder.generate_all_tdm_schemas()
    dfs = builder.generate_all_tdm_dataframes()

    # Register generated TDM schemas into STATE
    for d_name, yaml_text in schemas.items():
        parsed = yaml.safe_load(yaml_text)
        parsed["yaml_text"] = yaml_text
        STATE["specs"][d_name] = parsed
        if d_name in dfs:
            STATE["built_domains"][d_name] = dfs[d_name]

    STATE["active_study_design"] = req.design_id

    domain_list = list(schemas.keys())
    return {
        "status": "SUCCESS",
        "study_id": sid,
        "design_id": req.design_id,
        "generated_domains": domain_list,
        "domains": domain_list,
        "schemas": schemas,
        "message": f"Successfully synthesized {len(domain_list)} CDISC TDM domains: {', '.join(domain_list)}"
    }


class GenerateDocRequest(BaseModel):
    design_id: str
    custom_params: Optional[Dict[str, Any]] = None
    sample_size_params: Optional[Dict[str, Any]] = None
    provider: Optional[str] = "auto"
    api_key: Optional[str] = None
    model: Optional[str] = None
    custom_prompt: Optional[str] = None


@router.post("/generate_protocol")
async def api_generate_protocol(req: GenerateDocRequest):
    """Generates an ICH GCP E6 (R2) Clinical Trial Protocol Document."""
    from ...protocol_sap_generator import ProtocolSAPGenerator
    
    design = get_design_by_id(req.design_id)
    if not design:
        raise HTTPException(status_code=404, detail=f"Study design '{req.design_id}' not found")
    
    # Merge custom parameters if provided
    design_data = dict(design)
    if req.custom_params:
        design_data.update(req.custom_params)
        
    sample_size_res = req.sample_size_params
    if not sample_size_res:
        try:
            # Auto-calculate default sample size if not provided
            def_p = design.get("default_params", {})
            ss_req = SampleSizeRequest(
                design_id=req.design_id,
                endpoint_type=design.get("endpoint_type", "continuous"),
                hypothesis=design.get("hypothesis_type", "superiority"),
                **def_p
            )
            sample_size_res = calculate_sample_size(ss_req)
        except Exception:
            sample_size_res = {}

    gen = ProtocolSAPGenerator(
        provider=req.provider or "auto",
        api_key=req.api_key,
        model_name=req.model
    )
    result = gen.generate_protocol(
        design=design_data,
        sample_size=sample_size_res,
        custom_prompt=req.custom_prompt
    )
    return result


@router.post("/generate_sap")
async def api_generate_sap(req: GenerateDocRequest):
    """Generates an ICH E9 / E9(R1) Statistical Analysis Plan (SAP)."""
    from ...protocol_sap_generator import ProtocolSAPGenerator
    
    design = get_design_by_id(req.design_id)
    if not design:
        raise HTTPException(status_code=404, detail=f"Study design '{req.design_id}' not found")
    
    design_data = dict(design)
    if req.custom_params:
        design_data.update(req.custom_params)
        
    sample_size_res = req.sample_size_params
    if not sample_size_res:
        try:
            def_p = design.get("default_params", {})
            ss_req = SampleSizeRequest(
                design_id=req.design_id,
                endpoint_type=design.get("endpoint_type", "continuous"),
                hypothesis=design.get("hypothesis_type", "superiority"),
                **def_p
            )
            sample_size_res = calculate_sample_size(ss_req)
        except Exception:
            sample_size_res = {}

    gen = ProtocolSAPGenerator(
        provider=req.provider or "auto",
        api_key=req.api_key,
        model_name=req.model
    )
    result = gen.generate_sap(
        design=design_data,
        sample_size=sample_size_res,
        custom_prompt=req.custom_prompt
    )
    return result


