# Changelog

All notable changes to **HVL Family Office** are documented in this file.

## [v0.5.7] - 2026-10-30

### Baseline Overlays: Switch Off, Reorder, and Cleaner Charts
- **Switch an Overlay Off Without Unmerging It (`services/scenario_overlay_service.py`, `forecast/hierarchy.py`, `templates/components/scenarios/plan_card.html`)**: each plan merged into the Baseline has an on/off switch on its chip. Off keeps it in the overlay stack, in the same place, while the Baseline and its child plans are projected without it; on applies it again. Unmerging still removes it.
- **Drag to Reorder the Overlay Stack (`static/js/scenarios/cards_reorder.js`)**: drag the Baseline's overlay chips to change the order overlays apply in. Plan rows and overlay chips reorder their own lists only.
- **Charts Skip Merged Overlays**: a merged overlay that is switched on is already part of the Baseline's line, so it no longer gets its own line or plan pill on the forecasting charts, unless it is the plan being viewed.
- **Shared Switch Control (shared library `forms.css`)**: Family Office's toggle switches (accounts, education, equity, overlays) use one shared `.hvl-switch` control, with a compact size that matches small buttons.

### A Much Faster Forecasting Page
- **Fixed: Charts Redrawing Continuously (`static/js/app_navigation.js`, `static/js/widget_charts.js`)**: rendering a chart loaded its toggle strip, and that load redrew every chart again, about ten times a second for as long as the page was open. Charts now redraw only when the forecast or the page changes, once per refresh, and the forecast loader stays visible until the new forecast is drawn.
- **Smaller Refreshes (`ssr/scenarios_plan_detail.py`)**: the page carries the year-by-year series of the plan being viewed only; another plan's series loads when a chart picks it, with a loader. The year-by-year schedule table loads when it is opened. A forecast refresh for a household with eleven plans dropped from 1.7 MB to 0.75 MB.
- **Each Plan's Projection Is Cached by Its Inputs (`forecast/plan_run_cache.py`)**: a plan's projection is reused whenever its inputs are unchanged, so switching an overlay back to an earlier state, or editing one plan, no longer recomputes every plan.
- **Household Data Stays Cached Across Plan Edits (`db/store.py`, `forecast/snapshot_cache.py`)**: accounts, holdings, equity, family members, tuition and the balance-sheet snapshot are cached against the data they come from, so a plan edit no longer reloads and decrypts them.
- **Fewer Repeated Loads (`forecast/orchestrator.py`, `config.py`)**: private-market commitments are read once per forecast instead of once per plan, and the one-time data-folder migration check runs once per process instead of on every database lookup.

### Housekeeping
- **Restores Refresh Every Worker (`services/fovault_service.py`)**: restoring a backup leaves the household's data-version counters above their earlier values, so every server process reloads the household's data instead of keeping what it had cached.
- **Update Pill**: the "Update available" pill does a plain reload instead of purging caches first.

## [v0.5.6] - 2026-10-29

### Siri Moves to the Voice Assistant App
- **One Siri Endpoint (`routes/siri.py` removed, Settings)**: Family Office no longer has its own Siri endpoint or Siri tokens; voice questions go through the separate voice assistant app, which reads Family Office through its scoped endpoint. The Siri token option is gone from Settings and from the release highlights.

### Security Hardening
- **No Cross-App Key Reads**: the voice assistant app gets Family Office access tokens from a Family Office endpoint authenticated per household, instead of reading Family Office's keys or database.
- **Chat Markdown**: the advisor chat sanitizer escapes any `<` or `>` it did not rebuild itself.
- **Login Escrow Cleanup**: a login clears key escrow only in its own household database.

### Housekeeping
- **Copy**: the ISO hedge explanation matches the AMT engine; README module paths and release notes corrected.
- **Public Repository**: ships only the shared-library modules Family Office actually imports.
- **Tests**: the suite cleans up its temporary data, and checks that need a git checkout skip in exported copies.

## [v0.5.5] - 2026-10-29

### New Households Start in Your State, or Ask
- **Starting State From Your Location (`services/residence_state.py`, `services/auth_google.py`)**: a new household's state of residence comes from the sign-in's approximate location when it is one of the supported states. Otherwise it starts unset, and onboarding asks before continuing. Existing households keep their saved state.
- **"State Not Set" Is Explicit**: an unset state applies no state income, capital gains or estate tax, labelled "State not set", instead of borrowing one state's rules. The Settings, Estate and Arbitrage selectors start on "Choose your state", and Settings refuses states the tax engine does not model.

