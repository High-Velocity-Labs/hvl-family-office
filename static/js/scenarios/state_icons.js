/**
 * Scenario Event & Milestone SVG Icons and Canvas Images
 */

const svgWrap = (size, inner) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: -2px; flex-shrink: 0;">${inner}</svg>`;

export const EVENT_SVG_MAP = {
    // Existing & Core Categories + evt-* Semantic Keys
    'evt-equity': (size = 14) => svgWrap(size, `<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/><polygon points="13.5 15.5 23 6 23 18 1 18" fill="currentColor" fill-opacity="0.16" stroke="none"/>`),
    'company_equity': (size = 14) => EVENT_SVG_MAP['evt-equity'](size),
    'equity': (size = 14) => EVENT_SVG_MAP['evt-equity'](size),

    'evt-travel': (size = 14) => svgWrap(size, `<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3.5c-.5-.5-2.5 0-4 1.5L13.5 8.5 5.3 6.7c-.8-.2-1.6.2-2 1l-.3.5 6 4-3.5 3.5-3-.5-.7.7 2.5 1.5 1.5 2.5.7-.7-.5-3 3.5-3.5 4 6 .5-.3c.8-.4 1.2-1.2 1-2z" fill="currentColor" fill-opacity="0.16"/>`),
    'lifestyle': (size = 14) => EVENT_SVG_MAP['evt-travel'](size),
    'travel_surge': (size = 14) => EVENT_SVG_MAP['evt-travel'](size),

    'evt-real-estate': (size = 14) => svgWrap(size, `<path d="M3 10.5 12 3l9 7.5v10a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 20.5v-10z" fill="currentColor" fill-opacity="0.16"/><polyline points="9 22 9 12 15 12 15 22"/><line x1="18" y1="5.5" x2="18" y2="3"/>`),
    'real_estate': (size = 14) => EVENT_SVG_MAP['evt-real-estate'](size),

    'evt-debt': (size = 14) => svgWrap(size, `<rect x="2" y="5" width="20" height="14" rx="2" fill="currentColor" fill-opacity="0.16"/><line x1="2" y1="10" x2="22" y2="10"/><path d="m14 15 2 2 4-4"/>`),
    'debt_payoff': (size = 14) => EVENT_SVG_MAP['evt-debt'](size),

    'evt-refi': (size = 14) => svgWrap(size, `<path d="M21.5 2v6h-6"/><path d="M2.5 22v-6h6"/><path d="M2 11.5a10 10 0 0 1 18.8-4.3L21.5 8"/><path d="M22 12.5a10 10 0 0 1-18.8 4.3L2.5 16"/>`),
    'refinance': (size = 14) => EVENT_SVG_MAP['evt-refi'](size),

    'evt-k12': (size = 14) => svgWrap(size, `<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" fill="currentColor" fill-opacity="0.16"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" fill="currentColor" fill-opacity="0.16"/>`),
    'education': (size = 14) => EVENT_SVG_MAP['evt-k12'](size),

    'evt-college': (size = 14) => svgWrap(size, `<polygon points="12 3 1 9 12 15 23 9 12 3" fill="currentColor" fill-opacity="0.18"/><path d="M5 11.2v5.3c0 2.2 3.1 4 7 4s7-1.8 7-4v-5.3"/><path d="M23 9v7"/>`),
    'college': (size = 14) => EVENT_SVG_MAP['evt-college'](size),

    'evt-gifting': (size = 14) => svgWrap(size, `<polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5" fill="currentColor" fill-opacity="0.18"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>`),
    'gifting': (size = 14) => EVENT_SVG_MAP['evt-gifting'](size),
    'gifting_throughline': (size = 14) => EVENT_SVG_MAP['evt-gifting'](size),

    'evt-eldercare': (size = 14) => svgWrap(size, `<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" fill="currentColor" fill-opacity="0.16"/><polyline points="8 10 10.5 13 13.5 7 16 10"/>`),
    'eldercare': (size = 14) => EVENT_SVG_MAP['evt-eldercare'](size),
    'parent_care': (size = 14) => EVENT_SVG_MAP['evt-eldercare'](size),

    'evt-capital-outflow': (size = 14) => svgWrap(size, `<circle cx="12" cy="12" r="10" fill="currentColor" fill-opacity="0.16"/><polyline points="17 12 17 17 12 17"/><line x1="7" y1="7" x2="17" y2="17"/>`),
    'capital_outflow': (size = 14) => EVENT_SVG_MAP['evt-capital-outflow'](size),
    'withdrawal': (size = 14) => EVENT_SVG_MAP['evt-capital-outflow'](size),

    'evt-capital-inflow': (size = 14) => svgWrap(size, `<circle cx="12" cy="12" r="10" fill="currentColor" fill-opacity="0.16"/><polyline points="7 12 7 7 12 7"/><line x1="17" y1="17" x2="7" y2="7"/>`),
    'capital_inflow': (size = 14) => EVENT_SVG_MAP['evt-capital-inflow'](size),
    'custom_spike': (size = 14) => EVENT_SVG_MAP['evt-capital-inflow'](size),
    'windfall': (size = 14) => EVENT_SVG_MAP['evt-capital-inflow'](size),

    'evt-other': (size = 14) => svgWrap(size, `<polygon points="12 2 20 7 20 17 12 22 4 17 4 7 12 2" fill="currentColor" fill-opacity="0.16"/><circle cx="12" cy="12" r="3"/>`),
    'other': (size = 14) => EVENT_SVG_MAP['evt-other'](size),

    // New Curated Semantic Icons + Category Aliases
    'evt-vacation-home': (size = 14) => svgWrap(size, `<path d="M3 12l9-7 9 7v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-8z" fill="currentColor" fill-opacity="0.18"/><circle cx="18" cy="5" r="2.5"/><path d="M9 21v-6h6v6"/>`),
    'vacation_home': (size = 14) => EVENT_SVG_MAP['evt-vacation-home'](size),

    'evt-home-sale': (size = 14) => svgWrap(size, `<path d="M3 10.5 12 3l9 7.5v10a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 20.5v-10z" fill="currentColor" fill-opacity="0.18"/><path d="M9 14h6"/><path d="m12 11 3 3-3 3"/>`),
    'home_sale': (size = 14) => EVENT_SVG_MAP['evt-home-sale'](size),

    'evt-renovation': (size = 14) => svgWrap(size, `<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" fill="currentColor" fill-opacity="0.18"/>`),
    'home_renovation': (size = 14) => EVENT_SVG_MAP['evt-renovation'](size),

    'evt-house-key': (size = 14) => svgWrap(size, `<circle cx="7.5" cy="15.5" r="4.5" fill="currentColor" fill-opacity="0.18"/><path d="m10.7 12.3 9.3-9.3"/><path d="m17 6 3 3"/><path d="m14 9 2.5 2.5"/>`),
    'child_home_gift': (size = 14) => EVENT_SVG_MAP['evt-house-key'](size),

    'evt-solar': (size = 14) => svgWrap(size, `<circle cx="12" cy="12" r="5" fill="currentColor" fill-opacity="0.18"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>`),
    'solar_energy': (size = 14) => EVENT_SVG_MAP['evt-solar'](size),

    'evt-wedding': (size = 14) => svgWrap(size, `<circle cx="9" cy="14" r="5" fill="currentColor" fill-opacity="0.18"/><circle cx="15" cy="14" r="5" fill="currentColor" fill-opacity="0.18"/><polygon points="12 3 14.5 6 12 8.5 9.5 6 12 3"/>`),
    'wedding': (size = 14) => EVENT_SVG_MAP['evt-wedding'](size),

    'evt-celebration': (size = 14) => svgWrap(size, `<path d="M12 3l1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3L12 3z" fill="currentColor" fill-opacity="0.18"/><path d="M5 3v4"/><path d="M3 5h4"/><path d="M19 17v4"/><path d="M17 19h4"/>`),

    'evt-baby': (size = 14) => svgWrap(size, `<path d="M4 11h16a1 1 0 0 1 1 1v.5a7.5 7.5 0 0 1-15 0V11z" fill="currentColor" fill-opacity="0.18"/><path d="M12 11V4a7 7 0 0 1 7 7"/><path d="M2 7h3l1 4"/><circle cx="8" cy="20" r="2"/><circle cx="17" cy="20" r="2"/>`),
    'new_child': (size = 14) => EVENT_SVG_MAP['evt-baby'](size),

    'evt-grad-school': (size = 14) => svgWrap(size, `<path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6z" fill="currentColor" fill-opacity="0.18"/><line x1="8" y1="9" x2="16" y2="9"/><line x1="8" y1="13" x2="13" y2="13"/><circle cx="16" cy="16" r="2.5"/><path d="M15 18.2V22l1-1 1 1v-3.8"/>`),
    'grad_school': (size = 14) => EVENT_SVG_MAP['evt-grad-school'](size),

    'evt-medical': (size = 14) => svgWrap(size, `<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" fill="currentColor" fill-opacity="0.18"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>`),
    'medical_expense': (size = 14) => EVENT_SVG_MAP['evt-medical'](size),

    'evt-pet': (size = 14) => svgWrap(size, `<circle cx="12" cy="16" r="4" fill="currentColor" fill-opacity="0.18"/><circle cx="6.5" cy="11" r="1.8"/><circle cx="10" cy="8" r="1.8"/><circle cx="14" cy="8" r="1.8"/><circle cx="17.5" cy="11" r="1.8"/>`),

    'evt-car': (size = 14) => svgWrap(size, `<path d="M5 17h14v-5l-2-5H7L5 12v5z" fill="currentColor" fill-opacity="0.18"/><line x1="2" y1="17" x2="22" y2="17"/><circle cx="7.5" cy="17.5" r="2.5"/><circle cx="16.5" cy="17.5" r="2.5"/>`),
    'vehicle_purchase': (size = 14) => EVENT_SVG_MAP['evt-car'](size),

    'evt-yacht': (size = 14) => svgWrap(size, `<polygon points="12 3 4 15 12 15 12 3" fill="currentColor" fill-opacity="0.18"/><polygon points="14 6 20 15 14 15 14 6" fill="currentColor" fill-opacity="0.18"/><path d="M2 18h20l-2 3H4l-2-3z"/>`),
    'yacht_vessel': (size = 14) => EVENT_SVG_MAP['evt-yacht'](size),

    'evt-globe': (size = 14) => svgWrap(size, `<circle cx="12" cy="12" r="10" fill="currentColor" fill-opacity="0.18"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>`),

    'evt-art': (size = 14) => svgWrap(size, `<polygon points="6 3 18 3 22 9 12 22 2 9 6 3" fill="currentColor" fill-opacity="0.18"/><line x1="2" y1="9" x2="22" y2="9"/><polyline points="12 22 8 9 12 3 16 9 12 22"/>`),
    'major_purchase': (size = 14) => EVENT_SVG_MAP['evt-art'](size),

    'evt-mountain': (size = 14) => svgWrap(size, `<polygon points="8 3 2 19 14 19 8 3" fill="currentColor" fill-opacity="0.18"/><polygon points="16 8 11 19 22 19 16 8" fill="currentColor" fill-opacity="0.18"/>`),

    'evt-briefcase': (size = 14) => svgWrap(size, `<rect x="2" y="7" width="20" height="14" rx="2" fill="currentColor" fill-opacity="0.18"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/><line x1="2" y1="12" x2="22" y2="12"/>`),
    'sabbatical': (size = 14) => EVENT_SVG_MAP['evt-briefcase'](size),
    'income_change': (size = 14) => EVENT_SVG_MAP['evt-briefcase'](size),

    'evt-rocket': (size = 14) => svgWrap(size, `<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z" fill="currentColor" fill-opacity="0.18"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>`),
    'angel_investment': (size = 14) => EVENT_SVG_MAP['evt-rocket'](size),

    'evt-trophy': (size = 14) => svgWrap(size, `<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" fill="currentColor" fill-opacity="0.18"/>`),

    'evt-business-sale': (size = 14) => svgWrap(size, `<rect x="3" y="3" width="12" height="18" rx="1" fill="currentColor" fill-opacity="0.18"/><line x1="7" y1="7" x2="11" y2="7"/><line x1="7" y1="11" x2="11" y2="11"/><line x1="7" y1="15" x2="11" y2="15"/><circle cx="18" cy="16" r="4" fill="currentColor" fill-opacity="0.18"/><path d="m16.5 16 1 1 2-2"/>`),
    'asset_sale': (size = 14) => EVENT_SVG_MAP['evt-business-sale'](size),

    'evt-inheritance': (size = 14) => svgWrap(size, `<line x1="3" y1="21" x2="21" y2="21"/><polygon points="12 3 2 8 22 8 12 3" fill="currentColor" fill-opacity="0.18"/><line x1="6" y1="11" x2="6" y2="18"/><line x1="10" y1="11" x2="10" y2="18"/><line x1="14" y1="11" x2="14" y2="18"/><line x1="18" y1="11" x2="18" y2="18"/>`),
    'inheritance': (size = 14) => EVENT_SVG_MAP['evt-inheritance'](size),

    'evt-rental-income': (size = 14) => svgWrap(size, `<path d="M3 10.5 12 3l9 7.5v10a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 20.5v-10z" fill="currentColor" fill-opacity="0.18"/><line x1="12" y1="10" x2="12" y2="18"/><path d="M14.5 12h-3.5a1.5 1.5 0 0 0 0 3h2a1.5 1.5 0 0 1 0 3H9.5"/>`),
    'rental_income': (size = 14) => EVENT_SVG_MAP['evt-rental-income'](size),

    'evt-pension': (size = 14) => svgWrap(size, `<rect x="3" y="4" width="18" height="17" rx="2" fill="currentColor" fill-opacity="0.18"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="9" x2="21" y2="9"/><path d="M12 13v5"/><path d="m9.5 15.5 2.5-2.5 2.5 2.5"/>`),
    'deferred_comp': (size = 14) => EVENT_SVG_MAP['evt-pension'](size),

    'evt-philanthropy': (size = 14) => svgWrap(size, `<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" fill="currentColor" fill-opacity="0.18"/><path d="M12 8v6"/><path d="M9 11h6"/>`),
    'philanthropy_daf': (size = 14) => EVENT_SVG_MAP['evt-philanthropy'](size),
    'charitable': (size = 14) => EVENT_SVG_MAP['evt-philanthropy'](size),

    'evt-tax-legal': (size = 14) => svgWrap(size, `<line x1="12" y1="3" x2="12" y2="21"/><path d="M5 7h14"/><polygon points="5 7 2 14 8 14 5 7" fill="currentColor" fill-opacity="0.18"/><polygon points="19 7 16 14 22 14 19 7" fill="currentColor" fill-opacity="0.18"/><line x1="8" y1="21" x2="16" y2="21"/>`),
    'tax_legal': (size = 14) => EVENT_SVG_MAP['evt-tax-legal'](size),

    'evt-relocation': (size = 14) => svgWrap(size, `<path d="M12 2a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7z" fill="currentColor" fill-opacity="0.18"/><circle cx="12" cy="9" r="2.5"/>`),
    'state_relocation': (size = 14) => EVENT_SVG_MAP['evt-relocation'](size),

    'evt-roth-ladder': (size = 14) => svgWrap(size, `<path d="M4 19h4v-4h4v-4h4V7h4" stroke="currentColor"/><polygon points="4 19 8 19 8 15 12 15 12 11 16 11 16 7 20 7 20 19 4 19" fill="currentColor" fill-opacity="0.18"/><polyline points="15 4 20 4 20 9"/>`),
    'roth_conversion': (size = 14) => EVENT_SVG_MAP['evt-roth-ladder'](size),

    'evt-529-superfund': (size = 14) => svgWrap(size, `<polygon points="12 2 2 7 12 12 22 7 12 2" fill="currentColor" fill-opacity="0.18"/><path d="M6 10v5c0 2 2.7 3.5 6 3.5s6-1.5 6-3.5v-5"/><path d="M13 13l-2 3h3l-1 3"/>`),
    'superfund_529': (size = 14) => EVENT_SVG_MAP['evt-529-superfund'](size),

    'evt-j-curve': (size = 14) => svgWrap(size, `<path d="M3 3v18h18"/><path d="M6 11c2 5 4.5 6 7 2s5-8 8-9" fill="currentColor" fill-opacity="0.18"/><circle cx="21" cy="4" r="2"/>`),
    'pe_capital_call': (size = 14) => EVENT_SVG_MAP['evt-j-curve'](size),

    'evt-ltc-shield': (size = 14) => svgWrap(size, `<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" fill="currentColor" fill-opacity="0.18"/><path d="M12 15.5s-3.5-2.2-3.5-4.5a2 2 0 0 1 3.5-1.3 2 2 0 0 1 3.5 1.3c0 2.3-3.5 4.5-3.5 4.5z"/>`),
    'ltc_insurance': (size = 14) => EVENT_SVG_MAP['evt-ltc-shield'](size),

    'evt-asset-split': (size = 14) => svgWrap(size, `<circle cx="12" cy="5" r="2.5" fill="currentColor" fill-opacity="0.18"/><path d="M12 7.5v4l-5 5"/><path d="M12 11.5l5 5"/><polyline points="7 13.5 7 16.5 10 16.5"/><polyline points="17 13.5 17 16.5 14 16.5"/>`),
    'marital_settlement': (size = 14) => EVENT_SVG_MAP['evt-asset-split'](size),
};

