"""
Monarch Money Data Sync Utility with Full At-Rest Encryption
Authenticates with Monarch Money (via credentials or browser token),
encrypts all credentials and database records using AES-128/Fernet,
and syncs accounts and holdings into an encrypted SQLite database.
"""

import asyncio
import getpass
import json
import os
import sys
from pathlib import Path
from monarchmoney import MonarchMoney, RequireMFAException, LoginFailedException
try:
    from monarchmoney.monarchmoney import MonarchMoneyEndpoints
    MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"
    MonarchMoneyEndpoints.getLoginEndpoint = classmethod(lambda cls: "https://api.monarch.com/auth/login/")
    MonarchMoneyEndpoints.getGraphQL = classmethod(lambda cls: "https://api.monarch.com/graphql")
except Exception:
    pass
import security
import monarch_service

from config import get_data_dir, get_db_path_for_universe
DATA_DIR = get_data_dir()
SESSION_DIR = Path(__file__).resolve().parent / ".mm"
SESSION_FILE = SESSION_DIR / "mm_session.pickle"
DB_FILE = get_db_path_for_universe()


async def authenticate(mm: MonarchMoney) -> bool:
    """Authenticates using stored session, encrypted credentials, or interactive input."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Try restoring existing active session pickle
    if SESSION_FILE.exists():
        try:
            print("Found existing session. Testing connection...")
            mm.load_session(str(SESSION_FILE))
            await mm.get_accounts()
            print("Session restored and verified successfully!")
            return True
        except Exception:
            print("Session expired or invalid. Proceeding to authentication...")

    # 2. Try stored encrypted cookies
    stored_cookies = security.get_stored_cookies()
    if stored_cookies:
        try:
            print("Attempting login with stored encrypted browser cookies...")
            await mm.login_with_cookies(stored_cookies, save_session=True, verify=True)
            print("Cookies authenticated successfully!")
            return True
        except Exception:
            print("Stored cookies expired. Moving to interactive authentication...")

    # 3. Try stored encrypted credentials
    stored_email, stored_password = security.get_stored_credentials()
    if stored_email and stored_password:
        print(f"Attempting login with stored encrypted credentials for {stored_email}...")
        try:
            await mm.login(
                email=stored_email,
                password=stored_password,
                use_saved_session=False,
                save_session=False,
            )
            mm.save_session(str(SESSION_FILE))
            print("Login successful and session created!")
            return True
        except RequireMFAException:
            print("\nMonarch flagged this as a new device and sent a 6-digit code to your email.")
            totp_code = input("Enter the 6-digit code from your email: ").strip()
            try:
                await mm.multi_factor_authenticate(stored_email, stored_password, totp_code)
                mm.save_session(str(SESSION_FILE))
                print("Verification succeeded!")
                return True
            except Exception as e:
                print(f"Verification failed: {e}")
        except Exception as e:
            print(f"Auto-login failed: {e}")

    # 4. Interactive menu
    print("\n" + "=" * 60)
    print("MONARCH MONEY AUTHENTICATION")
    print("=" * 60)
    print("1. Paste Browser Cookie String (Fastest, 100% bypasses Cloudflare)")
    print("2. Email & Password")
    choice = input("\nSelect method [1 or 2, default 1]: ").strip()

    if choice in ("", "1"):
        print("\nHow to get your Cookie string from Monarch in your browser:")
        print("1. In your browser (where you are logged in to Monarch Money):")
        print("2. Open DevTools (F12) -> click 'Network' tab -> refresh page or click any tab.")
        print("3. Type 'graphql' in the filter box -> click any 'graphql' request.")
        print("4. Under 'Request Headers', look for 'Cookie:' -> copy that whole Cookie line.")
        cookie_input = getpass.getpass("Paste Cookie string (input hidden): ").strip()
        if cookie_input.lower().startswith("cookie:"):
            cookie_input = cookie_input[7:].strip()

        if not cookie_input:
            print("Cookie string cannot be empty.")
            return False

        try:
            print("Validating cookies with Monarch...")
            await mm.login_with_cookies(cookie_input, save_session=True, verify=True)
            security.save_encrypted_cookies(cookie_input)
            print("Cookies verified and encrypted into .env!")
            return True
        except Exception as e:
            print(f"Cookie authentication failed: {e}")
            return False

    # Default: Email + Password
    email = input("\nMonarch Email: ").strip()
    if not email:
        print("Email cannot be empty.")
        return False

    password = getpass.getpass("Monarch Password (input hidden): ")
    if not password:
        print("Password cannot be empty.")
        return False

    try:
        print("Connecting to Monarch...")
        await mm.login(
            email=email,
            password=password,
            use_saved_session=False,
            save_session=False,
        )
    except RequireMFAException:
        print("\nNOTE: Monarch requires new-device verification.")
        print("Please check your email inbox for a 6-digit verification code from Monarch.")
        totp_code = input("Enter 6-digit verification code: ").strip()
        try:
            await mm.multi_factor_authenticate(email, password, totp_code)
        except Exception as mfa_err:
            print(f"Verification failed: {mfa_err}")
            return False
    except LoginFailedException as lfe:
        print(f"Login failed: {lfe}")
        return False
    except Exception as e:
        print(f"Authentication error: {e}")
        return False

    # Save active session pickle
    try:
        mm.save_session(str(SESSION_FILE))
        print("Session saved successfully.")
    except Exception as save_err:
        print(f"Warning: Could not save session file: {save_err}")

    # Prompt to store credentials encrypted
    save_choice = input("Store credentials encrypted in .env for future syncs? [Y/n]: ").strip().lower()
    if save_choice in ("", "y", "yes"):
        security.save_encrypted_credentials(email, password)
        print("Credentials encrypted with AES-128 and saved to .env.")

    return True


async def sync_data():
    """Fetches all accounts and holdings from Monarch and stores them fully encrypted at rest in SQLite."""
    mm = MonarchMoney()
    ok = await authenticate(mm)
    if not ok:
        print("Sync aborted.")
        return

    print("\nFetching accounts from Monarch...")
    accounts_resp = await mm.get_accounts()
    accounts = accounts_resp.get("accounts", [])
    print(f"Successfully fetched {len(accounts)} accounts.")

    holdings_by_account = {}
    print("\nScanning for holdings and equity grants...")
    sem = asyncio.Semaphore(5)

    async def _fetch_acc_holdings(acc):
        acc_id = acc.get("id")
        acc_name = acc.get("displayName")
        acc_type = (acc.get("type") or {}).get("name", "")
        holdings_count = acc.get("holdingsCount", 0)
        if not acc_id:
            return None
        if acc_type in ("brokerage", "asset", "other") or holdings_count > 0 or acc.get("isManual"):
            async with sem:
                try:
                    holdings_resp = await mm.get_account_holdings(acc_id)
                    edges = (
                        holdings_resp.get("portfolio", {})
                        .get("aggregateHoldings", {})
                        .get("edges", [])
                    )
                    if edges:
                        print(f"  [{acc_type.upper()}] {acc_name}: {len(edges)} holding(s)")
                        return acc_id, [e.get("node", {}) for e in edges]
                except Exception:
                    pass
        return None

    results = await asyncio.gather(*(_fetch_acc_holdings(acc) for acc in accounts))
    for res in results:
        if res is not None:
            acc_id, nodes = res
            holdings_by_account[acc_id] = nodes

    # Save encrypted records into SQLite (data/family_office.db)
    print("\nEncrypting and writing records to SQLite database...")
    from db.accounts import replace_accounts, replace_holdings
    target_fid = int(os.environ.get("FAMILY_ID", "0") or 0)
    replace_accounts(DB_FILE, accounts, family_id=target_fid)
    replace_holdings(DB_FILE, holdings_by_account, family_id=target_fid)
    print(f"Encrypted snapshot written to: {DB_FILE} (All data encrypted at rest with AES-128/Fernet)")

    # Print high-level breakdown for immediate inspection
    print("\n" + "=" * 60)
    print("ACCOUNT SUMMARY:")
    print("=" * 60)
    for acc in accounts:
        acc_type = (acc.get("type") or {}).get("display", "Unknown")
        acc_name = acc.get("displayName", "Unnamed")
        bal = acc.get("currentBalance", 0)
        is_manual = " (Manual)" if acc.get("isManual") else ""
        print(f"- {acc_name}{is_manual} [{acc_type}]: ${bal:,.2f}")

    if holdings_by_account:
        print("\n" + "=" * 60)
        print("HOLDINGS / EQUITY DETECTED:")
        print("=" * 60)
        for acc_id, nodes in holdings_by_account.items():
            acc_name = next((a.get("displayName") for a in accounts if a.get("id") == acc_id), acc_id)
            print(f"\nAccount: {acc_name}")
            for node in nodes:
                sec = node.get("security") or {}
                sec_name = sec.get("name") or "Unknown"
                ticker = sec.get("ticker") or ""
                qty = node.get("quantity", 0)
                val = node.get("totalValue", 0)
                basis = node.get("basis", 0)
                print(f"  • {sec_name} ({ticker}): {qty:,.2f} shares | Total Value: ${val:,.2f} | Basis: ${basis:,.2f}")

    print("\nSync complete! All records are encrypted at rest.")


if __name__ == "__main__":
    asyncio.run(sync_data())
