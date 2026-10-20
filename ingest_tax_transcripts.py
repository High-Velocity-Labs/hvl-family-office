"""
IRS Wage & Income Transcript Ingestion and Encryption Engine
Extracts and persists 10 years (2016-2025) of IRS Wage & Income Transcripts:
- Form W-2 (Wages, federal withholding, FICA, Box 12 Code V NSO option spread, 401k)
- Form 1098 (Mortgage interest and principal history across properties)
- Form 1099-DIV (Ordinary and qualified dividends, foreign tax paid)
- Form 1099-INT (Interest income)
- Form 1099-B / Form 8949 (Brokerage sales, proceeds, cost basis, realized capital gains)
- Form 1099-R (Backdoor Roth IRA conversions and distributions)
- Form 5498 (Retirement account year-end FMVs and contributions)
Encrypts all records at rest into SQLite (data/family_office.db) via AES-128/Fernet.
"""

from __future__ import annotations
import io
from pathlib import Path
import re
import sys
from typing import Dict, Any, List
from pypdf import PdfReader
import security

from config import get_data_dir, get_db_path_for_universe
from ingest_tax_helpers import (
    clean_val,
    extract_field,
    get_default_employer,
    parse_w2_text,
    parse_form_1098_mortgages,
    parse_form_1099_div,
    parse_form_1099_int,
    parse_form_8949_b,
    parse_form_1099_r,
    parse_form_5498,
)

DATA_DIR = get_data_dir()
DB_PATH = get_db_path_for_universe()
W2S_DIR = Path(__file__).resolve().parent / "w2s"


