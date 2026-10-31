/**
 * Scenario Category Themes, Groups, and Formatting Helpers
 */
export const CATEGORY_THEMES = {
    'company_equity': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF' },
    'equity': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF' },
    'pe_capital_call': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF' },
    'lifestyle': { bg: 'rgba(192, 108, 38, 0.92)', border: '#C06C26', text: '#FFFFFF' },
    'travel_surge': { bg: 'rgba(192, 108, 38, 0.92)', border: '#C06C26', text: '#FFFFFF' },
    'real_estate': { bg: 'rgba(217, 119, 6, 0.92)', border: '#D97706', text: '#FFFFFF' },
    'home_renovation': { bg: 'rgba(217, 119, 6, 0.92)', border: '#D97706', text: '#FFFFFF' },
    'home_sale': { bg: 'rgba(217, 119, 6, 0.92)', border: '#D97706', text: '#FFFFFF' },
    'debt_payoff': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF' },
    'refinance': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF' },
    'state_relocation': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF' },
    'education': { bg: 'rgba(2, 132, 199, 0.92)', border: '#0284C7', text: '#FFFFFF' },
    'college': { bg: 'rgba(2, 132, 199, 0.92)', border: '#0284C7', text: '#FFFFFF' },
    'grad_school': { bg: 'rgba(2, 132, 199, 0.92)', border: '#0284C7', text: '#FFFFFF' },
    'superfund_529': { bg: 'rgba(2, 132, 199, 0.92)', border: '#0284C7', text: '#FFFFFF' },
    'gifting': { bg: 'rgba(29, 78, 216, 0.92)', border: '#1D4ED8', text: '#FFFFFF' },
    'gifting_throughline': { bg: 'rgba(29, 78, 216, 0.92)', border: '#1D4ED8', text: '#FFFFFF' },
    'philanthropy_daf': { bg: 'rgba(29, 78, 216, 0.92)', border: '#1D4ED8', text: '#FFFFFF' },
    'roth_conversion': { bg: 'rgba(29, 78, 216, 0.92)', border: '#1D4ED8', text: '#FFFFFF' },
    'child_home_gift': { bg: 'rgba(29, 78, 216, 0.92)', border: '#1D4ED8', text: '#FFFFFF' },
    'sabbatical': { bg: 'rgba(2, 101, 232, 0.92)', border: '#0265E8', text: '#FFFFFF' },
    'income_change': { bg: 'rgba(2, 101, 232, 0.92)', border: '#0265E8', text: '#FFFFFF' },
    'eldercare': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF' },
    'parent_care': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF' },
    'ltc_insurance': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF' },
    'pre65_healthcare': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF' },
    'new_child': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF' },
    'medical_expense': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF' },
    'wedding': { bg: 'rgba(192, 108, 38, 0.92)', border: '#C06C26', text: '#FFFFFF' },
    'vehicle_purchase': { bg: 'rgba(199, 93, 110, 0.92)', border: '#C75D6E', text: '#FFFFFF' },
    'angel_investment': { bg: 'rgba(199, 93, 110, 0.92)', border: '#C75D6E', text: '#FFFFFF' },
    'marital_settlement': { bg: 'rgba(199, 93, 110, 0.92)', border: '#C75D6E', text: '#FFFFFF' },
    'capital_inflow': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF' },
    'windfall': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF' },
    'rental_income': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF' },
    'deferred_comp': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF' },
    'capital_outflow': { bg: 'rgba(199, 93, 110, 0.92)', border: '#C75D6E', text: '#FFFFFF' },
    'withdrawal': { bg: 'rgba(199, 93, 110, 0.92)', border: '#C75D6E', text: '#FFFFFF' },
    'custom_spike': { bg: 'rgba(100, 116, 139, 0.92)', border: '#64748B', text: '#FFFFFF' },
    'other': { bg: 'rgba(100, 116, 139, 0.92)', border: '#64748B', text: '#FFFFFF' },
};

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
