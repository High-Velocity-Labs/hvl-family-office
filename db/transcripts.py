"""
db/transcripts.py: Normalized SQLAlchemy 2.0 ORM repository for IRS tax transcripts and safe-harbor summaries.
Operates on `TaxTranscriptRecord` and `TaxTranscriptMeta` with transparent `TypeDecorator` encryption
and automatic `after_commit` cache invalidation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, func, select

import config
from db.models import TaxTranscriptMeta, TaxTranscriptRecord
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def count_transcript_records(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Returns the count of `tax_transcript_records` rows for `family_id`."""
    if not family_id:
        return 0
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return 0
    try:
        with get_orm_session(path, family_id=family_id) as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(TaxTranscriptRecord)
                    .where(TaxTranscriptRecord.family_id == family_id)
                )
                or 0
            )
    except Exception:
        return 0


def get_transcripts_payload(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Reconstructs the family's tax transcript dictionary from normalized relational rows
    in `tax_transcript_records` and `tax_transcript_meta`.
    """
    if not family_id:
        return {}
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return {}

    try:
        with get_orm_session(path, family_id=family_id) as session:
            meta_row = session.get(TaxTranscriptMeta, family_id)
            rows = session.scalars(
                select(TaxTranscriptRecord)
                .where(TaxTranscriptRecord.family_id == family_id)
                .order_by(
                    TaxTranscriptRecord.tax_year.desc(),
                    TaxTranscriptRecord.record_id.asc(),
                )
            ).all()
            if not meta_row and not rows:
                return {}

            out: Dict[str, Any] = {
                "historical_summary": {},
                "transcripts_by_year": {},
                "transcripts_by_adult": {},
            }

            if meta_row is not None:
                if isinstance(meta_row.adults_enc, list):
                    out["adults"] = meta_row.adults_enc
                if isinstance(meta_row.available_years_enc, list):
                    out["available_years"] = meta_row.available_years_enc
                if meta_row.latest_tax_year is not None:
                    out["latest_tax_year"] = int(meta_row.latest_tax_year)
                if meta_row.safe_harbor_2026_target_enc not in ("", None, "None"):
                    try:
                        out["safe_harbor_2026_target"] = float(
                            meta_row.safe_harbor_2026_target_enc
                        )
                    except (ValueError, TypeError):
                        pass

            for r in rows:
                yr_str = str(r.tax_year)
                rtype = str(r.record_type or "summary")
                payload = r.payload_enc if isinstance(r.payload_enc, dict) else {}
                if not payload:
                    continue

                if rtype == "summary":
                    out["historical_summary"][yr_str] = dict(payload)
                elif rtype == "full_transcript":
                    out["transcripts_by_year"][yr_str] = dict(payload)
                elif rtype == "adult_summary":
                    adult_name = str(r.taxpayer_name_enc or "Primary Earner")
                    out["transcripts_by_adult"].setdefault(adult_name, {})[yr_str] = (
                        dict(payload)
                    )

            if "available_years" not in out and out["historical_summary"]:
                out["available_years"] = sorted(
                    [
                        int(y)
                        for y in out["historical_summary"].keys()
                        if str(y).isdigit()
                    ]
                )
            return out
    except Exception as e:
        logger.warning(
            "Error reading tax_transcript_records for family %s: %s", family_id, e
        )
        return {}


def _build_transcript_record(
    family_id: int,
    tax_year: int,
    record_type: str,
    taxpayer_name: str,
    item: Dict[str, Any],
) -> TaxTranscriptRecord:
    totals = item.get("totals", item) if isinstance(item.get("totals"), dict) else item
    w2_wages = float(
        totals.get("w2_wages")
        or totals.get("w2_wages_and_bonus")
        or totals.get("combined_w2_income")
        or 0.0
    )
    fed_tax = float(totals.get("federal_tax_withheld", 0.0) or 0.0)
    ss_tax = float(totals.get("social_security_withheld", 0.0) or 0.0)
    med_tax = float(
        totals.get("medicare_tax_withheld") or totals.get("medicare_withheld") or 0.0
    )
    mort_int = float(totals.get("mortgage_interest_paid", 0.0) or 0.0)
    qual_div = float(totals.get("qualified_dividends", 0.0) or 0.0)
    cap_gains = float(totals.get("realized_capital_gains", 0.0) or 0.0)
    sh_target = item.get("safe_harbor_110_target")
    sh_str = str(sh_target) if sh_target is not None else ""

    return TaxTranscriptRecord(
        family_id=family_id, tax_year=int(tax_year), record_type=record_type,
        taxpayer_name_enc=taxpayer_name, w2_wages_enc=w2_wages,
        federal_tax_withheld_enc=fed_tax, social_security_withheld_enc=ss_tax,
        medicare_tax_withheld_enc=med_tax, mortgage_interest_paid_enc=mort_int,
        qualified_dividends_enc=qual_div, realized_capital_gains_enc=cap_gains,
        safe_harbor_target_enc=sh_str, payload_enc=item,
    )


def save_transcripts_payload(
    family_id: int = 0,
    payload: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Atomically persists a family's tax transcript dictionary into normalized relational rows."""
    if not family_id or not isinstance(payload, dict):
        return

    adults = payload.get("adults")
    avail_years = payload.get("available_years")
    latest_yr = payload.get("latest_tax_year")
    sh_2026 = payload.get("safe_harbor_2026_target")

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        max_transcripts = int(getattr(config, "MAX_TAX_TRANSCRIPTS", 100))
        existing_rows = session.scalars(
            select(TaxTranscriptRecord).where(TaxTranscriptRecord.family_id == family_id)
        ).all()
        existing_count = len(existing_rows)
        existing_years = {
            int(r.tax_year) for r in existing_rows if r.tax_year is not None
        }

        new_records: List[TaxTranscriptRecord] = []
        hist = payload.get("historical_summary") or {}
        if isinstance(hist, dict):
            for yr_str, sdict in hist.items():
                if str(yr_str).isdigit() and isinstance(sdict, dict):
                    new_records.append(_build_transcript_record(family_id, int(yr_str), "summary", "Combined Household", sdict))

        by_yr = payload.get("transcripts_by_year") or {}
        if isinstance(by_yr, dict):
            for yr_str, tdict in by_yr.items():
                if str(yr_str).isdigit() and isinstance(tdict, dict):
                    new_records.append(_build_transcript_record(family_id, int(yr_str), "full_transcript", "Combined Household", tdict))

        by_adult = payload.get("transcripts_by_adult") or {}
        if isinstance(by_adult, dict):
            for adult_name, years_map in by_adult.items():
                if isinstance(years_map, dict):
                    for yr_str, adict in years_map.items():
                        if str(yr_str).isdigit() and isinstance(adict, dict):
                            new_records.append(_build_transcript_record(family_id, int(yr_str), "adult_summary", str(adult_name), adict))

        new_years = {int(r.tax_year) for r in new_records if r.tax_year is not None}
        is_adding_new = (
            bool(new_years - existing_years) or len(new_records) > existing_count
        )
        if is_adding_new and existing_count >= max_transcripts:
            raise ValueError(
                f"Maximum of {max_transcripts} tax transcript records per household reached."
            )

        session.execute(
            delete(TaxTranscriptRecord).where(
                TaxTranscriptRecord.family_id == family_id
            )
        )
        session.merge(
            TaxTranscriptMeta(
                family_id=family_id,
                adults_enc=adults if adults is not None else "",
                available_years_enc=avail_years if avail_years is not None else "",
                latest_tax_year=(
                    int(latest_yr)
                    if latest_yr is not None and str(latest_yr).isdigit()
                    else None
                ),
                safe_harbor_2026_target_enc=(
                    str(sh_2026) if sh_2026 is not None else ""
                ),
            )
        )
        if new_records:
            session.add_all(new_records)


def upsert_adult_year_summary(
    family_id: int = 0,
    adult_name: str = "",
    tax_year: int = 0,
    summary_dict: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Atomically upserts an adult taxpayer's summary row for a single tax year."""
    if (
        not family_id
        or not adult_name
        or not tax_year
        or not isinstance(summary_dict, dict)
    ):
        return

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        existing_rows = session.scalars(
            select(TaxTranscriptRecord).where(
                TaxTranscriptRecord.family_id == family_id,
                TaxTranscriptRecord.tax_year == int(tax_year),
                TaxTranscriptRecord.record_type == "adult_summary",
            )
        ).all()
        matched_existing = False
        for r in existing_rows:
            if r.taxpayer_name_enc == adult_name:
                session.delete(r)
                matched_existing = True

        if not matched_existing:
            max_transcripts = int(getattr(config, "MAX_TAX_TRANSCRIPTS", 100))
            total_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(TaxTranscriptRecord)
                    .where(TaxTranscriptRecord.family_id == family_id)
                )
                or 0
            )
            adult_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(TaxTranscriptRecord)
                    .where(
                        TaxTranscriptRecord.family_id == family_id,
                        TaxTranscriptRecord.record_type == "adult_summary",
                    )
                )
                or 0
            )
            has_year_transcript = (
                session.scalars(
                    select(TaxTranscriptRecord).where(
                        TaxTranscriptRecord.family_id == family_id,
                        TaxTranscriptRecord.tax_year == int(tax_year),
                        TaxTranscriptRecord.record_type != "adult_summary",
                    )
                ).first()
                is not None
            )
            if adult_count >= max_transcripts or (
                total_count >= max_transcripts and not has_year_transcript
            ):
                raise ValueError(
                    f"Maximum of {max_transcripts} tax transcript records per household reached."
                )

        session.add(
            _build_transcript_record(
                family_id, int(tax_year), "adult_summary", adult_name, summary_dict
            )
        )


