/**
 * Scenario Category Themes, Groups, and Formatting Helpers
 */
// Chart theme swatch for each scenario event category
const CATEGORY_SWATCHES = {
    company_equity: 'emerald',
    equity: 'emerald',
    pe_capital_call: 'emerald',
    lifestyle: 'ochre',
    travel_surge: 'ochre',
    real_estate: 'amber',
    home_renovation: 'amber',
    home_sale: 'amber',
    debt_payoff: 'teal',
    refinance: 'teal',
    state_relocation: 'teal',
    education: 'cerulean',
    college: 'cerulean',
    grad_school: 'cerulean',
    superfund_529: 'cerulean',
    gifting: 'sapphire',
    gifting_throughline: 'sapphire',
    philanthropy_daf: 'sapphire',
    roth_conversion: 'sapphire',
    child_home_gift: 'sapphire',
    sabbatical: 'brand',
    income_change: 'brand',
    eldercare: 'teal',
    parent_care: 'teal',
    ltc_insurance: 'teal',
    pre65_healthcare: 'teal',
    new_child: 'teal',
    medical_expense: 'teal',
    wedding: 'ochre',
    vehicle_purchase: 'rose',
    angel_investment: 'rose',
    marital_settlement: 'rose',
    capital_inflow: 'emerald',
    windfall: 'emerald',
    rental_income: 'emerald',
    deferred_comp: 'emerald',
    capital_outflow: 'rose',
    withdrawal: 'rose',
    custom_spike: 'slate',
    other: 'slate',
};

// Pin colors for an event category, read from the chart theme when drawn so theme switches apply
export function categoryTheme(cat) {
    const theme = window.CHART_THEME;
    const color = theme[CATEGORY_SWATCHES[cat] || CATEGORY_SWATCHES.other];
    return { bg: theme.alpha(color, 0.92), bgSoft: theme.alpha(color, 0.35), border: color, text: theme.onFill };
}

export function formatCategoryLabel(cat) {
    const map = {
        'college': 'College Education',
        'grad_school': 'Graduate / Professional School',
        'superfund_529': '529 Superfunding',
        'company_equity': 'Company Equity',
        'equity': 'Company Equity',
        'pe_capital_call': 'Private Equity / VC (J-Curve)',
        'real_estate': 'Real Estate',
        'home_renovation': 'Home Renovation / Remodel',
        'home_sale': 'Home Sale / Downsize',
        'state_relocation': 'State Tax Relocation',
        'sabbatical': 'Sabbatical / Career Pivot',
        'income_change': 'Career / Income Pivot',
        'philanthropy_daf': 'Charitable / DAF',
        'roth_conversion': 'Roth Conversion Ladder',
        'wedding': 'Wedding / Celebration',
        'child_home_gift': 'First-Home Down Payment Gift',
        'new_child': 'New Child / Childcare',
        'vehicle_purchase': 'Vehicle Purchase',
        'angel_investment': 'Angel / Venture Investment',
        'marital_settlement': 'Marital Settlement / Split',
        'rental_income': 'Rental Income Stream',
        'deferred_comp': 'Deferred Comp / Pension',
        'medical_expense': 'Major Medical Expense',
        'ltc_insurance': 'Long-Term Care (LTC) Policy',
        'pre65_healthcare': 'Pre-65 Healthcare / ACA Bridge',
        'lifestyle': 'Lifestyle & Travel',
        'travel_surge': 'Lifestyle & Travel',
        'education': 'K-12 Education',
        'eldercare': 'Elderly Parent Care',
        'parent_care': 'Elderly Parent Care',
        'gifting': 'Family Gifting',
        'gifting_throughline': 'Family Gifting',
        'debt_payoff': 'Debt Payoff',
        'refinance': 'Mortgage Refinance',
        'capital_outflow': 'Capital Outflow / Milestone',
        'withdrawal': 'Capital Outflow / Withdrawal',
        'capital_inflow': 'Capital Inflow / Windfall',
        'custom_spike': 'Capital Inflow / Windfall',
        'windfall': 'Capital Inflow / Windfall',
    };
    if (map[cat]) return map[cat];
    if (!cat) return 'Event';
    return cat.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

export function getCategoryBadgeClass(cat) {
    if (cat === 'college' || cat === 'education' || cat === 'grad_school' || cat === 'superfund_529') return 'badge-blue';
    if (cat === 'real_estate' || cat === 'home_renovation' || cat === 'home_sale') return 'badge-orange';
    if (cat === 'lifestyle' || cat === 'travel_surge' || cat === 'wedding') return 'badge-pink';
    if (cat === 'debt_payoff' || cat === 'refinance' || cat === 'state_relocation') return 'badge-green';
    if (cat === 'company_equity' || cat === 'equity' || cat === 'pe_capital_call') return 'badge-green';
    if (cat === 'eldercare' || cat === 'parent_care' || cat === 'new_child' || cat === 'medical_expense' || cat === 'ltc_insurance' || cat === 'pre65_healthcare') return 'badge-teal';
    if (cat === 'gifting' || cat === 'gifting_throughline' || cat === 'philanthropy_daf' || cat === 'child_home_gift' || cat === 'sabbatical' || cat === 'income_change' || cat === 'roth_conversion') return 'badge-purple';
    if (cat === 'capital_outflow' || cat === 'withdrawal' || cat === 'vehicle_purchase' || cat === 'angel_investment' || cat === 'marital_settlement') return 'badge-red';
    if (cat === 'capital_inflow' || cat === 'custom_spike' || cat === 'windfall' || cat === 'rental_income' || cat === 'deferred_comp') return 'badge-green';
    return 'badge-blue';
}
