"""
account_sync/sync_outcome.py: Pure combination of per-provider sync results into one honest outcome.

`success` (data was synced for at least one provider) and `status` ("success" | "partial" | "failed") are
derived from every attempted provider, so a failing provider is never hidden by a succeeding one.
"""

from __future__ import annotations

from typing import Any, Dict, List

PROVIDER_LABELS = {"monarch": "Monarch", "simplefin": "SimpleFIN"}


def result_status(res: Dict[str, Any]) -> str:
    """Returns "success" | "partial" | "failed" for one provider result."""
    status = str(res.get("status") or "")
    if status in ("success", "partial", "failed"):
        return status
    return "success" if res.get("success") else "failed"


def combine_provider_results(results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Combines `{provider: result}` for every attempted provider; per-provider detail lives under `providers`."""
    detail: Dict[str, Dict[str, Any]] = {
        name: {
            "status": result_status(res),
            "error": res.get("error"),
            "failed_accounts": list(res.get("failed_accounts") or []),
        }
        for name, res in results.items()
    }
    statuses = [d["status"] for d in detail.values()]
    if all(s == "success" for s in statuses):
        overall = "success"
    elif all(s == "failed" for s in statuses):
        overall = "failed"
    else:
        overall = "partial"

    ok = {n: r for n, r in results.items() if detail[n]["status"] != "failed"}
    base = dict(next(iter(ok.values()))) if ok else dict(next(iter(results.values())))
    out: Dict[str, Any] = base
    out["success"] = overall != "failed"
    out["status"] = overall
    out["providers"] = detail
    out["failed_accounts"] = [a for d in detail.values() for a in d["failed_accounts"]]
    out["warnings"] = [w for r in results.values() for w in (r.get("warnings") or [])]
    if len(results) > 1:
        out["provider"] = "combined"
        out["accounts_count"] = sum(int(r.get("accounts_count", 0)) for r in ok.values())
        out["holdings_count"] = sum(int(r.get("holdings_count", 0)) for r in ok.values())
        if "simplefin" in ok:
            out["simplefin_synced"] = True
    problems: List[str] = [
        f"{PROVIDER_LABELS.get(n, n)}: {d['error']}" for n, d in detail.items() if d["error"] and d["status"] != "success"
    ]
    if len(results) > 1:
        if problems:
            out["error"] = "; ".join(problems)
        else:
            out.pop("error", None)
    return out
