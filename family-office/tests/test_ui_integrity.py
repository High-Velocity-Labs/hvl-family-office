"""
F-UI-4/6/7/8 guardrails: no tax math or made-up figures in the browser or templates, no inverted layering
(ssr/ importing routes/) or compatibility shims, and JS state owned by one module per concern.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wsgi import app
from ssr.equity_grant_detail import build_ssr_grant_detail
from services.equity_curve import build_valuation_curve

REPO = Path(__file__).resolve().parent.parent
JS_DIR = REPO / "static" / "js"
COMPONENTS = REPO / "templates" / "components"


@pytest.fixture
def auth_client():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(
            authenticated=True, universe="test", family_id=1, user_email="test@example.com", role="editor", is_demo=False
        )
    return client


def test_ssr_does_not_import_route_modules_except_the_shared_request_context():
    offenders = []
    for path in (REPO / "ssr").glob("*.py"):
        for no, line in enumerate(path.read_text().splitlines(), 1):
            m = re.match(r"\s*(?:from|import)\s+routes\.(\w+)", line)
            if m and m.group(1) != "context":
                offenders.append(f"{path.name}:{no}: {line.strip()}")
    assert not offenders, "ssr/ must not import routes.*:\n" + "\n".join(offenders)


@pytest.mark.parametrize("shim", ["routes/ssr_builders.py", "services/advisor_engine.py"])
def test_compatibility_shims_are_deleted(shim):
    assert not (REPO / shim).exists()


def test_private_loaders_live_in_services_not_routes():
    for name in ("_load_compensation_records", "_load_gifting_data", "_load_tuition_records", "_parse_grade_index"):
        hits = [p.name for p in (REPO / "routes").glob("*.py") if name in p.read_text()]
        assert not hits, f"{name} must not live in routes/: {hits}"


def test_no_statutory_rates_or_limits_in_browser_code():
    banned = re.compile(r"0\.238|\b38000\b|\b0\.3935\b|\bfedRate\b")
    offenders = [
        f"{p.relative_to(REPO)}:{no}"
        for p in JS_DIR.rglob("*.js")
        for no, line in enumerate(p.read_text().splitlines(), 1)
        if banned.search(line)
    ]
    assert not offenders, "tax math belongs in services/: " + ", ".join(offenders)


def test_equity_grant_detail_card_is_not_built_in_js():
    src = (JS_DIR / "equity_modals.js").read_text()
    assert "grant-detail-content" not in src and "ltcgTax" not in src


MADE_UP_FALLBACK = re.compile(r"ssr_\w+\.\w+\)?\s+or\s+[1-9]\d*(?:\.\d+)?\b")


@pytest.mark.parametrize(
    "template",
    ["equity.html", "philanthropy.html", "estate.html", "holdings_breakdown_modals.html",
     "scenarios/plan_card.html", "scenarios/scorecard.html"],
)
def test_templates_do_not_fall_back_to_made_up_figures(template):
    hits = MADE_UP_FALLBACK.findall((COMPONENTS / template).read_text())
    assert not hits, f"{template} falls back to a literal figure: {hits}"


def test_advisor_and_equity_state_are_owned_by_one_module_each():
    advisor_files = [p for p in JS_DIR.glob("ai_advisor*.js") if p.name != "ai_advisor_state.js"]
    equity_files = [p for p in JS_DIR.glob("equity*.js") if p.name != "equity_state.js"]
    for path in advisor_files + equity_files:
        assert not re.search(r"^var \w+ = ", path.read_text(), re.M), f"{path.name} declares top-level globals"


def test_grant_detail_view_model_uses_engine_tax_and_marks_missing_figures():
    snapshot = {"company_equity": {"grants": [{
        "grant_id": "g1", "nickname": "Founder", "grant_date": "2024-01-01", "grant_type": "ISO",
        "owned_shares": 100.0, "owned_gross_value": 10000.0, "owned_cost_basis": 4000.0,
        "stock_tax": {"total_tax": 1428.0}, "strike_price": 5.0, "unvested_options": 0.0,
    }]}}
    rows = {r["label"]: r["value"] for r in build_ssr_grant_detail(snapshot, "g1")["rows"]}
    assert rows["EST. TAX ON OWNED SHARES"] == "$1,428"
    assert rows["UNREALIZED CAPITAL GAINS"] == "$6,000"
    assert rows["TAXABLE SPREAD"] == "--"
    assert build_ssr_grant_detail(snapshot, "missing") == {}


def test_valuation_curve_requires_a_base_price():
    with pytest.raises(ValueError):
        build_valuation_curve(family_id=1, base_price=0.0, include_wa_tax=False)


def test_curve_endpoint_rejects_missing_base_price(auth_client):
    assert auth_client.get("/api/equity/curve").status_code == 400
    assert auth_client.get("/api/equity/curve?base_price=0").status_code == 400


def test_grant_detail_fragment_reports_unknown_grant(auth_client):
    resp = auth_client.get("/fragments/equity_grant_detail?grant_id=does-not-exist")
    assert resp.status_code == 200
    assert "Grant not found" in resp.get_data(as_text=True)


@pytest.mark.parametrize("job", [
    {"status": "failed", "error": "boom"},
    {"status": "completed", "result": None},
    {"status": "weird"},
    {"status": None, "conversation_id": "c1"},
])
def test_advisor_job_poll_is_terminal_for_anything_but_processing(auth_client, monkeypatch, job):
    from services import background_jobs

    monkeypatch.setattr(background_jobs, "get_job", lambda job_id, family_id=0: dict(job))
    body = auth_client.get("/api/ai-advisor/jobs/abc").get_json()
    assert body["status"] == "failed" and body["success"] is False and body["error"]


def test_advisor_job_poll_reports_processing_only_when_processing(auth_client, monkeypatch):
    from services import background_jobs

    monkeypatch.setattr(background_jobs, "get_job", lambda job_id, family_id=0: {"status": "processing"})
    assert auth_client.get("/api/ai-advisor/jobs/abc").get_json()["status"] == "processing"
