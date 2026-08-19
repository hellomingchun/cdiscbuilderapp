"""
FastAPI backend for CDISC Builder v2 Web Application.
Handles ODM XML ingestion, AI-driven CDISC SDTM Yamaa schema generation,
live Yamaa YAML specification management, pipeline execution, SDTM data preview,
data quality validation, and export.
"""

import io
import json
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl
import yaml
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..ai_generator import AISDTMSchemaGenerator
from ..engine import CDISCEngine
from ..odm_parser import ODMParser
from ..pipeline import SDTMPipeline
from ..validator import YamaaSchemaValidator
from ..verifications import VerificationEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cdiscbuilderv2.app")

app = FastAPI(
    title="CDISC Builder v2 API",
    description="Next-Gen EDC to SDTM Automation Engine with AI Schema Studio",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global in-memory state - starts clean, no preloaded datasets
STATE = {
    "xml_path": None,
    "odm_parser": None,
    "df_long": None,
    "metadata_df": None,
    "specs_dir": None,
    "specs": {},
    "pipeline": None,
    "built_domains": {},
    "verification_reports": {},
    "output_dir": Path(tempfile.mkdtemp(prefix="sdtm_build_"))
}

# Mount static folder
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- Pydantic Models ---
class LoadPathRequest(BaseModel):
    path: str


class SpecUpdateRequest(BaseModel):
    domain: str
    yaml_content: str


class AIGenerateRequest(BaseModel):
    domains: Optional[List[str]] = None
    provider: Optional[str] = "auto"
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    custom_prompt: Optional[str] = None


class GenerateFromFormsRequest(BaseModel):
    form_mappings: Dict[str, str]
    provider: Optional[str] = "auto"
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    custom_prompt: Optional[str] = None


class RunPipelineRequest(BaseModel):
    formats: Optional[List[str]] = ["csv", "parquet", "xpt"]


# ==================== AI SDTM SCHEMA STUDIO ENDPOINTS ====================

@app.get("/api/ai/crf_forms")
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


@app.post("/api/ai/generate_from_forms")
async def ai_generate_from_forms(req: GenerateFromFormsRequest):
    """AI generates Yamaa YAML schemas for user-selected CRF Form -> SDTM Domain mappings."""
    if STATE["df_long"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file in Step 1 first.")

    ai_gen = AISDTMSchemaGenerator(
        metadata_df=STATE["metadata_df"],
        df_long=STATE["df_long"],
        parser=STATE["odm_parser"],
        provider=req.provider or "auto",
        api_key=req.api_key,
        model_name=req.model_name
    )

    generated_map = ai_gen.generate_schemas_for_form_mappings(req.form_mappings, custom_prompt=req.custom_prompt)
    for d_name, yaml_text in generated_map.items():
        parsed = yaml.safe_load(yaml_text)
        parsed["yaml_text"] = yaml_text
        STATE["specs"][d_name] = parsed

    return {
        "status": "SUCCESS",
        "provider": ai_gen.provider,
        "generated_domains": list(generated_map.keys()),
        "schemas": generated_map
    }


@app.get("/api/ai/discover_domains")
async def ai_discover_domains():
    """Analyze ingested EDC XML metadata and discover potential SDTM domains."""
    if STATE["metadata_df"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file in Step 1 first.")

    ai_gen = AISDTMSchemaGenerator(metadata_df=STATE["metadata_df"], df_long=STATE["df_long"], parser=STATE["odm_parser"])
    discovered = ai_gen.discover_domains()
    return {
        "status": "SUCCESS",
        "total_discovered": len(discovered),
        "discovered_domains": discovered
    }


@app.post("/api/ai/generate_schemas")
async def ai_generate_schemas(req: AIGenerateRequest):
    """AI generates full Yamaa YAML schemas for all or selected discovered SDTM domains."""
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
    discovered = ai_gen.discover_domains()
    
    target_domains = req.domains or [d["domain"] for d in discovered]
    generated_map = {}

    for d in discovered:
        d_name = d["domain"]
        if d_name in target_domains:
            yaml_text = ai_gen.generate_domain_schema(d_name, d["matched_items"], custom_prompt=req.custom_prompt)
            parsed = yaml.safe_load(yaml_text)
            parsed["yaml_text"] = yaml_text
            STATE["specs"][d_name] = parsed
            generated_map[d_name] = yaml_text

    return {
        "status": "SUCCESS",
        "provider": ai_gen.provider,
        "generated_domains": list(generated_map.keys()),
        "schemas": generated_map
    }


@app.post("/api/ai/generate_domain/{domain}")
async def ai_generate_single_domain(domain: str, req: AIGenerateRequest):
    """AI generates or refines a single domain schema based on CRF metadata."""
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
    yaml_text = ai_gen.generate_domain_schema(domain.upper(), custom_prompt=req.custom_prompt)
    
    parsed = yaml.safe_load(yaml_text)
    parsed["yaml_text"] = yaml_text
    STATE["specs"][domain.upper()] = parsed

    return {
        "status": "SUCCESS",
        "provider": ai_gen.provider,
        "domain": domain.upper(),
        "yaml_content": yaml_text
    }


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        with open(index_file, "r") as f:
            return f.read()
    return "<h1>CDISC Builder v2 API is running</h1>"


@app.post("/api/odm/upload")
async def upload_odm_xml(file: UploadFile = File(...)):
    """Upload and parse an ODM XML file from user's local machine."""
    try:
        content = await file.read()
        parser = ODMParser(content)
        
        # Save temp file
        temp_xml = STATE["output_dir"] / file.filename
        with open(temp_xml, "wb") as f:
            f.write(content)
            
        STATE["xml_path"] = temp_xml
        STATE["odm_parser"] = parser
        STATE["df_long"] = parser.df_long
        STATE["metadata_df"] = parser.get_metadata_summary()
        STATE["built_domains"] = {}
        STATE["verification_reports"] = {}

        return {
            "status": "SUCCESS",
            "filename": file.filename,
            "study_info": parser.study_info,
            "total_items": parser.df_long.height,
            "subjects_count": len(parser.df_long["SubjectKey"].unique()) if parser.df_long.height > 0 else 0,
            "forms_count": len(parser.df_long["FormOID"].unique()) if parser.df_long.height > 0 else 0,
            "item_defs_count": len(parser.item_defs)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse ODM XML: {str(e)}")


@app.post("/api/odm/load_path")
async def load_odm_path(req: LoadPathRequest):
    """Load an ODM XML file from a server path."""
    p = Path(req.path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {req.path}")

    try:
        parser = ODMParser(p)
        STATE["xml_path"] = p
        STATE["odm_parser"] = parser
        STATE["df_long"] = parser.df_long
        STATE["metadata_df"] = parser.get_metadata_summary()
        STATE["built_domains"] = {}
        STATE["verification_reports"] = {}

        return {
            "status": "SUCCESS",
            "path": str(p),
            "study_info": parser.study_info,
            "total_items": parser.df_long.height,
            "subjects_count": len(parser.df_long["SubjectKey"].unique()) if parser.df_long.height > 0 else 0,
            "forms_count": len(parser.df_long["FormOID"].unique()) if parser.df_long.height > 0 else 0,
            "item_defs_count": len(parser.item_defs)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse ODM XML from {req.path}: {str(e)}")


@app.get("/api/odm/info")
async def get_odm_info():
    """Retrieve current study and ingestion metrics."""
    if STATE["odm_parser"] is None:
        return {"loaded": False}

    parser = STATE["odm_parser"]
    return {
        "loaded": True,
        "xml_path": str(STATE["xml_path"]),
        "study_info": parser.study_info,
        "total_records": parser.df_long.height,
        "subjects_count": len(parser.df_long["SubjectKey"].unique()) if parser.df_long.height > 0 else 0,
        "forms": sorted(list(set(parser.df_long["FormOID"].to_list()))),
        "events": sorted(list(set(parser.df_long["StudyEventOID"].to_list()))),
        "item_defs_count": len(parser.item_defs)
    }


@app.get("/api/odm/metadata")
async def get_odm_metadata(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = None
):
    """Retrieve paginated CRF metadata definitions with sample values."""
    if STATE["odm_parser"] is None:
        return {"records": [], "total": 0, "page": page, "page_size": page_size}

    meta_df = STATE["odm_parser"].get_metadata_summary()
    if search and search.strip():
        s = search.strip().lower()
        meta_df = meta_df.filter(
            pl.col("FormOID").cast(pl.Utf8).str.to_lowercase().str.contains(s)
            | pl.col("ItemOID").cast(pl.Utf8).str.to_lowercase().str.contains(s)
            | pl.col("ItemName").cast(pl.Utf8).str.to_lowercase().str.contains(s)
            | pl.col("Question").cast(pl.Utf8).str.to_lowercase().str.contains(s)
        )

    total = meta_df.height
    offset = (page - 1) * page_size
    paged_df = meta_df.slice(offset, page_size)
    return {
        "records": paged_df.to_dicts(),
        "total": total,
        "page": page,
        "page_size": page_size
    }


@app.get("/api/odm/preview")
async def get_odm_preview(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    form: Optional[str] = None,
    subject: Optional[str] = None
):
    """Preview long-format clinical data items."""
    if STATE["df_long"] is None:
        return {"records": [], "total": 0, "columns": []}

    df = STATE["df_long"]
    if form:
        df = df.filter(pl.col("FormOID") == form)
    if subject:
        df = df.filter(pl.col("SubjectKey") == subject)

    total = df.height
    offset = (page - 1) * page_size
    paged_df = df.slice(offset, page_size)
    return {
        "records": paged_df.to_dicts(),
        "columns": df.columns,
        "total": total,
        "page": page,
        "page_size": page_size
    }


# ==================== AI SDTM SCHEMA STUDIO ENDPOINTS ====================

@app.get("/api/ai/discover_domains")
async def ai_discover_domains():
    """Analyze ingested EDC XML metadata and discover potential SDTM domains."""
    if STATE["metadata_df"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file in Step 1 first.")

    ai_gen = AISDTMSchemaGenerator(metadata_df=STATE["metadata_df"], df_long=STATE["df_long"])
    discovered = ai_gen.discover_domains()
    return {
        "status": "SUCCESS",
        "total_discovered": len(discovered),
        "discovered_domains": discovered
    }


@app.post("/api/ai/generate_schemas")
async def ai_generate_schemas(req: AIGenerateRequest):
    """AI generates full Yamaa YAML schemas for all or selected discovered SDTM domains."""
    if STATE["metadata_df"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file in Step 1 first.")

    ai_gen = AISDTMSchemaGenerator(
        metadata_df=STATE["metadata_df"],
        df_long=STATE["df_long"],
        provider=req.provider or "auto",
        api_key=req.api_key,
        model_name=req.model_name
    )
    discovered = ai_gen.discover_domains()
    
    target_domains = req.domains or [d["domain"] for d in discovered]
    generated_map = {}

    for d in discovered:
        d_name = d["domain"]
        if d_name in target_domains:
            yaml_text = ai_gen.generate_domain_schema(d_name, d["matched_items"], custom_prompt=req.custom_prompt)
            parsed = yaml.safe_load(yaml_text)
            parsed["yaml_text"] = yaml_text
            STATE["specs"][d_name] = parsed
            generated_map[d_name] = yaml_text

    return {
        "status": "SUCCESS",
        "provider": ai_gen.provider,
        "generated_domains": list(generated_map.keys()),
        "schemas": generated_map
    }


@app.post("/api/ai/generate_domain/{domain}")
async def ai_generate_single_domain(domain: str, req: AIGenerateRequest):
    """AI generates or refines a single domain schema based on CRF metadata."""
    if STATE["metadata_df"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file in Step 1 first.")

    ai_gen = AISDTMSchemaGenerator(
        metadata_df=STATE["metadata_df"],
        df_long=STATE["df_long"],
        provider=req.provider or "auto",
        api_key=req.api_key,
        model_name=req.model_name
    )
    yaml_text = ai_gen.generate_domain_schema(domain.upper(), custom_prompt=req.custom_prompt)
    
    parsed = yaml.safe_load(yaml_text)
    parsed["yaml_text"] = yaml_text
    STATE["specs"][domain.upper()] = parsed

    return {
        "status": "SUCCESS",
        "provider": ai_gen.provider,
        "domain": domain.upper(),
        "yaml_content": yaml_text
    }


# ==================== SPECIFICATION MANAGEMENT ENDPOINTS ====================

@app.get("/api/specs")
async def list_specs():
    """List all currently loaded or authored YAML domain specifications."""
    specs_list = []
    for domain, spec in sorted(STATE["specs"].items()):
        is_findings = False
        if spec.get("is_domain_format"):
            raw_cfg = spec.get("raw_config", {})
            is_findings = isinstance(raw_cfg, dict) and raw_cfg.get("type") == "FINDINGS"
        else:
            if "columns" in spec:
                is_findings = any("LB" in domain or "VS" in domain or "MB" in domain or "EG" in domain for _ in [1])

        specs_list.append({
            "domain": domain,
            "type": "FINDINGS" if is_findings else "EVENTS/GENERAL",
            "is_ref": domain.startswith("_")
        })
    return {"specs": specs_list}


@app.post("/api/specs/validate")
async def validate_yaml_spec(req: SpecUpdateRequest):
    """Validates a Yamaa YAML specification string in real-time."""
    validator = YamaaSchemaValidator(req.yaml_content, req.domain)
    is_valid, errors, warnings = validator.validate()
    return {
        "status": "VALID" if is_valid else "INVALID",
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "domain": validator.domain if hasattr(validator, "domain") else req.domain
    }


@app.post("/api/specs/fix")
async def auto_fix_spec(req: SpecUpdateRequest):
    """Automatically repairs and standardizes a YAML specification to 100% valid Yamaa standard."""
    from ..validator import auto_fix_yamaa_schema, YamaaSchemaValidator
    fixed_yaml, fixes = auto_fix_yamaa_schema(req.yaml_content, req.domain)
    
    v = YamaaSchemaValidator(fixed_yaml, req.domain)
    is_valid, errors, warnings = v.validate()
    
    return {
        "status": "SUCCESS",
        "fixed_yaml": fixed_yaml,
        "fixes_applied": fixes,
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings
    }


@app.get("/api/specs/{domain}")
async def get_spec(domain: str):
    """Get the YAML text content of a specific domain."""
    if domain not in STATE["specs"]:
        raise HTTPException(status_code=404, detail=f"Domain spec '{domain}' not found")
    spec_data = STATE["specs"][domain]
    return {
        "domain": domain,
        "yaml_content": spec_data.get("yaml_text", yaml.dump(spec_data, sort_keys=False))
    }


@app.post("/api/specs/{domain}")
async def update_spec(domain: str, req: SpecUpdateRequest):
    """Save or create a domain YAML specification."""
    try:
        parsed = yaml.safe_load(req.yaml_content)
        if isinstance(parsed, dict) and "domain" not in parsed and len(parsed) == 1:
            d_name = list(parsed.keys())[0]
            STATE["specs"][domain] = {
                "domain": domain,
                "is_domain_format": True,
                "raw_config": parsed[d_name],
                "yaml_text": req.yaml_content
            }
        else:
            if isinstance(parsed, dict):
                parsed["domain"] = domain
                parsed["yaml_text"] = req.yaml_content
                STATE["specs"][domain] = parsed
            else:
                STATE["specs"][domain] = {"domain": domain, "yaml_text": req.yaml_content}

        return {"status": "SUCCESS", "domain": domain}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML content: {str(e)}")


@app.post("/api/specs_upload")
async def upload_spec_files(files: List[UploadFile] = File(...)):
    """Upload one or more .yaml specification files."""
    loaded_domains = []
    for file in files:
        if not file.filename.endswith((".yaml", ".yml")):
            continue
        try:
            content = await file.read()
            text = content.decode("utf-8")
            parsed = yaml.safe_load(text)
            
            d_name = file.filename.rsplit(".", 1)[0].upper()
            if isinstance(parsed, dict) and "domain" in parsed:
                d_name = parsed["domain"]
                parsed["yaml_text"] = text
                STATE["specs"][d_name] = parsed
            elif isinstance(parsed, dict) and len(parsed) == 1:
                key_name = list(parsed.keys())[0]
                d_name = key_name.upper()
                STATE["specs"][d_name] = {
                    "domain": d_name,
                    "is_domain_format": True,
                    "raw_config": parsed[key_name],
                    "yaml_text": text
                }
            else:
                STATE["specs"][d_name] = {"domain": d_name, "yaml_text": text}
            loaded_domains.append(d_name)
        except Exception as e:
            logger.warning(f"Error parsing spec {file.filename}: {e}")

    return {"status": "SUCCESS", "loaded_domains": loaded_domains}


@app.post("/api/pipeline/run")
async def run_pipeline(req: RunPipelineRequest):
    """Execute the SDTM generation pipeline for all configured domain specs."""
    if STATE["df_long"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file first.")

    if not STATE["specs"]:
        raise HTTPException(status_code=400, detail="No domain specifications available. Please create, generate, or upload Yamaa YAML specs.")

    try:
        formats = req.formats or ["csv", "parquet", "xpt"]
        out_dir = STATE["output_dir"] / "sdtm_output"
        out_dir.mkdir(parents=True, exist_ok=True)

        built_domains: Dict[str, pl.DataFrame] = {}
        verification_reports: Dict[str, Any] = {}

        # 1. Separate reference domains
        ref_domains = [d for d in STATE["specs"] if d.startswith("_")]
        std_domains = [d for d in STATE["specs"] if not d.startswith("_") and not d.startswith("SUPP")]
        supp_domains = [d for d in STATE["specs"] if d.startswith("SUPP")]

        execution_order = ref_domains + (["DM"] if "DM" in std_domains else [])
        for d in std_domains:
            if d not in execution_order:
                execution_order.append(d)
        execution_order.extend(supp_domains)

        # 2. Execute builds in dependency order
        for domain in execution_order:
            spec_def = STATE["specs"].get(domain)
            if not spec_def:
                continue

            engine = CDISCEngine(
                spec=spec_def,
                df_long=STATE["df_long"],
                built_domains=built_domains
            )
            df = engine.build()
            built_domains[domain] = df

            if engine.verification_report:
                verification_reports[domain] = engine.verification_report.to_dict()

            if not domain.startswith("_"):
                engine.save(out_dir, formats=formats)

        STATE["built_domains"] = built_domains
        STATE["verification_reports"] = verification_reports

        # Build summary response
        results = []
        for domain, df in built_domains.items():
            if domain.startswith("_"):
                continue
            rep = verification_reports.get(domain, {})
            results.append({
                "domain": domain,
                "rows": df.height,
                "columns_count": len(df.columns),
                "columns": df.columns,
                "is_valid": rep.get("is_valid", True),
                "failing_rules_count": rep.get("failing_rules_count", 0)
            })

        return {
            "status": "SUCCESS",
            "results": results,
            "datasets": results,
            "verifications": verification_reports,
            "output_dir": str(out_dir)
        }

    except Exception as e:
        logger.exception("Pipeline execution failed")
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")


@app.get("/api/datasets/{domain}")
async def get_dataset(
    domain: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = None
):
    """Retrieve and filter records from a generated SDTM domain."""
    if domain not in STATE["built_domains"]:
        raise HTTPException(status_code=404, detail=f"Domain dataset '{domain}' not found. Run pipeline first.")

    df = STATE["built_domains"][domain]

    if search and search.strip():
        s = search.strip().lower()
        pred = None
        for col in df.columns:
            cond = pl.col(col).cast(pl.Utf8, strict=False).str.to_lowercase().str.contains(s)
            pred = cond if pred is None else (pred | cond)
        if pred is not None:
            df = df.filter(pred)

    total = df.height
    offset = (page - 1) * page_size
    paged_df = df.slice(offset, page_size)

    dtypes_map = {col: str(dtype) for col, dtype in zip(df.columns, df.dtypes)}

    return {
        "domain": domain,
        "records": paged_df.to_dicts(),
        "columns": df.columns,
        "dtypes": dtypes_map,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@app.get("/api/verifications")
async def get_all_verifications():
    """Retrieve verification compliance reports for all domains."""
    return {"verifications": STATE["verification_reports"]}


@app.get("/api/export/zip")
@app.get("/api/export_all_zip")
@app.get("/api/download/zip")
async def export_all_zip():
    """Download zip archive of all generated SDTM datasets."""
    out_dir = STATE["output_dir"] / "sdtm_output"
    
    # If not written to disk yet but built_domains exists, save them now
    if STATE["built_domains"]:
        out_dir.mkdir(parents=True, exist_ok=True)
        for domain, df in STATE["built_domains"].items():
            if domain.startswith("_"):
                continue
            csv_p = out_dir / f"{domain.lower()}.csv"
            parq_p = out_dir / f"{domain.lower()}.parquet"
            xpt_p = out_dir / f"{domain.lower()}.xpt"
            if not csv_p.exists():
                df.write_csv(csv_p)
            if not parq_p.exists():
                df.write_parquet(parq_p)
            if not xpt_p.exists():
                try:
                    import pyreadstat
                    pyreadstat.write_xport(df.to_pandas(), str(xpt_p), table_name=domain.upper())
                except Exception as e:
                    logger.warning(f"Could not export xpt for {domain}: {e}")

    if not out_dir.exists() or not list(out_dir.glob("*")):
        raise HTTPException(status_code=400, detail="No output datasets found. Please run the build pipeline in Step 3 first.")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_p in out_dir.glob("*"):
            if file_p.is_file():
                zip_file.write(file_p, arcname=file_p.name)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=sdtm_submission_package.zip",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


@app.get("/api/export/{domain}/{format}")
@app.get("/api/download/{domain}/{format}")
async def export_domain_file(domain: str, format: str):
    """Download single domain file (csv, parquet, xpt)."""
    if domain not in STATE["built_domains"]:
        raise HTTPException(status_code=404, detail=f"Domain dataset '{domain}' not found. Please run the build pipeline first.")

    out_dir = STATE["output_dir"] / "sdtm_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"{domain.lower()}.{format.lower()}"

    if not file_path.exists():
        df = STATE["built_domains"][domain]
        if format.lower() == "csv":
            df.write_csv(file_path)
        elif format.lower() == "parquet":
            df.write_parquet(file_path)
        elif format.lower() == "xpt":
            import pyreadstat
            pyreadstat.write_xport(df.to_pandas(), str(file_path), table_name=domain.upper())

    if not file_path.exists():
        raise HTTPException(status_code=500, detail=f"Could not generate {format} file for {domain}")

    media_types = {
        "csv": "text/csv",
        "parquet": "application/octet-stream",
        "xpt": "application/octet-stream"
    }

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type=media_types.get(format.lower(), "application/octet-stream")
    )
