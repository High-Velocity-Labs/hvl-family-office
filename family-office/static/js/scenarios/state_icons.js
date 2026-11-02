/**
 * Scenario event and milestone icons. The SVG artwork lives server-side in
 * templates/fragments/scenario_icon_sprite.html (one <symbol> per icon); this module only names symbols and builds
 * <svg><use href="#symbol"/></svg> nodes with DOM APIs, or a data-URI Image for canvas charts.
 */

/**
 * Scenario event and milestone icons. The artwork is the shared sprite (/common/icons.svg, `evt-*` / `ms-*`
 * symbols); this module only names symbols and builds <svg><use href></svg> nodes with DOM APIs, or a data-URI
 * Image of a symbol for canvas charts (which cannot reference <use>).
 */

const SVG_NS = 'http://www.w3.org/2000/svg';
const SPRITE_URL = '/common/icons.svg';
const MILESTONE_ICONS = {
    retirement: 'ms-retirement', life: 'ms-today', education: 'evt-college', health: 'ms-health', ss: 'ms-ss'
};

// Category / legacy key -> sprite symbol id. A key that is already an `evt-*` symbol id needs no entry.
export const EVENT_ICON_ALIASES = {
    'company_equity': 'evt-equity',
    'equity': 'evt-equity',
    'lifestyle': 'evt-travel',
    'travel_surge': 'evt-travel',
    'real_estate': 'evt-real-estate',
    'debt_payoff': 'evt-debt',
    'refinance': 'evt-refi',
    'education': 'evt-k12',
    'college': 'evt-college',
    'gifting': 'evt-gifting',
    'gifting_throughline': 'evt-gifting',
    'eldercare': 'evt-eldercare',
    'parent_care': 'evt-eldercare',
    'capital_outflow': 'evt-capital-outflow',
    'withdrawal': 'evt-capital-outflow',
    'capital_inflow': 'evt-capital-inflow',
    'custom_spike': 'evt-capital-inflow',
    'windfall': 'evt-capital-inflow',
    'other': 'evt-other',
    'vacation_home': 'evt-vacation-home',
    'home_sale': 'evt-home-sale',
    'home_renovation': 'evt-renovation',
    'child_home_gift': 'evt-house-key',
    'solar_energy': 'evt-solar',
    'wedding': 'evt-wedding',
    'new_child': 'evt-baby',
    'grad_school': 'evt-grad-school',
    'medical_expense': 'evt-medical',
    'vehicle_purchase': 'evt-car',
    'yacht_vessel': 'evt-yacht',
    'major_purchase': 'evt-art',
    'sabbatical': 'evt-briefcase',
    'income_change': 'evt-briefcase',
    'angel_investment': 'evt-rocket',
    'asset_sale': 'evt-business-sale',
    'inheritance': 'evt-inheritance',
    'rental_income': 'evt-rental-income',
    'deferred_comp': 'evt-pension',
    'philanthropy_daf': 'evt-philanthropy',
    'charitable': 'evt-philanthropy',
    'tax_legal': 'evt-tax-legal',
    'state_relocation': 'evt-relocation',
    'roth_conversion': 'evt-roth-ladder',
    'superfund_529': 'evt-529-superfund',
    'pe_capital_call': 'evt-j-curve',
    'ltc_insurance': 'evt-ltc-shield',
    'marital_settlement': 'evt-asset-split',
    'evt-gift': 'evt-gifting',
    'evt-tuition': 'evt-college',
    'evt-charity': 'evt-philanthropy',
    'evt-sabbatical': 'evt-briefcase',
    'evt-529': 'evt-529-superfund',
    'evt-capital-call': 'evt-j-curve',
    'evt-lifestyle': 'evt-travel',
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

const knownSymbol = (key) => EVENT_ICON_ALIASES[key] || (String(key).startsWith('evt-') ? key : null);
const eventSymbolId = (key) => knownSymbol(key) || 'evt-other';
/** An event's own icon when it names a sprite symbol, else its category. */
const eventIconKey = (evt) => (knownSymbol(evt.icon) ? evt.icon : (evt.category || 'other'));
const milestoneSymbolId = (cat) => MILESTONE_ICONS[cat] || MILESTONE_ICONS.life;

/** An inline <svg> that references a sprite symbol. */
function useIcon(symbolId, size) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'hvl-icon');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('width', String(size));
    svg.setAttribute('height', String(size));
    const use = document.createElementNS(SVG_NS, 'use');
    use.setAttribute('href', `${SPRITE_URL}#${symbolId}`);
    svg.appendChild(use);
    return svg;
}

export const getEventIcon = (cat, size = 14) => useIcon(eventSymbolId(cat || 'other'), size);
export const getMilestoneIcon = (cat, size = 14) => useIcon(milestoneSymbolId(cat), size);

/** The icon for an event object ({icon, category}) or a category/icon key. */
export function resolveEventIcon(evtOrCat, size = 14) {
    if (!evtOrCat) return getEventIcon('other', size);
    if (typeof evtOrCat === 'string') return getEventIcon(evtOrCat, size);
    return getEventIcon(eventIconKey(evtOrCat), size);
}

export function resolveMilestoneIcon(mOrCat, size = 14) {
    const cat = (mOrCat && typeof mOrCat === 'object') ? mOrCat.category : mOrCat;
    return getMilestoneIcon(cat || 'life', size);
}

const canvasImageCache = new Map();
let spritePromise = null;

/** The sprite document, fetched once. */
function loadSprite() {
    if (!spritePromise) {
        spritePromise = fetch(SPRITE_URL)
            .then(resp => resp.text())
            .then(text => new window.DOMParser().parseFromString(text, 'image/svg+xml'));
    }
    return spritePromise;
}

/** A data-URI Image of a sprite symbol drawn in `color`; its src is set once the sprite has loaded. */
function symbolImage(cacheKey, symbolId, color, size) {
    if (canvasImageCache.has(cacheKey)) return canvasImageCache.get(cacheKey);
    const img = new Image();
    img.onerror = () => { img._failed = true; };
    canvasImageCache.set(cacheKey, img);
    loadSprite().then((doc) => {
        const symbol = doc.getElementById(symbolId);
        if (!symbol) throw new Error(`no sprite symbol ${symbolId}`);
        const serializer = new window.XMLSerializer();
        const inner = Array.from(symbol.children)
            .map(c => serializer.serializeToString(c).replace(/ xmlns="[^"]*"/g, '')).join('');
        const svg = `<svg xmlns="${SVG_NS}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" `
            + `stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
        img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg.replace(/currentColor/g, color));
    }).catch(() => { img._failed = true; });
    return img;
}

export function getEventCanvasImage(evtOrCat, color = window.CHART_THEME?.onFill, size = 16) {
    const key = (typeof evtOrCat === 'object' && evtOrCat !== null)
        ? eventIconKey(evtOrCat)
        : (evtOrCat || 'other');
    return symbolImage(`ev_${key}_${color}_${size}`, eventSymbolId(key), color, size);
}

export function getMilestoneCanvasImage(cat, color = window.CHART_THEME?.onFill, size = 16) {
    return symbolImage(`ms_${cat}_${color}_${size}`, milestoneSymbolId(cat), color, size);
}
