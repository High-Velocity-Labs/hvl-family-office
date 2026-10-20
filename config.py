"""
Application Configuration and Shared Path References.
Centralizes environment variables, directory paths, and database references
to eliminate circular dependencies.
"""

from __future__ import annotations
import os
import secrets
import sys
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
_VENDOR_DIR = BASE_DIR / "vendor"
if _VENDOR_DIR.exists():
    _v_str = str(_VENDOR_DIR)
    if _v_str in sys.path:
        sys.path.remove(_v_str)
    sys.path.insert(0, _v_str)

APP_VERSION = os.getenv("APP_VERSION", "0.5.1").strip() or "0.5.1"
GITHUB_REPO_SLUG = os.getenv("GITHUB_REPO_SLUG", "High-Velocity-Labs/hvl-family-office").strip()



def is_local_mode() -> bool:
    """
    Returns True when running in Local Desktop / Standalone Mode
    (`LOCAL_MODE=1`, `FAMILY_OFFICE_LOCAL=1`, or `STANDALONE_MODE=1`).
    """
    for env_key in ("LOCAL_MODE", "FAMILY_OFFICE_LOCAL", "STANDALONE_MODE"):
        val = os.getenv(env_key, "").strip().lower()
        if val in ("1", "true", "yes", "on"):
            return True
    return False


def is_standalone_mode() -> bool:
    """Alias for `is_local_mode()` for backward compatibility."""
    return is_local_mode()


VALID_UNIVERSES = ("public", "demo", "sandbox", "test")

_LEGACY_DB_MOVES = (
    ("global.db", "public/global.db"), ("family_office.db", "public/family_office.db"), ("family_office_cache.db", "public/family_office_cache.db"),
    ("global_beta.db", "demo/global.db"), ("family_office_beta.db", "demo/family_office.db"), ("family_office_beta_cache.db", "demo/family_office_cache.db"),
    ("global_sandbox.db", "sandbox/global.db"), ("family_office_sandbox.db", "sandbox/family_office.db"), ("cache_sandbox.db", "sandbox/family_office_cache.db"),
    ("global_test.db", "test/global.db"), ("family_office_test.db", "test/family_office.db"), ("family_office_test_cache.db", "test/family_office_cache.db"),
)
_LEGACY_DIR_MOVES = (("families", "public/families"), ("families_beta", "demo/families"), ("families_sandbox", "sandbox/families"), ("families_test", "test/families"))


def migrate_legacy_data_layout(data_dir: Path) -> None:
    """Idempotently migrates legacy flat DB files and `families_*` folders into `data/{universe}/`."""
    if not data_dir.exists():
        return
    for src_rel, dst_rel in _LEGACY_DB_MOVES:
        src_db, dst_db = data_dir / src_rel, data_dir / dst_rel
        if src_db.exists():
            dst_db.parent.mkdir(parents=True, exist_ok=True)
            if not dst_db.exists():
                src_db.replace(dst_db)
                for sfx in ("-wal", "-shm"):
                    if Path(f"{src_db}{sfx}").exists():
                        Path(f"{src_db}{sfx}").replace(Path(f"{dst_db}{sfx}"))
            else:
                for sfx in ("", "-wal", "-shm"):
                    Path(f"{src_db}{sfx}").unlink(missing_ok=True)
    for src_rel, dst_rel in _LEGACY_DIR_MOVES:
        src_dir, dst_dir = data_dir / src_rel, data_dir / dst_rel
        if src_dir.exists() and src_dir.is_dir():
            dst_dir.mkdir(parents=True, exist_ok=True)
            for item in list(src_dir.iterdir()):
                if not (dst_dir / item.name).exists():
                    item.replace(dst_dir / item.name)
                elif item.is_file():
                    item.unlink(missing_ok=True)
            try:
                src_dir.rmdir()
            except OSError:
                pass
    for dev_file in list(data_dir.glob("*_dev*.db*")) + (list((data_dir / "families_dev").iterdir()) if (data_dir / "families_dev").is_dir() else []):
        if dev_file.is_file():
            dev_file.unlink(missing_ok=True)
    if (data_dir / "families_dev").is_dir():
        try:
            (data_dir / "families_dev").rmdir()
        except OSError:
            pass


