// =========================================================
// PHILANTHROPIC GIVING & DAF ENGINE (SSR + HTMX MORPHING)
// =========================================================

let philanthropyRawData = null;
let chartGivingOrgs = null;
let chartGivingTrends = null;
let philOrgChartScope = 'year';

function getPhilanthropyState() {
    const sec = document.getElementById('section-philanthropy');
    return {
        year: (sec && sec.dataset.activeYear) || '2026',
        budgetRaw: parseFloat((sec && sec.dataset.budgetRaw) || '150000') || 150000,
        sort: (sec && sec.dataset.sortKey) || '',
        dir: (sec && sec.dataset.sortDir) || 'asc',
    };
}

function scrollActiveDafYearIntoView() {
    const container = document.getElementById('daf-year-pills');
    if (!container) return;
    const activeBtn = container.querySelector('.pill-btn.active');
    if (activeBtn && container.clientWidth > 0) {
        container.scrollLeft = Math.max(0, activeBtn.offsetLeft - container.clientWidth / 2 + activeBtn.offsetWidth / 2);
    }
}

async function morphPhilanthropySection(overrides = {}) {
    const cur = getPhilanthropyState();
    const year = String(overrides.year || cur.year);
    const sort = overrides.sort !== undefined ? overrides.sort : cur.sort;
    const dir = overrides.dir !== undefined ? overrides.dir : cur.dir;

    const params = new URLSearchParams({ year });
    if (sort) {
        params.set('sort', sort);
        params.set('dir', dir || 'asc');
    }
    const url = `/fragments/philanthropy?${params.toString()}`;
    await window.htmx.ajax('GET', url, { target: '#section-philanthropy', swap: 'morph' });
    scrollActiveDafYearIntoView();
    renderPhilanthropyCharts();
}

async function loadPhilanthropyData() {
    initPhilanthropyControls();
    scrollActiveDafYearIntoView();
    try {
        const res = await fetch('/api/philanthropy');
        const json = await res.json();
        if (json.success) {
            philanthropyRawData = json;
            renderPhilanthropyCharts();
        }
    } catch (e) {
        console.error('Failed to load philanthropy chart data:', e);
    }
}