export const ICON_PICKER_GROUPS = [
    {
        group: 'Real Estate & Home',
        icons: [
            { id: 'evt-real-estate', label: 'Primary Residence / Real Estate' },
            { id: 'evt-vacation-home', label: 'Vacation / Secondary Property' },
            { id: 'evt-home-sale', label: 'Home Sale / Downsize' },
            { id: 'evt-renovation', label: 'Home Renovation / Remodel / ADU' },
            { id: 'evt-refi', label: 'Mortgage Refinance' },
            { id: 'evt-debt', label: 'Mortgage / Debt Payoff' },
            { id: 'evt-house-key', label: 'First Home Down Payment Gift' },
            { id: 'evt-solar', label: 'Solar & Home Infrastructure' },
            { id: 'evt-rental-income', label: 'Rental Property Income' },
            { id: 'evt-relocation', label: 'State Tax Domicile Relocation / Map Pin' },
        ],
    },
    {
        group: 'Family, Education & Milestones',
        icons: [
            { id: 'evt-college', label: 'Undergraduate College Tuition' },
            { id: 'evt-grad-school', label: 'Graduate / Med / Law / MBA' },
            { id: 'evt-k12', label: 'K-12 Private School Tuition' },
            { id: 'evt-529-superfund', label: '529 Superfunding (5-Year Gift Election)' },
            { id: 'evt-wedding', label: 'Wedding / Marriage' },
            { id: 'evt-celebration', label: 'Milestone Celebration' },
            { id: 'evt-baby', label: 'New Child / Adoption / Childcare' },
            { id: 'evt-gifting', label: 'Family Gifting / Wealth Transfer' },
            { id: 'evt-eldercare', label: 'Elderly Parent Assisted Living' },
            { id: 'evt-ltc-shield', label: 'Hybrid Long-Term Care (LTC) Policy' },
            { id: 'evt-medical', label: 'Major Medical / Healthcare' },
            { id: 'evt-asset-split', label: 'Marital Settlement / Divorce / Asset Split' },
        ],
    },
    {
        group: 'Lifestyle, Vehicles & Passions',
        icons: [
            { id: 'evt-travel', label: 'Luxury Travel & Aviation' },
            { id: 'evt-globe', label: 'World Cruise / International Living' },
            { id: 'evt-car', label: 'Luxury / Electric Vehicle' },
            { id: 'evt-yacht', label: 'Boat / Yacht / Vessel' },
            { id: 'evt-art', label: 'Art / Watch / Luxury Collectible' },
            { id: 'evt-mountain', label: 'Adventure / Expedition / Retreat' },
            { id: 'evt-pet', label: 'Equestrian / Pets' },
            { id: 'evt-philanthropy', label: 'Charitable / Donor-Advised Fund (DAF)' },
            { id: 'evt-other', label: 'General Milestone / Other' },
        ],
    },
    {
        group: 'Career, Income & Wealth',
        icons: [
            { id: 'evt-equity', label: 'Company Equity / Option Exercise' },
            { id: 'evt-roth-ladder', label: 'Roth Conversion Ladder (Bracket Filling)' },
            { id: 'evt-j-curve', label: 'Private Equity / VC Capital Call (J-Curve)' },
            { id: 'evt-briefcase', label: 'Sabbatical / Career Pivot / Consulting' },
            { id: 'evt-rocket', label: 'Angel / Venture Investment' },
            { id: 'evt-trophy', label: 'Executive Bonus / Performance Award' },
            { id: 'evt-business-sale', label: 'Business / Asset Sale Exit' },
            { id: 'evt-inheritance', label: 'Inheritance / Trust Distribution' },
            { id: 'evt-pension', label: 'Deferred Comp / Pension / Annuity' },
            { id: 'evt-tax-legal', label: 'Tax / Legal / Settlement' },
            { id: 'evt-capital-inflow', label: 'Capital Inflow / Windfall' },
            { id: 'evt-capital-outflow', label: 'Capital Outflow / Withdrawal' },
        ],
    },
];

