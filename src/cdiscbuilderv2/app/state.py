"""
Shared in-memory application state container for ClinForge / CDISC Builder v2.
"""

from typing import Any, Dict, Optional

# Global in-memory state - starts clean, no preloaded datasets
STATE: Dict[str, Any] = {
    "xml_path": None,
    "odm_parser": None,
    "df_long": None,
    "metadata_df": None,
    "specs_dir": None,
    "specs": {},
    "pipeline": None,
    "built_domains": {},
    "verification_reports": {},
    "active_study_design": None
}


def reset_study_state():
    """Resets the study data and generated domain state."""
    STATE["xml_path"] = None
    STATE["odm_parser"] = None
    STATE["df_long"] = None
    STATE["metadata_df"] = None
    STATE["specs"] = {}
    STATE["pipeline"] = None
    STATE["built_domains"] = {}
    STATE["verification_reports"] = {}
    STATE["active_study_design"] = None