def get_data_dir() -> Path:
    """
    Resolves the active base data directory:
    1. `FAMILY_OFFICE_DATA_DIR` environment override if set (always set by `desktop_app.py`)
    2. OS user application data directory when running as a frozen PyInstaller desktop bundle
    3. Default `BASE_DIR / "data"`
    Automatically migrates any legacy flat files into `data/{universe}/`.
    """
    override = os.getenv("FAMILY_OFFICE_DATA_DIR", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        migrate_legacy_data_layout(p)
        return p
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            local_app_data = os.getenv("LOCALAPPDATA", "").strip()
            base = Path(local_app_data) if local_app_data else (Path.home() / "AppData" / "Local")
            new_dir = base / "HVLFamilyOffice"
            legacy_dir = base / "AIFamilyOffice"
            p = legacy_dir if (not new_dir.exists() and legacy_dir.exists()) else new_dir
        elif sys.platform == "darwin":
            app_support = Path.home() / "Library" / "Application Support"
            new_dir = app_support / "HVLFamilyOffice"
            legacy_dir = app_support / "AIFamilyOffice"
            p = legacy_dir if (not new_dir.exists() and legacy_dir.exists()) else new_dir
        else:
            xdg = os.getenv("XDG_DATA_HOME", "").strip()
            base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
            new_dir = base / "hvl-family-office"
            legacy_dir = base / "ai-family-office"
            p = legacy_dir if (not new_dir.exists() and legacy_dir.exists()) else new_dir
        p.mkdir(parents=True, exist_ok=True)
        migrate_legacy_data_layout(p)
        return p
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    migrate_legacy_data_layout(DATA_DIR)
    return DATA_DIR


DATA_DIR = BASE_DIR / "data"


def normalize_universe(universe: str | None = None) -> str:
    """Normalizes universe name ('public', 'demo', 'sandbox', 'test'), mapping legacy 'beta' to 'demo'."""
    raw = (universe or os.getenv("APP_UNIVERSE", "public") or "public").strip().lower()
    if raw == "beta":
        return "demo"
    if raw in VALID_UNIVERSES:
        return raw
    return "public"


APP_UNIVERSE = normalize_universe(os.getenv("APP_UNIVERSE", "public"))


def get_universe_dir(universe: str | None = None) -> Path:
    """Resolves the isolated universe subdirectory (`data/public`, `data/demo`, `data/sandbox`, `data/test`)."""
    u = normalize_universe(universe)
    base_dir = get_data_dir()
    migrate_legacy_data_layout(base_dir)
    u_dir = base_dir / u
    u_dir.mkdir(parents=True, exist_ok=True)
    return u_dir


def get_db_path_for_universe(universe: str | None = None) -> Path:
    """Resolves monolithic SQLite database path inside the universe directory (`data/{universe}/family_office.db`)."""
    return get_universe_dir(universe) / "family_office.db"


def get_global_db_path(universe: str | None = None) -> Path:
    """Resolves SQLite global/auth database path inside the universe directory (`data/{universe}/global.db`)."""
    return get_universe_dir(universe) / "global.db"


def get_family_db_path(family_id: int | str, universe: str | None = None) -> Path:
    """Resolves dedicated SQLite database path for a given family_id and universe (`data/{universe}/families/{id}.db`)."""
    fid = int(family_id)
    fam_dir = get_universe_dir(universe) / "families"
    fam_dir.mkdir(parents=True, exist_ok=True)
    return fam_dir / f"{fid}.db"


def get_cache_db_path_for_universe(universe: str | None = None, family_id: int | str | None = None) -> Path:
    """Resolves dedicated L2 SQLite cache & job database path inside the universe directory."""
    u_dir = get_universe_dir(universe)
    if family_id is not None and int(family_id) > 0:
        fid = int(family_id)
        fam_dir = u_dir / "families"
        fam_dir.mkdir(parents=True, exist_ok=True)
        return fam_dir / f"{fid}_cache.db"
    return u_dir / "family_office_cache.db"


DB_PATH = get_db_path_for_universe(APP_UNIVERSE)
CACHE_DB_PATH = get_cache_db_path_for_universe(APP_UNIVERSE)

STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

def _resolve_flask_secret_key() -> str:
    env_key = os.getenv("FLASK_SECRET_KEY", "").strip()
    if env_key:
        return env_key
    if is_local_mode():
        try:
            data_dir = get_data_dir()
            secret_file = data_dir / ".flask_secret"
            if secret_file.exists():
                k = secret_file.read_text(encoding="utf-8").strip()
                if len(k) >= 32:
                    return k
            new_key = secrets.token_hex(32)
            secret_file.write_text(new_key, encoding="utf-8")
            return new_key
        except Exception:
            pass
    return secrets.token_hex(32)


FLASK_SECRET_KEY = _resolve_flask_secret_key()
PERMANENT_SESSION_LIFETIME = timedelta(days=30)

# AI Advisor & Conversational Multi-Turn Tuning
AI_ADVISOR_MAX_TURNS = int(os.getenv("AI_ADVISOR_MAX_TURNS", "8"))
AI_ADVISOR_MAX_INPUT_CHARS = int(os.getenv("AI_ADVISOR_MAX_INPUT_CHARS", "2000"))
AI_ADVISOR_BYO_MAX_INPUT_CHARS = int(os.getenv("AI_ADVISOR_BYO_MAX_INPUT_CHARS", "8000"))
AI_ADVISOR_MAX_HISTORY_CHARS = int(os.getenv("AI_ADVISOR_MAX_HISTORY_CHARS", "2500"))
AI_ADVISOR_SHARED_RATE_LIMITS = tuple(
    s.strip()
    for s in os.getenv("AI_ADVISOR_SHARED_RATE_LIMITS", "5/min,30/hr").split(",")
    if s.strip()
)
AI_ADVISOR_BYO_RATE_LIMITS = tuple(
    s.strip()
    for s in os.getenv("AI_ADVISOR_BYO_RATE_LIMITS", "30/min,300/hr").split(",")
    if s.strip()
)

# Per-Household Resource Guardrails
MAX_HOUSEHOLD_MEMBERS = int(os.getenv("MAX_HOUSEHOLD_MEMBERS", "20"))
MAX_HOUSEHOLD_ACCOUNTS = int(os.getenv("MAX_HOUSEHOLD_ACCOUNTS", "1000"))
MAX_HOUSEHOLD_HOLDINGS = int(os.getenv("MAX_HOUSEHOLD_HOLDINGS", "5000"))
MAX_SCENARIOS = int(os.getenv("MAX_SCENARIOS", "25"))
MAX_SCENARIO_DEPTH = int(os.getenv("MAX_SCENARIO_DEPTH", "3"))
MAX_CHILD_SCENARIOS_PER_PARENT = int(os.getenv("MAX_CHILD_SCENARIOS_PER_PARENT", "10"))
MAX_FORECAST_EVENTS = int(os.getenv("MAX_FORECAST_EVENTS", "100"))
MAX_GIFT_RECIPIENTS = int(os.getenv("MAX_GIFT_RECIPIENTS", "50"))
MAX_GIFT_RECORDS = int(os.getenv("MAX_GIFT_RECORDS", "1000"))
MAX_EQUITY_COMPANIES = int(os.getenv("MAX_EQUITY_COMPANIES", "20"))
MAX_EQUITY_GRANTS = int(os.getenv("MAX_EQUITY_GRANTS", "200"))
MAX_FMV_RECORDS_PER_COMPANY = int(os.getenv("MAX_FMV_RECORDS_PER_COMPANY", "200"))
MAX_PHILANTHROPY_YEARS = int(os.getenv("MAX_PHILANTHROPY_YEARS", "50"))
MAX_PHILANTHROPY_DONATIONS = int(os.getenv("MAX_PHILANTHROPY_DONATIONS", "1000"))
MAX_COMPENSATION_RECORDS = int(os.getenv("MAX_COMPENSATION_RECORDS", "200"))
MAX_TUITION_YEARS = int(os.getenv("MAX_TUITION_YEARS", "50"))
MAX_TUITION_RECORDS = int(os.getenv("MAX_TUITION_RECORDS", "500"))
MAX_TAX_TRANSCRIPTS = int(os.getenv("MAX_TAX_TRANSCRIPTS", "100"))
MAX_ADVISOR_CONVERSATIONS = int(os.getenv("MAX_ADVISOR_CONVERSATIONS", "50"))
MAX_ADVISOR_MESSAGES_PER_CONV = int(os.getenv("MAX_ADVISOR_MESSAGES_PER_CONV", "200"))
MAX_ACTIVE_INVITES_PER_FAMILY = int(os.getenv("MAX_ACTIVE_INVITES_PER_FAMILY", "25"))


def _get_custom_household_gemini_key(family_id: int = 0, db_path: Path | None = None) -> str:
    """Returns the household's custom encrypted `gemini_api_key` if configured, or `""`."""
    if family_id and family_id > 0:
        try:
            import security

            target_db = Path(db_path) if db_path is not None else get_family_db_path(family_id)
            if target_db.exists():
                creds = security.db_load_encrypted(target_db, "ai_credentials", family_id=family_id)
                if isinstance(creds, dict):
                    custom_key = str(creds.get("gemini_api_key") or "").strip()
                    if custom_key:
                        return custom_key
        except Exception:
            pass
    return ""


def has_custom_household_gemini_key(family_id: int = 0, db_path: Path | None = None) -> bool:
    """Returns True if the household has configured its own BYO `GEMINI_API_KEY`."""
    return bool(_get_custom_household_gemini_key(family_id=family_id, db_path=db_path))


def get_household_gemini_api_key(family_id: int = 0, db_path: Path | None = None) -> str:
    """
    Resolves the Google Gemini API key for the given household:
    1. If `family_id > 0`, checks the household's encrypted `"ai_credentials"` setting in the family DB.
    2. Falls back to `os.getenv("GEMINI_API_KEY", "").strip()`.
    """
    custom_key = _get_custom_household_gemini_key(family_id=family_id, db_path=db_path)
    if custom_key:
        return custom_key
    return os.getenv("GEMINI_API_KEY", "").strip()


def get_household_ai_limits(family_id: int = 0, db_path: Path | None = None) -> dict[str, object]:
    """
    Returns the active AI Advisor rate-limit and prompt-length policy for the household:
    - Standalone Local Desktop (`is_local_mode() == True`) or BYO Key (`has_custom_key == True`):
      Higher rate limits (`30/min, 300/hr`) and `8,000` char prompt ceiling.
    - Shared Server Default Key (`tier == "shared"`):
      Stricter rate limits (`5/min, 30/hr`) and `2,000` char prompt ceiling to protect shared quota.
    """
    local_mode = is_local_mode()
    has_custom = has_custom_household_gemini_key(family_id=family_id, db_path=db_path)
    if local_mode:
        tier = "local"
        limits = AI_ADVISOR_BYO_RATE_LIMITS
        max_chars = AI_ADVISOR_BYO_MAX_INPUT_CHARS
    elif has_custom:
        tier = "byo"
        limits = AI_ADVISOR_BYO_RATE_LIMITS
        max_chars = AI_ADVISOR_BYO_MAX_INPUT_CHARS
    else:
        tier = "shared"
        limits = AI_ADVISOR_SHARED_RATE_LIMITS
        max_chars = AI_ADVISOR_MAX_INPUT_CHARS

    return {
        "tier": tier,
        "has_custom_key": has_custom,
        "is_local_mode": local_mode,
        "rate_limits": limits,
        "rate_limit_label": " · ".join(limits),
        "max_input_chars": int(max_chars),
        "shared_rate_limit_label": " · ".join(AI_ADVISOR_SHARED_RATE_LIMITS),
        "byo_rate_limit_label": " · ".join(AI_ADVISOR_BYO_RATE_LIMITS),
        "shared_max_input_chars": int(AI_ADVISOR_MAX_INPUT_CHARS),
        "byo_max_input_chars": int(AI_ADVISOR_BYO_MAX_INPUT_CHARS),
    }


def get_site_admin_emails(db_path: Path | None = None) -> set[str]:
    """Returns lowercase site admin emails (`ADMIN_EMAIL` env var or Family 1 primary/editor)."""
    raw_env = os.getenv("ADMIN_EMAIL", os.getenv("HVL_ADMIN_EMAIL", ""))
    emails = {e.strip().lower() for e in raw_env.split(",") if e.strip()}
    if emails:
        return emails
    try:
        import security
        target = Path(db_path) if db_path is not None else get_global_db_path()
        if target.exists():
            for m in security.get_family_members(target, family_id=1) or []:
                em, role, rel = str(m.get("email") or "").strip().lower(), str(m.get("role") or "").strip().lower(), str(m.get("relationship") or "").strip().lower()
                if em and (rel == "primary" or role in ("admin", "editor")):
                    emails.add(em)
    except Exception:
        pass
    return emails


def is_site_admin_email(email: str | None, db_path: Path | None = None) -> bool:
    """Returns True if `email` belongs to the site administrator (`ADMIN_EMAIL` or Family 1 primary/editor)."""
    clean = (email or "").strip().lower()
    if not clean:
        return False
    if clean in get_site_admin_emails(db_path=db_path):
        return True
    from security_members import is_family_1_admin_email_hash
    return is_family_1_admin_email_hash(Path(db_path) if db_path is not None else get_global_db_path(), clean)


def is_beta_instance() -> bool:
    """Returns True when running as the isolated staging/beta deployment (`finances-beta`)."""
    if os.getenv("HVL_BETA_INSTANCE", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    try:
        from flask import has_request_context, request
        if has_request_context():
            host = (request.host or "").split(":", 1)[0].strip().lower()
            if host.startswith("finances-beta."):
                return True
    except Exception:
        pass
    return False


def get_admin_gate_secret_keys() -> list[str]:
    """Returns candidate secret keys used to sign/verify cross-subdomain `hvl_beta_admin` gate cookies."""
    keys: list[str] = []
    for k in (os.getenv("HVL_ADMIN_GATE_SECRET", "").strip(), os.getenv("APP_ENCRYPTION_KEY", "").strip(), os.getenv("FLASK_SECRET_KEY", "").strip(), FLASK_SECRET_KEY):
        if k and k not in keys:
            keys.append(k)
    return keys


def get_vault_cookie_name() -> str:
    """Returns instance-scoped vault FEK cookie name ('hvl_vault_fek_beta' on beta, 'hvl_vault_fek' on prod)."""
    return "hvl_vault_fek_beta" if is_beta_instance() else "hvl_vault_fek"


def get_vault_appdata_filename() -> str:
    """Returns instance-scoped Google Drive appDataFolder vault key filename."""
    return os.getenv("VAULT_APPDATA_FILENAME", "").strip() or ("hvl_vault_key_beta.json" if is_beta_instance() else "hvl_vault_key.json")
