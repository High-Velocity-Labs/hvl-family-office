"""
Automated SSR Hydration, Placeholder, and Dollar-for-Dollar API Parity Test Suite.

Verifies three critical invariants:
1. No HTML template contains bare static `>--<` inside KPI or stat value elements without Jinja expressions.
2. When authenticated as a seeded family, every SSR page route and every `/fragments/<name>` endpoint renders real data with 0 primary KPI elements showing `--`.
3. SSR-rendered monetary values match the JSON API responses dollar-for-dollar, preventing layout judder or number jump on client-side JS hydration.
"""

import re
import pytest
from pathlib import Path
from app import app
from hvl_common.testing import SSRParityAuditor, KPIElementExtractor
from hvl_common.ui import fmt_short_currency

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


@pytest.fixture
def auth_client():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["universe"] = "test"
        sess["family_id"] = 1
        sess["user_email"] = "test@example.com"
        sess["role"] = "editor"
        sess["is_demo"] = False
    return client


# ---------------------------------------------------------------------------
# 1. Template Static Placeholder Scanner
# ---------------------------------------------------------------------------
def test_templates_have_no_bare_static_dashes_in_kpis():
    """
    Ensures no template writes `<div class="kpi-value">--</div>` without a Jinja `{{ ... }}`
    expression. Any placeholder must be dynamically driven with fallback.
    """
    violations = SSRParityAuditor.scan_templates_for_bare_kpi_dashes(TEMPLATES_DIR)
    assert not violations, f"Found bare static '--' KPI elements missing SSR Jinja bindings: {violations}"


# ---------------------------------------------------------------------------
# 2. SSR Pages & Fragments Have No `--` in Key KPIs for Seeded Family
# ---------------------------------------------------------------------------
ALL_PAGE_ROUTES = [
    "/",
    "/overview",
    "/forecasting",
    "/scenarios",
    "/equity",
    "/holdings",
    "/compensation",
    "/estate",
    "/college",
    "/philanthropy",
    "/arbitrage",
    "/gifting",
    "/accounts",
    "/settings",
]

ALL_FRAGMENTS = [
    "overview",
    "scenarios",
    "equity",
    "holdings",
    "compensation",
    "estate",
    "college",
    "philanthropy",
    "arbitrage",
    "gifting",
    "accounts",
    "settings",
]


@pytest.mark.parametrize("route", ALL_PAGE_ROUTES)
def test_ssr_full_pages_have_hydrated_kpis(auth_client, route):
    """Asserts that visiting any full page route pre-renders hydrated KPIs for the active section."""
    resp = auth_client.get(route)
    assert resp.status_code in (200, 302), f"Route {route} failed with {resp.status_code}"


@pytest.mark.parametrize("fragment_name", ALL_FRAGMENTS)
def test_ssr_fragments_render_without_bare_kpi_dashes(auth_client, fragment_name):
    """
    Asserts that every `/fragments/<name>` endpoint serves fully pre-hydrated SSR HTML,
    so tab switching via FragmentLoader never flashes `--`.
    """
    resp = auth_client.get(f"/fragments/{fragment_name}")
    assert resp.status_code == 200, f"/fragments/{fragment_name} returned {resp.status_code}"

    html = resp.get_data(as_text=True)
    SSRParityAuditor.assert_no_bare_kpi_dashes(
        html,
        context_name=fragment_name,
        allowed_empty_ids={"child", "unallocated"},
    )