function renderPhilanthropyCharts() {
    if (!philanthropyRawData || typeof Chart === 'undefined') return;
    const { year: activePhilanthropyYear } = getPhilanthropyState();

    const byYear = philanthropyRawData.donations_by_year || {};
    const lifetimeHist = philanthropyRawData.lifetime_history || [];
    const annualBudgets = philanthropyRawData.annual_budgets || {};

    const orgTotals = {};
    const titleEl = document.getElementById('daf-org-chart-title');
    const subEl = document.getElementById('daf-org-chart-sub');

    const btnScopeYear = document.getElementById('btn-daf-org-year');
    const btnScopeLife = document.getElementById('btn-daf-org-lifetime');
    if (btnScopeYear) btnScopeYear.classList.toggle('active', philOrgChartScope === 'year');
    if (btnScopeLife) btnScopeLife.classList.toggle('active', philOrgChartScope === 'lifetime');

    if (philOrgChartScope === 'year') {
        if (titleEl) titleEl.textContent = `Giving by Organization (${activePhilanthropyYear})`;
        if (subEl) subEl.textContent = `Distribution across non-profit recipients for ${activePhilanthropyYear}`;

        const yrData = byYear[activePhilanthropyYear] || {};
        const yrDonations = yrData.donations || [];
        const yrTotal = yrData.total || 0;
        const yrBudget = yrData.budget || annualBudgets[activePhilanthropyYear] || (yrTotal > 0 ? yrTotal : 150000);
        let yrAllocated = 0;

        yrDonations.forEach(d => {
            const org = (d.organization || d.recipient || 'Other').trim();
            if (org.toLowerCase() === 'available') return;
            const amt = Number(d.amount) || 0;
            orgTotals[org] = (orgTotals[org] || 0) + amt;
            yrAllocated += amt;
        });

        const yrRemaining = Math.max(0, yrBudget - yrAllocated);
        if (yrRemaining > 0) {
            orgTotals['Available (Unallocated Budget)'] = yrRemaining;
        }
    } else {
        if (titleEl) titleEl.textContent = 'Lifetime Giving by Organization (All Years)';
        if (subEl) subEl.textContent = 'Cumulative charitable distributions across all historical & planned years';

        Object.values(byYear).forEach(yrObj => {
            (yrObj.donations || []).forEach(d => {
                const org = (d.organization || d.recipient || 'Other').trim();
                if (org.toLowerCase() === 'available') return;
                const amt = Number(d.amount) || 0;
                orgTotals[org] = (orgTotals[org] || 0) + amt;
            });
        });
    }

    const sortedOrgs = Object.entries(orgTotals).sort((a, b) => {
        if (a[0].startsWith('Available')) return 1;
        if (b[0].startsWith('Available')) return -1;
        return b[1] - a[1];
    });

    const regularOrgs = sortedOrgs.filter(x => !x[0].startsWith('Available'));
    const availEntry = sortedOrgs.find(x => x[0].startsWith('Available'));

    const topOrgs = regularOrgs.slice(0, 7);
    const otherOrgsSum = regularOrgs.slice(7).reduce((acc, cur) => acc + cur[1], 0);
    if (otherOrgsSum > 0) topOrgs.push(['Other Charities', otherOrgsSum]);
    if (availEntry) topOrgs.push(availEntry);

    const orgPalette = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f43f5e', '#64748b'];

    const ctxOrgs = document.getElementById('chart-giving-orgs');
    if (ctxOrgs) {
        if (chartGivingOrgs) chartGivingOrgs.destroy();

        const labels = topOrgs.length > 0 ? topOrgs.map(x => x[0]) : ['No Grants Recorded'];
        const values = topOrgs.length > 0 ? topOrgs.map(x => x[1]) : [1];
        const colors = topOrgs.length > 0
            ? topOrgs.map((x, idx) => x[0].startsWith('Available') ? 'rgba(148, 163, 184, 0.28)' : orgPalette[idx % orgPalette.length])
            : ['#334155'];

        chartGivingOrgs = new Chart(ctxOrgs, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#0f172a',
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '62%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: { color: '#94a3b8', font: { size: 11 }, boxWidth: 12, padding: 10 },
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                if (topOrgs.length === 0) return ' $0';
                                const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                                const pct = total > 0 ? ((ctx.raw / total) * 100).toFixed(1) : 0;
                                return ` ${ctx.label}: ${fmtCurrency(ctx.raw, 0)} (${pct}%)`;
                            },
                        },
                    },
                },
            },
        });
    }

    const ctxTrends = document.getElementById('chart-giving-trends');
    if (ctxTrends) {
        if (chartGivingTrends) chartGivingTrends.destroy();

        const yearSet = new Set([
            ...lifetimeHist.map(h => String(h.year)),
            ...Object.keys(byYear),
        ]);
        const sortedYears = Array.from(yearSet).sort((a, b) => Number(a) - Number(b));

        const globalOrgTotals = {};
        sortedYears.forEach(yr => {
            const yrObj = byYear[yr] || {};
            (yrObj.donations || []).forEach(d => {
                const org = (d.organization || d.recipient || 'Other').trim();
                if (org.toLowerCase() === 'available') return;
                const amt = Number(d.amount) || 0;
                globalOrgTotals[org] = (globalOrgTotals[org] || 0) + amt;
            });
        });

        const topGlobalOrgs = Object.entries(globalOrgTotals)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 6)
            .map(x => x[0]);

        const topSet = new Set(topGlobalOrgs);
        const datasets = [];

        topGlobalOrgs.forEach((orgName, idx) => {
            const dataArr = sortedYears.map(yr => {
                const yrDonations = (byYear[yr] && byYear[yr].donations) || [];
                return yrDonations
                    .filter(d => (d.organization || d.recipient || 'Other').trim() === orgName)
                    .reduce((sum, d) => sum + (Number(d.amount) || 0), 0);
            });
            datasets.push({
                label: orgName,
                data: dataArr,
                backgroundColor: orgPalette[idx % orgPalette.length],
                borderRadius: 2,
                stack: 'orgs',
            });
        });

        const otherAndUnitemizedData = sortedYears.map(yr => {
            const yrObj = byYear[yr] || {};
            const yrDonations = yrObj.donations || [];
            const histEntry = lifetimeHist.find(h => String(h.year) === yr);
            const histTotal = histEntry ? (Number(histEntry.amount) || 0) : (Number(yrObj.total) || 0);

            if (yrDonations.length === 0) return histTotal;

            const otherSum = yrDonations
                .filter(d => {
                    const o = (d.organization || d.recipient || 'Other').trim();
                    return o.toLowerCase() !== 'available' && !topSet.has(o);
                })
                .reduce((sum, d) => sum + (Number(d.amount) || 0), 0);

            const itemizedTotal = yrDonations
                .filter(d => (d.organization || d.recipient || '').trim().toLowerCase() !== 'available')
                .reduce((sum, d) => sum + (Number(d.amount) || 0), 0);

            const unitemizedDiff = Math.max(0, histTotal - itemizedTotal);
            return otherSum + unitemizedDiff;
        });

        if (otherAndUnitemizedData.some(v => v > 0)) {
            datasets.push({
                label: 'Other / Unitemized DAF Grants',
                data: otherAndUnitemizedData,
                backgroundColor: '#64748b',
                borderRadius: 2,
                stack: 'orgs',
            });
        }

        const availableData = sortedYears.map(yr => {
            const yrObj = byYear[yr] || {};
            const yrDonations = yrObj.donations || [];
            const yrBudget = yrObj.budget || annualBudgets[yr] || 0;
            if (!yrBudget) return 0;

            const allocated = yrDonations
                .filter(d => (d.organization || d.recipient || '').trim().toLowerCase() !== 'available')
                .reduce((sum, d) => sum + (Number(d.amount) || 0), 0);
            return Math.max(0, yrBudget - allocated);
        });

        if (availableData.some(v => v > 0)) {
            datasets.push({
                label: 'Available Budget',
                data: availableData,
                backgroundColor: 'rgba(148, 163, 184, 0.25)',
                borderRadius: 2,
                stack: 'orgs',
            });
        }

        chartGivingTrends = new Chart(ctxTrends, {
            type: 'bar',
            data: { labels: sortedYears, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: true, position: 'bottom', labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 10, padding: 8 } },
                    tooltip: { callbacks: { label: (ctx) => ctx.raw > 0 ? ` ${ctx.dataset.label}: ${fmtCurrency(ctx.raw, 0)}` : null } },
                },
                scales: {
                    x: { stacked: true, grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 10 } } },
                    y: { stacked: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8', font: { size: 10 }, callback: (val) => fmtShortCurrency(val) } },
                },
            },
        });
    }
}

