"""
Wave 1 Non-Beta Hacks Cleanup verification suite.
Validates:
1. estate_engine reads true_net_worth and eliminates $15M fake fallback.
2. monarch.snapshot avoids naive substring child name matching.
3. tools_core and tools_tabs return unavailable status on exceptions without fake fallbacks.
4. routes/tax.py truthfully reports when compensation sync fails.
"""

from unittest.mock import MagicMock, patch
import pytest

import estate_engine
from monarch import snapshot
from services.advisor import tools_core, tools_tabs
from routes import tax


def test_estate_engine_reads_true_net_worth_and_no_fake_15m_fallback():
    # Case A: monarch_service returns true_net_worth = 5_000_000
    with patch("monarch_service.get_financial_snapshot") as mock_snap, \
         patch("forecast_cache.get_cached_estate", return_value=None), \
         patch.object(estate_engine.DB_PATH, "exists", return_value=False):
        mock_snap.return_value = {"true_net_worth": 5_000_000.0, "net_worth": None}
        report = estate_engine.generate_estate_report(family_id=1)
        assert report["current_net_worth"] == 5_000_000.0

    # Case B: monarch_service returns true_net_worth = 0.0 (must NOT fall back to $15,000,000.0)
    with patch("monarch_service.get_financial_snapshot") as mock_snap, \
         patch("forecast_cache.get_cached_estate", return_value=None), \
         patch.object(estate_engine.DB_PATH, "exists", return_value=False):
        mock_snap.return_value = {"true_net_worth": 0.0, "net_worth": None}
        report_zero = estate_engine.generate_estate_report(family_id=2)
        assert report_zero["current_net_worth"] == 0.0
        assert report_zero["current_net_worth"] != 15_000_000.0


def test_monarch_snapshot_robinhood_child_name_word_boundary():
    # Child is named 'Rob'.
    # 'Robinhood Money Market' should NOT match child cash because 'rob' is not a whole word.
    # 'Rob Money' SHOULD match child cash (whole word 'rob' + 'money').
    accounts = [
        {
            "id": "acc-robinhood",
            "name": "Robinhood Money Market",
            "displayName": "Robinhood Money Market",
            "type": {"name": "depository"},
            "subtype": {"name": "money_market"},
            "currentBalance": 10_000.0,
            "includeInNetWorth": True,
            "includeBalanceInNetWorth": True,
        },
        {
            "id": "acc-rob-money",
            "name": "Rob Money",
            "displayName": "Rob Money",
            "type": {"name": "depository"},
            "subtype": {"name": "savings"},
            "currentBalance": 2_500.0,
            "includeInNetWorth": True,
            "includeBalanceInNetWorth": True,
        },
    ]

    mock_members = [{"name": "Rob Smith", "relationship": "child"}]
    with patch("monarch.categorizer.get_db_path") as mock_get_db, \
         patch("security.init_db"), \
         patch("db.store.get_accounts", return_value=accounts), \
         patch("db.store.get_holdings_by_account", return_value={}), \
         patch("db.store.get_family_members", return_value=mock_members), \
         patch("db.store.get_account_roles", return_value=[]), \
         patch("monarch.snapshot.get_brokerage_and_401k_positions", return_value=[]), \
         patch("monarch.snapshot.get_detailed_asset_allocation", return_value={}), \
         patch("equity_engine.get_current_409a_price", return_value=0.0):
        mock_db_obj = MagicMock()
        mock_db_obj.exists.return_value = True
        mock_get_db.return_value = mock_db_obj

        snap = snapshot.get_financial_snapshot(family_id=1, grants=[])
        # acc-robinhood must be included in reported net worth ($10,000.0)
        # acc-rob-money must be excluded (child cash)
        assert snap["monarch_reported_net_worth"] == 10_000.0


def test_advisor_tools_return_unavailable_on_error():
    # 1. tools_core.get_cash_flow_summary with DB error: must not return fake $250k spending
    with patch("db.families.get_household_profile", side_effect=RuntimeError("Profile DB down")):
        res_cf = tools_core.get_cash_flow_summary(family_id=1)
        assert res_cf.get("status") == "unavailable"
        assert "Profile DB down" in res_cf.get("error", "")
        assert "annual_spending" not in res_cf

    # 2. tools_core.get_estate_tax_summary
    with patch("estate_engine.get_family_estate_profile", side_effect=ValueError("Estate calculation failed")):
        res_est = tools_core.get_estate_tax_summary(family_id=1)
        assert res_est.get("status") == "unavailable"
        assert res_est.get("error") == "Estate calculation failed"

    # 3. tools_core.get_monte_carlo_stress_test
    with patch("forecast_engine.run_monte_carlo_simulation", side_effect=RuntimeError("MC timeout")):
        res_mc = tools_core.get_monte_carlo_stress_test(family_id=1)
        assert res_mc.get("status") == "unavailable"
        assert res_mc.get("error") == "MC timeout"

    # 4. tools_tabs error handling across all tab tools
    tab_tools = [
        tools_tabs.get_accounts_and_balance_sheet,
        tools_tabs.get_scenarios_and_forecast_plan,
        tools_tabs.get_compensation_and_tax_withholding,
        tools_tabs.get_state_tax_arbitrage,
        tools_tabs.get_education_529_plan,
        tools_tabs.get_philanthropy_and_daf_summary,
        tools_tabs.get_family_gifting_summary,
    ]
    with patch("services.advisor.tools_tabs.build_ssr_accounts", side_effect=RuntimeError("Tab error")), \
         patch("services.advisor.tools_tabs.build_ssr_scenarios", side_effect=RuntimeError("Tab error")), \
         patch("services.advisor.tools_tabs.build_ssr_compensation", side_effect=RuntimeError("Tab error")), \
         patch("services.advisor.tools_tabs.build_ssr_arbitrage", side_effect=RuntimeError("Tab error")), \
         patch("services.advisor.tools_tabs.build_ssr_college", side_effect=RuntimeError("Tab error")), \
         patch("services.advisor.tools_tabs.build_ssr_philanthropy", side_effect=RuntimeError("Tab error")), \
         patch("services.advisor.tools_tabs.build_ssr_gifting", side_effect=RuntimeError("Tab error")):
        for tool_fn in tab_tools:
            res = tool_fn(family_id=1)
            assert res.get("status") == "unavailable"
            assert "error" in res


def test_tax_route_truthful_message_on_compensation_save_failure(tmp_path):
    # When save_compensation_record fails, _process_transcript_upload_bytes must return
    # a truthful message instead of claiming compensation was updated.
    fake_pdf = b"%PDF-1.4 test"
    fake_parsed = {
        "year": 2025,
        "doc_type": "w2",
        "w2": {"employer": "Acme Corp", "wages_box1": 200_000.0},
        "totals": {"w2_wages": 200_000.0},
    }

    with patch("ingest_tax_transcripts.ingest_single_transcript_bytes", return_value=fake_parsed), \
         patch("db.transcripts.upsert_adult_year_summary"), \
         patch("routes.compensation.save_compensation_record", side_effect=RuntimeError("Disk full")):
        res = tax._process_transcript_upload_bytes(
            pdf_bytes=fake_pdf,
            family_id=1,
            target_adult="Primary Taxpayer",
            db_path=tmp_path / "test_tax.db",
        )

        assert res["success"] is True
        assert res["compensation_synced"] is False
        assert "compensation sync failed" in res["message"]
        assert "Compensation and safe harbor records updated" not in res["message"]

