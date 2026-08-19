"""
Clinical Study Design Archetypes & Biostatistical Calculation Engine for CDISC Builder v2.
Covers major industry clinical trial designs across Oncology, Medical Devices,
Bioequivalence, Cardiovascular, Rare Diseases, and CNS.
"""

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


# ==================== BIOSTATISTICAL CALCULATION MODELS & FUNCTIONS ====================

class SampleSizeRequest(BaseModel):
    design_id: str
    endpoint_type: str = "continuous"  # "continuous", "binary", "survival", "diagnostic", "simon"
    hypothesis: str = "superiority"     # "superiority", "non_inferiority", "equivalence", "single_arm"
    alpha: float = 0.05
    power: float = 0.80
    allocation_ratio: float = 1.0       # n2 / n1 (e.g. 1.0 for 1:1, 2.0 for 2:1)
    dropout_rate: float = 0.10          # anticipated attrition (e.g. 10%)
    
    # Continuous parameters
    mean_control: Optional[float] = 10.0
    mean_treatment: Optional[float] = 14.0
    sd_pooled: Optional[float] = 8.0
    
    # Binary parameters
    prop_control: Optional[float] = 0.30
    prop_treatment: Optional[float] = 0.50
    
    # Non-inferiority / Equivalence margin
    delta_margin: Optional[float] = 0.10
    
    # Survival / Time-to-Event parameters
    hazard_ratio: Optional[float] = 0.70
    event_rate_control: Optional[float] = 0.40
    
    # Diagnostic parameters
    sensitivity: Optional[float] = 0.90
    prevalence: Optional[float] = 0.20
    ci_half_width: Optional[float] = 0.05


def get_z_value(p: float) -> float:
    """Approximate inverse normal cumulative distribution function (quantile)."""
    # High precision Abramowitz and Stegun rational approximation
    if p <= 0.0 or p >= 1.0:
        return 1.96
    if p < 0.5:
        t = math.sqrt(-2.0 * math.log(p))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        return -(t - ((c2 * t + c1) * t + c0) / (((d3 * t + d2) * t + d1) * t + 1.0))
    else:
        t = math.sqrt(-2.0 * math.log(1.0 - p))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        return t - ((c2 * t + c1) * t + c0) / (((d3 * t + d2) * t + d1) * t + 1.0)


