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
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pypdf import PdfReader
import security
from config import get_data_dir, get_global_db_path

DATA_DIR = get_data_dir()
DB_PATH = get_global_db_path()
W2S_DIR = BASE_DIR / "w2s"


def clean_val(val_str: Any = "") -> float:
    if not val_str:
        return 0.0
    val_str = str(val_str).replace('$', '').replace(',', '').strip()
    try:
        return float(val_str)
    except ValueError:
        return 0.0


def extract_field(pattern: str, text: str, default: float = 0.0) -> float:
    m = re.search(pattern, text, re.IGNORECASE)
    return clean_val(m.group(1)) if m else default


def get_default_employer(family_id: int = 0) -> str:
    try:
        from services import equity_engine
        emp = equity_engine.get_primary_company_name(family_id=family_id)
        if emp and str(emp).strip():
            return str(emp).strip()
    except Exception:
        pass
    return "Primary Employer"


def parse_w2_text(text: str, source_name: str = "uploaded_w2.pdf", family_id: int = 0) -> Dict[str, Any]:
    """
    Parses a standard employer-issued Form W-2 (Wage and Tax Statement) PDF.
    Extracts tax year, employer name, Box 1 wages, Box 2 federal tax withheld,
    FICA/Medicare withholdings, and Box 12 codes (NSO spread, 401k, etc.).
    """
    m_year = re.search(r'(?:Form\s+W-2[^\n\d]{0,25}|Wage\s+and\s+Tax\s+Statement[^\n\d]{0,25}|OMB\s+No\.[^\n\d]{0,25})\b(20[12]\d)\b', text, re.IGNORECASE)
    if not m_year:
        m_year = re.search(r'\b(20[12]\d)\b', text)
    year = int(m_year.group(1)) if m_year else 0

    def extract_field_multi(patterns: List[str]) -> float:
        for pat in patterns:
            val = extract_field(pat, text)
            if val > 0:
                return val
        return 0.0

    wages = extract_field_multi([
        r'Wages,\s*Tips\s*and\s*Other\s*Compensation:\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'(?:1\s+Wages,?\s*tips,?\s*other\s*comp[^\n\d$]*)\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'1\s+Wages[^\n]*\n\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'Box\s*1\b[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})'
    ])

    fed_withheld = extract_field_multi([
        r'Federal\s*Income\s*Tax\s*Withheld:\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'(?:2\s+Federal\s*income\s*tax\s*withheld[^\n\d$]*)\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'2\s+Federal[^\n]*\n\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'Box\s*2\b[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})'
    ])

    ss_wages = extract_field_multi([
        r'Social\s*Security\s*Wages:\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'(?:3\s+Social\s*security\s*wages[^\n\d$]*)\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'3\s+Social[^\n]*\n\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'Box\s*3\b[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})'
    ])

    ss_withheld = extract_field_multi([
        r'Social\s*Security\s*Tax\s*Withheld:\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'(?:4\s+Social\s*security\s*tax\s*withheld[^\n\d$]*)\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'4\s+Social[^\n]*\n\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'Box\s*4\b[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})'
    ])

    med_wages = extract_field_multi([
        r'Medicare\s*Wages\s*and\s*Tips:\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'(?:5\s+Medicare\s*wages\s*and\s*tips[^\n\d$]*)\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'5\s+Medicare[^\n]*\n\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'Box\s*5\b[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})'
    ])

    med_withheld = extract_field_multi([
        r'Medicare\s*Tax\s*Withheld:\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'(?:6\s+Medicare\s*tax\s*withheld[^\n\d$]*)\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'6\s+Medicare[^\n]*\n\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'Box\s*6\b[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})'
    ])

    nso_v = extract_field_multi([
        r'Code\s*"V"\s*Income[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})',
        r'12[a-d]?\s+V\b[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})',
        r'\bV\s+([0-9,]+\.[0-9]{2})\b'
    ])

    def_comp = extract_field_multi([
        r'Deferred\s*Compensation:\s*[\$]?([0-9,]+\.[0-9]{2})',
        r'12[a-d]?\s+D\b[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})',
        r'\bD\s+([0-9,]+\.[0-9]{2})\b'
    ])

    health = extract_field_multi([
        r'Code\s*"DD"\s*Cost[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})',
        r'12[a-d]?\s+DD\b[^\n\d$]*[\$]?([0-9,]+\.[0-9]{2})',
        r'\bDD\s+([0-9,]+\.[0-9]{2})\b'
    ])

    employer = ""
    m_emp = re.search(r'(?:c\s+Employer[’\']?s\s+name[^\n]*\n\s*|Employer:\s*)([^\n]+)', text, re.IGNORECASE)
    if m_emp:
        candidate = m_emp.group(1).strip()
        if candidate and len(candidate) > 2 and not candidate.lower().startswith("form"):
            employer = candidate[:100].strip()

    if not employer:
        employer = get_default_employer(family_id=family_id)

    base_and_bonus = round(max(0.0, wages - nso_v), 2)

    w2 = {
        "employer": employer,
        "wages_box1": wages,
        "federal_tax_withheld_box2": fed_withheld,
        "social_security_wages_box3": ss_wages,
        "social_security_tax_withheld_box4": ss_withheld,
        "medicare_wages_box5": med_wages,
        "medicare_tax_withheld_box6": med_withheld,
        "nso_exercise_spread_box12_v": nso_v,
        "deferred_compensation_401k_box12_d": def_comp,
        "health_coverage_cost_box12_dd": health,
        "base_salary_and_bonus": base_and_bonus,
        "effective_federal_withholding_rate": round(fed_withheld / wages, 4) if wages > 0 else 0.0,
        "total_fica_medicare_withheld": round(ss_withheld + med_withheld, 2),
        "total_w2_payroll_taxes_withheld": round(fed_withheld + ss_withheld + med_withheld, 2),
    }

    return {
        "year": year,
        "tracking_number": "",
        "source_pdf": source_name,
        "doc_type": "w2",
        "w2": w2,
        "mortgages": [],
        "dividends": [],
        "interest": [],
        "capital_gains_sales": [],
        "retirement_distributions": [],
        "ira_information": [],
        "totals": {
            "w2_wages": wages,
            "w2_base_salary_and_bonus": base_and_bonus,
            "nso_exercise_spread": nso_v,
            "federal_tax_withheld": fed_withheld,
            "social_security_withheld": ss_withheld,
            "medicare_withheld": med_withheld,
            "401k_deferred_comp": def_comp,
            "ordinary_dividends": 0.0,
            "qualified_dividends": 0.0,
            "interest_income": 0.0,
            "stock_sales_proceeds": 0.0,
            "stock_sales_basis": 0.0,
            "realized_capital_gains": 0.0,
            "mortgage_interest_paid": 0.0,
            "approx_gross_income": wages,
        }
    }