export const ICON_PICKER_CATALOG = ICON_PICKER_GROUPS.flatMap(g => g.icons.map(item => ({ ...item, group: g.group })));

export const MILESTONE_SVG_MAP = {
    'retirement': (size = 14) => svgWrap(size, `<path d="M12 3v3M18.4 5.6l-2.1 2.1M21 12h-3M5.6 5.6l2.1 2.1M3 12h3M7 16a5 5 0 0 1 10 0" fill="currentColor" fill-opacity="0.18"/><line x1="2" y1="20" x2="22" y2="20"/>`),
    'life': (size = 14) => svgWrap(size, `<circle cx="12" cy="12" r="10" fill="currentColor" fill-opacity="0.14"/><circle cx="12" cy="12" r="3" fill="currentColor"/><line x1="12" y1="2" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="2" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="22" y2="12"/>`),
    'education': (size = 14) => svgWrap(size, `<polygon points="12 3 1 9 12 15 23 9 12 3" fill="currentColor" fill-opacity="0.18"/><path d="M5 11.2v5.3c0 2.2 3.1 4 7 4s7-1.8 7-4v-5.3"/><path d="M23 9v7"/>`),
    'health': (size = 14) => svgWrap(size, `<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" fill="currentColor" fill-opacity="0.16"/><line x1="12" y1="8" x2="12" y2="14"/><line x1="9" y1="11" x2="15" y2="11"/>`),
    'ss': (size = 14) => svgWrap(size, `<line x1="3" y1="21" x2="21" y2="21"/><polygon points="12 3 2 8 22 8 12 3" fill="currentColor" fill-opacity="0.18"/><line x1="6" y1="11" x2="6" y2="18"/><line x1="10" y1="11" x2="10" y2="18"/><line x1="14" y1="11" x2="14" y2="18"/><line x1="18" y1="11" x2="18" y2="18"/>`)
};