def calculate_sample_size(req: SampleSizeRequest) -> Dict[str, Any]:
    """
    Computes biostatistically rigorous sample size and required events
    based on study design, hypothesis, alpha, and power.
    """
    # 1-sided vs 2-sided alpha
    is_one_sided = req.hypothesis in ("non_inferiority", "single_arm")
    effective_alpha = req.alpha if is_one_sided else req.alpha / 2.0
    
    z_alpha = get_z_value(1.0 - effective_alpha)
    z_beta = get_z_value(req.power)
    r = max(req.allocation_ratio, 0.1)

    n1, n2, total_n = 0, 0, 0
    events_required = None
    details = {}

    if req.endpoint_type == "continuous":
        m1 = req.mean_control or 0.0
        m2 = req.mean_treatment or 0.0
        sd = max(req.sd_pooled or 1.0, 0.001)
        diff = abs(m2 - m1)
        
        if req.hypothesis == "non_inferiority":
            margin = req.delta_margin or (0.1 * sd)
            effective_diff = max(diff + margin, 0.001)
            n1_raw = ((r + 1.0) * (z_alpha + z_beta)**2 * (sd**2)) / (r * (effective_diff**2))
            details["Formula"] = "Continuous Non-Inferiority: N1 = (r+1)(Z_alpha + Z_beta)^2 * SD^2 / (r * (Diff + Margin)^2)"
        elif req.hypothesis == "equivalence":
            margin = max(req.delta_margin or (0.1 * sd), 0.001)
            n1_raw = (2.0 * (z_alpha + z_beta)**2 * (sd**2)) / (margin**2)
            details["Formula"] = "Continuous TOST Equivalence: N1 = 2(Z_alpha + Z_beta)^2 * SD^2 / Margin^2"
        else:  # Superiority
            eff_diff = max(diff, 0.001)
            n1_raw = ((r + 1.0) * (z_alpha + z_beta)**2 * (sd**2)) / (r * (eff_diff**2))
            details["Formula"] = "Continuous Superiority: N1 = (r+1)(Z_alpha/2 + Z_beta)^2 * SD^2 / (r * Delta^2)"

        n1 = math.ceil(n1_raw)
        n2 = math.ceil(n1 * r)
        total_n = n1 + n2

    elif req.endpoint_type == "binary":
        p1 = max(min(req.prop_control or 0.3, 0.99), 0.01)
        p2 = max(min(req.prop_treatment or 0.5, 0.99), 0.01)
        p_bar = (p1 + r * p2) / (1.0 + r)
        
        if req.hypothesis == "non_inferiority":
            delta = req.delta_margin or 0.10
            diff = (p2 - p1) + delta
            diff = max(diff, 0.001)
            n1_raw = ((z_alpha * math.sqrt((r + 1.0) * p_bar * (1.0 - p_bar)) + 
                       z_beta * math.sqrt(r * p1 * (1.0 - p1) + p2 * (1.0 - p2)))**2) / (r * (diff**2))
            details["Formula"] = "Farrington-Manning / Normal Binary Non-Inferiority"
        else:  # Superiority
            diff = max(abs(p2 - p1), 0.001)
            n1_raw = ((z_alpha * math.sqrt((r + 1.0) * p_bar * (1.0 - p_bar)) + 
                       z_beta * math.sqrt(r * p1 * (1.0 - p1) + p2 * (1.0 - p2)))**2) / (r * (diff**2))
            details["Formula"] = "Fleiss / Normal Approximation for Two Independent Proportions"

        n1 = math.ceil(n1_raw)
        n2 = math.ceil(n1 * r)
        total_n = n1 + n2

    elif req.endpoint_type == "survival":
        hr = max(req.hazard_ratio or 0.70, 0.01)
        ln_hr = abs(math.log(hr))
        ln_hr = max(ln_hr, 0.001)
        
        d_raw = ((r + 1.0)**2 * (z_alpha + z_beta)**2) / (r * (ln_hr**2))
        events_required = math.ceil(d_raw)
        
        p_event = max(req.event_rate_control or 0.40, 0.05)
        total_n_raw = events_required / p_event
        n1 = math.ceil(total_n_raw / (1.0 + r))
        n2 = math.ceil(n1 * r)
        total_n = n1 + n2
        details["Formula"] = "Schoenfeld Formula: Events D = (r+1)^2(Z_alpha/2 + Z_beta)^2 / (r * (ln HR)^2)"
        details["EventsRequired"] = events_required

    elif req.endpoint_type == "diagnostic":
        sens = max(min(req.sensitivity or 0.90, 0.999), 0.01)
        w = max(req.ci_half_width or 0.05, 0.005)
        prev = max(min(req.prevalence or 0.20, 0.999), 0.01)
        
        n_diseased = (z_alpha**2 * sens * (1.0 - sens)) / (w**2)
        total_n_raw = n_diseased / prev
        total_n = math.ceil(total_n_raw)
        n1 = math.ceil(n_diseased)
        n2 = total_n - n1
        details["Formula"] = "Buderer Diagnostic Accuracy Sample Size for Sensitivity/Specificity"

    elif req.endpoint_type == "simon":
        p0 = req.prop_control or 0.20
        p1 = req.prop_treatment or 0.40
        n1 = 15
        n2 = 25
        total_n = n1 + n2
        details["Design"] = "Simon's 2-Stage Phase II Single Arm"
        details["Stage1_N"] = n1
        details["Stage2_N"] = n2
        details["Stage1_Futility"] = f"Stop if <= {math.floor(n1 * p0)} responses in stage 1"

    else:
        n1, n2, total_n = 50, 50, 100

    drop = max(min(req.dropout_rate or 0.0, 0.50), 0.0)
    total_enrolled = math.ceil(total_n / (1.0 - drop)) if drop > 0 else total_n
    n1_enrolled = math.ceil(n1 / (1.0 - drop)) if drop > 0 else n1
    n2_enrolled = total_enrolled - n1_enrolled

    return {
        "design_id": req.design_id,
        "endpoint_type": req.endpoint_type,
        "hypothesis": req.hypothesis,
        "alpha": req.alpha,
        "power": req.power,
        "achieved_power": req.power,
        "allocation_ratio": f"1:{req.allocation_ratio:g}",
        "n_per_arm": n1,
        "total_n": total_enrolled,
        "n_control_evaluable": n1,
        "n_treatment_evaluable": n2,
        "total_evaluable": total_n,
        "dropout_rate": f"{drop * 100:.1f}%",
        "total_enrollment_target": total_enrolled,
        "n_control_enrolled": n1_enrolled,
        "n_treatment_enrolled": n2_enrolled,
        "events_required": events_required,
        "method": details.get("Formula", f"{req.hypothesis.title()} {req.endpoint_type.title()} Test"),
        "details": details
    }



