# Security & Privacy Policy

## Our Security Philosophy

HVL Family Office is designed from first principles with a **zero-trust, user-controlled encryption architecture**. When managing personal finances, investment accounts, compensation structures, and tax records, users should never have to take a developer's or cloud provider's word that their data is private.

The system is engineered to minimize data exposure through physical per-household isolation and client-held keys. No system can make leakage impossible: see the limitations below and the Support Access note in section 3.

---

## Threat Model & Anti-Leak Guarantees

### 1. 100% Local Desktop Sovereignty (Default Mode)
- **Zero Cloud Leakage**: In local desktop mode (`LOCAL_MODE=1`, used by macOS `.dmg`, Windows `.exe`, and local Docker), the entire application runs offline on your own machine.
- **Local Storage**: Databases and configuration reside strictly on your local disk:
  - macOS: `~/Library/Application Support/HVLFamilyOffice/`
  - Windows: `%LOCALAPPDATA%\HVLFamilyOffice\`
  - Linux/Docker: `~/.local/share/hvl-family-office/` (or mounted volume)
- **Zero Third-Party Telemetry**: There are no analytics libraries, tracking pixels, behavioral monitors, or crash reporters sending telemetry to external endpoints.

### 2. Multi-Tenant Physical Isolation (Cloud Mode)
- **Database-per-Household Multi-Tenancy**: In hosted multi-tenant cloud deployments (`LOCAL_MODE=0`), every household is partitioned into an isolated SQLite database (`data/families/{family_id}.db`).
- **Elimination of Cross-Tenant Query Contamination**: Traditional SaaS architectures rely on logical filtering (`WHERE family_id = ?`) in a shared database. A single missing filter or ORM vulnerability in shared databases can expose records across tenants. Physical database separation eliminates this risk by design.

### 3. Zero-Knowledge Key Escrow & Support Lockout
- **Client-Held Encryption Keys**: In cloud mode, each household's randomly generated 256-bit Fernet vault key is stored in the user's private Google Drive `appDataFolder` (`drive.appdata`) or browser session cookie.
- **Admin Lockout by Default**: When the household's **Developer & Admin Support Access** toggle (`families.support_access_enabled`) is `0` (Locked), encryption keys are physically `NULL` in the server database.
- **Cryptographic Enforcement**: Any CLI tool, background script, or unauthorized server query that attempts to read or decrypt records raises `PermissionError: Household <id> vault is cryptographically locked`. While Support Access is off, server administrators and developers cannot inspect balances, holdings, tax transcripts, or credentials; turning Support Access on (a user-initiated toggle, and the default for the shared demo households) gives the server the key and lifts this protection.

### 4. AI Advisor Privacy & Model Training Boundaries
- **Zero Training on User Data**: User financial records, transaction histories, net worth, and compensation data are never used by this application to train models. Whether Google trains on advisor prompts depends on the Gemini API tier in use (paid-tier API data is not used for training; free-tier data may be).
- **What Is Sent to the AI Provider**: Names are not redacted. When you use the AI Financial Advisor via Google Gemini, the prompt and tool results include:
  - Your family name and company name, family member names and birthdates, employers on compensation records, account names and institutions, and gift-recipient names.
  - Balances, holdings, tickers, and category totals relevant to the question.
  - Account numbers, credentials, and tax identification numbers are not part of the advisor context.
- **Bring Your Own Key (BYO API Key)**: Users can supply their own private Gemini API key in **Settings**, ensuring direct, private quota management with Google without intermediary proxying. AI features can also be disabled entirely.

### 5. Column-Level Encryption at Rest
- Sensitive database fields (third-party API tokens, SimpleFIN access URLs, Monarch session credentials, institution credentials, and personal notes) are encrypted at rest using Fernet encryption (AES-128-CBC + HMAC-SHA256; `EncryptedString`, `EncryptedJSON`, `EncryptedFloat`).
- Column keys are randomly generated Fernet keys, not derived from a password. In local desktop mode, your PIN or passphrase is stretched with scrypt (N=2^17, r=8, p=1, random salt) and only wraps that key with AES-256-GCM, the same envelope a `.fovault` backup uses (`hvl_common.security.passphrase_wrap`).

---

## Verifying Code & Auditing Security

We encourage open security reviews and adversarial auditing of the codebase. You can run our automated security audit suite locally at any time:

```bash
# Run the automated adversarial security, encryption-at-rest, and zero-PII audit
python scripts/audit_security_and_data.py

# Run the automated pytest security and access control suite
python -m pytest tests/test_security_access.py tests/test_family_dbs.py
```

The audit script verifies:
1. **Zero Plaintext PII**: Confirms no real names, financial figures, or credentials exist in unencrypted columns or templates.
2. **Key Isolation**: Confirms distinct household encryption keys cannot cross-decrypt records.
3. **Escrow Integrity**: Validates that locked vaults refuse access to server processes when support access is disabled.
4. **Denylist & Pattern Enforcement**: Checks code, templates, and tracked files against a maintainer-side denylist of personal identifiers and private infrastructure strings (the list itself is not shipped in this repository) and flags non-round placeholder numbers.

---

## Limitation of Security Warranty & Zero Breach Liability

While HVL Family Office implements cryptographic isolation, Fernet (AES-128-CBC + HMAC-SHA256) column encryption, and zero-knowledge key escrow in good faith, **no software, operating system, or cloud infrastructure can guarantee 100% immunity from zero-day vulnerabilities, compiler defects, hardware attacks, or sophisticated breaches**.

By using this software or accessing any hosted instance:
1. **Assumption of Risk**: You acknowledge that you use the software, binaries, source code, and services at your own sole risk.
2. **Zero Liability for Breaches & Leaks**: The authors, maintainers, contributors, and server operators explicitly disclaim all liability for any security incidents, unauthorized data access, hacking, data theft, data leaks, corruption, hardware failures, or loss of confidentiality.
3. **No Financial or Regulatory Warranty**: High Velocity Labs does not warrant compliance with FINRA, SEC, HIPAA, or statutory bank-secrecy standards. Users are solely responsible for evaluating the suitability of the software for their personal or organizational privacy requirements.
4. **Governing Terms**: All access to hosted instances is subject to the **[Master Terms of Service](https://highvelocitylabs.dev/terms)**. If you do not agree to these terms and limitations, you must not use or deploy the software.

---

## Reporting a Security Vulnerability

If you discover a potential security vulnerability or privacy flaw in HVL Family Office:

1. **Do not open a public GitHub issue.**
2. Send a detailed report to **`privacy@highvelocitylabs.dev`**.
3. Include:
   - Description of the vulnerability and attack vector.
   - Minimal steps or script to reproduce the issue.
   - Any potential impact on confidentiality or integrity.

We acknowledge receipt of security reports within 48 hours and work with researchers to validate, patch, and disclose responsibly.
