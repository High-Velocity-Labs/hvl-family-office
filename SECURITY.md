# Security & Privacy Policy

## Our Security Philosophy

HVL Family Office is designed from first principles with a **zero-trust, user-controlled encryption architecture**. When managing personal finances, investment accounts, compensation structures, and tax records, users should never have to take a developer's or cloud provider's word that their data is private.

The system is engineered to make data leakage mathematically and architecturally impossible.

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
- **Client-Held Encryption Keys**: In cloud mode, each household's 256-bit vault encryption key is stored in the user's private Google Drive `appDataFolder` (`drive.appdata`) or browser session cookie.
- **Admin Lockout by Default**: When the household's **Developer & Admin Support Access** toggle (`families.support_access_enabled`) is `0` (Locked), encryption keys are physically `NULL` in the server database.
- **Cryptographic Enforcement**: Any CLI tool, background script, or unauthorized server query that attempts to read or decrypt records raises an uncatchable `PermissionError: Household <id> vault is cryptographically locked`. Server administrators and developers cannot inspect balances, holdings, tax transcripts, or credentials without explicit, user-initiated authorization.

### 4. AI Advisor Privacy & Model Training Boundaries
- **Zero Training on User Data**: User financial records, transaction histories, net worth, and compensation data are **never used to train commercial AI models**.
- **Sanitized Prompts**: When invoking the AI Financial Advisor or document ingestion features via Google Gemini, prompts are strictly sanitized:
  - Personal names, family member names, and employers are omitted or pseudonymized.
  - Account numbers, bank identifiers, and tax identification numbers are completely stripped.
  - Only high-level category aggregates, asset allocations, and market ticker symbols are passed into context.
- **Bring Your Own Key (BYO API Key)**: Users can supply their own private Gemini API key in **Settings**, ensuring direct, private quota management with Google without intermediary proxying. AI features can also be disabled entirely.

### 5. Column-Level Encryption at Rest
- Sensitive database fields (third-party API tokens, SimpleFIN access URLs, Monarch session credentials, institution credentials, and personal notes) are encrypted at rest using AES-256 Fernet encryption (`EncryptedString`, `EncryptedJSON`, `EncryptedFloat`).
- Keys are derived via `PBKDF2-HMAC-SHA256` using 600,000 iterations with cryptographically random salts.

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
4. **Denylist & Pattern Enforcement**: Ensures forbidden personal identifiers, private infrastructure strings, and non-round placeholder numbers never appear in code, templates, or tracked files.

---

## Limitation of Security Warranty & Zero Breach Liability

While HVL Family Office implements cryptographic isolation, AES-256 column encryption, and zero-knowledge key escrow in good faith, **no software, operating system, or cloud infrastructure can guarantee 100% immunity from zero-day vulnerabilities, compiler defects, hardware attacks, or sophisticated breaches**.

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