### Demo Personas and Sample Files Match the Engine
- **Persona inputs fit each household's story (`scripts/seed_demo_families.py`, `data/fixtures/demo_jones_profile.json`, `services/auth_session.py`, `README.md`)**: spending, savings targets, retirement ages and plan choices were reset so each demo family's plans tell its theme instead of most showing under 15% Monte Carlo success (1,000 trials, seed 42, to age 100). Jones 91.3% baseline, 36.4% retire at 55, 37.4% Tahoe home and retire at 58; Miller 94.4% baseline, 79.5% travel, 25.8% cabin, 99.7% guardrail; Chen 65.9% baseline, 75.8% secondary tender, 43.0% Westchester estate, 90.2% delayed exit; Ramirez 88.5% baseline, 21.2% retire at 62, 63.5% with solar savings, 100% working to 67; Taylor 76.0% baseline, 90.6% higher savings, 69.6% retire at 63, 94.7% work to 67; Foster 84.8% baseline, 99.6% work to 67, 99.5% clinic, 63.1% early exit.
- **Pension and mortgage inputs are seeded**: Sofia Ramirez's Texas TRS pension ($48k a year from 62, 1% increases, 50% survivor share) and each mortgage's real rate and remaining term (Jones, Chen, Ramirez, Taylor, Foster) are stored in the household assumptions, replacing the engine's 6.5% / 30-year default debt service. Living spend is the non-housing budget; savings targets are set from what take-home pay leaves. Foster's clinic plan carries owner distributions as a cash-inflow event, and the Ramirez mortgage payoff moved to 2041, when it can be paid.
- **Statutory figures**: the Chen superfunding question and answer use the $190,000 five-year limit (5 x the $38,000 couple's exclusion) and its projected growth; the $32,200 2026 standard deduction was already current in the Miller answers.
- **Plan text from engine output (`scripts/seed_demo_families.py`, demo fixtures)**: child plans now carry their parent's events, so scenario descriptions, advisor answers and Monte Carlo figures were rewritten from the engine's results. Claims for unmodeled features (student loan payoff, 403(b) match, practice equity sales, savings beyond take-home surplus) were removed.
- **Facts**: Washington's SB 6346 (9.9% over $1M from 2028) is stated for the Jones domicile answer; Colorado conservatorship for a minor ends at 21 and a guardian can be nominated in a will or another signed writing; Chen's ISO value uses a $2.80 409A common price instead of the $8.50 preferred price, and Chen and Jones vested counts follow the October 2026 vest schedule.
- **Refreshed for the updated engine**: figures were recomputed after per-person Social Security, banded capital-gains tax with NIIT, the ISO/AMT model, ACA by household size, DAF AGI limits and mortgage amortization. The Jones safe-harbor target is now the lower of 110% of last year's tax and 90% of this year's projected tax ($218,925), the Chen ISO answer gives an AMT estimate (about $67,900) instead of saying the app does not compute AMT, the Miller ACA bridge text describes the per-adult 65 rule and the credit that returns after the conversions end, and Ramirez and Taylor Social Security amounts follow their earnings (Miller and Ramirez use entered benefits).
- **Sample files (`sample_data/`)**: the W-2 and wage transcript show Box 1 wages net of the $23,000 deferral; the sample vault was regenerated from the seeded Miller household.

### Housekeeping
- **Account Categorization**: vehicle and private-investment detection now uses only generic keywords.
- **Voice Commands**: the advisor's voice commands ("compact this conversation", "start a fresh thread", "health check") use a shared generic vocabulary.
- **Public Repository**: history is consolidated into a single baseline commit; earlier release tags point at it.

### Data Integrity: Saves No Longer Read Older Encrypted Values as Zero
- **One Key Ring for Reads and Writes (`db/session.py`, `db/types.py`)**: older rows (for example gift amounts, compensation and equity grants) are still encrypted under the server root key. Read views decrypted them, but save operations opened their database session with the household key alone, so inside a save those rows read as `0` / empty. A save that copied or rewrote them (such as **Copy previous year** in Gifting) could store the blank value. Saves now use the same household-then-root key ring as reads; new values are still encrypted under the household key.
- **Fail Loud on Undecryptable Values (shared library)**: a value that cannot be decrypted now raises an error instead of silently reading as empty, so a key problem is caught rather than saved over.

### Security: `.fovault` Backups Now Require a Passphrase (Format v2)
- **Passphrase-Protected Export (`security/fovault_wrap.py`, `db/fovault_repo.py`, `services/fovault_service.py`, `routes/desktop.py`)**:
  - **Fixed**: any holder of a `.fovault` file could decrypt it. The embedded key was wrapped with a key derived from `FOVAULT_EXPORT_PASSPHRASE` (default empty), a fixed salt and 100k PBKDF2 rounds, and files could also carry a raw key. The environment default is removed.
  - Export requires a passphrase chosen per export (12-128 characters, confirmed). The key is wrapped with scrypt (N=2^17, r=8, p=1, random per-file salt) and AES-256-GCM; KDF parameters and `fovault_format: 2` are stored in the file and authenticated. The exported copy no longer carries the server-KEK escrow or the Local Desktop passphrase wrap. Export is now `POST /api/desktop/backup` (and `/api/sandbox/download-vault`); the passphrase travels only in the request body.
  - Restore requires the passphrase; a wrong one returns "Wrong passphrase." and writes nothing. The passphrase is never stored, logged, placed in the session or a job ticket.
  - Old-format files (empty-passphrase wrap, server-KEK escrow, raw key) are refused with a message naming the old unprotected format. Editors can import one with the explicit **Import an old-format backup** option, which is logged; the old format is never written again.
- **Sandbox Restore No Longer Puts the FEK in a Job Result (`routes/sandbox.py`, `services/desktop_service.py`)**: the async sandbox restore result previously carried `raw_fek_b64`, persisted in the job cache under the server root key for an hour, contradicting the browser-cookie-only key guarantee. The FEK is now unwrapped in the request and delivered only as the HttpOnly cookie on that response; job results hold ids and a redirect, and the polling request builds the summary.
- **UI (`templates/components/fovault_modals.html`, `static/js/fovault_vault.js`, `static/css/fovault_modals.css`)**: server-rendered export (passphrase + confirm) and restore (passphrase + old-format option) prompts.
- **Sample vault**: `sample_data/sample_family_vault.fovault` re-generated in format v2; its passphrase is documented in `sample_data/README.md`.

## [v0.5.4] - 2026-10-23

### Scenario Archiving, Drag-and-Drop Plan Reordering & Mobile Viewport Geometry
- **Scenario Archiving & Quick-Toggle Visibility (`services/scenario_archive_service.py`, `routes/scenarios.py`, `ssr/scenarios.py`, `ssr/scenarios_scorecard.py`, `templates/components/scenarios/scorecard.html`, `templates/components/scenarios/plan_card.html`, `static/js/scenarios/cards_scorecard.js`, `static/js/scenarios/modals_plan.js`)**:
  - **Non-Destructive Archiving**: Archive experimental or obsolete scenario plans without permanent deletion, keeping historical records intact while decluttering the active comparison workspace.
  - **Quick-Toggle Visibility & Dedicated Controls**: Toggle archived scenario visibility via `#btn-toggle-archived-scenarios` (`Show Archived (N)` / `Hide Archived (N)`), table row and plan card Archive/Unarchive action buttons, and an **Archive this scenario** checkbox in the Edit Plan modal.
  - **Safety Invariants**: Guarded against archiving `scen_baseline` and the active plan to ensure planning continuity.
- **Drag-and-Drop Plan Reordering & Instant Trajectory Synchronization (`services/scenario_reorder_service.py`, `routes/scenarios.py`, `static/js/scenarios/cards_reorder.js`, `templates/components/scenarios/scorecard.html`)**:
  - **Two-Way HTML5 Drag-and-Drop**: Reorder scenarios seamlessly using drag handles across both plan selector pills and comparison scorecard rows with keyboard accessibility.
  - **Immediate Trajectory Curve & Toggle Updates**: Reordering triggers immediate canvas re-rendering of 30-year net worth trajectory curves and scorecard toggles without requiring a page reload.
  - **Persistent Ordering**: Persists custom sort orders to `forecast_scenarios.sort_order` in the per-family database via `POST /api/scenarios/reorder`.
- **Mobile Viewport Overflow Remediation (`common/hvl_common/ui/settings_integrations.py`, `templates/components/scenarios/scorecard.html`)**:
  - **Small-Screen Viewport Containment**: Resolved 375px mobile viewport overflow for Siri integration token URLs and child plan selector badges with responsive wrapping, ellipsis clipping, and responsive padding.

## [v0.5.3] - 2026-10-23

### Company Equity Exercise & LTCG Exit Modeling, Conversational Scenario Assumptions, Notification Center & Siri Shortcuts
- **Company Equity Exercise, Hold & Long-Term Capital Gains Exit Modeling**:
  - **Four Holding, Exercise & Exit Strategies**: Model four distinct strategies for company equity life events: **Cashless Repurchase (Exercise & Sell All)**, **Exercise & Hold (Pay Strike & Tax from Cash)**, **Exercise & Hold (Sell-to-Cover Strike & Tax)**, and **Sell Held Shares Later (Post-Exercise Long-Term Capital Gains Exit)**—enabling two-stage plans where you exercise and hold options in one year to start the long-term capital gains clock and sell held shares in a later year or multi-year tranche taxed on the gain above the exercise-date value at the top 20% long-term capital gains rate plus the 3.8% NIIT for every household, plus WA state capital gains tax where applicable.
  - **Staged Tranches, Custom Equity Growth Overrides & Deficit Fallback**: Supports multi-year option and share-sale tranches, post-tax valuation of retained company shares and unexercised vested options in Net Worth projections, per-scenario Equity Growth Rate (`%`) overrides in the Edit Plan modal, and automatic company equity liquidation fallback to cover unfunded retirement deficits.
- **Conversational Scenario & Assumption Modeling & Independent Scenario Events**:
  - **Conversational Scenario & Assumption Modeling**: Ask the AI Financial Advisor to create, branch, or reset "what-if" child scenarios and adjust plan-level assumptions (retirement age, annual living spend, annual savings, withdrawal order, dynamic spending guardrails, or company equity growth rates) with Before vs. After net worth comparisons at ages 65, 85, and 95, plus drill into annual company equity cash flows or attach files and screenshots directly in chat.
  - **Independent Scenario Events & Collapsible Event Strip**: Editing a life event in one scenario automatically isolates that event so sibling scenarios that originally shared it remain unchanged, paired with a collapsible `SCENARIO EVENTS (N)` header strip and normalized custom SVG event icons.
- **Notification Center, Household Health Alerts & Lock-Screen Web Push**:
  - **Unified Header Bell & Slide-Out Drawer**: Combines background sync notifications (Monarch/SimpleFIN sync outcomes, unconfirmed account classifications) with automated household health checks (stale institutional syncs, quarterly Safe Harbor shortfalls, unreviewed readiness items) and optional browser/lock-screen Web Push alerts.
- **Siri & Apple Shortcuts Voice Queries & Installable Mobile PWA**:
  - **Hands-Free iPhone Action Button & Siri Integration**: Ask voice questions from Siri or the iPhone Action Button using a revocable Siri token minted in **Settings &rarr; Integrations**, alongside standalone mobile PWA installation.

## [v0.5.2] - 2026-10-21

### Modular Tabbed Settings Subnav, AI Advisor Model Tier Selector & Auto Index Classification
- **Responsive Menu Bar Auto-Collapse & Viewport Parity (`common/hvl_common/ui/static/components.css`, `static/css/theme.css`, `static/css/components_modals.css`)**:
  - **Medium Viewport Auto-Collapse (769px–1024px)**: Auto-collapses the left navigation sidebar to a sleek 68px icon rail across tablet and responsive desktop viewports, removing redundant CSS imports and ensuring un-clipped content bodies with full label suppression.
  - **Mobile Shell Isolation (≤768px)**: Guarantees complete sidebar suppression (`display: none !important`) on mobile viewports in favor of the mobile navigation select header, preventing viewport overflow and layout bleed.
- **Modular Tabbed Settings Experience (`templates/components/settings.html`, `common/hvl_common/ui/settings.py`, `common/hvl_common/ui/settings_household.py`)**:
  - **Shared 4-Tab Subnav & Layout**: Refactored Settings into responsive tabbed sections (Appearance, Household & Access, Integrations, and System/Data) backed by `hvl_common` tabbed subnav routing, unified theme choice cards, dedicated household member role cards, security vault status, and AI quota telemetry.
- **AI Financial Advisor Model Tier Selector (`services/advisor/chat_service.py`, `templates/components/ai_advisor_drawer.html`, `static/js/ai_advisor.js`)**:
  - **Runtime Model Switcher**: Added in-drawer runtime tier selector supporting Gemini 2.5 Flash Lite (default, high-throughput), Gemini 2.5 Flash, Gemini 2.5 Pro, and Gemma 2 9B.
  - **Persistence & Graceful Fallback**: Preserves selected model tier across sessions via `localStorage`, hosts the selector in the full-width chat policy toolbar to prevent clipping on mobile viewports, and automatically applies tool-free fallback for lightweight models.
- **Automatic Index Fund & Cash Sweep Classification (`account_sync/allocation.py`, `db/accounts.py`)**:
  - **Asset Allocation Normalization**: Automatically classifies ubiquitous index ETFs, broad-market mutual funds, and Treasury money market cash sweep instruments (`VTI`, `VOO`, `VIIIX`, `FXAIX`, `FSKAX`, `SWTSX`, `VXUS`, `VEA`, `BND`, `AGG`, `VUSXX`, `FDLXX`, `SPAXX`) into correct asset classes during Monarch sync and holding normalization.

## [v0.5.1] - 2026-10-20

### Personal Assistant MCP Gateway, Chief of Staff Executive Radar & Ephemeral Life-Event Simulation
- **Personal Assistant MCP Gateway (`services/mcp_service.py`, `routes/mcp.py`, `templates/components/settings/_mcp_assistant.html`, `common/hvl_common/mcp/`)**:
  - **Streamable HTTP JSON-RPC 2.0 Endpoint (`POST /mcp`)**: Exposes a permissioned Model Context Protocol server (`hvl-family-office`) so external AI assistants can query household financial state and run ephemeral simulations without consuming server-side LLM tokens.
  - **Zero-Knowledge Token-Wrapped Vault Encryption & Mutation Firewall**: Wraps the household vault encryption key (`vault_fek`) at token-mint time using `Fernet(SHA256(raw_token + server_secret))` so only a caller presenting the raw `hvl_mcp_...` bearer token can unwrap the household vault in memory, while enforcing a strict two-layer mutation firewall (`read` and `simulate` tiers only; `mutate` tools remain unexposed over MCP).
  - **Per-User Settings Controls**: Added a **Personal AI Assistant (MCP Gateway)** card under **Settings &rarr; Integrations** with per-user enable/disable toggle, `Read-Only` vs. `Read + Ephemeral Simulation` scope selector, 1-click token mint/rotate/revoke, and copyable MCP configuration snippets.
- **Chief of Staff Executive Radar, Annual Cash Flow Waterfall & Ephemeral Life-Event Tools (`services/advisor/tools_chief_of_staff.py`, `services/advisor/tools_tabs.py`)**:
  - **25-Tool AI Financial Advisor (`get_chief_of_staff_radar`, `get_annual_cash_flow_detail`, `simulate_life_event_impact`)**: Expanded the advisor tool suite to 25 deterministic tools (21 non-mutating; 20 of them exposed via MCP):
    - `get_chief_of_staff_radar`: Single-call executive briefing aggregating institutional sync freshness (Monarch/SimpleFIN), Household Readiness Audit action items, pending Tax Season Checklist items (`Waiting`), quarterly Safe Harbor shortfall alerts, Private Markets LP unfunded capital calls & stale NAV marks, and remaining DAF/annual gift exclusion headroom.
    - `get_annual_cash_flow_detail`: Year-by-year and age-by-age cash-flow waterfall and balance-sheet drilldown across any named scenario.
    - `simulate_life_event_impact`: Ephemeral in-memory life-event and Monte Carlo simulation (`persisted_to_db: False`) returning Before vs. After net worth deltas at ages 65/85/95 and solvency probability impact without altering saved plans.

## [v0.5.0] - 2026-10-20

### Overview Graph Widgets, Unbundled Forecasting, AI Scenario Event Manager, Survivorship Audit & LP Commitment Book
- **Customizable Overview Graph Widgets, Unbundled Forecasting Charts & Collapsible Domain Graphs (`ssr/widgets.py`, `ssr/widgets_charts.py`, `static/js/widget_charts.js`, `static/js/scenarios/charts/`)**:
  - **4 Opt-In Overview Graph Widgets**: Added 4 opt-in Overview graph widgets (`Multi-Scenario Lifetime Net Worth Forecast` with interactive scenario switcher pills, `Active Plan Cash Flow & Tax Drawdown`, `Monte Carlo Wealth Fan P10–P90`, and `Career Compensation Trajectory`).
  - **Unbundled Reorderable Forecasting Canvas**: Retired the single-view `canvas_lenses.html` switcher in favor of simultaneous reorderable Forecasting canvas widgets (`Lifetime Net Worth Trajectory` locked as Core alongside companion `Annual Cash Flow & Tax Drawdown` with `Timeline Bars | Single-Year Sankey` toggle, `Monte Carlo Wealth Fan P10–P90` with `Parametric | Historical (1928–2025)` toggle, and `Actuarial Longevity Survival Curve`).
  - **Persistent Collapsible Domain Graphs & Demo Layout State**: Added persistent collapsible chart toggles across Holdings, Equity, Compensation, and Philanthropy, plus session-scoped widget/chart customization persistence for Demo and Viewer sessions.
- **AI Advisor Multi-Scenario Event Manager, Operational Tools & Dynamic Bracket-Fill Roth Conversions (`services/advisor/tools_scenarios.py`, `services/advisor/tools_operations.py`, `forecast/scenarios.py`)**:
  - **19-Tool AI Financial Advisor (`manage_scenario_life_event`, `get_private_markets_lp_book`, `manage_lp_commitment`, `update_tax_document_checklist_status`, `audit_household_risks`)**: Expanded the advisor tool suite from 14 to 19 deterministic Python tools—enabling conversational multi-scenario lookup by name (`scenarios_by_name`), life event creation/editing/branching with Before vs. After net worth and FI crossover deltas, private markets LP commitment book queries and upserts, and tax season document status updates.
  - **Dynamic Tax-Bracket-Fill Roth Conversions**: Upgraded scenario Roth conversion events to support dynamic annual ceiling presets (`auto_bracket_12`, `auto_bracket_22`, `auto_bracket_24`, and `auto_bracket_32`) that compute remaining statutory Federal ordinary-income headroom each projection year after salary and an estimated 2% yield on the liquid balance (RSU vests and RMDs are not counted).
- **Survivorship, Probate & Household Readiness Audit (`services/household_audit_service.py`, `routes/estate.py`, `templates/components/estate.html`)**:
  - **Deterministic 8-Rule Readiness Engine & Custodian Verification (`✓ Mark Verified`)**: Evaluates live household accounts, titling, beneficiaries, liquid cash reserves, single-stock concentration, 90-day RSU supplemental withholding gaps, tax-advantaged cash drag, and 529 coverage—surfacing a composite `0–100` Readiness Score on the **Estate & Generational Wealth** tab and as an optional **Overview** dashboard widget (`ov_needs_attention`), complete with deep-link action buttons to affected accounts and persistent `✓ Mark Verified` custodian sign-off.
  - **AI Advisor Risk Audit (`audit_household_risks`)**: Exposed the deterministic audit engine and verified finding state to the AI Modeling Assistant for household risk diagnostics.
- **Private Investment / LP Commitment Book & Scenario Stress Test (`services/private_markets_service.py`, `templates/components/holdings_breakdown.html`)**:
  - **Per-Investment LP Annotations & Multiples**: Annotate private equity, venture, private credit, and real estate commitments (`Committed`, `Called`, `Unfunded`, `Distributions`, `Current NAV`, `Vintage Year`, `Expected Call Horizon`, `Last Mark Date` with *"Oldest Mark Wins"* staleness tracking, and `K-1 Status`) with automatic **DPI**, **RVPI**, and **TVPI (MOIC)** calculation.
  - **Scenario Cash-Flow & 18-Month Stress Toggle**: Wires unfunded LP capital call schedules directly into the multi-year scenario cash-flow waterfall, with a per-plan stress toggle to accelerate unfunded capital calls into the next 18 months.
- **Per-Plan Drawdown Order Override (`forecast/waterfall.py`, `templates/components/scenarios/plan_card_assumptions.html`)**:
  - **Configurable Withdrawal Sequencing**: Choose between `Taxable → Pre-Tax → Roth (Standard)`, `Pre-Tax First (Bracket Fill)`, or `Pro-Rata Blend (Taxable + Pre-Tax) → Roth` per scenario to compare retirement drawdown tax efficiency side-by-side.
- **Auto-Derived Tax Season Checklist, Monarch Core Burn Calibrator & Peer DB Sync Hardening (`services/tax_checklist_service.py`, `db/session.py`, `db/users.py`)**:
  - **Tax Season Readiness Checklist**: Automatically derives expected annual tax forms (`Form W-2`, `1099-Consolidated`, `1099-INT`, `Form 3921`, `Schedule K-1`, `Form 1099-Q`, `Form 1098`, `Form 8283`) from active household records with clickable `Waiting → Received → Sent to CPA` status tracking.
  - **Monarch Core Burn Auto-Calibrator & Freshness Badges**: Computes steady-state living burn from trailing 12-month Monarch cash flows (automatically stripping out Mortgage P&I and Kids/Education outflows) with 1-click baseline calibration and institutional sync freshness/staleness indicators.
  - **Non-Destructive Peer DB Auth Sync**: Replaced `INSERT OR REPLACE` in `_sync_auth_records_to_peer_db` with `ON CONFLICT DO UPDATE` so cross-DB auth synchronization never triggers `ON DELETE CASCADE` on domain tables, and added automatic self-healing from per-family DB snapshots when `global.db` is missing a household row.

## [v0.4.1] - 2026-10-19

### Customizable Dashboard Widgets, Streamlined Forecasting Layout & Domain-Scoped Fragment Caching
- **Customizable & Drag-and-Drop Widgets (`ssr/widgets.py`, `static/js/overview.js`)**:
  - **Per-Household Widget Customizer**: Added an explicit **Customize Widgets** edit mode on **Overview** and **Longevity & Scenarios** to toggle optional analytics widgets (for example Steady-State FIRE Burn Waterfall, Roth Conversion & Tax-Bracket Window, Historical Cohort Backtest, Company Equity & Post-Tax Liquidity, and Pre-65 Healthcare Bridge) and reorder cards via desktop/mobile drag-and-drop (`⋮⋮ Drag`) or keyboard arrow keys.
- **Forecasting Canvas Streamlining (`templates/components/scenarios/canvas_lenses.html`)**:
  - **Promoted Multi-Lens Forecast Graph**: Removed the duplicate top Timeline Ribbon & Scrubber Bar so the primary Multi-Lens Trajectory Canvas sits directly beneath the scenario header, with the view mode (`Timeline Bars | Single-Year Sankey`) and scenario curve toggles anchored on a dedicated row.
  - **1-Click Market Return Presets**: Added quick-select market return profiles (**Conservative**, US equities 6.5%; **Historical Baseline**, 8.5%; and **Aggressive Growth**, 10.0%) inside the Advanced Levers drawer.
- **AI Advisor & Domain-Scoped Fragment Cache (`services/advisor/`, `forecast/cache.py`)**:
  - **Advisor Historical Backtest & Guardrails Context**: Exposed 1928–2025 rolling cohort survival rates, named historical stress cohorts, and active dynamic spending guardrail settings to the AI Advisor simulation tools.
  - **Domain-Scoped L1 HTML Fragment Cache**: Scoped server-side L1 fragment cache keys to each tab's declared domain dependencies (`FRAGMENT_ETAG_DOMAINS`) so mutations in unrelated modules no longer evict cached HTML fragments across the portal.

## [v0.4.0] - 2026-10-19

### 1928–2025 Historical Backtesting, Cash-Flow Sankey, Spending Guardrails & Scenario Playbooks
- **1928–2025 Historical Cohort Backtesting Engine (`forecast/historical_cohorts.py`)**:
  - **Rolling Historical Regime Replay**: Simulates retirement and multi-decade wealth trajectories against every rolling historical start year from 1928 through 2025 using actual S&P 500 total returns, 10-Year US Treasury bond returns, and CPI inflation series.
  - **Interactive Lens Toggle & Stress Cohorts**: Switch directly between `Parametric (1,000-Trial Monte Carlo)` and `Historical (1928–2025 Backtest)` on the Longevity & Scenarios canvas, highlighting named historical stress cohorts (**1929 Great Depression**, **1966 Stagflation**, **2000 Dot-Com Peak**, and **2008 Global Financial Crisis**) alongside the 10th–90th percentile corridor and an expandable **Tall Chart** view.
- **Single-Year Cash-Flow Sankey Waterfall (`static/js/scenarios/charts/cash_flow_sankey.js`)**:
  - **Full-Width Horizontal Flow Diagram**: Visualizes year-by-year cash inflows (W-2 salary, RSU/equity vests, Social Security, and portfolio drawdowns) flowing through statutory tax drags (Federal, State, FICA, NIIT) and living/milestone outflows into net savings reinvestment across any selected projection year.
- **Dynamic Spending Guardrails & Early-Retirement Event Presets**:
  - **Per-Plan Dynamic Spending Guardrails**: Choose a per-scenario spending guardrail mode (**Off**, **Moderate**, or **Aggressive**; fixed thresholds, not configurable) that trims portfolio withdrawals in down markets: Moderate cuts 15% when the portfolio is more than 15% below its peak; Aggressive cuts 25% at that point and 15% when it is more than 10% below its peak.
  - **Pre-65 ACA Healthcare Bridge & IRS Rule 72(t) SEPP Presets**: Added one-click Life Event Wizard presets for modeling pre-Medicare ACA marketplace health insurance bridges (`Age < 65`) and Substantially Equal Periodic Payments (`IRC § 72(t)` SEPP) from pre-tax retirement accounts prior to age `59.5` without the 10% early withdrawal penalty.
- **Scenario Planning Playbooks (`/playbooks`)**:
  - **Step-by-Step Modeling Recipes**: Added a standalone `/playbooks` guide covering 6 common household planning workflows: Early Retirement & Pre-65 ACA Bridge, Roth Conversion Ladders, Rule 72(t) SEPP Penalty-Free Access, Private/Public Equity Windfalls, Multi-State Domicile Relocation, and Dynamic Spending Guardrails—linked contextually across the scenario planner, `/help`, and `/projectionlab`.

## [v0.3.1] - 2026-10-19

### Bug Fixes & Polish
- **SimpleFIN Sync & Account Categorization**:
  - Fixed SimpleFIN Setup Token linking and initial sync when running inside an Anonymous Workspace.
  - Improved account detection so high-yield savings, checking, and cash management accounts holding money-market sweep funds categorize under **Cash / Depository** instead of **Brokerage**.
- **General Bug Fixes & Performance**:
  - Fixed dashboard cards and sidebar account counts not updating immediately after adding/deleting accounts or importing CSVs.
  - Fixed empty workspaces showing non-zero placeholder numbers before accounts or income are entered.
  - Fixed sub-navigation bar links jumping when scrolling to page sections, and improved tab switching speed on cached views.

## [v0.3.0] - 2026-10-18

### Open Cloud Vaults, Anonymous Workspace & In-Pane Calculation Triage
- **Cloud Vault Now Open to All Users — Two First-Class Web Modes (`/login` & `/sandbox`)**:
  - **Open Self-Serve Cloud Vault (`Cloud Vault Sign In`)**: Hosted Cloud Vaults are now open to everyone without a private-alpha invite code. Signing in with Google automatically provisions an isolated, encrypted household database saved across sessions and devices, with optional spouse/partner access and your 256-bit decryption key stored in your personal Google Drive (`appDataFolder`).
  - **Equal-Prominence Anonymous Workspace (`/sandbox`)**: Side-by-side on `/login` with Cloud Vault Sign-In, the Anonymous Workspace lets you use every planning tool immediately (scenario branching, Monarch/SimpleFIN sync, and AI Advisor) with no login required, browser-cookie-only key retention, and automatic 24-hour (or 7-day) server auto-wipe.
  - **Full `.fovault` Portability Across All Modes**: Whether you use a persistent Cloud Vault, an ephemeral Anonymous Workspace, or the 100% offline macOS/Windows Desktop App, you can download or restore an encrypted `.fovault` file at any time to move between modes or keep a permanent copy on your computer. (Hosted cloud storage is provided as a free, non-commercial hobby project; vaults inactive for `365+` days may be deleted.)
- **In-Pane Bug Reporter & AI Calculation Triage**:
  - **Contextual Card-Header Reporting**: Every domain view (Overview, Accounts, Scenarios, Equity, Compensation, Estate, State Tax Arbitrage, 529 Education, Philanthropy, Gifting, and Settings) includes a contextual report trigger that captures the active pane and view state.
  - **Live Engine Math Verification (`Verify Math / Explain`)**: Before filing a report, users can invoke deterministic Python engine reconciliation against their live household snapshot to verify how statutory tax brackets, safe-harbor rules, or scenario cash flows were calculated.
  - **Anonymized & Scaled Snapshot Preview**: Submitting a bug report scrubs personal names, emails, and institutions (`Person_A`, `Institution_1`) and multiplies monetary balances by a random obfuscation factor (a random factor between `0.37x` and `0.83x`) so mathematical ratios are preserved without exposing real net worth, with a full JSON preview before submission.

## [v0.2.0] - 2026-10-17

### Interactive Ephemeral Sandbox, 14-Tool AI Advisor & Performance
- **Interactive Ephemeral Web Sandbox (`/sandbox`)**:
  - **Zero-Credential Household Trial**: Instant sandbox session requiring no Google sign-in or invite code, running against an isolated `sandbox` database universe (`data/families_sandbox/{id}.db`).
  - **Browser-Cookie-Only Encryption**: The household vault encryption key is retained exclusively in an encrypted browser cookie and is physically `NULL` on server disk (`encryption_key_enc = NULL`), preventing persistent server-side key retention.
  - **Lifecycle Automation & Portability**: Automatic 24-hour auto-wipe timer with real-time countdown banner, optional one-click 7-day lease extension ("Save for 7 Days"), instant self-service purge ("Wipe & Exit Now"), and full `.fovault` backup export and restore to migrate sandbox data into local desktop or permanent accounts.
  - **Resumable Session Detection**: Login page detects active unexpired sandbox cookies with countdown indicators and direct "Resume Active Sandbox" routing.
- **Comprehensive 14-Tool AI Financial Advisor**:
  - **Full-Domain Tab Coverage**: Expanded callable tool suite from 7 to 14 deterministic Python functions, granting the advisor direct query access to all application domains: Accounts & Balance Sheet (`get_accounts_and_balance_sheet`), Longevity & Scenarios (`get_scenarios_and_forecast_plan`), Career Compensation & 110% Safe Harbor Withholding (`get_compensation_and_tax_withholding`), Multi-State Tax Arbitrage & Outflows (`get_state_tax_arbitrage`), Education 529 & College Funding (`get_education_529_plan`), Philanthropy & DAF Grants (`get_philanthropy_and_daf_summary`), and Intergenerational Gifting & IRS Form 709 (`get_family_gifting_summary`).
  - **Tab-Aware Suggestion Chips & Deterministic Fallbacks**: `/api/ai-advisor/context` dynamically generates contextual question chips tailored to the active tab, backed by deterministic tabular fallback responses when running without external API keys or in demo mode.
- **Local Desktop Mode & Portable Vault Migration**:
  - **1-Click Guided Setup Restore**: Added a direct "Already have a .fovault backup? Upload .fovault" option to Step 1 of the Guided Setup wizard (for both Local Desktop and Cloud Sandbox) to restore existing household databases and skip onboarding.
  - **Asynchronous Vault Restoration**: Added background-job-backed vault restore (`/api/desktop/restore_async`) with pre-restore safety snapshots (`pre_restore_*.fovault`) and cross-instance family ID remapping.
- **HTTP Caching & Performance (`state_version` ETag)**:
  - **Conditional ETag Short-Circuiting**: Tab fragments (`/fragments/*`) and dashboard read APIs (`/api/dashboard`, `/api/networth/history`) emit weak `ETags` keyed on household `state_version`. Unchanged navigation requests short-circuit before database queries or SSR rendering with `304 Not Modified` (`0 B` body).
  - **Immutable Static Asset Headers**: Upgraded `/static/*`, `/common/*`, and root icon routes to `Cache-Control: public, max-age=2592000, immutable`, eliminating redundant HTTP revalidation requests on repeat page loads.
  - **Dynamic Route-Aware Caching**: Dynamic HTML responses preserve explicit route headers, while API JSON responses default to `Cache-Control: private, no-cache`.
- **Deployment Resilience & Session Tagging**:
  - **In-App Deployment Notification Pill**: `X-App-Version` response headers trigger a non-disruptive header pill (`✨ Update available — Reload`) when a new backend release is deployed, letting active sessions reload at convenience.
  - **Transient Deploy Auto-Retry**: Client-side HTMX requests automatically retry once after a 1.2-second delay upon encountering transient `502` or `503` responses during Gunicorn worker reloads.
- **Responsive Mobile & Header Polish**:
  - **Mobile Onboarding Wizard**: Responsive flex wrapping and touch-target sizing for the 4-step Guided Setup wizard across narrow smartphone viewports.
  - **Responsive Header Banner**: Sandbox expiry countdown, lease controls, and sync buttons wrap cleanly on mobile screens without horizontal clipping.

## [v0.1.0] - 2026-10-16

### Initial Public Preview (Alpha) — Initial Release Baseline
- **Local Desktop Mode & Encrypted Vault (`.fovault`)**:
  - Standalone zero-cloud desktop runtime (`LOCAL_MODE=1`) for macOS (`.dmg`) and Windows (`.exe`) storing per-household SQLite vaults in standard OS application data directories (`~/Library/Application Support/HVLFamilyOffice` on macOS, `%LOCALAPPDATA%\HVLFamilyOffice` on Windows).
  - Offline Passphrase / PIN key derivation using `PBKDF2-HMAC-SHA256` (600,000 iterations) wrapping the household's random Fernet (AES-128-CBC + HMAC-SHA256) vault key, with automatic pre-migration `.fovault` snapshots and one-click encrypted backup/restore.
  - Loopback-by-default (`127.0.0.1`) network binding with `Host` header DNS-rebinding protection and optional 10-minute single-use QR pairing for mobile devices on local Wi-Fi or Tailscale.
- **Account Aggregation, Onboarding & CSV Data Portability**:
  - **Multi-Provider `Sync Accounts`**: Read-only token exchange supporting 16,000+ North American banks and brokerages via **SimpleFIN Bridge**, headless GraphQL sync with **Monarch Money**, and manual account tracking with automatic historical balance series reconstruction across `Annual`, `Quarterly`, and `Monthly` views.
  - **Full CSV Import & Export**: Round-trip CSV import and export for account balance histories (`Date, Account, Balance` or multi-column tables) and 30-year deterministic scenario cash-flow/tax projections.
  - **4-Step Guided Setup & Help Manual (`/help`)**: Interactive onboarding wizard covering household and tax profile, family members, accounts and balances, and income and retirement targets (IRS transcript and W-2 PDF ingestion and the Gemini API key are configured afterward in Settings).
- **Deterministic Financial, Tax, Equity & Estate Engines**:
  - **30-Year Branching Scenarios & Stochastic Monte Carlo**: Side-by-side life-event scenario trees and vectorized 1,000-trial NumPy simulations across Taxable, Pre-Tax (`401k`/`IRA`), and Tax-Free (`Roth`) pools with Roth conversion ladders, state tax domicile comparisons, 529 college funding waterfalls, and dynamic spending guardrails.
  - **Executive Compensation, Equity & Statutory Taxes**: RSU/ISO/NSO vesting and refresh grant waterfalls, statutory supplemental withholding gap calculations, quarterly safe-harbor estimated tax schedules, and Federal + California tax and NIIT modeling (AMT is not computed).
  - **Estate, Trust & Philanthropy Modeling**: Estate distribution flowcharts, an exemption rollback stress test (the lifetime exemption is permanent under OBBBA), annual exclusion gifting trackers, and Donor-Advised Fund (DAF) bunching projections.
- **AI Financial Advisor & Cryptographic Release Provenance**:
  - **Context-Grounded AI Advisor**: Deterministic financial scope guardrails and two-tier household rate quotas (`5 req/min, 30 req/hr` on the shared cloud server key; `30 req/min, 300 req/hr` with a BYO Gemini API key or in Local Desktop Mode).
  - **SLSA Build Provenance & Checksums**: Native macOS and Windows installers built via GitHub Actions and attested with cryptographic **SLSA Build Provenance** (`gh attestation verify --owner High-Velocity-Labs`) and `SHA256SUMS.txt`.