export function getEventIcon(cat, size = 14) {
    if (!cat) return EVENT_SVG_MAP.other(size);
    const fn = EVENT_SVG_MAP[cat];
    if (fn) return fn(size);
    return EVENT_SVG_MAP.other(size);
}

export function getMilestoneIcon(cat, size = 14) {
    if (!cat) return MILESTONE_SVG_MAP.life(size);
    const fn = MILESTONE_SVG_MAP[cat];
    if (fn) return fn(size);
    return MILESTONE_SVG_MAP.life(size);
}

export function resolveEventIcon(evtOrCat, size = 14) {
    if (!evtOrCat) return getEventIcon('other', size);
    if (typeof evtOrCat === 'string') {
        if (evtOrCat.includes('<svg')) return evtOrCat;
        return getEventIcon(evtOrCat, size);
    }
    if (evtOrCat.icon && typeof evtOrCat.icon === 'string') {
        if (evtOrCat.icon.includes('<svg')) return evtOrCat.icon;
        if (EVENT_SVG_MAP[evtOrCat.icon]) return EVENT_SVG_MAP[evtOrCat.icon](size);
    }
    return getEventIcon(evtOrCat.category || 'other', size);
}

export function resolveMilestoneIcon(mOrCat, size = 14) {
    if (!mOrCat) return getMilestoneIcon('life', size);
    if (typeof mOrCat === 'string') {
        if (mOrCat.includes('<svg')) return mOrCat;
        return getMilestoneIcon(mOrCat, size);
    }
    if (mOrCat.icon && typeof mOrCat.icon === 'string' && mOrCat.icon.includes('<svg')) {
        return mOrCat.icon;
    }
    return getMilestoneIcon(mOrCat.category || 'life', size);
}