def upsert_transcript_record(
    family_id: int = 0,
    tax_year: int = 2026,
    record_type: str = "summary",
    taxpayer_name: str = "Combined Household",
    payload: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Upserts a single `TaxTranscriptRecord` row, enforcing `MAX_TAX_TRANSCRIPTS` on net-new insertions."""
    if not family_id or not tax_year:
        return 0

    item = payload if isinstance(payload, dict) else {}
    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        existing_rows = session.scalars(
            select(TaxTranscriptRecord).where(
                TaxTranscriptRecord.family_id == family_id,
                TaxTranscriptRecord.tax_year == int(tax_year),
                TaxTranscriptRecord.record_type == str(record_type or "summary"),
            )
        ).all()
        matched_existing = False
        for r in existing_rows:
            if (r.taxpayer_name_enc or "") == taxpayer_name:
                session.delete(r)
                matched_existing = True

        if not matched_existing:
            max_transcripts = int(getattr(config, "MAX_TAX_TRANSCRIPTS", 100))
            total_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(TaxTranscriptRecord)
                    .where(TaxTranscriptRecord.family_id == family_id)
                )
                or 0
            )
            if total_count >= max_transcripts:
                raise ValueError(
                    f"Maximum of {max_transcripts} tax transcript records per household reached."
                )

        rec = _build_transcript_record(
            family_id,
            int(tax_year),
            str(record_type or "summary"),
            taxpayer_name,
            item,
        )
        session.add(rec)
        session.flush()
        return int(rec.record_id or 0)


save_transcript_record = upsert_transcript_record
