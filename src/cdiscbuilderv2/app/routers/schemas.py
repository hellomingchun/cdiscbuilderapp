"""
Yamaa Schema Studio & AI Domain Synthesizer API Router.
Handles CRUD operations on Yamaa YAML specs, automated rule validation,
schema auto-fixing, CRF form discovery, and AI synthesis.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
import yaml

from ...ai_generator import AISDTMSchemaGenerator
from ...validator import YamaaSchemaValidator, auto_fix_yamaa_schema
from ..state import STATE

logger = logging.getLogger("cdiscbuilderv2.app.schemas")
router = APIRouter(tags=["Schema Studio & AI Generation"])


class GenerateFromFormsRequest(BaseModel):
    form_oids: Optional[List[str]] = None
    form_mappings: Optional[Dict[str, str]] = None
    mappings: Optional[Dict[str, str]] = None
    provider: Optional[str] = "auto"
    api_key: Optional[str] = None
    model: Optional[str] = None
    model_name: Optional[str] = None
    custom_prompt: Optional[str] = None


class DomainGenerationRequest(BaseModel):
    provider: Optional[str] = "auto"
    api_key: Optional[str] = None
    model: Optional[str] = None
    model_name: Optional[str] = None
    custom_prompt: Optional[str] = None


class SpecContentRequest(BaseModel):
    domain: str
    yaml_content: Optional[str] = None
    content: Optional[str] = None

    def get_content(self) -> str:
        return self.yaml_content or self.content or ""


# ==================== CRF FORMS & AI SYNTHESIS ====================

@router.get("/api/ai/crf_forms")
async def ai_get_crf_forms():
    """Explores all CRF Forms in the ingested XML and provides suggested SDTM domains."""
    if STATE["df_long"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file in Step 1 first.")

    ai_gen = AISDTMSchemaGenerator(
        metadata_df=STATE["metadata_df"],
        df_long=STATE["df_long"],
        parser=STATE["odm_parser"]
    )
    forms = ai_gen.discover_crf_forms()
    return {
        "status": "SUCCESS",
        "total_forms": len(forms),
        "forms": forms
    }


@router.post("/api/ai/generate")
@router.post("/api/ai/generate_from_forms")
async def ai_generate_from_forms(req: GenerateFromFormsRequest):
    """AI generates Yamaa YAML schemas for user-selected CRF Form -> SDTM Domain mappings."""
    if STATE["df_long"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file in Step 1 first.")

    mappings = req.form_mappings or req.mappings or {}
    if not mappings and req.form_oids:
        # Default mapping if only OIDs provided
        mappings = {oid: "DM" for oid in req.form_oids}

    ai_gen = AISDTMSchemaGenerator(
        metadata_df=STATE["metadata_df"],
        df_long=STATE["df_long"],
        parser=STATE["odm_parser"],
        provider=req.provider or "auto",
        api_key=req.api_key,
        model_name=req.model_name or req.model
    )

    generated_map = ai_gen.generate_schemas_for_form_mappings(mappings, custom_prompt=req.custom_prompt)
    STATE["specs"] = {}
    for d_name, yaml_text in generated_map.items():
        parsed = yaml.safe_load(yaml_text)
        parsed["yaml_text"] = yaml_text
        STATE["specs"][d_name] = parsed

    return {
        "status": "SUCCESS",
        "provider": ai_gen.provider,
        "generated_domains": list(generated_map.keys()),
        "schemas": generated_map,
        "specs": generated_map
    }



@router.get("/api/ai/discover_domains")
async def ai_discover_domains():
    """Analyze ingested EDC XML metadata and discover potential SDTM domains."""
    if STATE["metadata_df"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file in Step 1 first.")

    ai_gen = AISDTMSchemaGenerator(metadata_df=STATE["metadata_df"], df_long=STATE["df_long"], parser=STATE["odm_parser"])
    discovered = ai_gen.discover_domains()
    return {
        "status": "SUCCESS",
        "total_discovered": len(discovered),
        "domains": discovered
    }


@router.post("/api/ai/generate_domain/{domain}")
async def ai_generate_single_domain(domain: str, req: DomainGenerationRequest):
    """Generate a compliant Yamaa YAML schema for a specific SDTM domain."""
    if STATE["metadata_df"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file in Step 1 first.")

    ai_gen = AISDTMSchemaGenerator(
        metadata_df=STATE["metadata_df"],
        df_long=STATE["df_long"],
        parser=STATE["odm_parser"],
        provider=req.provider or "auto",
        api_key=req.api_key,
        model_name=req.model_name
    )

    yaml_text = ai_gen.generate_domain_schema(domain=domain.upper(), custom_prompt=req.custom_prompt)
    parsed = yaml.safe_load(yaml_text)
    parsed["yaml_text"] = yaml_text
    STATE["specs"][domain.upper()] = parsed

    return {
        "status": "SUCCESS",
        "domain": domain.upper(),
        "provider": ai_gen.provider,
        "yaml_content": yaml_text,
        "spec": parsed
    }


@router.post("/api/ai/generate_all")
async def ai_generate_all(req: DomainGenerationRequest):
    """Generate Yamaa YAML specifications for all discovered domains in the study."""
    if STATE["metadata_df"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file in Step 1 first.")

    ai_gen = AISDTMSchemaGenerator(
        metadata_df=STATE["metadata_df"],
        df_long=STATE["df_long"],
        parser=STATE["odm_parser"],
        provider=req.provider or "auto",
        api_key=req.api_key,
        model_name=req.model_name
    )

    all_schemas = ai_gen.generate_all_schemas(custom_prompt=req.custom_prompt)
    STATE["specs"] = {}
    for d_name, yaml_text in all_schemas.items():
        parsed = yaml.safe_load(yaml_text)
        parsed["yaml_text"] = yaml_text
        STATE["specs"][d_name] = parsed

    return {
        "status": "SUCCESS",
        "provider": ai_gen.provider,
        "total_generated": len(all_schemas),
        "domains": list(all_schemas.keys()),
        "schemas": all_schemas
    }


# ==================== SPECIFICATIONS CRUD & VALIDATION ====================

@router.get("/api/specs/list")
@router.get("/api/specs")
async def list_specs():
    """List all loaded and in-memory Yamaa domain specifications."""
    specs_summary = []
    for domain, spec in STATE["specs"].items():
        specs_summary.append({
            "domain": domain,
            "description": spec.get("description", ""),
            "base": spec.get("base", "ODM"),
            "columns_count": len(spec.get("columns", [])),
            "keys": spec.get("keys", []),
            "has_sql": bool(spec.get("sql")),
            "is_ref": bool(spec.get("is_reference", False))
        })
    return {
        "domains": list(STATE["specs"].keys()),
        "specs": specs_summary,
        "total": len(STATE["specs"])
    }


@router.post("/api/specs/validate")
async def validate_spec(req: SpecContentRequest):
    """Validate a YAML schema against Yamaa standards and CDISC SDTM guidelines."""
    validator = YamaaSchemaValidator(req.get_content(), domain_hint=req.domain)
    is_valid, errors, warnings = validator.validate()
    return {
        "status": "SUCCESS",
        "domain": req.domain,
        "valid": is_valid,
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings
    }


@router.post("/api/specs/fix")
async def fix_spec(req: SpecContentRequest):
    """Automatically correct syntax, keys, and CDISC schema errors in a Yamaa YAML specification."""
    fixed_yaml, fixes = auto_fix_yamaa_schema(req.get_content(), domain=req.domain)
    validator = YamaaSchemaValidator(fixed_yaml, domain_hint=req.domain)
    is_valid, errors, warnings = validator.validate()
    return {
        "status": "SUCCESS",
        "domain": req.domain,
        "fixes_applied": fixes,
        "valid": is_valid,
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "fixed_yaml": fixed_yaml,
        "content": fixed_yaml
    }



@router.get("/api/specs/{domain}")
async def get_spec(domain: str):
    """Retrieve the full YAML specification for a given domain."""
    d_upper = domain.upper()
    if d_upper not in STATE["specs"]:
        raise HTTPException(status_code=404, detail=f"Spec for domain '{d_upper}' not found")

    spec = STATE["specs"][d_upper]
    yaml_text = spec.get("yaml_text") or yaml.dump(spec, sort_keys=False)
    return {
        "domain": d_upper,
        "yaml_content": yaml_text,
        "content": yaml_text,
        "parsed": spec
    }


@router.post("/api/specs/{domain}")
async def save_spec(domain: str, req: SpecContentRequest):
    """Save/update a YAML specification for a domain."""
    d_upper = domain.upper()
    try:
        content = req.get_content()
        parsed = yaml.safe_load(content)
        if not isinstance(parsed, dict) or "domain" not in parsed:
            raise ValueError("YAML must contain a top-level 'domain' key")

        parsed["yaml_text"] = content
        STATE["specs"][d_upper] = parsed
        return {"status": "SUCCESS", "domain": d_upper}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML content: {str(e)}")



@router.post("/api/specs_upload")
async def upload_specs(files: List[UploadFile] = File(...)):
    """Upload one or more Yamaa YAML domain specifications."""
    uploaded = []
    for f in files:
        if not (f.filename.endswith(".yaml") or f.filename.endswith(".yml")):
            continue
        try:
            content = await f.read()
            text = content.decode("utf-8")
            parsed = yaml.safe_load(text)
            if isinstance(parsed, dict) and "domain" in parsed:
                d_name = parsed["domain"].upper()
                parsed["yaml_text"] = text
                STATE["specs"][d_name] = parsed
                uploaded.append(d_name)
        except Exception as e:
            logger.warning(f"Failed to parse uploaded spec {f.filename}: {e}")

    return {
        "status": "SUCCESS",
        "uploaded_domains": uploaded,
        "total_active_specs": len(STATE["specs"])
    }