const canvasImageCache = new Map();

export function getEventCanvasImage(evtOrCat, color = '#FFFFFF', size = 16) {
    const iconKey = (typeof evtOrCat === 'object' && evtOrCat !== null)
        ? ((evtOrCat.icon && EVENT_SVG_MAP[evtOrCat.icon]) ? evtOrCat.icon : (evtOrCat.category || 'other'))
        : (evtOrCat || 'other');
    const key = `ev_${iconKey}_${color}_${size}`;
    if (canvasImageCache.has(key)) {
        return canvasImageCache.get(key);
    }
    let svg = getEventIcon(iconKey, size);
    svg = svg.replace(/currentColor/g, color);
    if (!svg.includes('xmlns=')) {
        svg = svg.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ');
    }
    const img = new Image();
    img.onerror = () => { img._failed = true; };
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
    canvasImageCache.set(key, img);
    return img;
}

export function getMilestoneCanvasImage(cat, color = '#FFFFFF', size = 16) {
    const key = `ms_${cat}_${color}_${size}`;
    if (canvasImageCache.has(key)) {
        return canvasImageCache.get(key);
    }
    let svg = getMilestoneIcon(cat, size);
    svg = svg.replace(/currentColor/g, color);
    if (!svg.includes('xmlns=')) {
        svg = svg.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ');
    }
    const img = new Image();
    img.onerror = () => { img._failed = true; };
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
    canvasImageCache.set(key, img);
    return img;
}
