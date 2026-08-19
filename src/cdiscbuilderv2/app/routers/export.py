"""
Submission Export & Packaging API Router.
Handles complete zip archive generation with CSV, Parquet, and SAS XPT datasets.
"""

import io
import os
import logging
import tempfile
import zipfile
from typing import Optional
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from starlette.responses import StreamingResponse
import pyreadstat
import yaml

from ..state import STATE

logger = logging.getLogger("cdiscbuilderv2.app.export")
router = APIRouter(tags=["Export & Packaging"])


def build_complete_zip() -> io.BytesIO:
    """Helper that packages all built SDTM domains into a zip buffer."""
    if not STATE["built_domains"] and not STATE["specs"]:
        raise HTTPException(status_code=400, detail="No built datasets or specifications available for export.")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # 1. Export Specs
        for d_name, spec in STATE["specs"].items():
            yaml_content = spec.get("yaml_text") or yaml.dump(spec, sort_keys=False)
            zip_file.writestr(f"specs/{d_name.lower()}.yaml", yaml_content)

        # 2. Export Datasets in multiple formats
        for d_name, df in STATE["built_domains"].items():
            # CSV
            csv_buf = io.BytesIO()
            df.write_csv(csv_buf)
            zip_file.writestr(f"sdtm_csv/{d_name.lower()}.csv", csv_buf.getvalue())

            # Parquet
            pq_buf = io.BytesIO()
            df.write_parquet(pq_buf)
            zip_file.writestr(f"sdtm_parquet/{d_name.lower()}.parquet", pq_buf.getvalue())

            # SAS XPT
            try:
                pandas_df = df.to_pandas()
                with tempfile.NamedTemporaryFile(suffix=".xpt", delete=False) as tf:
                    tmp_p = tf.name
                pyreadstat.write_xport(
                    pandas_df,
                    tmp_p,
                    table_name=d_name,
                    file_label=f"SDTM {d_name} Domain",
                    file_format_version=5
                )
                with open(tmp_p, "rb") as f:
                    xpt_bytes = f.read()
                os.unlink(tmp_p)
                zip_file.writestr(f"sdtm_xpt/{d_name.lower()}.xpt", xpt_bytes)
            except Exception as e:
                logger.warning(f"Failed to convert {d_name} to XPT in zip export: {e}")

    zip_buffer.seek(0)
    return zip_buffer



class ExportZipOptions(BaseModel):
    include_csv: Optional[bool] = True
    include_xpt: Optional[bool] = True
    include_parquet: Optional[bool] = True
    include_yaml: Optional[bool] = True
    include_define_xml: Optional[bool] = False


@router.get("/api/export/zip")
@router.post("/api/export/zip")
@router.get("/api/download/zip")
@router.post("/api/download/zip")
async def export_zip_archive(options: Optional[ExportZipOptions] = None):
    """Download complete SDTM submission package as a ZIP archive."""
    zip_buf = build_complete_zip()
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=sdtm_submission_package.zip"}
    )



@router.get("/api/export/{domain}/{format}")
async def export_single_domain(domain: str, format: str):
    """Export a single SDTM domain in CSV, Parquet, or XPT format."""
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
        pandas_df = df.to_pandas()
        buf = io.BytesIO()
        pyreadstat.write_xport(
            pandas_df,
            buf,
            table_name=d_upper,
            dataset_label=f"SDTM {d_upper} Domain",
            file_format_version=5
        )
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="application/x-sas-xport",
            headers={"Content-Disposition": f"attachment; filename={d_upper.lower()}.xpt"}
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format '{format}'")
