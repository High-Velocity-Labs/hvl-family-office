"""
Shared Multi-Worker Rate Limiter (`hvl_common.web.rate_limit`).
Backed by SQLite `diskcache.Cache` (`disk_min_file_size = 2**31 - 1`) so rate-limit
counters are atomically shared across all Gunicorn worker processes without Redis.
"""

from __future__ import annotations

from functools import wraps
import hashlib
import logging
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

import diskcache
from flask import Blueprint, current_app, g, has_app_context, has_request_context, jsonify, request, session

from hvl_common.telemetry.store import EVENT_RATE_LIMIT, record_telemetry_event

logger = logging.getLogger(__name__)

_COMMON_ROOT = Path(__file__).resolve().parent.parent.parent
_APP_ROOT = _COMMON_ROOT.parent if _COMMON_ROOT.name == "vendor" else _COMMON_ROOT
_DEFAULT_RATELIMIT_DIR = _APP_ROOT / "data" / "ratelimit_cache"

_PERIOD_MAP: Dict[str, int] = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
}

_LIMIT_SPEC_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)?\s*([a-zA-Z]+)\s*$")

_caches_lock = threading.RLock()
_caches: Dict[str, diskcache.Cache] = {}


def _resolve_cache_dir(cache_dir: Optional[Union[str, Path]] = None) -> Path:
    if cache_dir is not None:
        return Path(cache_dir)
    if has_app_context():
        try:
            cfg_dir = current_app.config.get("RATELIMIT_CACHE_DIR")
            if cfg_dir:
                return Path(cfg_dir)
        except Exception:
            pass
    env_dir = os.getenv("HVL_RATELIMIT_CACHE_DIR") or os.getenv("RATELIMIT_CACHE_DIR")
    if env_dir:
        return Path(env_dir)
    return _DEFAULT_RATELIMIT_DIR


def _get_diskcache(cache_dir: Optional[Union[str, Path]] = None) -> diskcache.Cache:
    target = _resolve_cache_dir(cache_dir).resolve()
    key = str(target)
    with _caches_lock:
        cached = _caches.get(key)
        if cached is not None and target.exists():
            return cached
        target.mkdir(parents=True, exist_ok=True)
        cache = diskcache.Cache(
            directory=key, timeout=5.0, disk_min_file_size=2**31 - 1,
            size_limit=64 * 1024 * 1024, eviction_policy="least-recently-stored", statistics=0,
        )
        _caches[key] = cache
        return cache


def parse_rate_limits(*specs: Union[str, Iterable[str]]) -> List[Tuple[int, int, str]]:
    """
    Parses one or more rate limit strings (e.g. `"15/min"`, `"100/hr"`, `"15/min;100/hr"`)
    into a list of `(max_calls, period_seconds, canonical_label)` tuples.
    """
    raw_items: List[str] = []
    for spec in specs:
        if isinstance(spec, str):
            raw_items.extend(p.strip() for p in re.split(r"[;,]+", spec) if p.strip())
        elif isinstance(spec, Iterable):
            for item in spec:
                raw_items.extend(p.strip() for p in re.split(r"[;,]+", str(item)) if p.strip())

    parsed: List[Tuple[int, int, str]] = []
    for item in raw_items:
        match = _LIMIT_SPEC_RE.match(item)
        if not match:
            raise ValueError(f"Invalid rate limit specification: {item!r}")
        count = int(match.group(1))
        multiplier = int(match.group(2)) if match.group(2) else 1
        unit_raw = match.group(3).lower()
        base_seconds = _PERIOD_MAP.get(unit_raw)
        if base_seconds is None:
            raise ValueError(f"Unsupported rate limit unit in {item!r}")
        if count <= 0 or multiplier <= 0:
            raise ValueError(f"Rate limit count and period must be positive in {item!r}")
        parsed.append((count, base_seconds * multiplier, item))
    return parsed


def _should_bypass_rate_limit() -> bool:
    """
    Determines whether rate limiting should be bypassed in the current context.
    """
    if has_app_context():
        enabled = current_app.config.get("RATELIMIT_ENABLED")
        if enabled is False:
            return True
        if enabled is True:
            return False
        if current_app.config.get("TESTING"):
            return True
    if "PYTEST_CURRENT_TEST" in os.environ:
        return True
    return False