def parse_form_1098_mortgages(text: str) -> List[Dict[str, Any]]:
    mortgages = []
    chunks_1098 = text.split("Form 1098: Mortgage Interest Statement")[1:]
    for ch in chunks_1098:
        next_form = re.search(r'\nForm [A-Z0-9\-]+:', ch)
        content = ch[:next_form.start()] if next_form else ch
        interest = extract_field(r'Mortgage Interest Received[^\$]+\$([0-9,]+\.[0-9]{2})', content)
        principal = extract_field(r'Outstanding Mortgage Principle:\s*\$([0-9,]+\.[0-9]{2})', content)
        orig_match = re.search(r'Mortgage Origination Date:\s*([0-9\-]+)', content)
        addr_match = re.search(r'Address of Property Securing Mortgage:\s*([^\n]+)', content)
        lender_match = re.search(r'Name:\s*([^\n]+)', content)
        if interest > 0 or principal > 0:
            mortgages.append({
                "lender": lender_match.group(1).strip() if lender_match else "Mortgage Lender",
                "interest_paid": interest,
                "outstanding_principal": principal,
                "origination_date": orig_match.group(1).strip() if orig_match else "",
                "property_address": addr_match.group(1).strip() if addr_match else "",
            })
    return mortgages


def parse_form_1099_div(text: str) -> List[Dict[str, Any]]:
    div_records = []
    chunks_div = text.split("Form 1099-DIV: Dividends and Distributions")[1:]
    for ch in chunks_div:
        next_form = re.search(r'\nForm [A-Z0-9\-]+:', ch)
        content = ch[:next_form.start()] if next_form else ch
        ord_div = extract_field(r'Ordinary Dividend:\s*\$([0-9,]+\.[0-9]{2})', content)
        qual_div = extract_field(r'Qualified Dividends:\s*\$([0-9,]+\.[0-9]{2})', content)
        sec_199a = extract_field(r'Section 199A Dividends:\s*\$([0-9,]+\.[0-9]{2})', content)
        cg_dist = extract_field(r'Total Capital Gain Distributions:\s*\$([0-9,]+\.[0-9]{2})', content)
        foreign_tax = extract_field(r'Foreign Tax Paid:\s*\$([0-9,]+\.[0-9]{2})', content)
        exempt_int = extract_field(r'Exempt Interest Dividends:\s*\$([0-9,]+\.[0-9]{2})', content)
        fed_withheld_div = extract_field(r'Federal Income Tax Withheld:\s*\$([0-9,]+\.[0-9]{2})', content)
        payer_match = re.search(r'Name:\s*([^\n]+)', content)
        acc_match = re.search(r'Account Number:\s*([^\n]+)', content)
        if ord_div > 0 or qual_div > 0 or exempt_int > 0:
            div_records.append({
                "payer": payer_match.group(1).strip() if payer_match else "Vanguard",
                "account_number": acc_match.group(1).strip() if acc_match else "",
                "ordinary_dividends": ord_div,
                "qualified_dividends": qual_div,
                "section_199a_dividends": sec_199a,
                "capital_gain_distributions": cg_dist,
                "foreign_tax_paid": foreign_tax,
                "exempt_interest_dividends": exempt_int,
                "federal_tax_withheld": fed_withheld_div,
            })
    return div_records


