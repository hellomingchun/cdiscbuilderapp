"""
EDC ODM XML Ingest & Metadata API Router.
Handles uploading, parsing, and exploring ODM XML files and CRF data dictionaries.
"""

import os
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from ...odm_parser import ODMParser
from ...ai_generator import AISDTMSchemaGenerator
from ..state import STATE, reset_study_state

logger = logging.getLogger("cdiscbuilderv2.app.ingest")
router = APIRouter(prefix="/api/odm", tags=["EDC Ingestion"])


class LoadPathRequest(BaseModel):
    xml_path: str
    specs_dir: Optional[str] = None


class LoadRequest(BaseModel):
    path: str


@router.post("/upload")
async def upload_odm_xml(file: UploadFile = File(...)):
    """Upload and parse an ODM XML file directly into in-memory Polars dataframes."""
    if not file.filename.endswith(".xml"):
        raise HTTPException(status_code=400, detail="Only .xml files are supported")

    # Reset state
    reset_study_state()

    temp_dir = tempfile.mkdtemp(prefix="cdisc_upload_")
    saved_path = os.path.join(temp_dir, file.filename)

    try:
        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logger.info(f"Parsing uploaded ODM XML: {saved_path}")
        parser = ODMParser(saved_path)
        metadata_df = parser.get_metadata_summary()

        STATE["xml_path"] = saved_path
        STATE["odm_parser"] = parser
        STATE["df_long"] = parser.df_long
        STATE["metadata_df"] = metadata_df

        study_info = parser.study_info
        subjects_count = parser.df_long["SubjectKey"].n_unique() if not parser.df_long.is_empty() else 0

        return {
            "status": "SUCCESS",
            "filename": file.filename,
            "study_info": study_info,
            "clinical_records": parser.df_long.height,
            "total_items": metadata_df.height,
            "subjects_count": subjects_count
        }
    except Exception as e:
        logger.exception("Error parsing uploaded ODM XML")
        raise HTTPException(status_code=400, detail=f"Failed to parse ODM XML: {str(e)}")


@router.post("/load_path")
async def load_odm_from_path(req: LoadPathRequest):
    """Load an ODM XML directly from a local filesystem path."""
    xml_p = Path(req.xml_path)
    if not xml_p.exists():
        raise HTTPException(status_code=404, detail=f"XML file not found: {req.xml_path}")

    # Reset state
    reset_study_state()

    try:
        parser = ODMParser(xml_p)
        metadata_df = parser.get_metadata_summary()

        STATE["xml_path"] = str(xml_p)
        STATE["odm_parser"] = parser
        STATE["df_long"] = parser.df_long
        STATE["metadata_df"] = metadata_df

        study_info = parser.study_info
        subjects_count = parser.df_long["SubjectKey"].n_unique() if not parser.df_long.is_empty() else 0

        return {
            "status": "SUCCESS",
            "filename": xml_p.name,
            "study_info": study_info,
            "clinical_records": parser.df_long.height,
            "total_items": metadata_df.height,
            "subjects_count": subjects_count
        }
    except Exception as e:
        logger.exception(f"Error loading ODM XML from path: {req.xml_path}")
        raise HTTPException(status_code=400, detail=f"Failed to parse ODM XML: {str(e)}")


@router.post("/load")
async def load_odm_from_path_alias(req: LoadRequest):
    """Frontend-compatible alias: load an ODM XML from a local path using {path: ...} body."""
    xml_p = Path(req.path)
    if not xml_p.exists():
        raise HTTPException(status_code=404, detail=f"XML file not found: {req.path}")

    reset_study_state()
    try:
        parser = ODMParser(xml_p)
        metadata_df = parser.get_metadata_summary()
        STATE["xml_path"] = str(xml_p)
        STATE["odm_parser"] = parser
        STATE["df_long"] = parser.df_long
        STATE["metadata_df"] = metadata_df
        study_info = parser.study_info
        subjects_count = parser.df_long["SubjectKey"].n_unique() if not parser.df_long.is_empty() else 0
        return {
            "status": "SUCCESS",
            "filename": xml_p.name,
            "study_info": study_info,
            "clinical_records": parser.df_long.height,
            "total_items": metadata_df.height,
            "subjects_count": subjects_count
        }
    except Exception as e:
        logger.exception(f"Error loading ODM XML from path: {req.path}")
        raise HTTPException(status_code=400, detail=f"Failed to parse ODM XML: {str(e)}")