def parse_transcript_pdf(pdf_source: Any, family_id: int = 0) -> Dict[str, Any]:
    if isinstance(pdf_source, bytes):
        reader = PdfReader(io.BytesIO(pdf_source))
        source_name = "in_memory_upload.pdf"
    elif hasattr(pdf_source, "read"):
        reader = PdfReader(pdf_source)
        source_name = getattr(pdf_source, "name", "uploaded_file.pdf")
    else:
        pdf_path = Path(pdf_source)
        reader = PdfReader(str(pdf_path))
        source_name = pdf_path.name

    text = '\n'.join([page.extract_text() or '' for page in reader.pages])

    has_transcript_header = bool(re.search(r'Tax Period Requested:\s*12-31-(\d{4})', text))
    has_transcript_forms = bool("Form W-2:" in text or "Form 1098:" in text or "Form 1099" in text)

    if not has_transcript_header and not has_transcript_forms:
        this_mod = sys.modules.get(__name__)
        p_w2 = getattr(this_mod, "parse_w2_text", parse_w2_text)
        return p_w2(text, source_name=source_name, family_id=family_id)

    m_year = re.search(r'Tax Period Requested:\s*12-31-(\d{4})', text)
    year = int(m_year.group(1)) if m_year else 0
    if not year:
        m_fallback = re.search(r'\b(20[12]\d)\b', text)
        year = int(m_fallback.group(1)) if m_fallback else 0

    m_track = re.search(r'Tracking Number:\s*(\d+)', text)
    tracking = m_track.group(1) if m_track else ""

    w2 = {}
    if "Form W-2:" in text:
        wages = extract_field(r'Wages, Tips and Other Compensation:\s*\$([0-9,]+\.[0-9]{2})', text)
        fed_withheld = extract_field(r'Federal Income Tax Withheld:\s*\$([0-9,]+\.[0-9]{2})', text)
        ss_wages = extract_field(r'Social Security Wages:\s*\$([0-9,]+\.[0-9]{2})', text)
        ss_withheld = extract_field(r'Social Security Tax Withheld:\s*\$([0-9,]+\.[0-9]{2})', text)
        med_wages = extract_field(r'Medicare Wages and Tips:\s*\$([0-9,]+\.[0-9]{2})', text)
        med_withheld = extract_field(r'Medicare Tax Withheld:\s*\$([0-9,]+\.[0-9]{2})', text)
        nso_v = extract_field(r'Code "V" Income from Exercise of Non-statutory Stock\s*Options:\s*\$([0-9,]+\.[0-9]{2})', text)
        def_comp = extract_field(r'Deferred Compensation:\s*\$([0-9,]+\.[0-9]{2})', text)
        health = extract_field(r'Code "DD" Cost of Employer-Sponsored Health Coverage:\s*\$([0-9,]+\.[0-9]{2})', text)

        w2 = {
            "employer": get_default_employer(family_id=family_id),
            "wages_box1": wages,
            "federal_tax_withheld_box2": fed_withheld,
            "social_security_wages_box3": ss_wages,
            "social_security_tax_withheld_box4": ss_withheld,
            "medicare_wages_box5": med_wages,
            "medicare_tax_withheld_box6": med_withheld,
            "nso_exercise_spread_box12_v": nso_v,
            "deferred_compensation_401k_box12_d": def_comp,
            "health_coverage_cost_box12_dd": health,
            "base_salary_and_bonus": round(wages - nso_v, 2),
            "effective_federal_withholding_rate": round(fed_withheld / wages, 4) if wages > 0 else 0.0,
            "total_fica_medicare_withheld": round(ss_withheld + med_withheld, 2),
            "total_w2_payroll_taxes_withheld": round(fed_withheld + ss_withheld + med_withheld, 2),
        }

    mortgages = parse_form_1098_mortgages(text)
    div_records = parse_form_1099_div(text)
    int_records = parse_form_1099_int(text)
    b_transactions = parse_form_8949_b(text)
    r_records = parse_form_1099_r(text)
    ira_records = parse_form_5498(text)

    tot_ord_div = sum(d["ordinary_dividends"] for d in div_records)
    tot_qual_div = sum(d["qualified_dividends"] for d in div_records)
    tot_interest = sum(i["interest_income"] for i in int_records)
    tot_proceeds = sum(b["proceeds"] for b in b_transactions)
    tot_basis = sum(b["cost_basis"] for b in b_transactions)
    tot_realized_gains = round(tot_proceeds - tot_basis, 2)
    tot_mortgage_int = sum(m["interest_paid"] for m in mortgages)
    approx_agi = round((w2.get("wages_box1", 0.0) + tot_ord_div + tot_interest + tot_realized_gains), 2)

    return {
        "year": year,
        "tracking_number": tracking,
        "source_pdf": source_name,
        "doc_type": "transcript",
        "w2": w2,
        "mortgages": mortgages,
        "dividends": div_records,
        "interest": int_records,
        "capital_gains_sales": b_transactions,
        "retirement_distributions": r_records,
        "ira_information": ira_records,
        "totals": {
            "w2_wages": w2.get("wages_box1", 0.0),
            "w2_base_salary_and_bonus": w2.get("base_salary_and_bonus", 0.0),
            "nso_exercise_spread": w2.get("nso_exercise_spread_box12_v", 0.0),
            "federal_tax_withheld": w2.get("federal_tax_withheld_box2", 0.0),
            "social_security_withheld": w2.get("social_security_tax_withheld_box4", 0.0),
            "medicare_withheld": w2.get("medicare_tax_withheld_box6", 0.0),
            "401k_deferred_comp": w2.get("deferred_compensation_401k_box12_d", 0.0),
            "ordinary_dividends": tot_ord_div,
            "qualified_dividends": tot_qual_div,
            "interest_income": tot_interest,
            "stock_sales_proceeds": tot_proceeds,
            "stock_sales_basis": tot_basis,
            "realized_capital_gains": tot_realized_gains,
            "mortgage_interest_paid": tot_mortgage_int,
            "approx_gross_income": approx_agi,
        }
    }


