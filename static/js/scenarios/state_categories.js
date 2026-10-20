/**
 * Scenario Category Themes, Groups, and Formatting Helpers
 */
import { getEventIcon } from './state_icons.js';

export const CATEGORY_THEMES = {
    'company_equity': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF', icon: getEventIcon('company_equity') },
    'equity': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF', icon: getEventIcon('equity') },
    'pe_capital_call': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF', icon: getEventIcon('pe_capital_call') },
    'lifestyle': { bg: 'rgba(192, 108, 38, 0.92)', border: '#C06C26', text: '#FFFFFF', icon: getEventIcon('lifestyle') },
    'travel_surge': { bg: 'rgba(192, 108, 38, 0.92)', border: '#C06C26', text: '#FFFFFF', icon: getEventIcon('travel_surge') },
    'real_estate': { bg: 'rgba(217, 119, 6, 0.92)', border: '#D97706', text: '#FFFFFF', icon: getEventIcon('real_estate') },
    'home_renovation': { bg: 'rgba(217, 119, 6, 0.92)', border: '#D97706', text: '#FFFFFF', icon: getEventIcon('home_renovation') },
    'home_sale': { bg: 'rgba(217, 119, 6, 0.92)', border: '#D97706', text: '#FFFFFF', icon: getEventIcon('home_sale') },
    'debt_payoff': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF', icon: getEventIcon('debt_payoff') },
    'refinance': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF', icon: getEventIcon('refinance') },
    'state_relocation': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF', icon: getEventIcon('state_relocation') },
    'education': { bg: 'rgba(2, 132, 199, 0.92)', border: '#0284C7', text: '#FFFFFF', icon: getEventIcon('education') },
    'college': { bg: 'rgba(2, 132, 199, 0.92)', border: '#0284C7', text: '#FFFFFF', icon: getEventIcon('college') },
    'grad_school': { bg: 'rgba(2, 132, 199, 0.92)', border: '#0284C7', text: '#FFFFFF', icon: getEventIcon('grad_school') },
    'superfund_529': { bg: 'rgba(2, 132, 199, 0.92)', border: '#0284C7', text: '#FFFFFF', icon: getEventIcon('superfund_529') },
    'gifting': { bg: 'rgba(29, 78, 216, 0.92)', border: '#1D4ED8', text: '#FFFFFF', icon: getEventIcon('gifting') },
    'gifting_throughline': { bg: 'rgba(29, 78, 216, 0.92)', border: '#1D4ED8', text: '#FFFFFF', icon: getEventIcon('gifting_throughline') },
    'philanthropy_daf': { bg: 'rgba(29, 78, 216, 0.92)', border: '#1D4ED8', text: '#FFFFFF', icon: getEventIcon('philanthropy_daf') },
    'roth_conversion': { bg: 'rgba(29, 78, 216, 0.92)', border: '#1D4ED8', text: '#FFFFFF', icon: getEventIcon('roth_conversion') },
    'child_home_gift': { bg: 'rgba(29, 78, 216, 0.92)', border: '#1D4ED8', text: '#FFFFFF', icon: getEventIcon('child_home_gift') },
    'sabbatical': { bg: 'rgba(2, 101, 232, 0.92)', border: '#0265E8', text: '#FFFFFF', icon: getEventIcon('sabbatical') },
    'income_change': { bg: 'rgba(2, 101, 232, 0.92)', border: '#0265E8', text: '#FFFFFF', icon: getEventIcon('income_change') },
    'eldercare': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF', icon: getEventIcon('eldercare') },
    'parent_care': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF', icon: getEventIcon('parent_care') },
    'ltc_insurance': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF', icon: getEventIcon('ltc_insurance') },
    'pre65_healthcare': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF', icon: getEventIcon('evt-ltc-shield') },
    'new_child': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF', icon: getEventIcon('new_child') },
    'medical_expense': { bg: 'rgba(13, 148, 136, 0.92)', border: '#0D9488', text: '#FFFFFF', icon: getEventIcon('medical_expense') },
    'wedding': { bg: 'rgba(192, 108, 38, 0.92)', border: '#C06C26', text: '#FFFFFF', icon: getEventIcon('wedding') },
    'vehicle_purchase': { bg: 'rgba(199, 93, 110, 0.92)', border: '#C75D6E', text: '#FFFFFF', icon: getEventIcon('vehicle_purchase') },
    'angel_investment': { bg: 'rgba(199, 93, 110, 0.92)', border: '#C75D6E', text: '#FFFFFF', icon: getEventIcon('angel_investment') },
    'marital_settlement': { bg: 'rgba(199, 93, 110, 0.92)', border: '#C75D6E', text: '#FFFFFF', icon: getEventIcon('marital_settlement') },
    'capital_inflow': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF', icon: getEventIcon('capital_inflow') },
    'windfall': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF', icon: getEventIcon('windfall') },
    'rental_income': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF', icon: getEventIcon('rental_income') },
    'deferred_comp': { bg: 'rgba(5, 150, 105, 0.92)', border: '#059669', text: '#FFFFFF', icon: getEventIcon('deferred_comp') },
    'capital_outflow': { bg: 'rgba(199, 93, 110, 0.92)', border: '#C75D6E', text: '#FFFFFF', icon: getEventIcon('capital_outflow') },
    'withdrawal': { bg: 'rgba(199, 93, 110, 0.92)', border: '#C75D6E', text: '#FFFFFF', icon: getEventIcon('withdrawal') },
    'custom_spike': { bg: 'rgba(100, 116, 139, 0.92)', border: '#64748B', text: '#FFFFFF', icon: getEventIcon('custom_spike') },
    'other': { bg: 'rgba(100, 116, 139, 0.92)', border: '#64748B', text: '#FFFFFF', icon: getEventIcon('other') },
};

