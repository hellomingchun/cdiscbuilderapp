"""
SDTM Datasets Explorer & Single-Domain Export API Router.
Provides paginated tabular data exploration and format streaming (CSV, Parquet, XPT).
"""

import io
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
import polars as pl
import pyreadstat

from ..state import STATE

logger = logging.getLogger("cdiscbuilderv2.app.datasets")
router = APIRouter(tags=["Datasets Explorer"])


@router.get("/api/datasets/list")
@router.get("/api/datasets")
async def list_datasets():
    """Return list of all built SDTM domains."""
    return {"domains": list(STATE["built_domains"].keys()), "total": len(STATE["built_domains"])}


@router.get("/api/datasets/{domain}")
async def get_dataset_records(
    domain: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    search: Optional[str] = None
):
    """Retrieve paginated records from a built SDTM domain."""
    d_upper = domain.upper()
    if d_upper not in STATE["built_domains"]:
        raise HTTPException(status_code=404, detail=f"Domain '{d_upper}' has not been built yet. Run the pipeline in Step 3.")

    df = STATE["built_domains"][d_upper]

    if search and not df.is_empty():
        s = search.lower()
        predicates = []
        for col in df.columns:
            if df[col].dtype == pl.Utf8 or df[col].dtype == pl.Categorical:
                predicates.append(df[col].str.to_lowercase().str.contains(s))
        if predicates:
            comb = predicates[0]
            for p in predicates[1:]:
                comb = comb | p
            df = df.filter(comb)

    total = df.height
    offset = (page - 1) * page_size
    sliced = df.slice(offset, page_size)

    return {
        "domain": d_upper,
        "total": total,
        "page": page,
        "page_size": page_size,
        "columns": df.columns,
        "dtypes": {col: str(dtype) for col, dtype in zip(df.columns, df.dtypes)},
        "records": sliced.to_dicts()
    }


@router.get("/api/download/{domain}/{format}")
async def download_single_dataset(domain: str, format: str):
    """Download a single built SDTM domain in CSV, Parquet, or SAS XPT format."""
    d_upper = domain.upper()
    if d_upper not in STATE["built_domains"]:
        raise HTTPException(status_code=404, detail=f"Domain '{d_upper}' has not been built yet.")

    df = STATE["built_domains"][d_upper]
    fmt = format.lower()

    if fmt == "csv":
        buf = io.BytesIO()
        df.write_csv(buf)
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={d_upper.lower()}.csv"}
        )

    elif fmt == "parquet":
        buf = io.BytesIO()
        df.write_parquet(buf)
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={d_upper.lower()}.parquet"}
        )

    elif fmt in ("xpt", "sas7bdat"):
        import tempfile
        import os
        pandas_df = df.to_pandas()
        with tempfile.NamedTemporaryFile(suffix=".xpt", delete=False) as tf:
            tmp_p = tf.name
        pyreadstat.write_xport(
            pandas_df,
            tmp_p,
            table_name=d_upper,
            file_label=f"SDTM {d_upper} Domain",
            file_format_version=5
        )
        with open(tmp_p, "rb") as f:
            xpt_bytes = f.read()
        os.unlink(tmp_p)
        return Response(
            content=xpt_bytes,
            media_type="application/x-sas-xport",
            headers={"Content-Disposition": f"attachment; filename={d_upper.lower()}.xpt"}
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format '{format}'. Use csv, parquet, or xpt.")
