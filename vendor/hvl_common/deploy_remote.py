"""
Remote SSH command construction, beta isolation, file permission hardening,
service restart, and post-deploy health check helpers for `hvl_common.deploy`.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Callable
from urllib.parse import urlparse

from hvl_common.deploy_manifest import SHARED_LANDING_SYMLINK_ASSETS


def stop_beta_service(
    remote_user: str,
    remote_host: str,
    beta_service_name: str,
    *,
    run_fn: Callable[..., Any] = subprocess.run,
) -> None:
    """Stops a remote staging/beta systemd service and reclaims server memory."""
    print("=" * 65)
    print(f"[CLEANUP] Stopping staging service '{beta_service_name}' on {remote_host}...")
    print("=" * 65)
    stop_cmd = (
        f"ssh {remote_user}@{remote_host} "
        f"'systemctl stop {beta_service_name} 2>/dev/null || true; "
        f"systemctl reset-failed {beta_service_name} 2>/dev/null || true; "
        f"systemctl is-active {beta_service_name} || true; "
        f"free -h'"
    )
    run_fn(stop_cmd, shell=True)
    print(f"[CLEANUP] Staging service '{beta_service_name}' stopped. Memory reclaimed!")


def build_remote_post_deploy_commands(
    *,
    cfg: dict[str, Any],
    service_name: str,
    base_service_name: str,
    remote_path: str,
    base_remote_path: str,
    admin_remote_path: str | None,
    is_beta: bool,
    sync_prod_db: bool,
    force: bool,
    changed_files: list[str],
    admin_files: list[str],
    vendor_files: list[str],
    public_commit_sha: str = "",
) -> list[str]:
    """Constructs the post-transfer remote shell commands with hardened permissions and beta isolation."""
    is_dual_target = bool(admin_remote_path)
    target_paths = f"{remote_path} {admin_remote_path}" if is_dual_target else remote_path
    cmd_parts = [
        f"find {target_paths} -name '._*' -delete 2>/dev/null || true",
        f"mkdir -p {remote_path}/data",
    ]
    if public_commit_sha:
        cmd_parts.append(f"echo '{public_commit_sha}' > {remote_path}/.public_commit_sha")

    if is_beta and base_service_name == "finances":
        cmd_parts.append(f"ln -sfn {base_remote_path}/venv {remote_path}/venv")
        cmd_parts.append(
            f"mkdir -p {remote_path}/data/beta/families "
            f"{remote_path}/data/public/families "
            f"{remote_path}/data/demo/families "
            f"{remote_path}/data/sandbox/families"
        )
        cmd_parts.append(
            f"if [ ! -f {remote_path}/.env ]; then "
            f"umask 077 && printf 'HVL_BETA_INSTANCE=1\\nHVL_TELEMETRY_SERVICE=finances-beta\\n' > {remote_path}/.env && "
            f"chmod 640 {remote_path}/.env; fi"
        )
        if sync_prod_db:
            cmd_parts.append(
                f"if [ -f {base_remote_path}/data/public/global.db ]; then "
                f"sqlite3 {base_remote_path}/data/public/global.db '.backup '{remote_path}/data/public/global.db; fi && "
                f"if [ -d {base_remote_path}/data/public/families ]; then "
                f"(cd {base_remote_path}/data/public/families && find . -maxdepth 1 -name '*.db' ! -name '*_cache.db' "
                f"-exec sqlite3 {{}} '.backup {remote_path}/data/public/families/{{}}' \\;); fi"
            )

    cmd_parts.extend([
        f"chown -R deploy:www-data {target_paths}",
        f"chmod -R u=rwX,g=rX,o= {target_paths}",
        f"if [ -f {remote_path}/.env ]; then chmod 640 {remote_path}/.env; fi",
    ])
    if (not is_beta) and (force or "requirements.txt" in changed_files):
        cmd_parts.append(
            f"if [ -x {remote_path}/venv/bin/pip ] && [ -f {remote_path}/requirements.txt ]; then "
            f"{remote_path}/venv/bin/pip install -q -r {remote_path}/requirements.txt >/dev/null; fi"
        )
    cmd_parts.append(
        f"if [ -x {remote_path}/venv/bin/pip ] && [ -d {remote_path}/vendor ]; then "
        f"{remote_path}/venv/bin/pip install --no-deps --force-reinstall {remote_path}/vendor >/dev/null; fi"
    )
    if is_dual_target:
        cmd_parts.append(
            f"if [ -d {remote_path}/vendor ]; then cp -a {remote_path}/vendor {admin_remote_path}/ 2>/dev/null || true; fi"
        )
        cmd_parts.append(
            f"if [ -x {admin_remote_path}/venv/bin/pip ] && [ -d {admin_remote_path}/vendor ]; then "
            f"{admin_remote_path}/venv/bin/pip install --no-deps --force-reinstall {admin_remote_path}/vendor >/dev/null; fi"
        )
    elif service_name == "ff":
        cmd_parts.append(
            f'if [ -x {remote_path}/venv/bin/python ]; then cd {remote_path} && '
            f'{remote_path}/venv/bin/python -c \\"import db; db.init_db()\\" >/dev/null && '
            f'chown -R deploy:www-data {remote_path}/data && chmod -R u=rwX,g=rwX,o= {remote_path}/data; fi'
        )
    elif base_service_name == "finances":
        cmd_parts.append(
            f'if [ -x {remote_path}/venv/bin/python ]; then cd {remote_path} && '
            f'{remote_path}/venv/bin/python -c \\"from pathlib import Path; import security; '
            f'[security.init_db(Path(p)) for p in (\'data/public/global.db\', \'data/demo/global.db\', \'data/global.db\', \'data/global_beta.db\') if Path(p).exists()]\\" >/dev/null && '
            f'mkdir -p {remote_path}/data/public/families {remote_path}/data/demo/families {remote_path}/data/families && '
            f'chown -R deploy:www-data {remote_path}/data && chmod -R u=rwX,g=rwX,o= {remote_path}/data; fi'
        )

    if cfg.get("mirror_path") and not is_beta:
        cmd_parts.append(f"cp -a {remote_path}/. {cfg['mirror_path']}/ 2>/dev/null || true")

    if is_dual_target or (service_name and service_name.lower() == "none"):
        for shared_asset in SHARED_LANDING_SYMLINK_ASSETS:
            cmd_parts.append(
                f"ln -sf {remote_path}/vendor/hvl_common/ui/static/{shared_asset} {remote_path}/{shared_asset} 2>/dev/null || true"
            )
        if admin_remote_path:
            cmd_parts.append(f"rm -f {admin_remote_path}/studio.html {admin_remote_path}/icons.html 2>/dev/null || true")

    admin_service = cfg.get("admin_service_name") if not is_beta else None
    if admin_service and (admin_files or vendor_files or force):
        print(f"[RESTART] Restarting {admin_service}.service...")
        cmd_parts.append(f"systemctl restart {admin_service}")

    if service_name and service_name.lower() != "none":
        print(f"[RESTART] Restarting {service_name}.service...")
        cmd_parts.append(f"systemctl restart {service_name}")
    else:
        print("[POST] Setting permissions and updating mirrors...")

    return cmd_parts


def verify_remote_health(
    urls_to_check: list[tuple[str, str]],
    remote_user: str,
    remote_host: str,
    *,
    run_fn: Callable[..., Any] = subprocess.run,
) -> bool:
    """Polls post-deploy HTTP health endpoints locally and via SSH loopback fallback."""
    if not urls_to_check:
        return True
    curl_bin = "curl.exe -s -o NUL" if os.name == "nt" else "curl -s -o /dev/null"
    all_healthy = True
    for label, url in urls_to_check:
        print(f"[HEALTH] Verifying {label} ({url})...")
        code = "000"
        for _ in range(5):
            time.sleep(1.5)
            hc = run_fn(f"{curl_bin} -w '%{{http_code}}' {url}", shell=True, capture_output=True, text=True)
            code = hc.stdout.strip().strip("'").strip('"')
            if code in ("", "000") and remote_host:
                parsed = urlparse(url)
                host_hdr = parsed.hostname or ""
                hc_remote = run_fn(
                    f'ssh {remote_user}@{remote_host} "curl -ks -o /dev/null -w \'%{{http_code}}\' --resolve {host_hdr}:443:127.0.0.1 {url}"',
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                code = hc_remote.stdout.strip().strip("'").strip('"')
            if code in ("200", "301", "302"):
                break
        if code in ("200", "301", "302"):
            print(f"[HEALTH] {label} OK (HTTP {code})")
        else:
            print(f"[WARN] {label} returned HTTP {code}.")
            all_healthy = False
    return all_healthy