def ingest_all_transcripts(family_id: int = 0) -> Dict[str, Any]:
    """Ingests, parses, and encrypts all transcripts found in w2s/ into SQLite."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf_files = list(W2S_DIR.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No transcript PDF files found in {W2S_DIR}")

    this_mod = sys.modules.get(__name__)
    parser_fn = getattr(this_mod, "parse_transcript_pdf", parse_transcript_pdf)

    years_data = {}
    for pdf_path in pdf_files:
        parsed = parser_fn(pdf_path, family_id=family_id)
        if parsed["year"]:
            years_data[str(parsed["year"])] = parsed

    sorted_years = sorted([int(y) for y in years_data.keys()])
    summary_by_year = {}
    for yr in sorted_years:
        curr = years_data[str(yr)]
        prior = years_data.get(str(yr - 1))
        prior_tax = prior["totals"]["federal_tax_withheld"] if prior else None
        safe_harbor_110 = round(prior_tax * 1.10, 2) if prior_tax is not None else None

        summary_by_year[str(yr)] = {
            "year": yr,
            "w2_wages": curr["totals"]["w2_wages"],
            "base_salary_and_bonus": curr["totals"]["w2_base_salary_and_bonus"],
            "nso_exercise_spread": curr["totals"]["nso_exercise_spread"],
            "federal_tax_withheld": curr["totals"]["federal_tax_withheld"],
            "medicare_tax_withheld": curr["totals"]["medicare_withheld"],
            "social_security_withheld": curr["totals"]["social_security_withheld"],
            "401k_contributions": curr["totals"]["401k_deferred_comp"],
            "mortgage_interest_paid": curr["totals"]["mortgage_interest_paid"],
            "qualified_dividends": curr["totals"]["qualified_dividends"],
            "realized_capital_gains": curr["totals"]["realized_capital_gains"],
            "prior_year_federal_tax": prior_tax,
            "safe_harbor_110_target": safe_harbor_110,
        }

    payload = {
        "transcripts_by_year": years_data,
        "historical_summary": summary_by_year,
        "available_years": sorted_years,
        "latest_tax_year": max(sorted_years) if sorted_years else None,
        "safe_harbor_2026_target": round(summary_by_year[str(max(sorted_years))]["federal_tax_withheld"] * 1.10, 2) if sorted_years else None,
    }

    import db
    target_db = getattr(this_mod, "DB_PATH", DB_PATH)
    db.transcripts.save_transcripts_payload(family_id=family_id, payload=payload, db_path=target_db)
    return payload


def ingest_single_transcript_bytes(pdf_bytes: bytes, family_id: int = 0, db_path: Any = None) -> Dict[str, Any]:
    """
    Parses an IRS Wage & Income Transcript or Form W-2 PDF directly from in-memory bytes,
    updates the encrypted SQLite database, and returns the parsed summary.
    Zero files are saved to disk.
    """
    import db
    this_mod = sys.modules.get(__name__)
    target_db = db_path or getattr(this_mod, "DB_PATH", DB_PATH)
    parser_fn = getattr(this_mod, "parse_transcript_pdf", parse_transcript_pdf)
    parsed = parser_fn(pdf_bytes, family_id=family_id)
    yr = parsed.get("year")
    if not yr:
        raise ValueError("Could not extract Tax Period year from uploaded document.")

    payload = db.transcripts.get_transcripts_payload(family_id=family_id, db_path=target_db) or {
        "transcripts_by_year": {},
        "historical_summary": {},
        "available_years": [],
        "latest_tax_year": None,
        "safe_harbor_2026_target": 0.0
    }

    years_data = payload.get("transcripts_by_year", {})
    years_data[str(yr)] = parsed
    payload["transcripts_by_year"] = years_data

    sorted_years = sorted([int(y) for y in years_data.keys()])
    payload["available_years"] = sorted_years
    payload["latest_tax_year"] = max(sorted_years)

    summary_by_year = payload.get("historical_summary", {})
    prior_tax = None
    if str(yr - 1) in years_data:
        prior_tax = years_data[str(yr - 1)]["totals"]["federal_tax_withheld"]

    safe_harbor_110 = round(prior_tax * 1.10, 2) if prior_tax is not None else None

    summary_by_year[str(yr)] = {
        "year": yr,
        "w2_wages": parsed["totals"]["w2_wages"],
        "base_salary_and_bonus": parsed["totals"]["w2_base_salary_and_bonus"],
        "nso_exercise_spread": parsed["totals"]["nso_exercise_spread"],
        "federal_tax_withheld": parsed["totals"]["federal_tax_withheld"],
        "medicare_tax_withheld": parsed["totals"]["medicare_withheld"],
        "social_security_withheld": parsed["totals"]["social_security_withheld"],
        "401k_contributions": parsed["totals"]["401k_deferred_comp"],
        "mortgage_interest_paid": parsed["totals"]["mortgage_interest_paid"],
        "qualified_dividends": parsed["totals"]["qualified_dividends"],
        "realized_capital_gains": parsed["totals"]["realized_capital_gains"],
        "prior_year_federal_tax": prior_tax,
        "safe_harbor_110_target": safe_harbor_110,
    }
    payload["historical_summary"] = summary_by_year

    latest_yr = max(sorted_years)
    latest_fed = summary_by_year[str(latest_yr)]["federal_tax_withheld"]
    payload["safe_harbor_2026_target"] = round(latest_fed * 1.10, 2)

    db.transcripts.save_transcripts_payload(family_id=family_id, payload=payload, db_path=target_db)
    return {
        "success": True,
        "year": yr,
        "doc_type": parsed.get("doc_type", "transcript"),
        "w2": parsed.get("w2", {}),
        "totals": parsed.get("totals", {}),
        "mortgages": parsed.get("mortgages", []),
        "summary": summary_by_year[str(yr)],
        "safe_harbor_target": payload["safe_harbor_2026_target"],
        "historical_summary": summary_by_year,
    }