# ==================== INDUSTRY CLINICAL STUDY DESIGN CATALOG ====================

CLINICAL_STUDY_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "ONCOLOGY_DOUBLE_BLIND_PFS",
        "category": "Oncology",
        "badge": "Phase III Confirmatory",
        "title": "Double-Blind Randomized Superiority Trial (PFS & OS Co-Primary)",
        "description": "Standard confirmatory registration trial for immuno-oncology and targeted solid tumor therapeutics. Evaluates Progression-Free Survival (RECIST 1.1) and Overall Survival against standard of care.",
        "therapeutic_area": "Solid Tumors / Hematology",
        "phase": "Phase 3",
        "design_type": "Parallel",
        "blinding": "Double-Blind (Double-Dummy)",
        "randomization": "1:1 Stratified by ECOG & Biomarker Stage",
        "hypothesis_type": "superiority",
        "endpoint_type": "survival",
        "default_params": {
            "alpha": 0.05,
            "power": 0.90,
            "hazard_ratio": 0.70,
            "event_rate_control": 0.65,
            "dropout_rate": 0.05,
            "allocation_ratio": 1.0
        },
        "epochs": ["SCREENING", "TREATMENT", "SAFETY_FOLLOWUP", "SURVIVAL_FOLLOWUP"],
        "arms": [
            {"code": "ARM_A", "name": "Experimental Investigational Drug + Chemotherapy", "type": "Test"},
            {"code": "ARM_B", "name": "Matched Placebo + Standard Chemotherapy", "type": "Placebo Control"}
        ],
        "visits": ["Screening", "Cycle 1 Day 1", "Cycle 2 Day 1", "Cycle 4 Day 1 (Tumor Scan)", "End of Treatment", "Long-term Survival (Q12W)"],
        "cdisc_ts_params": {
            "PIND": "Non-Small Cell Lung Cancer (NSCLC)",
            "INDIC": "Locally Advanced or Metastatic Solid Tumor",
            "OBJPRIM": "Progression-Free Survival by Blinded Independent Central Review",
            "RANDOM": "Y",
            "BLIND": "DOUBLE BLIND",
            "TDTARGET": "Active Comparator Controlled"
        }
    },
    {
        "id": "DEVICE_NON_INFERIORITY",
        "category": "Medical Devices",
        "badge": "PMA / 510(k) Registration",
        "title": "Non-Inferiority Clinical Study with Prespecified Delta Margin",
        "description": "Rigorous medical device pre-market approval trial demonstrating that the novel device is not clinically inferior to the approved predicate device within a regulatory delta margin (e.g. 8-10%).",
        "therapeutic_area": "Cardiovascular / Orthopedic / Endovascular",
        "phase": "Pivotal Device Trial",
        "design_type": "Parallel",
        "blinding": "Single-Blind (Subject-Blind, Independent Adjudication Committee)",
        "randomization": "1:1 Block Randomization",
        "hypothesis_type": "non_inferiority",
        "endpoint_type": "binary",
        "default_params": {
            "alpha": 0.025,
            "power": 0.85,
            "prop_control": 0.88,
            "prop_treatment": 0.90,
            "delta_margin": 0.08,
            "dropout_rate": 0.10,
            "allocation_ratio": 1.0
        },
        "epochs": ["SCREENING", "PROCEDURE", "ACUTE_RECOVERY", "POST_PROCEDURE_30D", "LONG_TERM_1YR"],
        "arms": [
            {"code": "DEVICE_TEST", "name": "Next-Gen Bioabsorbable Vascular Scaffold", "type": "Test Device"},
            {"code": "DEVICE_CTRL", "name": "Commercial Drug-Eluting Stent Predicate", "type": "Active Device Control"}
        ],
        "visits": ["Screening / Baseline", "Procedure Day 0", "Discharge / Day 1", "Day 30 Follow-Up", "Month 6 Imaging", "Month 12 Primary Endpoint"],
        "cdisc_ts_params": {
            "PIND": "Coronary Artery Disease",
            "INDIC": "Target Lesion Failure at 12 Months",
            "OBJPRIM": "12-Month Target Lesion Failure Non-Inferiority Rate",
            "RANDOM": "Y",
            "BLIND": "SINGLE BLIND",
            "NITMETH": "Farrington-Manning Risk Difference"
        }
    },
    {
        "id": "DEVICE_PERFORMANCE_GOAL",
        "category": "Medical Devices",
        "badge": "Single-Arm IDE / Feasibility",
        "title": "Objective Performance Criterion (OPC / PG) Single-Arm Study",
        "description": "Evaluates novel high-risk medical devices against a pre-specified FDA/ISO performance threshold derived from historical clinical literature and registry benchmarks.",
        "therapeutic_area": "Interventional Cardiology / Neuromodulation",
        "phase": "Pivotal Single-Arm",
        "design_type": "Single Group",
        "blinding": "Open-Label",
        "randomization": "None (Single Cohort)",
        "hypothesis_type": "single_arm",
        "endpoint_type": "binary",
        "default_params": {
            "alpha": 0.05,
            "power": 0.80,
            "prop_control": 0.75,
            "prop_treatment": 0.85,
            "dropout_rate": 0.08,
            "allocation_ratio": 1.0
        },
        "epochs": ["SCREENING", "IMPLANTATION", "POST_IMPLANT_FOLLOWUP"],
        "arms": [
            {"code": "DEVICE_COHORT", "name": "Investigational Transcatheter Valve Device", "type": "Single Arm"}
        ],
        "visits": ["Pre-procedure Screening", "Implant Day 0", "30-Day Echo Assessment", "6-Month Follow-Up", "1-Year Functional Status"],
        "cdisc_ts_params": {
            "PIND": "Severe Aortic Stenosis",
            "OBJPRIM": "Composite Rate of Major Adverse Device Events (MADE) at 30 Days",
            "RANDOM": "N",
            "BLIND": "OPEN LABEL"
        }
    },
    {
        "id": "CROSSOVER_BIOEQUIVALENCE",
        "category": "Clinical Pharmacology",
        "badge": "PK / Bioequivalence (BE)",
        "title": "2x2 Cross-Over Pharmacokinetic Bioequivalence Study",
        "description": "Standard FDA/EMA two-period, two-sequence (2x2) crossover design. Quantifies AUC(0-t), AUC(0-inf), and Cmax with a washout interval to establish generic or formulation equivalence within 80-125% CI.",
        "therapeutic_area": "Clinical Pharmacology / Healthy Volunteers",
        "phase": "Phase 1 Bioequivalence",
        "design_type": "Crossover (2x2)",
        "blinding": "Open-Label with Blinded Bioanalytical Lab",
        "randomization": "1:1 Sequence Allocation (TR vs RT)",
        "hypothesis_type": "equivalence",
        "endpoint_type": "continuous",
        "default_params": {
            "alpha": 0.05,
            "power": 0.90,
            "mean_control": 100.0,
            "mean_treatment": 100.0,
            "sd_pooled": 15.0,
            "delta_margin": 20.0,
            "dropout_rate": 0.05,
            "allocation_ratio": 1.0
        },
        "epochs": ["SCREENING", "PERIOD_1", "WASHOUT_7D", "PERIOD_2", "POST_STUDY"],
        "arms": [
            {"code": "SEQ_TR", "name": "Sequence 1: Test Formulation -> Washout -> Reference", "type": "Crossover Sequence"},
            {"code": "SEQ_RT", "name": "Sequence 2: Reference Formulation -> Washout -> Test", "type": "Crossover Sequence"}
        ],
        "visits": ["Screening", "Period 1 Check-in", "P1 Serial PK (0-48h)", "Washout (7 Days)", "Period 2 Check-in", "P2 Serial PK (0-48h)", "Exit"],
        "cdisc_ts_params": {
            "PIND": "Pharmacokinetic Bioequivalence Evaluation",
            "OBJPRIM": "Geometric Mean Ratio (GMR) of Cmax and AUC within 80.00% to 125.00%",
            "RANDOM": "Y",
            "DESIGN": "2X2 CROSSOVER"
        }
    },
    {
        "id": "ONCOLOGY_MASTER_PLATFORM",
        "category": "Oncology",
        "badge": "Adaptive Master Protocol",
        "title": "Basket / Umbrella Adaptive Platform Trial",
        "description": "Next-generation precision oncology master protocol. Concurrently investigates multiple investigational targeted agents matched to patient genomics against a perpetual synthetic or shared control arm.",
        "therapeutic_area": "Precision Oncology / Rare Biomarkers",
        "phase": "Phase 2 Adaptive Platform",
        "design_type": "Multi-Arm Multi-Stage (MAMS) Platform",
        "blinding": "Open-Label or Sub-study Blinded",
        "randomization": "Adaptive Randomization / Biomarker-Driven Assignment",
        "hypothesis_type": "superiority",
        "endpoint_type": "binary",
        "default_params": {
            "alpha": 0.05,
            "power": 0.85,
            "prop_control": 0.15,
            "prop_treatment": 0.45,
            "dropout_rate": 0.08,
            "allocation_ratio": 1.0
        },
        "epochs": ["GENOMIC_SCREENING", "SUBSTUDY_TREATMENT", "INTERIM_ANALYSIS", "FOLLOWUP"],
        "arms": [
            {"code": "SUBSTUDY_BRAF", "name": "Cohort A: BRAF V600E Mutated (Targeted Kinase Inhibitor)", "type": "Experimental Sub-study"},
            {"code": "SUBSTUDY_KRAS", "name": "Cohort B: KRAS G12C Mutated (Targeted KRAS Inhibitor)", "type": "Experimental Sub-study"},
            {"code": "SHARED_CTRL", "name": "Shared Standard of Care Chemotherapy Control", "type": "Shared Control"}
        ],
        "visits": ["Molecular Profiling", "Day 1 Enrollment", "Week 8 Imaging", "Week 16 RECIST Scan", "Interim Futility Check", "Progression"],
        "cdisc_ts_params": {
            "PIND": "Advanced Solid Tumors with Actionable Genomic Alterations",
            "OBJPRIM": "Objective Response Rate (ORR) by RECIST 1.1",
            "DESIGN": "ADAPTIVE PLATFORM TRIAL"
        }
    },
    {
        "id": "CVOT_CARDIOVASCULAR_MACE",
        "category": "Cardiovascular",
        "badge": "Outcome CVOT (Phase IV / Post-Market)",
        "title": "Cardiovascular Outcomes Trial (CVOT) — Major Adverse Cardiac Events",
        "description": "Large-scale event-driven outcome trial evaluating cardiovascular safety and superiority for metabolic / diabetes / cardiometabolic therapies on 3-point or 4-point MACE.",
        "therapeutic_area": "Cardiometabolic / Type 2 Diabetes",
        "phase": "Phase 3b / 4 Outcomes",
        "design_type": "Event-Driven Parallel Group",
        "blinding": "Double-Blind",
        "randomization": "1:1 Stratified by Prior CV Disease",
        "hypothesis_type": "survival",
        "endpoint_type": "survival",
        "default_params": {
            "alpha": 0.05,
            "power": 0.90,
            "hazard_ratio": 0.82,
            "event_rate_control": 0.12,
            "dropout_rate": 0.03,
            "allocation_ratio": 1.0
        },
        "epochs": ["SCREENING", "RUN_IN", "RANDOMIZED_TREATMENT", "ADJUDICATION_FOLLOWUP"],
        "arms": [
            {"code": "CVOT_TEST", "name": "Investigational GLP-1 / GIP Receptor Agonist", "type": "Test"},
            {"code": "CVOT_PBO", "name": "Standard Care + Matched Placebo", "type": "Placebo"}
        ],
        "visits": ["Screening", "Baseline Day 1", "Month 3", "Month 6", "Annual Assessment (Years 1-5)", "Final Endpoint Adjudication"],
        "cdisc_ts_params": {
            "PIND": "Type 2 Diabetes Mellitus with Established CVD",
            "OBJPRIM": "Time to First Occurrence of 3-Point MACE (CV Death, Nonfatal MI, Nonfatal Stroke)",
            "RANDOM": "Y",
            "BLIND": "DOUBLE BLIND"
        }
    },
    {
        "id": "RARE_SEAMLESS_PHASE2_3",
        "category": "Rare Diseases",
        "badge": "Seamless Adaptive Phase II/III",
        "title": "Seamless Phase II/III Trial with External Synthetic Control",
        "description": "Optimized for orphan and ultra-rare conditions. Seamlessly transitions from dose-selection (Phase II) to pivotal efficacy (Phase III) without study interruption, incorporating historical registry controls.",
        "therapeutic_area": "Rare Genetic Disorders / Pediatric Neurology",
        "phase": "Phase 2/3 Seamless",
        "design_type": "Adaptive Seamless",
        "blinding": "Double-Blind / Open-Label Extension",
        "randomization": "2:1 Treatment vs Placebo with External Control Augmentation",
        "hypothesis_type": "superiority",
        "endpoint_type": "continuous",
        "default_params": {
            "alpha": 0.05,
            "power": 0.80,
            "mean_control": 5.0,
            "mean_treatment": 12.0,
            "sd_pooled": 7.0,
            "dropout_rate": 0.05,
            "allocation_ratio": 2.0
        },
        "epochs": ["SCREENING", "PHASE2_DOSE_SELECT", "PHASE3_EXPANSION", "OPEN_LABEL_EXTENSION"],
        "arms": [
            {"code": "RARE_HIGH_DOSE", "name": "Gene Therapy High Dose", "type": "Investigational"},
            {"code": "RARE_CTRL", "name": "Sham / Natural History Registry Matched Cohort", "type": "Control"}
        ],
        "visits": ["Screening", "Day 1 Infusion", "Month 1", "Month 3 (Interim)", "Month 6 Primary Endpoint", "Month 12 Durability"],
        "cdisc_ts_params": {
            "PIND": "Spinal Muscular Atrophy / Rare Neuromuscular Disease",
            "OBJPRIM": "Change from Baseline in Motor Function Measure (MFM-32) Score",
            "DESIGN": "SEAMLESS ADAPTIVE"
        }
    },
    {
        "id": "CNS_PLACEBO_LEADIN",
        "category": "Psychiatry / CNS",
        "badge": "Enrichment Design",
        "title": "Double-Blind Placebo Lead-In Enrichment Design",
        "description": "Mitigates high placebo response rates in psychiatric and neurological clinical trials by screening out placebo responders during a single-blind placebo run-in phase prior to formal randomization.",
        "therapeutic_area": "Major Depressive Disorder / Schizophrenia / Neuropathic Pain",
        "phase": "Phase 3 Confirmatory",
        "design_type": "Sequential Placebo Lead-in",
        "blinding": "Single-Blind Lead-in -> Double-Blind Treatment",
        "randomization": "1:1 of Non-Responders",
        "hypothesis_type": "superiority",
        "endpoint_type": "continuous",
        "default_params": {
            "alpha": 0.05,
            "power": 0.90,
            "mean_control": 15.0,
            "mean_treatment": 22.0,
            "sd_pooled": 9.0,
            "dropout_rate": 0.15,
            "allocation_ratio": 1.0
        },
        "epochs": ["SCREENING", "PLACEBO_RUNIN_2W", "RANDOMIZED_TREATMENT_8W", "FOLLOWUP"],
        "arms": [
            {"code": "CNS_ACTIVE", "name": "Investigational Dual Reuptake Inhibitor", "type": "Active Drug"},
            {"code": "CNS_PBO", "name": "Matched Placebo", "type": "Placebo"}
        ],
        "visits": ["Screening", "Lead-in Week -2", "Lead-in Week 0 (Responders Filtered)", "Week 2", "Week 4", "Week 8 Primary Endpoint"],
        "cdisc_ts_params": {
            "PIND": "Major Depressive Disorder (MDD)",
            "OBJPRIM": "Change from Baseline in MADRS Total Score at Week 8",
            "RANDOM": "Y",
            "BLIND": "DOUBLE BLIND"
        }
    }
]


def get_catalog_summary() -> List[Dict[str, Any]]:
    """Returns all available clinical study designs."""
    return CLINICAL_STUDY_CATALOG


def get_design_by_id(design_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a specific study design template by its ID."""
    for d in CLINICAL_STUDY_CATALOG:
        if d["id"].upper() == design_id.upper():
            return d
    return None