@router.get("/info")
async def get_study_info():
    """Retrieve study header and metadata summary."""
    if STATE["odm_parser"] is None:
        return {"loaded": False, "message": "No ODM XML loaded yet."}

    parser = STATE["odm_parser"]
    study_info = parser.study_info
    subjects_count = STATE["df_long"]["SubjectKey"].n_unique() if not STATE["df_long"].is_empty() else 0

    return {
        "loaded": True,
        "filename": Path(STATE["xml_path"]).name if STATE["xml_path"] else "Uploaded XML",
        "study_info": study_info,
        "stats": {
            "subjects_count": subjects_count,
            "form_count": STATE["metadata_df"]["FormOID"].n_unique() if STATE["metadata_df"] is not None else 0,
            "field_count": STATE["metadata_df"].height if STATE["metadata_df"] is not None else 0,
        },
        "clinical_records": STATE["df_long"].height,
        "total_items": STATE["metadata_df"].height if STATE["metadata_df"] is not None else 0,
        "subjects_count": subjects_count
    }


@router.get("/metadata")
async def get_metadata_dictionary(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = None
):
    """Retrieve paginated CRF metadata and data dictionary."""
    if STATE["metadata_df"] is None:
        raise HTTPException(status_code=400, detail="No EDC ODM XML loaded. Please upload a .xml file first.")

    meta_df = STATE["metadata_df"]

    if search:
        s = search.lower()
        meta_df = meta_df.filter(
            meta_df["ItemOID"].str.to_lowercase().str.contains(s) |
            meta_df["FormOID"].str.to_lowercase().str.contains(s) |
            meta_df["Question"].str.to_lowercase().str.contains(s)
        )

    total = meta_df.height
    offset = (page - 1) * page_size
    sliced = meta_df.slice(offset, page_size)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "records": sliced.to_dicts(),
        "forms": _get_forms_list()
    }


def _get_forms_list():
    """Build a list of form summaries with suggested domains using AISDTMSchemaGenerator."""
    if STATE["metadata_df"] is None or STATE["df_long"] is None:
        return []
    
    try:
        ai_gen = AISDTMSchemaGenerator(
            metadata_df=STATE["metadata_df"],
            df_long=STATE["df_long"],
            parser=STATE["odm_parser"]
        )
        discovered = ai_gen.discover_crf_forms()
        
        forms = []
        for f in discovered:
            forms.append({
                "FormOID": f["FormOID"],
                "FormName": f.get("FormName") or f["FormOID"],
                "Description": f.get("FormName") or f["FormOID"],
                "SuggestedDomain": f["SuggestedDomain"],
                "SuggestedClass": f.get("SuggestedClass", "FINDINGS"),
                "ItemCount": f.get("ItemCount", 0),
                "TotalRecords": f.get("TotalRecords", 0),
                "Confidence": f.get("Confidence", 80)
            })
        return forms
    except Exception as e:
        logger.warning(f"Failed to run AI form discovery: {e}")
        return []



@router.get("/forms")
async def get_forms():
    """Return list of EDC forms with suggested SDTM domain mappings for Schema Studio."""
    if STATE["metadata_df"] is None:
        raise HTTPException(status_code=400, detail="No ODM XML loaded yet.")
    return {"forms": _get_forms_list(), "total_forms": len(_get_forms_list())}
