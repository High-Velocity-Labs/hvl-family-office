# Sample Test Data for HVL Family Office

These sample files are designed to test data ingestion and features in the HVL Family Office desktop and web apps without using personal financial documents.

## Available Sample Files

1. **`sample_w2_2024.pdf`**
   - **Target**: **Tax** or **Compensation** tab &rarr; **Upload W-2 / Transcript**
   - **Data**: Form W-2 for tax year 2024.
     - Employer: *Acme Systems Technologies Inc*
     - Box 1 Wages: $362,000.00 (Box 5 less the $23,000 Code D deferral)
     - Box 2 Federal Tax Withheld: $96,250.00
     - Box 3 Social Security Wages: $168,600.00 (tax: $10,453.20)
     - Box 5 Medicare Wages: $385,000.00 (Box 6 tax: $7,247.50, which includes the 0.9% Additional Medicare Tax on wages over $200,000)
     - Box 12a Code D (401k): $23,000.00
     - Box 12b Code V (NSO Option Spread): $85,000.00
     - Box 12c Code DD (Health Coverage): $14,200.00

2. **`sample_tax_transcript_2024.pdf`**
   - **Target**: **Tax** tab &rarr; **Upload IRS Wage & Income Transcript**
   - **Data**: Multi-form IRS Wage & Income Transcript for tax year 2024.
     - Form W-2: $397,000 Box 1 wages ($420,000 Medicare wages less the $23,000 deferral), $105,000 withholding, $8,070 Medicare tax withheld (includes the 0.9% Additional Medicare Tax), $95,000 NSO spread
     - Form 1098: First National Mortgage Corp ($24,500 interest paid, $680,000 principal)
     - Form 1099-DIV: Vanguard Group ($12,400 ordinary / $10,800 qualified dividends, $1,250 capital gain distribution)
     - Form 1099-INT: High Yield Trust Bank ($4,850 interest)

3. **`sample_account_balances_long.csv`**
   - **Target**: **Accounts** tab &rarr; **Import CSV** or **Guided Setup Step 1**
   - **Format**: Long format with 6 columns (`Date, Account Name, Balance, Role, Institution, Include in Net Worth`)
   - **Accounts**: Primary Checking, Emergency HYSA, Taxable Index Brokerage, Traditional 401(k), Backdoor Roth IRA, Rewards Credit Card across 2024.

4. **`sample_account_balances_wide.csv`**
   - **Target**: **Accounts** tab &rarr; **Import CSV** or **Guided Setup Step 1**
   - **Format**: Wide pivot table (`Date, Primary Checking, Emergency HYSA, Taxable Index Brokerage, Traditional 401(k), Backdoor Roth IRA`) across 5 snapshot periods.

5. **`sample_family_vault.fovault`**
   - **Target**: **Interactive Sandbox Banner (`Upload .fovault`)** or **Local Desktop (`Settings` &rarr; `Local Vault & Backups` &rarr; `Restore .fovault`)**
   - **Passphrase**: `synthetic-sample-vault` (enter it in the restore dialog). This is a public passphrase for synthetic data only; do not reuse it for a real backup.
   - **Format**: `.fovault` format v2 &mdash; a portable SQLite 3 snapshot of the synthetic Miller household (early-retired, Washington State): 7 accounts, 6 holdings positions (VTI, VXUS, BND and VBTLX across the taxable, IRA and Roth accounts), 2 members, 4 scenarios (the FIRE baseline with its $80k Roth conversion ladder and ACA bridge events, a global travel plan, a San Juan Islands cabin plan and a bear-market spending guardrail; the baseline spends $160k a year and shows about 94.4% Monte Carlo success), 3 years of tax transcript records, and 3 advisor conversations. Sensitive fields are encrypted per-field with the household key (Fernet); the file as a whole is not encrypted. The household key inside is wrapped under the passphrase with scrypt (N=2^17, r=8, p=1, random salt stored in the file) and AES-256-GCM, so a wrong passphrase is rejected. Real backups use a passphrase you choose at export time; it is never stored and **cannot be recovered**.