def parse_form_1099_int(text: str) -> List[Dict[str, Any]]:
    int_records = []
    chunks_int = text.split("Form 1099-INT: Interest Income")[1:]
    for ch in chunks_int:
        next_form = re.search(r'\nForm [A-Z0-9\-]+:', ch)
        content = ch[:next_form.start()] if next_form else ch
        interest_amt = extract_field(r'Interest:\s*\$([0-9,]+\.[0-9]{2})', content)
        fed_withheld_int = extract_field(r'Federal Income Tax Withheld:\s*\$([0-9,]+\.[0-9]{2})', content)
        payer_match = re.search(r'Name:\s*([^\n]+)', content)
        if interest_amt > 0:
            int_records.append({
                "payer": payer_match.group(1).strip() if payer_match else "Bank / Brokerage",
                "interest_income": interest_amt,
                "federal_tax_withheld": fed_withheld_int,
            })
    return int_records


def parse_form_8949_b(text: str) -> List[Dict[str, Any]]:
    b_transactions = []
    chunks_8949 = re.split(r'Form 8949:', text)[1:]
    for ch in chunks_8949:
        next_form = re.search(r'\nForm (?:1099|1098|5498|8949)', ch)
        content = ch[:next_form.start()] if next_form else ch
        desc_match = re.search(r'Description:\s*([^\n]+)', content)
        acq_match = re.search(r'Date Acquired:\s*([0-9\-]+)', content)
        sold_match = re.search(r'Date Sold or Disposed:\s*([0-9\-]+)', content)
        proceeds = extract_field(r'Proceeds:\s*\$([0-9,]+\.[0-9]{2})', content)
        basis = extract_field(r'Cost or Basis:\s*\$([0-9,]+\.[0-9]{2})', content)
        term_match = re.search(r'Type of Gain or Loss Code:\s*([^\n]+)', content)
        if proceeds > 0 or basis > 0:
            term = term_match.group(1).strip() if term_match else "Unknown"
            b_transactions.append({
                "description": desc_match.group(1).strip() if desc_match else "Security Sale",
                "date_acquired": acq_match.group(1).strip() if acq_match else "",
                "date_sold": sold_match.group(1).strip() if sold_match else "",
                "proceeds": proceeds,
                "cost_basis": basis,
                "gain_loss": round(proceeds - basis, 2),
                "term": term,
            })
    return b_transactions


def parse_form_1099_r(text: str) -> List[Dict[str, Any]]:
    r_records = []
    chunks_1099r = text.split("Form 1099-R: Distributions From Pensions, Annuities, Retirement")[1:]
    for ch in chunks_1099r:
        next_form = re.search(r'\nForm [A-Z0-9\-]+:', ch)
        content = ch[:next_form.start()] if next_form else ch
        gross_dist = extract_field(r'Gross Distribution:\s*\$([0-9,]+\.[0-9]{2})', content)
        taxable_amt = extract_field(r'Taxable Amount:\s*\$([0-9,]+\.[0-9]{2})', content)
        fed_withheld_r = extract_field(r'Federal Income Tax Withheld:\s*\$([0-9,]+\.[0-9]{2})', content)
        payer_match = re.search(r'Name:\s*([^\n]+)', content)
        dist_code = re.search(r'Distribution Code:\s*([^\n]+)', content)
        if gross_dist > 0:
            r_records.append({
                "payer": payer_match.group(1).strip() if payer_match else "Retirement Plan",
                "gross_distribution": gross_dist,
                "taxable_amount": taxable_amt,
                "distribution_code": dist_code.group(1).strip() if dist_code else "",
                "federal_tax_withheld": fed_withheld_r,
            })
    return r_records


def parse_form_5498(text: str) -> List[Dict[str, Any]]:
    ira_records = []
    chunks_5498 = text.split("Form 5498: Individual Retirement Arrangement Contribution Information")[1:]
    for ch in chunks_5498:
        next_form = re.search(r'\nForm [A-Z0-9\-]+:', ch)
        content = ch[:next_form.start()] if next_form else ch
        fmv = extract_field(r'Fair Market Value of Account:\s*\$([0-9,]+\.[0-9]{2})', content)
        ira_contrib = extract_field(r'IRA Contributions[^\$]+\$([0-9,]+\.[0-9]{2})', content)
        roth_contrib = extract_field(r'Roth IRA Contributions:\s*\$([0-9,]+\.[0-9]{2})', content)
        issuer_match = re.search(r'Name:\s*([^\n]+)', content)
        if fmv > 0 or ira_contrib > 0 or roth_contrib > 0:
            ira_records.append({
                "issuer": issuer_match.group(1).strip() if issuer_match else "IRA Custodian",
                "fair_market_value": fmv,
                "traditional_ira_contributions": ira_contrib,
                "roth_ira_contributions": roth_contrib,
            })
    return ira_records


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
