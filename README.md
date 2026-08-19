# CDISC Builder v2 (Yamaa Schema Standard)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Polars](https://img.shields.io/badge/Polars-0.20+-CD792C.svg)](https://pola.rs)
[![CDISC SDTM](https://img.shields.io/badge/CDISC-SDTM%20v1.7%2F3.3-orange.svg)](https://www.cdisc.org)

**CDISC Builder v2** is a next-generation clinical trial data transformation platform. It reads raw Electronic Data Capture (EDC) XML (OpenClinica, Medidata Rave, Castor) and creates submission-ready CDISC SDTM datasets using declarative **Yamaa YAML specifications** and an ultra-fast **Polars transformation engine**.

---

## Key Features

1. **EDC ODM XML Ingestion**: Streamlined parsing of `MetaDataVersion` (Forms, Items, CodeLists) and `ClinicalData`.
2. **CRF Form Explorer & Domain Mapping Matrix**: Interactive matrix for reviewing study forms and selecting target SDTM domains (`DM`, `VS`, `LB`, `AE`, `EX`, `DS`, `MH`, `RS`, `RP`, `CM`, `PE`, `QS`, `EG`, `SUPP--`).
3. **Multi-Provider AI Schema Synthesizer**: Auto-generates valid Yamaa YAML specs using **Google Gemini**, **Anthropic Claude 3.7**, **OpenAI GPT-4o**, or the built-in **Offline CDISC Semantic Knowledge Engine**.
4. **Declarative Yamaa YAML Engine**: Direct mapping, column derivations, SQL row-level slicing, sequence numbering, and cross-domain reference resolution.
5. **Quality Verifications & Rule Engine**: Automated conformance checks for uniqueness and missingness constraints.
6. **Multi-Format Export Center**: One-click generation of **CSV**, **Apache Parquet**, and **SAS Transport (.XPT)** datasets or a complete submission archive (`.zip`).

---

## Quick Start (Download & Run)

### Method 1: One-Click Launchers

* **Linux / macOS**:
  ```bash
  ./run.sh
  ```
* **Windows**:
  Double-click `run.bat` or run:
  ```cmd
  run.bat
  ```

---

### Method 2: Using `uv` (Fastest Python Tooling)

```bash
# Clone or download repository
cd cdiscbuilderv2

# Launch Web Application
uv run cdiscbuilder app
```

---

### Method 3: Standard Python / PIP

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install package
pip install -e .

# Launch Web Application
cdiscbuilder app
```
The browser will automatically open to `http://127.0.0.1:8000`.

---

### Method 4: Docker & Docker Compose

```bash
docker compose up --build
```
Open `http://localhost:8000` in your browser.

---

## CLI Commands

CDISC Builder v2 includes a full-featured CLI:

* **Launch Web UI**:
  ```bash
  cdiscbuilder app --host 127.0.0.1 --port 8000
  ```

* **Headless Batch SDTM Generation**:
  ```bash
  cdiscbuilder build \
    --xml /path/to/odm.xml \
    --specs /path/to/yaml_specs_dir \
    --output ./sdtm_output \
    --formats csv,parquet,xpt
  ```

* **List & Export Built-in Yamaa Domain Templates**:
  ```bash
  # List templates
  cdiscbuilder schemas

  # Export all templates to a folder
  cdiscbuilder schemas --export-dir ./my_study_specs
  ```

* **Parse Raw ODM XML to Long Format**:
  ```bash
  cdiscbuilder parse-odm --xml /path/to/odm.xml --output long_data.csv
  ```

---

## Pre-Packaged Schema Standards & Templates

All standard Yamaa definitions and domain templates are bundled inside the package:
* `schemas/standards/`: Yamaa Schema Meta-Specifications (`schema.yaml`, `schema_derivation.yaml`, `schema_expression_*.yaml`, `schema_verification.yaml`).
* `schemas/templates/`: CDISC SDTM domain templates (`DM`, `VS`, `LB`, `AE`, `EX`, `DS`, `MH`, `RS`, `RP`, `CM`, `PE`, `QS`, `SUPPDM`, `SUPPEX`, `SUPPMH`).
* `schemas/examples/cath/`: Complete benchmark study reference specifications from the CATH study.

---

## Testing & Quality Assurance

Run the test suite:
```bash
uv run pytest
```
All 21 test suites execute in < 2 seconds with 100% pass rate.
