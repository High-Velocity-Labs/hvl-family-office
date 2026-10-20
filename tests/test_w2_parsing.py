import pytest
import ingest_tax_transcripts


def test_parse_w2_standard_layout():
    sample_w2 = """
    Form W-2 Wage and Tax Statement 2024
    OMB No. 1545-0008
    c Employer's name, address, and ZIP code
    Acme Cloud Systems Inc
    123 Tech Way, Seattle WA 98101
    1 Wages, tips, other comp. $520,000.00
    2 Federal income tax withheld $145,000.00
    3 Social security wages $168,600.00
    4 Social security tax withheld $10,453.20
    5 Medicare wages and tips $520,000.00
    6 Medicare tax withheld $7,540.00
    12a V 120,000.00
    12b D 23,000.00
    12c DD 14,200.00
    """
    res = ingest_tax_transcripts.parse_w2_text(sample_w2)
    assert res["year"] == 2024
    assert res["doc_type"] == "w2"
    assert res["w2"]["wages_box1"] == 520000.0
    assert res["w2"]["federal_tax_withheld_box2"] == 145000.0
    assert res["w2"]["social_security_tax_withheld_box4"] == 10453.20
    assert res["w2"]["medicare_tax_withheld_box6"] == 7540.0
    assert res["w2"]["nso_exercise_spread_box12_v"] == 120000.0
    assert res["w2"]["deferred_compensation_401k_box12_d"] == 23000.0
    assert res["w2"]["health_coverage_cost_box12_dd"] == 14200.0
    assert res["w2"]["base_salary_and_bonus"] == 400000.0
    assert "Acme" in res["w2"]["employer"]


def test_parse_w2_alternate_layout():
    sample_w2 = """
    Copy B - To Be Filed With Employee's FEDERAL Tax Return
    2025 Form W-2
    c Employer:
    Global Robotics LLC
    1 Wages, tips, other compensation 380,000.00
    2 Federal income tax withheld 98,500.00
    3 Social security wages 176,100.00
    4 Social security tax withheld 10,918.20
    5 Medicare wages and tips 380,000.00
    6 Medicare tax withheld 5,510.00
    """
    res = ingest_tax_transcripts.parse_w2_text(sample_w2)
    assert res["year"] == 2025
    assert res["w2"]["wages_box1"] == 380000.0
    assert res["w2"]["federal_tax_withheld_box2"] == 98500.0
    assert res["w2"]["base_salary_and_bonus"] == 380000.0
    assert "Global Robotics" in res["w2"]["employer"]


def test_w2_upload_and_compensation_sync(monkeypatch, tmp_path):
    import io
    from app import app
    import security

    test_db = tmp_path / "test_family_office.db"
    security.init_db(test_db)
    monkeypatch.setattr("routes.helpers.DB_PATH", test_db)
    monkeypatch.setattr("routes.tax.DB_PATH", test_db)
    monkeypatch.setattr("routes.compensation.DB_PATH", test_db)
    monkeypatch.setattr("ingest_tax_transcripts.DB_PATH", test_db)

    sample_result = {
        "year": 2028,
        "doc_type": "w2",
        "w2": {
            "employer": "Vertex Technologies Inc",
            "wages_box1": 600000.0,
            "base_salary_and_bonus": 450000.0,
            "nso_exercise_spread_box12_v": 150000.0,
            "federal_tax_withheld_box2": 160000.0,
            "social_security_tax_withheld_box4": 11000.0,
            "medicare_tax_withheld_box6": 8700.0,
            "deferred_compensation_401k_box12_d": 24000.0,
        },
        "totals": {
            "w2_wages": 600000.0,
            "w2_base_salary_and_bonus": 450000.0,
            "nso_exercise_spread": 150000.0,
            "federal_tax_withheld": 160000.0,
            "social_security_withheld": 11000.0,
            "medicare_withheld": 8700.0,
            "401k_deferred_comp": 24000.0,
            "ordinary_dividends": 0.0,
            "qualified_dividends": 0.0,
            "interest_income": 0.0,
            "stock_sales_proceeds": 0.0,
            "stock_sales_basis": 0.0,
            "realized_capital_gains": 0.0,
            "mortgage_interest_paid": 0.0,
            "approx_gross_income": 600000.0,
        }
    }

    monkeypatch.setattr(ingest_tax_transcripts, "parse_transcript_pdf", lambda *args, **kwargs: sample_result)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["user"] = "testuser"
            sess["family_id"] = 1
            sess["user_family_id"] = 1
            sess["role"] = "editor"
            sess["universe"] = "public"

        from pypdf import PdfWriter
        w = PdfWriter()
        w.add_blank_page(200, 200)
        buf = io.BytesIO()
        w.write(buf)
        pdf_bytes = buf.getvalue()

        data = {
            "file": (io.BytesIO(pdf_bytes), "w2_2028.pdf"),
            "adult": "Primary Taxpayer"
        }

        resp = client.post("/api/compensation/upload_w2", data=data, content_type="multipart/form-data")
        assert resp.status_code == 200
        res = resp.get_json()
        assert res["success"] is True
        assert res["compensation_synced"] is True
        assert res["data"]["year"] == 2028

        # Verify that Career Compensation now contains the 2028 record
        resp_comp = client.get("/api/compensation")
        assert resp_comp.status_code == 200
        comp_records = resp_comp.get_json()["history"]
        rec_2028 = next((r for r in comp_records if r["year"] == 2028), None)
        assert rec_2028 is not None
        assert rec_2028["salary"] == 450000.0
        assert "Vertex Technologies" in rec_2028["company"]
