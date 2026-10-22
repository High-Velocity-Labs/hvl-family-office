"""
Extended tab deterministic response builders for the AI Financial Advisor fallback engine:
Private Markets LP book, Tax Season Checklist, Survivorship Audit, Education 529s,
Philanthropy & DAFs, Family Gifting (Form 709), State Tax Arbitrage, Career Compensation,
and Accounts & Balance Sheet.
"""

from __future__ import annotations

from typing import Optional

from services.advisor.tools_operations import get_private_markets_lp_book
from services.advisor.tools_tabs import (
    get_accounts_and_balance_sheet,
    get_compensation_and_tax_withholding,
    get_education_529_plan,
    get_family_gifting_summary,
    get_philanthropy_and_daf_summary,
    get_state_tax_arbitrage,
)
from services.household_audit_service import audit_household_risks
from services.tax_checklist_service import get_tax_document_checklist

_DISCLAIMER_SUFFIX = (
    "\n\n---\n*Disclaimer: AI-generated for educational and modeling purposes only. "
    "Not formal financial, investment, legal, or tax advice. Consult a certified financial "
    "professional before making financial decisions.*"
)


def _render_extended_tab_fallback(
    p_lower: str,
    tab: str,
    fam_id: int,
    family_name: str,
    state: str,
) -> Optional[str]:
    """Handles deterministic responses for LP book, Tax checklist, Survivorship audit, Education, Philanthropy, Gifting, Arbitrage, Compensation, and Accounts."""
    # 1. Private Markets LP Commitment Book
    if any(k in p_lower for k in ("lp", "private market", "unfunded", "tvpi", "dpi", "dry powder", "capital call", "venture fund")) or "private" in tab:
        book = get_private_markets_lp_book(family_id=fam_id)
        summ = book.get("summary") or {}
        comms = book.get("commitments") or []
        comm_lines = [
            f"- **{c.get('fund_name')}** ({c.get('fund_type')} {c.get('vintage_year')}): "
            f"Committed **${c.get('total_commitment', 0):,.0f}** | Called **${c.get('capital_called', 0):,.0f}** | TVPI **{c.get('tvpi', 0):.2f}x**"
            for c in comms[:5]
        ]
        cov = summ.get("liquid_cash_coverage_ratio", 0.0)
        cov_str = f"{cov:.1f}x" if cov < 999 else "Covered"
        return (
            f"### 💼 Private Markets & LP Commitment Book for {family_name}\n\n"
            f"**Total Committed:** **${summ.get('total_committed', 0):,.0f}** | **Called:** **${summ.get('total_called', 0):,.0f}** | **Unfunded:** **${summ.get('total_unfunded', 0):,.0f}**  \n"
            f"**Portfolio TVPI:** **{summ.get('portfolio_tvpi', 0):.2f}x** | **DPI:** **{summ.get('portfolio_dpi', 0):.2f}x** | **Liquid Cash Coverage:** **{cov_str}**\n\n"
            f"---\n\n"
            f"#### 1. Fund Commitment Portfolio\n"
            f"{chr(10).join(comm_lines) if comm_lines else '- No private LP commitments recorded.'}\n\n"
            f"#### 2. Liquidity & Capital Call Pacing\n"
            f"- Liquid cash reserves provide **{cov_str}** coverage of remaining unfunded commitments.\n"
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 2. Tax Season Document Checklist
    if any(k in p_lower for k in ("tax document", "checklist", "1099", "1098", "3921", "8283", "cpa packet", "tax season checklist")):
        chk = get_tax_document_checklist(family_id=fam_id)
        items = chk.get("items") or []
        item_lines = [f"- **{it.get('form_type')}** ({it.get('source')}): **{it.get('status_label')}**" for it in items[:6]]
        return (
            f"### 📋 Tax Season Document Checklist ({chk.get('tax_year', 2025)}) for {family_name}\n\n"
            f"**Progress:** **{chk.get('completed_count', 0)} of {chk.get('total_count', len(items))} Received / Sent to CPA**\n\n"
            f"---\n\n"
            f"#### 1. Expected Tax Documents\n"
            f"{chr(10).join(item_lines) if item_lines else '- No expected tax documents identified.'}\n\n"
            f"#### 2. Status Tracking\n"
            f"- Update document readiness via `update_tax_document_checklist_status`.\n"
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 3. Survivorship & Household Risk Audit
    if any(k in p_lower for k in ("survivorship", "probate", "beneficiary", "tod", "pod", "household risk", "audit risk")):
        audit = audit_household_risks(family_id=fam_id)
        findings = audit.get("findings") or []
        finding_lines = [f"- **{f.get('title')}** ({f.get('severity', '').upper()}): {f.get('detail')}" for f in findings[:4]]
        return (
            f"### 🛡️ Household Survivorship & Risk Audit for {family_name}\n\n"
            f"**Readiness Score:** **{audit.get('readiness_score', 100)} / 100** ({audit.get('status_badge', 'Ready')})  \n"
            f"**Identified Issues:** **{audit.get('critical_count', 0)} Critical**, **{audit.get('warning_count', 0)} Warning**\n\n"
            f"---\n\n"
            f"#### 1. Key Governance & Survivorship Findings\n"
            f"{chr(10).join(finding_lines) if finding_lines else '- All accounts have beneficiary or TOD/POD designations configured.'}\n\n"
            f"#### 2. Risk Mitigation Guidance\n"
            f"- Review beneficiary designations and transfer-on-death instructions to bypass statutory probate.\n"
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 4. Education & 529s
    if any(k in p_lower for k in ("529", "530a", "college", "tuition", "university", "k-12", "k12", "education")) or "college" in tab or "education" in tab:
        edu = get_education_529_plan(family_id=fam_id)
        kids_lines = [
            f"- **{c.get('name')}** (Class of {c.get('college_matriculation_year')}): "
            f"Current 529 **{c.get('current_529_balance')}** -> Projected: **{c.get('projected_529_at_matriculation')}**"
            for c in (edu.get("children") or [])
        ]
        bench_lines = [
            f"- **{b.get('tier')}** ({b.get('four_year_baseline_total')} 4-yr baseline): **{b.get('funding_status')}**"
            for b in (edu.get("university_funding_benchmarks") or [])
        ]
        return (
            f"### 🎓 Education & 529 Funding Review for {family_name}\n\n"
            f"**Total 529 & Custodial Education Assets:** **{edu.get('total_529_and_education_assets', '$0')}** ({edu.get('synchronized_accounts_summary', '0 Accounts')})  \n"
            f"**Modeled Tuition Total:** **{edu.get('total_modeled_tuition', '$0')}** | **529 Eligible Coverage:** **{edu.get('total_529_eligible_coverage', '$0')}** | **Out-of-Pocket Cashflow:** **{edu.get('projected_out_of_pocket_cashflow', '$0')}**\n\n"
            f"---\n\n"
            f"#### 1. Per-Child 529 Trajectory\n"
            f"{chr(10).join(kids_lines) if kids_lines else '- No child 529 profiles configured yet.'}\n\n"
            f"#### 2. 4-Year University Cost-of-Attendance Benchmarks\n"
            f"{chr(10).join(bench_lines) if bench_lines else '- Benchmark comparisons unavailable.'}\n"
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 5. Philanthropy & DAFs
    if any(k in p_lower for k in ("philanthropy", "charity", "charitable", "daf", "donor", "donation", "bunching")) or "philanthropy" in tab:
        phil = get_philanthropy_and_daf_summary(family_id=fam_id)
        grant_lines = [
            f"- **{g.get('organization')}** ({g.get('date')}): **{g.get('amount')}** — {g.get('description')}"
            for g in (phil.get("donations_ledger") or [])[:6]
        ]
        return (
            f"### 🤝 Philanthropy & Donor-Advised Fund (DAF) Review for {family_name}\n\n"
            f"**Lifetime Charitable Giving:** **{phil.get('lifetime_charitable_giving', '$0')}** ({phil.get('history_span', '')})  \n"
            f"**{phil.get('active_year', '2026')} Annual Budget:** **{phil.get('annual_budget', '$0')}** | **Allocated:** **{phil.get('allocated_grants_total', '$0')}** | **Remaining Available:** **{phil.get('remaining_unallocated_budget', '$0')}**\n\n"
            f"---\n\n"
            f"#### 1. Active Grant Ledger ({phil.get('grant_count', 0)} Grants)\n"
            f"{chr(10).join(grant_lines) if grant_lines else '- No charitable grants recorded for the active year.'}\n\n"
            f"#### 2. Tax-Smart Giving Strategy\n"
            f"- **Appreciated Stock Donations:** Contribute long-term appreciated shares directly to your DAF to eliminate federal and {state} capital gains taxes while claiming a full fair-market-value deduction.\n"
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 6. Family Gifting (IRS Form 709)
    if any(k in p_lower for k in ("709", "exclusion", "family gift", "gifting", "annual gift")) or "gifting" in tab:
        gift = get_family_gifting_summary(family_id=fam_id)
        rec_lines = [
            f"- **{r.get('recipient_group')}** ({r.get('beneficiary_count')}): "
            f"Gifted **{r.get('gifted_amount')}** of **{r.get('annual_couple_exclusion_limit')}** limit -> Headroom: **{r.get('remaining_headroom')}** ({r.get('tax_status')})"
            for r in (gift.get("recipients") or [])
        ]
        return (
            f"### 🎁 Intergenerational Family Gifting & Form 709 Audit for {family_name}\n\n"
            f"**Active Tax Year:** **{gift.get('active_year', '2026')}**  \n"
            f"**Total Gifted:** **{gift.get('total_gifted_in_year', '$0')}** | **Combined Exclusion Limit:** **{gift.get('total_annual_exclusion_limit', '$0')}** | **Remaining Tax-Exempt Headroom:** **{gift.get('remaining_tax_exempt_headroom', '$0')}**\n\n"
            f"---\n\n"
            f"#### 1. Recipient Exclusion Breakdown\n"
            f"{chr(10).join(rec_lines) if rec_lines else '- No recipient groups configured.'}\n\n"
            f"#### 2. Compliance & Wealth Transfer Guidance\n"
            f"- Gifts within the annual couple exclusion transfer wealth 100% tax-free without consuming your lifetime federal estate & gift tax exemption.\n"
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 7. Multi-State Tax Arbitrage
    if any(k in p_lower for k in ("arbitrage", "relocate", "relocation", "california", "nevada", "texas", "florida", "wyoming", "oregon", "domicile")) or "arbitrage" in tab:
        arb = get_state_tax_arbitrage(family_id=fam_id)
        card_lines = [
            f"- **{c.get('state_name')} ({c.get('state_code')})**: State Tax **{c.get('annual_state_tax')}** "
            f"(Eff: {c.get('effective_state_tax_rate')}) | Property Tax: {c.get('property_tax')} | vs. {arb.get('baseline_home_state', state)}: **{c.get('savings_vs_home_state')}**"
            for c in (arb.get("state_comparisons") or [])[:8]
        ]
        return (
            f"### 🗺️ Multi-State Tax & Lifestyle Arbitrage for {family_name}\n\n"
            f"**Baseline Residence:** **{arb.get('baseline_home_state', state)}** | **Modeled W-2 Income:** **{arb.get('base_w2_salary', '--')}** | **Options Spread:** **{arb.get('options_ordinary_spread', '--')}**\n\n"
            f"---\n\n"
            f"#### 1. State-by-State Comparison ({arb.get('active_mode', 'comprehensive').title()} Mode)\n"
            f"{chr(10).join(card_lines) if card_lines else '- State arbitrage comparisons unavailable.'}\n\n"
            f"#### 2. Domicile & Statutory Residency Considerations\n"
            f"- Establishing bona fide domicile before a major equity liquidity event (>183 physical days, voter registration, driver's license, primary homestead) can shield option spread and capital gains from high-bracket state taxes.\n"
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 8. Career Compensation, Safe Harbor Withholding & IRS Transcripts
    if any(k in p_lower for k in ("compensation", "salary", "bonus", "w-2", "w2", "safe harbor", "withholding", "transcript", "transcripts", "fica")) or any(k in tab for k in ("compensation", "withholding", "transcript", "tax")):
        comp = get_compensation_and_tax_withholding(family_id=fam_id)
        sh = comp.get("safe_harbor_withholding") or {}
        hist_lines = [
            f"- **{h.get('year')} ({h.get('taxpayer')} — {h.get('employer')})**: Base **{h.get('base_salary')}** + Bonus **{h.get('bonus')}** = **{h.get('total_cash_comp')}**"
            for h in (comp.get("compensation_history") or [])[:5]
        ]
        return (
            f"### 💼 Career Compensation & Safe Harbor Tax Audit for {family_name}\n\n"
            f"**Active Base Salary:** **{comp.get('active_base_salary', '--')}** ({comp.get('active_base_salary_detail', '')})  \n"
            f"**Peak Annual Compensation:** **{comp.get('peak_annual_compensation', '--')}** | **Lifetime Cash Earnings:** **{comp.get('lifetime_cash_earnings', '--')}** ({comp.get('bonus_summary', '')})\n\n"
            f"---\n\n"
            f"#### 1. IRS Safe Harbor (110% Prior-Year Tax) Pacing\n"
            f"- **Status:** **{sh.get('status', 'N/A')}**\n"
            f"- **Prior-Year Federal Tax:** **{sh.get('prior_year_federal_tax', '$0')}** -> **110% Safe Harbor Target:** **{sh.get('safe_harbor_110_pct_target', '$0')}**\n"
            f"- **Remaining Shortfall:** **{sh.get('remaining_shortfall', '$0')}** -> **Recommended Extra Withholding:** **{sh.get('recommended_extra_withholding_per_paycheck', '$0 / pay')}** across {sh.get('remaining_paychecks', 12)} remaining paychecks.\n\n"
            f"#### 2. Recent W-2 Compensation History\n"
            f"{chr(10).join(hist_lines) if hist_lines else '- No W-2 compensation history recorded yet.'}\n"
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 9. Accounts & Balance Sheet
    if any(k in p_lower for k in ("accounts", "monarch", "simplefin", "institution", "credit card", "mortgage")) or "account" in tab:
        acc_data = get_accounts_and_balance_sheet(family_id=fam_id)
        cat_lines = [
            f"- **{c.get('category_label')}**: **{c.get('category_total')}** ({len(c.get('accounts') or [])} accounts)"
            for c in (acc_data.get("categories") or [])
        ]
        return (
            f"### 🏦 Accounts & Balance Sheet Breakdown for {family_name}\n\n"
            f"**Total Linked & Manual Accounts:** **{acc_data.get('total_accounts_count', 0)}** "
            f"(Monarch: {acc_data.get('monarch_synced_count', 0)}, SimpleFIN: {acc_data.get('simplefin_synced_count', 0)}, Manual: {acc_data.get('manual_accounts_count', 0)})\n\n"
            f"---\n\n"
            f"#### 1. Balance Sheet Categories\n"
            f"{chr(10).join(cat_lines) if cat_lines else '- No accounts linked yet.'}\n"
            f"{_DISCLAIMER_SUFFIX}"
        )

    return None
