"""
ClinForge — End-to-End Clinical Trial Design, Data Management & Biostatistical Analysis Suite.
FastAPI modular orchestrator.
"""

import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .state import STATE, reset_study_state
from .routers import (
    study_design,
    ingest,
    schemas,
    pipeline,
    datasets,
    verifications,
    export,
    coding
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cdiscbuilderv2.app")

app = FastAPI(
    title="ClinForge API",
    description="End-to-End Clinical Trial Design, Biostatistics & CDISC SDTM Engine",
    version="2.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Modular Domain Routers
app.include_router(study_design.router)
app.include_router(ingest.router)
app.include_router(schemas.router)
app.include_router(pipeline.router)
app.include_router(datasets.router)
app.include_router(verifications.router)
app.include_router(export.router)
app.include_router(coding.router)

# Static Files & SPA Frontend
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    """Serves the ClinForge Single Page Application."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "ClinForge API is running. Build and deploy static files to view the UI."}