function initPhilanthropyControls() {
    if (typeof window.initPhilanthropyModals === 'function') {
        window.initPhilanthropyModals();
    }
    if (!document.body || document.body.dataset.philanthropyDelegated === 'true') return;
    document.body.dataset.philanthropyDelegated = 'true';

    document.addEventListener('click', async (e) => {
        const scopeYrBtn = e.target.closest('#btn-daf-org-year');
        if (scopeYrBtn) {
            philOrgChartScope = 'year';
            renderPhilanthropyCharts();
            return;
        }

        const scopeLifeBtn = e.target.closest('#btn-daf-org-lifetime');
        if (scopeLifeBtn) {
            philOrgChartScope = 'lifetime';
            renderPhilanthropyCharts();
            return;
        }

        const yearPill = e.target.closest('#daf-year-pills .pill-btn[data-year]');
        if (yearPill) {
            const yr = yearPill.getAttribute('data-year');
            if (yr) await morphPhilanthropySection({ year: yr });
            return;
        }

        const prevBtn = e.target.closest('#btn-daf-prev-yr');
        if (prevBtn) {
            const pills = Array.from(document.querySelectorAll('#daf-year-pills .pill-btn[data-year]')).map(b => b.getAttribute('data-year'));
            const { year } = getPhilanthropyState();
            const idx = pills.indexOf(year);
            const targetYr = idx > 0 ? pills[idx - 1] : String(parseInt(year, 10) - 1);
            await morphPhilanthropySection({ year: targetYr });
            return;
        }

        const nextBtn = e.target.closest('#btn-daf-next-yr');
        if (nextBtn) {
            const pills = Array.from(document.querySelectorAll('#daf-year-pills .pill-btn[data-year]')).map(b => b.getAttribute('data-year'));
            const { year } = getPhilanthropyState();
            const idx = pills.indexOf(year);
            const targetYr = (idx >= 0 && idx < pills.length - 1) ? pills[idx + 1] : String(parseInt(year, 10) + 1);
            await morphPhilanthropySection({ year: targetYr });
            return;
        }

        const sortTh = e.target.closest('#th-phil-org, #th-phil-date, #th-phil-amount');
        if (sortTh) {
            const key = sortTh.getAttribute('data-sort');
            const cur = getPhilanthropyState();
            const nextDir = (cur.sort === key && cur.dir === 'asc') ? 'desc' : 'asc';
            await morphPhilanthropySection({ sort: key, dir: nextDir });
            return;
        }
    });
}

Object.assign(window, {
    getPhilanthropyState,
    loadPhilanthropyData,
    fetchPhilanthropyData: loadPhilanthropyData,
    morphPhilanthropySection,
    renderPhilanthropyCharts,
    initPhilanthropyControls,
});
if (typeof window !== 'undefined' && typeof window.registerSectionHydrator === 'function') {
    window.registerSectionHydrator('section-philanthropy', loadPhilanthropyData, {
        morphFn: () => morphPhilanthropySection()
    });
}
