import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from cdiscbuilderv2.app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_api_index(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "CDISC Builder" in response.text


def test_api_clean_initial_state(client):
    res = client.get("/api/odm/info")
    assert res.status_code == 200
    assert res.json()["loaded"] is False


def test_api_load_odm_path(client):
    cath_xml = "/home/ming/Documents/yamaa/cath/odm/odm.xml"
    if not Path(cath_xml).exists():
        pytest.skip("CATH ODM XML not found")

    response = client.post("/api/odm/load_path", json={"path": cath_xml})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["subjects_count"] == 82
    assert data["total_items"] > 5000


def test_api_upload_spec_and_pipeline(client):
    # 1. Add spec using standard Yamaa format
    spec_yaml = """domain: DM
datasets:
  ODM: input/odm.csv
base: ODM
keys: [STUDYID, USUBJID]
columns:
  - name: STUDYID
    type: str
    derivation: { source: StudyOID }
  - name: DOMAIN
    type: str
    derivation: { literal: DM }
  - name: USUBJID
    type: str
    derivation: { source: SubjectKey }
rows:
  - id: subject
    filter: "ItemOID = 'IT.NCT00789880.DM.SEX'"
    derivations:
      USUBJID: { source: SubjectKey }
"""
    spec_res = client.post("/api/specs/DM", json={"domain": "DM", "yaml_content": spec_yaml})
    assert spec_res.status_code == 200

    # 2. Run pipeline
    cath_xml = "/home/ming/Documents/yamaa/cath/odm/odm.xml"
    if Path(cath_xml).exists():
        client.post("/api/odm/load_path", json={"path": cath_xml})
        response = client.post("/api/pipeline/run", json={"formats": ["csv", "parquet"]})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "SUCCESS"


def test_api_crf_forms_and_generate(client):
    cath_xml = "/home/ming/Documents/yamaa/cath/odm/odm.xml"
    if not Path(cath_xml).exists():
        pytest.skip("CATH ODM XML not found")

    client.post("/api/odm/load_path", json={"path": cath_xml})
    
    # 1. Fetch CRF forms
    forms_res = client.get("/api/ai/crf_forms")
    assert forms_res.status_code == 200
    forms_data = forms_res.json()
    assert forms_data["total_forms"] > 10
    
    # 2. Generate specs from selected form mappings
    gen_res = client.post("/api/ai/generate_from_forms", json={
        "form_mappings": {
            "FO.NCT00789880.DM": "DM",
            "FO.NCT00789880.VS": "VS",
            "FO.NCT00789880.SK": "RS"
        }
    })
    assert gen_res.status_code == 200
    gen_data = gen_res.json()
    # 3. Run pipeline to build datasets from generated specs
    pipe_res = client.post("/api/pipeline/run", json={"formats": ["csv", "parquet"]})
    assert pipe_res.status_code == 200

    # 4. Query dataset
    dm_res = client.get("/api/datasets/DM")
    assert dm_res.status_code == 200
    assert dm_res.json()["total"] == 82

def test_api_zip_export(client):
    import polars as pl
    from cdiscbuilderv2.app.main import STATE
    STATE["built_domains"]["DM"] = pl.DataFrame({"STUDYID": ["ST01"], "DOMAIN": ["DM"], "USUBJID": ["001"]})
    res = client.get("/api/export/zip")
    assert res.status_code == 200
    assert "application/zip" in res.headers.get("content-type", "")
    assert len(res.content) > 0
