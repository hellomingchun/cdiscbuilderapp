"""
Medical Coding API Router for MedDRA and WHO Drug Global Dictionary Standardization.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import polars as pl

from ...medical_coder import (
    MEDDRA_CODER,
    WHO_DRUG_CODER,
    MEDDRA_KNOWLEDGE_BASE,
    WHO_DRUG_KNOWLEDGE_BASE,
    auto_code_dataframe
)
from ..state import STATE

router = APIRouter(prefix="/api/coding", tags=["Medical Coding"])


class CodeTermsRequest(BaseModel):
    terms: List[str]
    dictionary: str = "meddra"  # "meddra" or "whodrug"


class AutoCodeDomainRequest(BaseModel):
    domain: str                 # "AE", "MH", "CM"
    dataset_name: Optional[str] = None


@router.get("/dictionary_stats")
async def get_dictionary_stats():
    """Returns statistics and coverage metrics for loaded medical dictionaries."""
    meddra_socs = sorted(list({e["soc"] for e in MEDDRA_KNOWLEDGE_BASE}))
    whodrug_classes = sorted(list({e["therapeutic_class"] for e in WHO_DRUG_KNOWLEDGE_BASE}))
    
    return {
        "status": "SUCCESS",
        "meddra": {
            "version": "MedDRA 26.1 Curated",
            "total_preferred_terms": len(MEDDRA_KNOWLEDGE_BASE),
            "total_synonyms": sum(len(e.get("synonyms", [])) for e in MEDDRA_KNOWLEDGE_BASE),
            "system_organ_classes": meddra_socs,
            "total_socs": len(meddra_socs)
        },
        "whodrug": {
            "version": "WHO Drug Global B3/C3 Curated",
            "total_preferred_names": len(WHO_DRUG_KNOWLEDGE_BASE),
            "total_synonyms": sum(len(e.get("synonyms", [])) for e in WHO_DRUG_KNOWLEDGE_BASE),
            "therapeutic_classes": whodrug_classes,
            "total_classes": len(whodrug_classes)
        }
    }


@router.post("/code_terms")
async def code_terms(req: CodeTermsRequest):
    """
    Codes a batch of verbatim terms into MedDRA or WHO Drug hierarchies.
    """
    results = []
    dict_type = req.dictionary.lower().strip()
    
    for term in req.terms:
        if dict_type in ("meddra", "ae", "mh"):
            rec = MEDDRA_CODER.code_term(term)
            results.append(rec.model_dump())
        elif dict_type in ("whodrug", "who_drug", "cm"):
            rec = WHO_DRUG_CODER.code_term(term)
            results.append(rec.model_dump())
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported dictionary type: {req.dictionary}")
            
    return {
        "status": "SUCCESS",
        "dictionary": req.dictionary,
        "total_terms": len(req.terms),
        "results": results
    }


@router.post("/auto_code_domain")
async def auto_code_domain_endpoint(req: AutoCodeDomainRequest):
    """
    Automatically codes an active built domain or uploaded dataset in app state.
    """
    d = req.domain.upper()
    df: Optional[pl.DataFrame] = None

    built_domains = STATE.get("built_domains", {})
    if d in built_domains:
        df = built_domains[d]

    if df is None or df.height == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No dataset found for domain '{d}'. Please build the domain in SDTM pipeline first."
        )

    enriched_df, metrics = auto_code_dataframe(df, d)
    
    # Update app state with enriched DataFrame
    STATE["built_domains"][d] = enriched_df

    # Convert preview to JSON dict
    preview_rows = enriched_df.head(100).to_dicts()
    
    return {
        "status": "SUCCESS",
        "domain": d,
        "metrics": metrics,
        "columns": enriched_df.columns,
        "preview": preview_rows,
        "total_rows": enriched_df.height
    }