def _resolve_client_key(custom_key: Optional[str] = None) -> str:
    """
    Resolves and SHA-256 hashes the caller identity so raw IPs/emails are never written to disk.
    """
    if custom_key:
        raw_id = str(custom_key)
    elif has_request_context():
        raw_id = ""
        try:
            user_email = session.get("user_email")
            family_id = session.get("family_id")
            user_name = session.get("user")
            if user_email:
                raw_id = f"user:{user_email}"
            elif family_id or user_name:
                raw_id = f"fam:{family_id}:{user_name}"
        except Exception:
            raw_id = ""

        if not raw_id:
            cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
            xff = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            remote = (request.remote_addr or "").strip()
            raw_id = f"ip:{cf_ip or xff or remote or 'anon'}"
    else:
        raw_id = "ip:anon"

    return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:24]


def _record_rate_limit_telemetry(exceeded_spec: str) -> None:
    if not has_request_context():
        return
    try:
        g._hvl_ratelimit_recorded = True
        svc = str(current_app.config.get("HVL_SERVICE_NAME", "app")) if has_app_context() else "app"
        telemetry_db = current_app.config.get("TELEMETRY_DB_PATH") if has_app_context() else None
        telemetry_enabled = current_app.config.get("TELEMETRY_ENABLED") if has_app_context() else None
        from hvl_common.telemetry.middleware import is_internal_or_owner_request

        active_app = current_app._get_current_object() if has_app_context() else None
        should_record = (
            telemetry_enabled is not False
            and not is_internal_or_owner_request(active_app)
            and (
                telemetry_db is not None
                or telemetry_enabled is True
                or bool(os.getenv("HVL_TELEMETRY_DB_PATH") or os.getenv("TELEMETRY_DB_PATH"))
                or (
                    "PYTEST_CURRENT_TEST" not in os.environ
                    and not (has_app_context() and current_app.config.get("TESTING"))
                )
            )
        )
        if should_record:
            start = getattr(g, "_hvl_req_start", None)
            duration_ms = (time.perf_counter() - start) * 1000.0 if start is not None else 0.0
            record_telemetry_event(
                service=svc, event_type=EVENT_RATE_LIMIT,
                method=request.method or "GET", path=request.path or "/",
                status_code=429, duration_ms=duration_ms,
                error_type="RateLimitExceeded", detail=f"Limit {exceeded_spec} exceeded",
                db_path=telemetry_db,
            )
    except Exception as exc:
        logger.debug("Telemetry recording on rate limit skipped: %s", exc)


