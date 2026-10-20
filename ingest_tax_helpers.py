"""
ingest_tax_helpers.py: Regex parsers and extraction helpers for tax transcripts and W-2 statements.
Extracts Form W-2, 1098, 1099-DIV, 1099-INT, 1099-B, 1099-R, and 5498 data.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List


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
        import equity_engine
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
