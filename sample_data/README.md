# Sample Test Data for HVL Family Office

These sample files are designed to test data ingestion and features in the HVL Family Office desktop and web apps without using personal financial documents.

## Available Sample Files

1. **`sample_w2_2024.pdf`**
   - **Target**: **Tax** or **Compensation** tab &rarr; **Upload W-2 / Transcript**
   - **Data**: Form W-2 for tax year 2024.
     - Employer: *Acme Systems Technologies Inc*
     - Box 1 Wages: $385,000.00
     - Box 2 Federal Tax Withheld: $96,250.00
     - Box 3 Social Security Wages: $168,600.00 (tax: $10,453.20)
     - Box 5 Medicare Wages: $385,000.00 (tax: $5,582.50)
     - Box 12a Code D (401k): $23,000.00
     - Box 12b Code V (NSO Option Spread): $85,000.00
     - Box 12c Code DD (Health Coverage): $14,200.00

2. **`sample_tax_transcript_2024.pdf`**
   - **Target**: **Tax** tab &rarr; **Upload IRS Wage & Income Transcript**
   - **Data**: Multi-form IRS Wage & Income Transcript for tax year 2024.
     - Form W-2: $420,000 wages, $105,000 withholding, $95,000 NSO spread
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
   - **Format**: Portable encrypted SQLite 3 household vault snapshot pre-populated with synthetic household accounts, holdings, scenarios, and tax profile. Can be uploaded into any Cloud Sandbox or Local Desktop instance.

