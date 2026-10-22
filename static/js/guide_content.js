/**
 * Page Guide & Tool Documentation Content Catalog
 * Structured reference data for each platform tool and section.
 */

window.GUIDE_DATA = {
    'section-scenarios': {
        title: 'Forecasting: Scenarios & Longevity',
        badge: 'Forecasting',
        purpose: 'Simulates household liquid net worth, annual cash flows, tax drag, and retirement feasibility over a 50-year horizon (2026–2076).',
        mentalModel: {
            title: 'The "Parent & Child" Plan Model (Steady-State Baseline vs. Toggleable Events)',
            calloutClass: 'guide-callout',
            text: 'Keep your <strong>Baseline (Parent) Plan</strong> anchored to your recurring steady-state living expenses plus your amortizing mortgage (which automatically drops to $0 at payoff). Place temporary or discretionary life events—such as K–12/college tuition, a home rebuild, a Pre-65 ACA healthcare bridge, or a sabbatical—onto the shared <strong>Event Shelf</strong> and toggle them on or off across lightweight <strong>Child Plans</strong>.<br><br><a href="/playbooks" target="_blank" rel="noopener noreferrer" style="color: var(--accent-blue); font-weight: 700; text-decoration: underline;">Open Scenario Planning Playbooks &amp; Common "What-If" Workflows (/playbooks) →</a>'
        },

        steps: [
            { title: 'Select or Create a Child Plan', text: 'Use the Plan pills or click <strong>+ Child Plan</strong> to branch off Baseline while automatically inheriting live balances and salaries.' },
            { title: 'Toggle Events & Inspect the Single-Year Sankey', text: 'Add milestones (Pre-65 ACA Healthcare Bridge, Roth Ladder, Home Rebuild, State Relocation) and switch Cash Flow to <strong>Single-Year Sankey</strong> to trace every dollar.' },
            { title: 'Compare Side-by-Side in the Scorecard', text: 'Click <strong>Compare Plans ▼</strong> to see exact deltas in retirement readiness age, Age 65/85 Net Worth, and Monte Carlo solvency.' },
            { title: 'Stress-Test 1928–2025 Cohorts & Dynamic Guardrails', text: 'Open the <strong>Monte Carlo Stress Test</strong> lens to toggle the <strong>1928–2025 Backtest (98 Cohorts)</strong> or enable <strong>Dynamic Spending Guardrails</strong> in Advanced Levers.' },
            { title: 'Toggle Real vs. Nominal', text: 'Switch between <strong>Today\'s Dollars (Real)</strong> to see purchasing power discounted by inflation, or <strong>Future Value (Nominal)</strong> to inspect compounding figures.' }
        ],

        calculations: [
            '<strong>1,000-Trial Monte Carlo &amp; 1928–2025 Historical Cohort Backtester:</strong> Combines stochastic GBM trials with all 98 rolling historical US market cohorts (1928–2025 S&amp;P 500, 10-Yr Treasury, T-Bills, and CPI) plus optional Guyton-Klinger dynamic spending guardrails.',
            '<strong>Actuarial Joint Longevity &amp; Pre-65 ACA Healthcare Bridge:</strong> Integrates SSA cohort life tables through age 100 and models MAGI-based ACA healthcare subsidies prior to Age 65 Medicare + IRMAA.',
            '<strong>Cash Flow Sequencing:</strong> Annual living expenses and taxes are funded from ordinary cash flow; deficits draw from taxable brokerage first, then tax-deferred retirement accounts.'
        ]
    },

    'section-equity': {
        title: 'Company Equity: Stock Options & Buybacks',
        badge: 'Company Equity',
        purpose: 'Tracks private startup incentive stock options (ISOs) and non-qualified stock options (NSOs), tranche vesting schedules, exercise strike costs, and cashless company buybacks.',
        mentalModel: {
            title: 'Tranche Tracking & Secondary Liquidity',
            calloutClass: 'guide-callout-green',
            text: 'Stock option grants are modeled across distinct tranches, each with its own grant date, strike price, and vesting schedule. The Secondary Buyback module simulates selling shares back to the company in secondary tenders, deducting strike exercise costs and statutory tax withholdings to compute net cash proceeds available for portfolio reinvestment.'
        },

        steps: [
            { title: 'Review Grant Tranches', text: 'Inspect total grants, vested quantities, unvested shares, and current unrealized spread based on fair market value (FMV).' },
            { title: 'Simulate Secondary Buyback', text: 'Input target share count and company purchase price in the Cashless Buyback Calculator.' },
            { title: 'Inspect Net Proceeds', text: 'Review the itemized breakdown of gross value, strike costs, federal withholding, and state taxes.' },
            { title: 'Link to Forecasting', text: 'Realized net proceeds can be linked directly into forecasting scenarios for automatic reinvestment into index portfolios.' }
        ],

        calculations: [
            '<strong>Washington State RCW 82.87:</strong> 7.0% tax on long-term capital gains exceeding the $250,000 standard annual exemption.',
            '<strong>California Ordinary Income Tax:</strong> Up to 13.3% top marginal rate applied to NSO spread at time of exercise.',
            '<strong>Alternative Minimum Tax (AMT):</strong> ISO spread at exercise is calculated as an AMT preference item under IRC § 56(b)(3).'
        ]
    },

    'section-college': {
        title: 'Education: Tuition Schedules & 529 Outflows',
        badge: 'Education',
        purpose: 'Manages multi-year education tuition schedules by student and links educational expenses into long-term forecast cash flows.',
        mentalModel: {
            title: 'The 529 Custodial Depletion Waterfall',
            calloutClass: 'guide-callout-orange',
            text: 'Education expenses are modeled using a strict custodial drawdown waterfall: tuition outflows first deplete the student\'s designated tax-free 529 custodial balance. Only once the 529 reserve reaches $0 does the engine draw remaining tuition from parent taxable brokerage cash flows.<br><br>Education milestones in Forecasting support two operational modes: syncing directly with recorded tuition schedules, or overriding values to test hypothetical college scenarios.'
        },

        steps: [
            { title: 'Maintain Tuition Schedules', text: 'Record student grade progression, expected enrollment years, and annual tuition figures.' },
            { title: 'Link to Forecasting', text: 'In Forecasting, select <strong>[ Synced with Ledger ]</strong> on Education events to automatically pull scheduled rates.' },
            { title: 'Monitor 529 Trajectory', text: 'Inspect annual 529 balance drawdowns and verify when parent cash flow will be impacted.' },
            { title: 'Evaluate Leftover Funds', text: 'Review leftover 529 reserves for potential graduate school funding or Roth IRA rollovers.' }
        ],

        calculations: [
            '<strong>Qualified 529 Distributions:</strong> 100% federal and state tax-free distributions under IRC § 529 for tuition, fees, books, and qualified room and board.',
            '<strong>SECURE 2.0 Act § 126 Rollover:</strong> Allows up to $35,000 lifetime rollover of unused 529 funds into the student\'s personal Roth IRA, subject to annual Roth IRA contribution limits and a 15-year account seasoning rule.'
        ]
    },

    'section-estate': {
        title: 'Estate & Generational Wealth Transfer',
        badge: 'Estate & Trusts',
        purpose: 'Calculates statutory state estate tax exposure, models post-2025 federal exemption sunset impacts, and evaluates irrevocable trust funding.',
        mentalModel: {
            title: 'State Death Tax Arbitrage & Irrevocable Trusts',
            calloutClass: 'guide-callout-purple',
            text: 'State estate tax laws diverge sharply from federal rules. Several states impose low exclusion thresholds and steep graduated brackets. Irrevocable trusts legally remove appreciating assets from the gross taxable estate, allowing wealth to compound for future generations outside the death tax net.'
        },

        steps: [
            { title: 'Review Taxable Estate', text: 'Examine current gross assets against federal and state statutory exclusion thresholds.' },
            { title: 'Toggle Exemption Sunset', text: 'Switch between today\'s ~$28M MFJ federal exclusion and the post-2025 TCJA sunset back to ~$14M MFJ.' },
            { title: 'Compare State Liabilities', text: 'Inspect state estate tax calculations across benchmark jurisdictions (Washington, New York, Massachusetts, Oregon, and 0% states).' },
            { title: 'Model Irrevocable Trusts', text: 'Simulate asset transfers into SLATs, IDGTs, GRATs, or ILITs to project estate reduction and net legacy to heirs.' }
        ],

        calculations: [
            '<strong>Washington State (RCW 83.100):</strong> Graduated rates from 10% to 20% on taxable amounts above the $2.193M exclusion threshold.',
            '<strong>New York (Tax Law § 952):</strong> Graduated rates from 3.06% to 16%, with a 105% cliff rule that erases the entire $6.94M exemption if the estate exceeds 105% of the threshold.',
            '<strong>IDGT Grantor Tax Burn:</strong> Grantor pays income tax on trust investment returns under IRC § 671, allowing trust assets to compound gross without income tax friction.'
        ]
    },

    'section-arbitrage': {
        title: 'Multi-State Tax Arbitrage',
        badge: 'Tax Arbitrage',
        purpose: 'Compares net take-home income and tax drag across primary states: Washington, California, New York, Texas, and Florida.',
        mentalModel: {
            title: 'Side-by-Side Jurisdictional Analysis',
            calloutClass: 'guide-callout',
            text: 'Evaluates statutory state and municipal tax schedules across ordinary W-2 salary, equity option vesting, capital gains, and investment yield on identical household income baselines.'
        },

        steps: [
            { title: 'Configure Income Baselines', text: 'Set gross salary, expected equity vesting, and investment dividend/interest yield.' },
            { title: 'Compare Effective Rates', text: 'Review total tax liabilities and effective tax percentages side-by-side across all five states.' },
            { title: 'Review 10-Year Projections', text: 'Inspect multi-year compounding differences in net take-home pay.' }
        ],

        calculations: [
            '<strong>Washington:</strong> 0% state income tax; 7.0% RCW 82.87 capital gains tax on long-term gains exceeding $250k.',
            '<strong>California:</strong> Graduated ordinary income tax up to 12.3% plus 1.0% Mental Health Services tax (13.3% top marginal rate).',
            '<strong>New York:</strong> Combined NY State income tax (up to 10.9%) and NYC resident local tax (up to 3.876%).',
            '<strong>Texas & Florida:</strong> 0% individual state income tax.'
        ]
    },

    'section-compensation': {
        title: 'Compensation, Withholding & Safe Harbor',
        badge: 'Compensation',
        purpose: 'Reconciles dual-earner payroll withholdings and parses IRS Form 1040 Account Transcripts to ensure safe harbor compliance and prevent underpayment penalties.',
        mentalModel: {
            title: 'Dual-Earner Safe Harbor Reconciliation',
            calloutClass: 'guide-callout-orange',
            text: 'Dual-earner households often experience underwithholding due to progressive tax bracket stacking. Meeting the statutory safe harbor eliminates IRS Form 2210 underpayment penalties regardless of total balance due at tax filing.'
        },

        steps: [
            { title: 'Input Payroll Withholdings', text: 'Enter or sync bi-weekly gross pay, federal withholding, and state tax withholdings for both earners.' },
            { title: 'Ingest IRS Transcripts', text: 'Upload or paste IRS Form 1040 Account Transcript data to extract quarterly estimated tax payments and prior-year tax baseline.' },
            { title: 'Verify Safe Harbor Status', text: 'Confirm whether year-to-date withholdings satisfy the 110% prior-year safe harbor threshold.' }
        ],

        calculations: [
            '<strong>IRC § 6654(d)(1)(C):</strong> 110% safe harbor rule applies to taxpayers with prior-year adjusted gross income (AGI) exceeding $150,000 ($75,000 if married filing separately).',
            '<strong>Quarterly Installment Allocation:</strong> Evaluates required quarterly withholding pace to prevent annualized income installment penalties.'
        ]
    },

    'section-overview': {
        title: 'Overview & Net Worth Dashboard',
        badge: 'Overview & Net Worth',
        purpose: 'Central consolidated balance sheet displaying liquid assets, retirement accounts, real estate equity, and private investments.',
        mentalModel: {
            title: 'Consolidated Household Balance Sheet',
            calloutClass: 'guide-callout',
            text: 'Aggregates all financial holdings into three tiers: Liquid (taxable brokerage, cash), Tax-Advantaged (401k, IRA, HSA, 529), and Illiquid (real estate equity, private stock). Tracks monthly savings velocity and checks asset allocation against target Investment Policy Statement (IPS) bands.'
        },

        steps: [
            { title: 'Inspect Net Worth Snapshot', text: 'Review total household net worth and 30-day velocity.' },
            { title: 'Check Asset Allocation', text: 'Verify current portfolio weights against target asset class allocation bands.' },
            { title: 'Identify Drift', text: 'Review any asset classes that have drifted beyond policy tolerance limits.' }
        ],

        calculations: [
            '<strong>Liquid Net Worth:</strong> Excludes primary residence equity and illiquid private shares to reflect readily accessible capital.',
            '<strong>IPS Drift Monitoring:</strong> Calculates percentage variance between current holdings and target model portfolio weights.'
        ]
    },

    'section-holdings': {
        title: 'Investments & Asset Allocation',
        badge: 'Investments',
        purpose: 'Granular inventory of public equities, index funds, bond holdings, and private shares across all connected brokerage accounts.',
        mentalModel: {
            title: 'Portfolio-Wide Allocation Aggregation',
            calloutClass: 'guide-callout-green',
            text: 'Consolidates underlying securities across multiple financial institutions to determine true asset class distribution (US Equity, International Equity, Fixed Income, Cash, Alternatives).'
        },

        steps: [
            { title: 'Filter & Search Holdings', text: 'Sort securities by account, asset class, or market value.' },
            { title: 'Inspect Allocation Weights', text: 'Review percentage allocation across public securities.' },
            { title: 'Review Rebalancing Signals', text: 'Identify overweight and underweight asset categories for tax-efficient rebalancing.' }
        ],

        calculations: [
            '<strong>Aggregate Asset Weights:</strong> Security values divided by total investment portfolio value.',
            '<strong>IPS Rebalancing Bands:</strong> Tolerance thresholds (typically ±5%) around target model percentages.'
        ]
    },

    'section-philanthropy': {
        title: 'Philanthropy & Structured Giving',
        badge: 'Philanthropy',
        purpose: 'Models charitable contribution strategies including Donor-Advised Funds (DAFs), appreciated stock gifting, and charitable trusts.',
        mentalModel: {
            title: 'Appreciated Asset Donation & Deduction Bunching',
            calloutClass: 'guide-callout-purple',
            text: 'Donating appreciated long-term capital assets directly to charity eliminates unrealized capital gains while providing a full fair-market-value tax deduction. Bunching multiple years of donations into a DAF maximizes deductions above the standard deduction.'
        },

        steps: [
            { title: 'Set Giving Budget', text: 'Specify annual charitable contribution targets.' },
            { title: 'Compare Funding Vehicles', text: 'Evaluate cash donations versus transferring appreciated stock or private shares.' },
            { title: 'Model DAF Bunching', text: 'Simulate funding multiple years of giving in high-income tax years.' }
        ],

        calculations: [
            '<strong>IRC § 170(b) AGI Limitations:</strong> 60% of AGI limit for cash gifts to public charities; 30% of AGI limit for long-term appreciated capital gain property.',
            '<strong>Capital Gains Elimination:</strong> Realized gain on contributed shares is permanently excluded from gross income.'
        ]
    },

    'section-gifting': {
        title: 'Family Gifting & Exclusion Tracking',
        badge: 'Family Gifting',
        purpose: 'Coordinates intra-family gifts to transfer wealth across generations within annual and lifetime gift tax exclusions.',
        mentalModel: {
            title: 'Annual Exclusions & 529 Superfunding',
            calloutClass: 'guide-callout-green',
            text: 'Annual exclusion gifts do not count against the lifetime unified gift and estate tax exemption and do not require IRS Form 709 filings. Five-year 529 superfunding allows front-loading five years of annual exclusions into a single contribution.'
        },

        steps: [
            { title: 'Log Annual Gifts', text: 'Record gifts made to children and relatives by calendar year.' },
            { title: 'Track Exclusion Caps', text: 'Monitor gifts against the annual per-recipient limit ($18,000 individual, $36,000 married split).' },
            { title: 'Model 529 Superfunding', text: 'Calculate 5-year front-loaded 529 contributions up to $90,000 individual / $180,000 married.' }
        ],

        calculations: [
            '<strong>IRC § 2503(b):</strong> Annual exclusion of $18,000 per donor per recipient.',
            '<strong>IRC § 529(c)(2)(B):</strong> Five-year averaging election allowing up to $90,000 ($180,000 MFJ) front-loaded 529 contributions.'
        ]
    },

    'section-accounts': {
        title: 'Connected Accounts & Assets Registry',
        badge: 'Accounts & Assets',
        purpose: 'Centralized administration of connected financial institutions, sync statuses, and manually tracked property assets.',
        mentalModel: {
            title: 'Hybrid Automated & Manual Asset Ledger',
            calloutClass: 'guide-callout',
            text: 'Combines automated API synchronization for liquid and retirement accounts with manual asset records (real estate, vehicles, private loans) with recorded appraisal dates.'
        },

        steps: [
            { title: 'Verify Connection Health', text: 'Check institution connection statuses and latest sync timestamps.' },
            { title: 'Manage Manual Assets', text: 'Add or update valuations for real estate, private business equity, or liabilities.' },
            { title: 'Configure Universe Routing', text: 'Review household tenancy and database routing settings.' }
        ],

        calculations: [
            '<strong>Balance Aggregation:</strong> Sum of verified institution balances plus active manual asset valuations.',
            '<strong>Net Asset Value (NAV):</strong> Total asset valuations minus recorded mortgage and loan liabilities.'
        ]
    }
};