export const EVENT_CATEGORY_GROUPS = [
    {
        key: 'education',
        title: 'Education & College Tuition',
        icon: getEventIcon('college', 16),
        color: '#0284C7',
        categories: ['education', 'college', 'grad_school', 'superfund_529'],
    },
    {
        key: 'equity',
        title: 'Company Equity, Career & Private Markets',
        icon: getEventIcon('company_equity', 16),
        color: '#059669',
        categories: ['company_equity', 'equity', 'sabbatical', 'income_change', 'pe_capital_call'],
    },
    {
        key: 'real_estate',
        title: 'Real Estate, Relocation & Mortgages',
        icon: getEventIcon('real_estate', 16),
        color: '#D97706',
        categories: ['real_estate', 'home_renovation', 'home_sale', 'refinance', 'debt_payoff', 'state_relocation'],
    },
    {
        key: 'gifting',
        title: 'Tax Strategy, Gifting & Philanthropy (DAF)',
        icon: getEventIcon('gifting', 16),
        color: '#1D4ED8',
        categories: ['gifting', 'gifting_throughline', 'philanthropy_daf', 'child_home_gift', 'roth_conversion'],
    },
    {
        key: 'eldercare',
        title: 'Family Care, LTC & Eldercare',
        icon: getEventIcon('eldercare', 16),
        color: '#0D9488',
        categories: ['eldercare', 'parent_care', 'new_child', 'medical_expense', 'ltc_insurance', 'pre65_healthcare'],
    },
    {
        key: 'lifestyle',
        title: 'Lifestyle, Milestones & Travel Surges',
        icon: getEventIcon('lifestyle', 16),
        color: '#C06C26',
        categories: ['lifestyle', 'travel_surge', 'wedding', 'vehicle_purchase'],
    },
    {
        key: 'capital_outflow',
        title: 'Capital Outflows & Settlements',
        icon: getEventIcon('capital_outflow', 16),
        color: '#C75D6E',
        categories: ['capital_outflow', 'withdrawal', 'angel_investment', 'marital_settlement'],
    },
    {
        key: 'capital_inflow',
        title: 'Capital Inflows & Income Streams',
        icon: getEventIcon('capital_inflow', 16),
        color: '#059669',
        categories: ['capital_inflow', 'custom_spike', 'windfall', 'rental_income', 'deferred_comp'],
    },
    {
        key: 'other',
        title: 'Other Financial Events',
        icon: getEventIcon('other', 16),
        color: '#64748B',
        categories: ['other'],
    },
];

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