class RateLimiter:
    """
    Multi-worker SQLite `diskcache`-backed rate limiter for Flask routes and blueprints.
    """

    def __init__(self, app: Optional[Any] = None, *, cache_dir: Optional[Union[str, Path]] = None) -> None:
        self._explicit_cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._lock = threading.RLock()
        if app is not None:
            self.init_app(app, cache_dir=cache_dir)

    def init_app(self, app: Any, *, cache_dir: Optional[Union[str, Path]] = None) -> None:
        if cache_dir is not None:
            app.config["RATELIMIT_CACHE_DIR"] = str(cache_dir)
        elif self._explicit_cache_dir is not None:
            app.config.setdefault("RATELIMIT_CACHE_DIR", str(self._explicit_cache_dir))
        app.extensions["hvl_rate_limiter"] = self

    def evaluate(
        self,
        *limit_specs: Union[str, Iterable[str]],
        scope: Optional[str] = None,
        client_key: Optional[str] = None,
        cache_dir: Optional[Union[str, Path]] = None,
    ) -> Tuple[bool, int, str]:
        """
        Atomically checks and increments counters for all given `limit_specs`.
        Returns `(allowed, retry_after_seconds, exceeded_limit_str)`.
        """
        if _should_bypass_rate_limit():
            return True, 0, ""

        parsed_limits = parse_rate_limits(*limit_specs)
        if not parsed_limits:
            return True, 0, ""

        eff_scope = scope or ((request.endpoint or request.path or "default") if has_request_context() else "default")
        client_hash = _resolve_client_key(client_key)
        eff_cache_dir = cache_dir or self._explicit_cache_dir
        cache = _get_diskcache(eff_cache_dir)
        now = time.time()

        with self._lock:
            with cache.transact():
                bucket_keys: List[Tuple[str, int, int, str]] = []
                for max_calls, period_seconds, raw_spec in parsed_limits:
                    bucket_idx = int(now // period_seconds)
                    bucket_end = (bucket_idx + 1) * period_seconds
                    retry_after = max(1, int(math.ceil(bucket_end - now)))
                    k = f"rl:{eff_scope}:{client_hash}:{max_calls}:{period_seconds}:{bucket_idx}"
                    current_count = int(cache.get(k, 0) or 0)
                    if current_count >= max_calls:
                        return False, retry_after, raw_spec
                    bucket_keys.append((k, current_count + 1, period_seconds, raw_spec))

                for k, new_count, period_seconds, _ in bucket_keys:
                    cache.set(k, new_count, expire=period_seconds + 5)

        return True, 0, ""

    def check(
        self,
        *limit_specs: Union[str, Iterable[str]],
        scope: Optional[str] = None,
        client_key: Optional[str] = None,
        cache_dir: Optional[Union[str, Path]] = None,
    ) -> Optional[Any]:
        """
        Evaluates rate limits inside a Flask request context.
        If allowed, returns `None`.
        If exceeded, records a `RATE_LIMIT` telemetry event and returns a `(Response, 429, headers)` tuple.
        """
        allowed, retry_after, exceeded_spec = self.evaluate(
            *limit_specs, scope=scope, client_key=client_key, cache_dir=cache_dir,
        )
        if allowed:
            return None

        _record_rate_limit_telemetry(exceeded_spec)
        return (
            jsonify({
                "success": False,
                "error": "Rate limit exceeded. Please try again later.",
                "retry_after": retry_after,
            }),
            429,
            {"Retry-After": str(retry_after)},
        )

    def limit(
        self,
        *limit_specs: Union[str, Iterable[str]],
        scope: Optional[str] = None,
        methods: Optional[Iterable[str]] = None,
    ) -> Callable[[Any], Any]:
        """
        Decorator that applies one or more rate limits to a Flask view function or Blueprint.
        """
        if not parse_rate_limits(*limit_specs):
            raise ValueError("At least one rate limit specification is required.")
        allowed_methods = {m.upper() for m in methods} if methods is not None else None

        def decorator(target: Any) -> Any:
            if isinstance(target, Blueprint):
                self.limit_blueprint(target, *limit_specs, scope=scope, methods=allowed_methods)
                return target

            func_scope = scope or f"{getattr(target, '__module__', '')}.{getattr(target, '__qualname__', getattr(target, '__name__', 'view'))}"

            @wraps(target)
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                if allowed_methods is not None and has_request_context() and (request.method or "GET").upper() not in allowed_methods:
                    return target(*args, **kwargs)
                rejection = self.check(*limit_specs, scope=func_scope)
                if rejection is not None:
                    return rejection
                return target(*args, **kwargs)

            return wrapped

        return decorator

    def limit_blueprint(
        self,
        blueprint: Blueprint,
        *limit_specs: Union[str, Iterable[str]],
        scope: Optional[str] = None,
        methods: Optional[Iterable[str]] = None,
    ) -> Blueprint:
        """
        Registers a `before_request` rate limit check on a Flask `Blueprint`.
        """
        parse_rate_limits(*limit_specs)
        allowed_methods = {m.upper() for m in methods} if methods is not None else None
        bp_scope = scope or f"bp:{blueprint.name}"

        @blueprint.before_request
        def _bp_rate_limit_check() -> Optional[Any]:
            if allowed_methods is not None and (request.method or "GET").upper() not in allowed_methods:
                return None
            return self.check(*limit_specs, scope=bp_scope)

        return blueprint

    def reset(self, cache_dir: Optional[Union[str, Path]] = None) -> None:
        """Clears all rate-limit counters in the underlying `diskcache.Cache`."""
        eff_dir = cache_dir or self._explicit_cache_dir
        cache = _get_diskcache(eff_dir)
        with self._lock:
            cache.clear()


_default_limiter = RateLimiter()


def rate_limit(
    *limit_specs: Union[str, Iterable[str]],
    scope: Optional[str] = None,
    methods: Optional[Iterable[str]] = None,
) -> Callable[[Any], Any]:
    """Convenience decorator applying shared multi-worker rate limits to a Flask view or Blueprint."""
    return _default_limiter.limit(*limit_specs, scope=scope, methods=methods)


def reset_rate_limits(cache_dir: Optional[Union[str, Path]] = None) -> None:
    """Clears all rate-limit counters in the active or specified `cache_dir`."""
    if (time.time() % 60) > 54.0:
        time.sleep(60.1 - (time.time() % 60))
    _default_limiter.reset(cache_dir=cache_dir)