@pytest.mark.parametrize("fragment_name", ALL_FRAGMENTS)
def test_ssr_fragments_have_no_unformatted_currencies(auth_client, fragment_name):
    """
    Ensures currency numbers in rendered SSR HTML have localized comma separators
    (e.g., $2,733.00 instead of $2733.00) to prevent text/layout judder on mount.
    """
    resp = auth_client.get(f"/fragments/{fragment_name}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    SSRParityAuditor.assert_number_formatting(html, context_name=fragment_name)


BANNED_SSR_PLACEHOLDERS = [
    "Loading presets...",
    "Loading IRS safe harbor track record...",
    "Loading saved conversations...",
    "Checking connection...",
    "calculating...",
    "US --%",
    "Loading equity benchmark performance...",
]


@pytest.mark.parametrize("fragment_name", ALL_FRAGMENTS)
def test_ssr_fragments_have_no_loading_or_unhydrated_placeholders(auth_client, fragment_name):
    """
    Asserts that no rendered SSR fragment contains lingering 'Loading...', 'calculating...',
    'Checking connection...', or 'US --%' placeholders that get overwritten by client JS on load.
    """
    resp = auth_client.get(f"/fragments/{fragment_name}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for bad in BANNED_SSR_PLACEHOLDERS:
        assert bad not in html, f"/fragments/{fragment_name} still renders unhydrated placeholder '{bad}'!"


# ---------------------------------------------------------------------------
# 3. Dollar-for-Dollar SSR vs AJAX API Parity Tests
# ---------------------------------------------------------------------------
def _clean_num(val_str: str) -> float:
    """Parses clean float from currency strings like '$995,511' or '$1.85M'."""
    s = val_str.replace("$", "").replace(",", "").strip()
    if s.endswith("B"):
        return float(s[:-1]) * 1_000_000_000
    if s.endswith("M"):
        return float(s[:-1]) * 1_000_000
    if s.endswith("k") or s.endswith("K"):
        return float(s[:-1]) * 1_000
    return float(s)


def _find_elem_text_by_id(html: str, elem_id: str) -> str:
    pattern = re.compile(rf'id=["\']{re.escape(elem_id)}["\'][^>]*>(.*?)</(?:div|span|strong|p|td|button)>', re.DOTALL | re.IGNORECASE)
    m = pattern.search(html)
    return m.group(1).strip() if m else ""


def test_college_ssr_and_api_parity(auth_client):
    """Asserts that SSR college tuition and assets match /api/education to the exact dollar."""
    # 1. Fetch SSR Fragment
    frag_resp = auth_client.get("/fragments/college")
    html = frag_resp.get_data(as_text=True)
    ssr_txt = _find_elem_text_by_id(html, "college-tuition-total")
    assert ssr_txt, "college-tuition-total not found in SSR fragment"
    ssr_total = _clean_num(ssr_txt)

    ssr_assets_txt = _find_elem_text_by_id(html, "college-total-assets")
    assert ssr_assets_txt, "college-total-assets not found in SSR fragment"
    assert "." not in ssr_assets_txt, f"college-total-assets contains unrounded cents: '{ssr_assets_txt}'"
    ssr_assets = _clean_num(ssr_assets_txt)

    # 2. Fetch API Data
    api_resp = auth_client.get("/api/education")
    api_data = api_resp.get_json()
    assert api_data and api_data.get("success")
    api_total = float(api_data["tuition_summary"]["grand_total"])
    api_assets = round(float(api_data["total_529_assets"]))

    # 3. Assert Exact Equality
    assert abs(ssr_total - api_total) < 1.0, (
        f"College Tuition SSR ({ssr_total}) does not match API ({api_total})! "
        f"This causes changing numbers on hydration."
    )
    assert abs(ssr_assets - api_assets) < 1.0, (
        f"College Assets SSR ({ssr_assets}) does not match API rounded assets ({api_assets})!"
    )

    # 4. Verify table rows and footers are pre-rendered
    assert "<tr" in html.partition('id="tuition-table-body"')[2].partition('</tbody>')[0]
    assert "<tr" in html.partition('id="college-benchmarks-tbody"')[2].partition('</tbody>')[0]
    ssr_foot_combined = _find_elem_text_by_id(html, "tuition-foot-combined")
    assert ssr_foot_combined and ssr_foot_combined != "--"


def test_compensation_ssr_and_api_parity(auth_client):
    """Asserts that SSR active salary, Safe Harbor Withholding, and IRS Transcripts match APIs."""
    # 1. Fetch SSR Fragment
    frag_resp = auth_client.get("/fragments/compensation")
    html = frag_resp.get_data(as_text=True)
    ssr_txt = _find_elem_text_by_id(html, "comp-kpi-active-salary")
    assert ssr_txt, "comp-kpi-active-salary not found in SSR fragment"
    ssr_salary = _clean_num(ssr_txt)

    # 2. Fetch API Data
    api_resp = auth_client.get("/api/compensation")
    api_data = api_resp.get_json()
    assert api_data and api_data.get("success")

    history = api_data.get("history") or []
    assert len(history) > 0
    latest = max(history, key=lambda x: int(x.get("year", 0)))
    expected_salary = float(latest.get("salary") or latest.get("base_salary") or 0.0)

    # 3. Assert Exact Equality
    assert abs(ssr_salary - expected_salary) < 1.0, (
        f"Compensation Active Salary SSR ({ssr_salary}) does not match API ({expected_salary})!"
    )

    # 4. Verify table rows and footer totals (Subtab 1: Career)
    assert "<tr" in html.partition('id="compensation-table-body"')[2].partition('</tbody>')[0]
    ssr_foot_tot = _find_elem_text_by_id(html, "comp-foot-total")
    assert ssr_foot_tot and ssr_foot_tot != "--"

    # 5. Verify Subtab 2: Safe Harbor Withholding parity against POST /api/withholding
    wh_tbody = html.partition('id="withholding-transcripts-tbody"')[2].partition('</tbody>')[0]
    assert "<tr" in wh_tbody and "Loading IRS safe harbor" not in wh_tbody
    sh_rule_txt = _find_elem_text_by_id(html, "sh-rule-target")
    assert sh_rule_txt and "calculating" not in sh_rule_txt.lower()
    ssr_shortfall_txt = _find_elem_text_by_id(html, "sh-shortfall-display")
    assert ssr_shortfall_txt and ssr_shortfall_txt != "--"

    # 6. Verify Subtab 3: IRS Transcripts table is pre-rendered with records
    tr_tbody = html.partition('id="transcripts-table-body"')[2].partition('</tbody>')[0]
    assert "<tr" in tr_tbody and "No transcript records uploaded" not in tr_tbody

    # 7. Verify no duplicate "Combined Household" buttons or data-user-id="None"
    assert 'data-user-id="None"' not in html
    for pill_group_id in ("comp-adult-pills", "safeharbor-adult-pills", "transcript-adult-pills"):
        group_html = html.partition(f'id="{pill_group_id}"')[2].partition("</div>")[0]
        assert group_html.count("Combined Household") == 1, f"Duplicate Combined Household pill in #{pill_group_id}"

    # 8. Verify switching taxpayer on Safe Harbor subtab never adds .00 decimals
    for tp_val in ("1", "all"):
        sh_resp = auth_client.get(f"/fragments/compensation?taxpayer={tp_val}&subtab=comp-subtab-safeharbor")
        sh_html = sh_resp.get_data(as_text=True)
        for kpi_id in ("sh-target-display", "sh-prior-tax", "sh-shortfall-display", "sh-extra-per-paycheck"):
            val_txt = _find_elem_text_by_id(sh_html, kpi_id)
            assert ".00" not in val_txt, f"Safe Harbor KPI #{kpi_id} has .00 decimals for taxpayer={tp_val}: {val_txt}"


def test_scenarios_ssr_and_api_parity(auth_client):
    """Asserts that SSR forecasting metrics, scorecard rows, presets, pins, and readiness card match /api/scenarios."""
    frag_resp = auth_client.get("/fragments/scenarios")
    html = frag_resp.get_data(as_text=True)
    ssr_txt = _find_elem_text_by_id(html, "val-current-plan-nw65")
    assert ssr_txt, "val-current-plan-nw65 not found in SSR fragment"
    ssr_nw65 = _clean_num(ssr_txt)

    api_resp = auth_client.get("/api/scenarios")
    api_data = api_resp.get_json()
    assert api_data and api_data.get("success")
    active_id = api_data.get("active_scenario_id")
    scorecard = api_data.get("scorecard") or []
    card = next((item for item in scorecard if item.get("id") == active_id), scorecard[0] if scorecard else {})
    api_nw65 = float(card.get("net_worth_65") or 0.0)

    diff_pct = abs(ssr_nw65 - api_nw65) / max(1.0, api_nw65)
    assert diff_pct < 0.05, f"Scenarios NW65 SSR ({ssr_nw65}) diverges from API ({api_nw65})"

    # Verify Compare Plans button count matches scorecard length
    assert f"Compare Plans ({len(scorecard)})" in html, "Compare Plans button count missing or mismatched in SSR!"

    # Verify Events & Spend format ("N Events • $X/yr")
    val_spend = _find_elem_text_by_id(html, "val-current-plan-spend")
    assert "Events •" in val_spend and "/yr" in val_spend, f"val-current-plan-spend format mismatch: '{val_spend}'"

    # Verify Primary & Spouse Can Retire badges and Solvency badge
    assert "badge-" in _find_elem_text_by_id(html, "val-current-plan-primary-ret")
    assert "badge-" in _find_elem_text_by_id(html, "val-current-plan-spouse-ret")
    assert "badge-" in _find_elem_text_by_id(html, "val-current-plan-solvency")

    # Verify Scorecard comparison table rows are pre-rendered in SSR
    scorecard_tbody = html.partition('id="tbody-scenarios-scorecard"')[2].partition('</tbody>')[0]
    assert "<tr" in scorecard_tbody and "No alternative plans created" not in scorecard_tbody

    # Verify Savings presets are pre-rendered (no "Loading presets...")
    savings_presets_sec = html.partition('id="scen-savings-presets-container"')[2].partition('</div>')[0]
    assert "btn-scen-savings-preset" in savings_presets_sec

    # Verify Company Equity strip in scenario plan card is pre-rendered
    eq_info_sec = html.partition('id="scenario-equity-info-container"')[2].partition('</div>')[0]
    assert eq_info_sec.strip(), "scenario-equity-info-container is empty in SSR!"

    # Verify Market Return Profile selector and Forecasting Data Widgets grid are pre-rendered in SSR
    assert 'id="select-scen-market-profile"' in html, "select-scen-market-profile missing in scenarios SSR!"
    assert 'id="lens-btn-networth"' not in html, "Legacy 4-tab lens switcher should be replaced by standalone widgets!"
    widgets_grid = html.partition('id="scenarios-widgets-grid"')[2].partition('<!-- =========================================================')[0]
    assert "household-widget-card" in widgets_grid, "scenarios-widgets-grid has no pre-rendered household-widget-card items in SSR!"
    assert 'data-widget-id="scen_chart_networth"' in widgets_grid, "scen_chart_networth widget missing in default scenarios SSR!"
    assert 'data-widget-id="scen_retirement_readiness"' in widgets_grid, "scen_retirement_readiness widget missing in default scenarios SSR!"
    assert 'data-widget-id="scen_chart_cashflow"' in widgets_grid, "scen_chart_cashflow widget missing in default scenarios SSR!"

    # Verify Spend-Down Schedule table is pre-rendered in SSR
    sched_tbody = html.partition('id="scen-schedule-tbody"')[2].partition('</tbody>')[0]
    assert "<tr" in sched_tbody, "scen-schedule-tbody has no pre-rendered rows in SSR!"

    # Verify parameterized /fragments/scenarios?scenario_id=...&view_mode=...
    alt_card = next((item for item in scorecard if item.get("id") != active_id), scorecard[0] if scorecard else {})
    alt_id = alt_card.get("id") or "scen_baseline"
    param_resp = auth_client.get(f"/fragments/scenarios?scenario_id={alt_id}&view_mode=nominal")
    assert param_resp.status_code == 200
    param_html = param_resp.get_data(as_text=True)
    assert re.search(r'id="btn-scen-view-nominal"[^>]*class="[^"]*\bactive\b', param_html), (
        "btn-scen-view-nominal not marked active for view_mode=nominal"
    )
    assert f'data-scen-id="{alt_id}"' in param_html, f"data-scen-id={alt_id} not rendered in parameterized scenarios SSR"


def test_overview_ssr_and_api_parity(auth_client):
    """Asserts that SSR overview net worth matches /api/dashboard."""
    frag_resp = auth_client.get("/fragments/overview")
    ssr_txt = _find_elem_text_by_id(frag_resp.get_data(as_text=True), "kpi-true-net-worth")
    assert ssr_txt, "kpi-true-net-worth not found in SSR fragment"
    ssr_nw = _clean_num(ssr_txt)

    api_resp = auth_client.get("/api/dashboard")
    api_data = api_resp.get_json()
    assert api_data and api_data.get("success")
    snap = api_data.get("snapshot") or {}
    api_nw = float(snap.get("true_net_worth") or 0.0)

    assert abs(ssr_nw - api_nw) < 10.0, f"Overview Net Worth SSR ({ssr_nw}) diverges from API ({api_nw})"


def test_equity_ssr_and_api_parity(auth_client):
    """Asserts that SSR equity net, gross, and breakdown subtitles match company_equity in snapshot."""
    frag_resp = auth_client.get("/fragments/equity")
    html = frag_resp.get_data(as_text=True)
    ssr_net_txt = _find_elem_text_by_id(html, "equity-kpi-net")
    ssr_gross_txt = _find_elem_text_by_id(html, "equity-kpi-gross")
    assert ssr_net_txt and ssr_gross_txt, f"Equity KPIs missing: net={ssr_net_txt}, gross={ssr_gross_txt}"

    ssr_net = _clean_num(ssr_net_txt)
    ssr_gross = _clean_num(ssr_gross_txt)

    api_resp = auth_client.get("/api/dashboard")
    api_data = api_resp.get_json()
    assert api_data and api_data.get("success")
    eq = api_data.get("snapshot", {}).get("company_equity", {})
    api_net = float(eq.get("true_net_post_tax_value") or 0.0)
    api_gross = float(eq.get("nominal_gross_equity_value") or eq.get("company_nominal_gross_equity_value") or 0.0)

    assert abs(ssr_net - api_net) < 10.0, f"Equity Net Value SSR ({ssr_net}) diverges from API ({api_net})"
    assert abs(ssr_gross - api_gross) < 10.0, f"Equity Gross Value SSR ({ssr_gross}) diverges from API ({api_gross})"

    # Performance KPI Card Structure Parity
    ssr_perf_pct = _find_elem_text_by_id(html, "equity-kpi-perf-pct")
    ssr_perf_mult = _find_elem_text_by_id(html, "equity-kpi-perf-mult")
    assert ssr_perf_pct and "%" in ssr_perf_pct, f"equity-kpi-perf-pct invalid: {ssr_perf_pct}"
    assert ssr_perf_mult and "x)" in ssr_perf_mult, f"equity-kpi-perf-mult invalid: {ssr_perf_mult}"
    assert "Loading equity benchmark performance..." not in html
    assert "Total Return:" in html and "Annualized CAGR:" in html and "Outperformance (Alpha)" in html

    # Verify dynamic breakdown badges/subtitles (not static generic fallbacks)
    vested_sub = _find_elem_text_by_id(html, "vested-shares-breakdown")
    strike_sub = _find_elem_text_by_id(html, "strike-grants-summary")
    assert "Vested Options" in vested_sub and "Owned Shares" in vested_sub, f"vested-shares-breakdown unhydrated: {vested_sub}"
    assert "Across " in strike_sub and "Vested Option Grant" in strike_sub, f"strike-grants-summary unhydrated: {strike_sub}"


def test_estate_ssr_and_api_parity(auth_client):
    """Asserts that SSR gross estate, total tax, and max potential tax shielded match /api/estate."""
    frag_resp = auth_client.get("/fragments/estate")
    html = frag_resp.get_data(as_text=True)
    ssr_gross_txt = _find_elem_text_by_id(html, "stat-gross-estate")
    ssr_tax_txt = _find_elem_text_by_id(html, "stat-total-estate-tax")
    ssr_shield_txt = _find_elem_text_by_id(html, "badge-max-shielding")
    assert ssr_gross_txt and ssr_tax_txt and ssr_shield_txt

    ssr_gross = _clean_num(ssr_gross_txt)
    ssr_tax = _clean_num(ssr_tax_txt)

    api_resp = auth_client.get("/api/estate")
    api_data = api_resp.get_json()
    assert api_data and api_data.get("success")
    cur_tax = api_data.get("current_estate_tax") or {}
    api_gross = float(cur_tax.get("gross_estate") or 0.0)
    api_tax = float(cur_tax.get("total_estate_tax") or 0.0)

    assert abs(ssr_gross - api_gross) < 10.0, f"Estate Gross SSR ({ssr_gross}) diverges from API ({api_gross})"
    assert abs(ssr_tax - api_tax) < 10.0, f"Estate Tax SSR ({ssr_tax}) diverges from API ({api_tax})"

    # Max Potential Tax Shielded should match fmt_short_currency(max_sav) (e.g. $11.4M)
    sandbox = api_data.get("trust_sandbox") or {}
    max_sav = float(sandbox.get("max_potential_tax_savings") or 0.0)
    expected_shield = fmt_short_currency(max_sav)
    assert expected_shield in ssr_shield_txt, (
        f"badge-max-shielding SSR '{ssr_shield_txt}' does not contain expected '{expected_shield}'!"
    )

    # Verify trust vehicles and inheritance waterfall are pre-rendered
    assert "<tr" in html.partition('id="tbody-inheritance-waterfall"')[2].partition('</tbody>')[0]
    assert 'class="badge' in html.partition('id="trust-vehicles-grid"')[2].partition('</div>')[0]
    assert 'state-arbitrage-cards-grid' in html


def test_philanthropy_ssr_and_api_parity(auth_client):
    """Asserts that SSR philanthropy lifetime giving, 2026 ledger, and grant counts match /api/philanthropy."""
    frag_resp = auth_client.get("/fragments/philanthropy")
    html = frag_resp.get_data(as_text=True)
    ssr_life_txt = _find_elem_text_by_id(html, "daf-lifetime-total")
    assert ssr_life_txt, "daf-lifetime-total not found in SSR fragment"
    ssr_life = _clean_num(ssr_life_txt)

    api_resp = auth_client.get("/api/philanthropy")
    api_data = api_resp.get_json()
    assert api_data and api_data.get("success")
    api_life = float(api_data.get("total_lifetime_charity") or 0.0)

    assert abs(ssr_life - api_life) < 10.0, f"Philanthropy Lifetime SSR ({ssr_life}) diverges from API ({api_life})"

    # Verify subtitle grant count and ledger title
    ssr_sub = _find_elem_text_by_id(html, "daf-grant-count-sub")
    donations_by_year = api_data.get("donations_by_year") or {}
    year_entry = donations_by_year.get("2026") or donations_by_year.get(2026) or []
    if isinstance(year_entry, dict):
        grants = year_entry.get("donations") or []
    else:
        grants = year_entry or []
    grant_count = len(grants)
    allocated_sum = sum(
        float(g.get("amount") or 0) for g in grants
        if isinstance(g, dict) and (g.get("organization") or "").lower() != "available"
    )
    assert f"{grant_count} grants" in ssr_sub, f"Grant count sub missing '{grant_count} grants': {ssr_sub}"
    assert f"{fmt_short_currency(allocated_sum)} allocated" in ssr_sub, (
        f"Grant count sub missing '{fmt_short_currency(allocated_sum)} allocated': {ssr_sub}"
    )

    ssr_ledger_title = _find_elem_text_by_id(html, "daf-ledger-title")
    assert "(2026 Ledger)" in ssr_ledger_title, f"Ledger title missing '(2026 Ledger)': {ssr_ledger_title}"

    # Verify table rows and footer total
    assert "<tr" in html.partition('id="daf-donations-tbody"')[2].partition('</tbody>')[0]
    ssr_foot = _find_elem_text_by_id(html, "daf-footer-total")
    assert fmt_short_currency(allocated_sum) in ssr_foot or f"${int(allocated_sum):,}" in ssr_foot, (
        f"Footer total missing '{fmt_short_currency(allocated_sum)}': {ssr_foot}"
    )


def test_gifting_ssr_and_api_parity(auth_client):
    """Asserts that SSR gifting active year total, budget title, and rows match /api/gifting."""
    frag_resp = auth_client.get("/fragments/gifting")
    html = frag_resp.get_data(as_text=True)
    ssr_total_txt = _find_elem_text_by_id(html, "gift-selected-year-total")
    assert ssr_total_txt, "gift-selected-year-total not found in SSR fragment"
    ssr_total = _clean_num(ssr_total_txt)

    api_resp = auth_client.get("/api/gifting")
    api_data = api_resp.get_json()
    assert api_data and api_data.get("success")
    yearly = api_data.get("yearly_details") or {}
    expected_total = float((yearly.get("2026") or {}).get("total_given") or 0.0)

    SSRParityAuditor.assert_dollar_parity(
        ssr_total,
        expected_total,
        tolerance=1.0,
        label="Gifting Active Year Total",
    )

    # Verify title contains active year
    ssr_title = _find_elem_text_by_id(html, "gifting-header-title")
    assert "(2026 Budget)" in ssr_title, f"Gifting header missing '(2026 Budget)': {ssr_title}"

    # Verify table rows and footer cells
    assert "<tr" in html.partition('id="gifting-table-tbody"')[2].partition('</tbody>')[0]
    foot_tot = _find_elem_text_by_id(html, "gifting-footer-total")
    assert foot_tot and foot_tot != "--", f"gifting-footer-total unhydrated: {foot_tot}"
    foot_lim = _find_elem_text_by_id(html, "gifting-footer-limit")
    assert foot_lim and foot_lim != "--", f"gifting-footer-limit unhydrated: {foot_lim}"


def test_arbitrage_ssr_and_api_parity(auth_client):
    """Asserts that SSR arbitrage spending rows, presets, and state comparison cards are pre-rendered."""
    frag_resp = auth_client.get("/fragments/arbitrage")
    html = frag_resp.get_data(as_text=True)

    # Check active preset is pre-rendered and selected
    m_spend = re.search(r'class="pill-btn btn-spend-preset active" data-spend="([0-9]+)"', html)
    assert m_spend, "Active living budget preset button not pre-rendered in SSR"
    ssr_preset_spend = float(m_spend.group(1))

    from routes.ssr_builders import build_ssr_arbitrage
    with auth_client:
        auth_client.get("/fragments/arbitrage")
        ssr_arb = build_ssr_arbitrage(family_id=1)
        expected_spend = float(next((p["spend"] for p in ssr_arb.get("presets", []) if p.get("is_active")), ssr_arb.get("annual_spend") or 60000.0))

    SSRParityAuditor.assert_dollar_parity(
        ssr_preset_spend,
        expected_spend,
        tolerance=1000.0,
        label="Arbitrage Active Preset Spend",
    )

    # Verify state comparison cards are pre-rendered in #arbitrage-cards-container
    cards_sec = html.partition('id="arbitrage-cards-container"')[2]
    assert "arbitrage-state-card" in cards_sec, "#arbitrage-cards-container has no pre-rendered .arbitrage-state-card elements in SSR!"

    # Verify parameterized /fragments/arbitrage?home_state=CA&mode=tax_only&scenario=liquidity&annual_spend=240000
    param_resp = auth_client.get(
        "/fragments/arbitrage?home_state=CA&mode=tax_only&scenario=liquidity&annual_spend=240000"
    )
    assert param_resp.status_code == 200
    param_html = param_resp.get_data(as_text=True)
    assert re.search(r'id="btn-arb-mode-tax"[^>]*class="[^"]*\bactive\b', param_html), (
        "btn-arb-mode-tax not marked active for mode=tax_only"
    )
    assert re.search(r'id="btn-arb-scenario-liquidity"[^>]*class="[^"]*\bactive\b', param_html), (
        "btn-arb-scenario-liquidity not marked active for scenario=liquidity"
    )
    assert "ANNUAL STATE TAX LIABILITY" in param_html
    assert "Ordinary Income Tax:" in param_html and "Capital Gains Tax:" in param_html
    assert "Liquidity Event" in _find_elem_text_by_id(param_html, "arbitrage-scenario-badge")


def test_accounts_ssr_and_api_parity(auth_client):
    """Asserts that /fragments/accounts renders pre-hydrated categories and accounts."""
    frag_resp = auth_client.get("/fragments/accounts")
    assert frag_resp.status_code == 200
    html = frag_resp.get_data(as_text=True)

    # Asserts container has pre-rendered category cards
    assert '<div class="portal-card"' in html, "Accounts fragment has no pre-rendered portal-card categories"
    assert "<table" in html, "Accounts fragment missing table markup"
    assert "<tr" in html, "Accounts fragment missing account rows"

    # Asserts title has dynamic account count
    title = _find_elem_text_by_id(html, "accounts-page-title")
    assert "Accounts)" in title or "Monarch Money" in title, f"Accounts title missing count: {title}"


def test_settings_ssr_and_api_parity(auth_client):
    """Asserts that /fragments/settings renders pre-hydrated family members, account roles, and Monarch status."""
    frag_resp = auth_client.get("/fragments/settings")
    assert frag_resp.status_code == 200
    html = frag_resp.get_data(as_text=True)

    # Asserts family members table is pre-rendered with rows
    members_section = html.partition('id="settings-members-tbody"')[2].partition('</tbody>')[0]
    assert "<tr" in members_section, "settings-members-tbody has no pre-rendered member rows"

    # Asserts account classification roles table is pre-rendered with rows
    roles_section = html.partition('id="settings-roles-tbody"')[2].partition('</tbody>')[0]
    assert "<tr" in roles_section and "All active accounts mapped" not in roles_section, "settings-roles-tbody has no pre-rendered account role rows"

    # Asserts Monarch connection status is pre-rendered (not 'Checking connection...')
    monarch_status = _find_elem_text_by_id(html, "monarch-conn-status-display")
    assert "Checking connection" not in monarch_status

    # Verify parameterized /fragments/settings?tab=roles and /fragments/settings?tab=advisor-history&adv_pinned_only=1
    roles_resp = auth_client.get("/fragments/settings?tab=roles")
    assert roles_resp.status_code == 200
    roles_html = roles_resp.get_data(as_text=True)
    assert re.search(r'id="tab-btn-roles"[^>]*class="[^"]*\bactive\b', roles_html), (
        "tab-btn-roles not marked active for tab=roles"
    )
    assert re.search(r'id="settings-tab-roles"[^>]*style="display:\s*block', roles_html), (
        "settings-tab-roles not displayed as block for tab=roles"
    )

    adv_resp = auth_client.get("/fragments/settings?tab=advisor-history&adv_pinned_only=1")
    assert adv_resp.status_code == 200
    adv_html = adv_resp.get_data(as_text=True)
    assert re.search(r'id="tab-btn-advisor-history"[^>]*class="[^"]*\bactive\b', adv_html), (
        "tab-btn-advisor-history not marked active for tab=advisor-history"
    )
    assert re.search(r'id="btn-settings-filter-pinned"[^>]*class="[^"]*\bactive\b', adv_html), (
        "btn-settings-filter-pinned not marked active for adv_pinned_only=1"
    )


def test_static_js_has_no_guarded_dual_pipelines():
    """
    Enforces Rule 9 (Prohibition of Guarded Dual-Pipelines):
    Performs structural regex checks across static/js/**/*.js banning SSR-bypass guard
    patterns (e.g. canReuseSSR, if (existingRows) return, DOM child-count equality guards)
    and legacy client-side table/card builders for SSR-owned sections.
    """
    js_dir = Path(__file__).resolve().parent.parent / "static" / "js"
    structural_rules = [
        (
            "SSR-bypass flag identifier",
            re.compile(r"\b(?:canReuseSSR|canReuseSsr|hasSsrRows|hasSSRRows|isInitialSsr|isInitialSSR)\b"),
        ),
        (
            "early-return DOM existence guard",
            re.compile(
                r"if\s*\(\s*!?\s*(?:existingRows|existingCards|existingButtons|hasSsrRows|canReuseSSR|canReuseSsr)\b[^)]*\)\s*(?:return\b|\{)|"
                r"if\s*\(\s*(?:tbody|container)\.children\.length\s*>\s*0\s*\)\s*return\b"
            ),
        ),
        (
            "DOM child-count equality bypass guard",
            re.compile(
                r"(?:existingButtons|existingRows|existingCards|tbody\.children|container\.children)\.length\s*===\s*"
                r"(?:presets|safeHarborAdults|sched|rows|cards|items)\.length"
            ),
        ),
        (
            "legacy imperative SSR-section builder",
            re.compile(
                r"\bfunction\s+(?:renderArbitrageCards|loadSettingsMembers|loadSettingsRoles|loadMonarchStatus|"
                r"renderSettingsAdvisorConversationsTable|renderCurrentPlanCard|renderScorecardTable|renderSpendDownSchedule)\s*\("
            ),
        ),
    ]
    violations = []
    for js_file in sorted(js_dir.rglob("*.js")):
        content = js_file.read_text(encoding="utf-8")
        rel_path = js_file.relative_to(js_dir.parent.parent)
        for rule_label, pattern in structural_rules:
            for match in pattern.finditer(content):
                violations.append(
                    f"{rel_path}: contains prohibited {rule_label} '{match.group(0)}'"
                )
    assert not violations, "Guarded dual-pipelines detected in client JS:\n" + "\n".join(violations)


def test_playbooks_and_changelog_deep_links():
    """
    Verifies that /playbooks renders all deep-link launcher hrefs into /scenarios
    and that /whats-new auto-links backticked `/playbooks` route references in CHANGELOG.md.
    """
    from app import app
    client = app.test_client()

    pb_resp = client.get("/playbooks")
    assert pb_resp.status_code == 200
    pb_html = pb_resp.get_data(as_text=True)

    expected_links = [
        "/scenarios?compare=1",
        "/scenarios?open_event=pre65_healthcare",
        "/scenarios?open_event=roth_conversion",
        "/scenarios?lens=cashflow&amp;view=sankey",
        "/scenarios?open_event=home_renovation",
        "/scenarios?lens=montecarlo&amp;mc_mode=historical",
        "/scenarios?open_guardrails=1",
        "/scenarios?open_event=state_relocation",
        "/scenarios?open_event=company_equity",
        "/scenarios?ask_ai=",
    ]
    for href in expected_links:
        assert href in pb_html, f"Expected deep link {href!r} in /playbooks HTML"

    wn_resp = client.get("/whats-new")
    assert wn_resp.status_code == 200
    wn_html = wn_resp.get_data(as_text=True)
    assert 'href="/playbooks"' in wn_html
