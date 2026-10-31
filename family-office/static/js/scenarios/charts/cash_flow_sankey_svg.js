/**
 * Single-Year Cash-Flow Sankey SVG Renderer & Tooltip Helpers
 * Computes source/target node ribbons and binds interactive hover tooltips.
 */
import { h, s as svgNode } from './dom.js';
import { state, fmtCurrency, fmtShortCurrency, getPlanStartYear } from '../state.js';

export function renderSankeySvg(chartArea, yr, cf, row) {
    let inflow_rsu = Number(cf.inflow_rsu || row.inflow_rsu || 0);
    let inflow_salary = Number(cf.inflow_salary || row.inflow_salary || 0);
    if (!inflow_salary && !inflow_rsu) {
        const gross = Number(cf.gross_compensation || 0);
        const takehome = Number(cf.household_salary || 0);
        if (gross > 0) {
            inflow_salary = gross;
        } else if (takehome > 0) {
            inflow_salary = takehome + Number(cf.income_tax_haircut || 0);
        } else if (cf.salary_savings > 0) {
            inflow_salary = Number(cf.salary_savings);
        }
    }
    const inflow_ss = Number(cf.inflow_ss ?? (cf.social_security || row.social_security || 0));
    const inflow_events = Number(cf.inflow_events ?? (cf.event_inflows || 0));
    let portfolio_draw = Number(cf.portfolio_draw ?? (row.net_portfolio_draw || 0));

    let living_core = Number(cf.living_core ?? (row.living_spending || 0));
    if (cf.travel_gogo && Number(cf.travel_gogo) > 0) {
        living_core += Number(cf.travel_gogo);
    }
    const mortgage_payment = Number(cf.mortgage_payment ?? (cf.mortgage_debt_service || 0));
    const tax_outflow = Number(cf.tax_outflow ?? (cf.income_tax_haircut || 0));
    let education = Number(cf.education_k12 || 0) + Number(cf.college_tuition || 0);
    let raw_events = Number(cf.outflow_events ?? (cf.events_outflow || 0));

    if (education === 0 && state.scenariosData?.events_catalog) {
        const eduEvents = state.scenariosData.events_catalog.filter(e => {
            const cat = (e.category || '').toLowerCase();
            const nm = (e.name || '').toLowerCase();
            const start = e.start_year || e.year || getPlanStartYear();
            const end = e.end_year || start;
            const isEdu = cat === 'education' || cat === 'college' || nm.includes('tuition') || nm.includes('college') || nm.includes('school');
            return isEdu && (yr >= start && yr <= end);
        });
        const eduTotal = eduEvents.reduce((acc, e) => acc + Number(e.annual_amount || e.one_time_amount || e.amount || 0), 0);
        if (eduTotal > 0) {
            education = eduTotal;
            raw_events = Math.max(0, raw_events - eduTotal);
        }
    }
    const gifting = Number(cf.gifting || 0);
    const outflow_events = raw_events;
    let net_savings = Number(cf.net_savings ?? (cf.net_cash_flow > 0 ? cf.net_cash_flow : (row.salary_savings > 0 ? row.salary_savings : 0)));

    let totalIn = inflow_salary + inflow_rsu + inflow_ss + inflow_events + portfolio_draw;
    let totalOut = living_core + mortgage_payment + tax_outflow + education + gifting + outflow_events + net_savings;

    if (totalIn > totalOut) {
        net_savings += (totalIn - totalOut);
        totalOut = totalIn;
    } else if (totalOut > totalIn) {
        portfolio_draw += (totalOut - totalIn);
        totalIn = totalOut;
    }

    const W = Math.max(760, Math.round(chartArea.clientWidth || 1240));
    const H_svg = Math.max(380, Math.round(chartArea.clientHeight || 500));

    if (totalIn <= 0) {
        chartArea.replaceChildren(
            svgNode('svg', { viewBox: `0 0 ${W} ${H_svg}`, style: 'width:100%;height:100%;' },
                svgNode('text', {
                    x: Math.round(W / 2), y: Math.round(H_svg / 2), 'text-anchor': 'middle', 'font-size': 15,
                    fill: 'var(--text-muted)', text: `No cash flow activity recorded for Year ${yr}`
                }))
        );
        return;
    }

    const sources = [
        { id: 'salary', label: 'Salary / W-2', amount: inflow_salary, color: '#059669' },
        { id: 'rsu', label: 'RSU / Equity Vests', amount: inflow_rsu, color: '#10B981' },
        { id: 'ss', label: 'Social Security', amount: inflow_ss, color: '#0D9488' },
        { id: 'events_in', label: 'Event Inflows', amount: inflow_events, color: '#34D399' },
        { id: 'draw', label: 'Net Portfolio Draw', amount: portfolio_draw, color: '#F59E0B' }
    ].filter(s => s.amount > 0);

    const targets = [
        { id: 'living', label: 'Core Living', amount: living_core, color: '#1D4ED8' },
        { id: 'mortgage', label: 'Mortgage P&I', amount: mortgage_payment, color: '#0284C7' },
        { id: 'taxes', label: 'Taxes', amount: tax_outflow, color: '#DC2626' },
        { id: 'education', label: 'Kids K-12 & College', amount: education, color: '#8B5CF6' },
        { id: 'gifting', label: 'Family Gifting', amount: gifting, color: '#C06C26' },
        { id: 'events_out', label: 'Event Outflows', amount: outflow_events, color: '#C75D6E' },
        { id: 'savings', label: 'Net Savings / Reinvest', amount: net_savings, color: '#059669' }
    ].filter(t => t.amount > 0);

    const topY = 58;
    const bottomY = H_svg - 20;
    const H = bottomY - topY;
    const labelMargin = Math.min(205, Math.max(165, Math.round(W * 0.16)));
    const barW = 20;
    const hubW = 24;
    const xLeftBar = labelMargin;
    const xRightBar = W - labelMargin - barW;
    const xHub = Math.round(W / 2 - hubW / 2);

    const gap_s = sources.length > 1 ? Math.min(20, Math.floor(84 / sources.length)) : 0;
    const availH_s = H - (sources.length - 1) * gap_s;
    sources.forEach(s => {
        s.h = Math.max(18, (s.amount / totalIn) * availH_s);
    });
    const sumH_s = sources.reduce((a, b) => a + b.h, 0);
    if (sumH_s > availH_s) {
        sources.forEach(s => {
            s.h = (s.h / sumH_s) * availH_s;
        });
    }
    let curY = topY + Math.max(0, (availH_s - sumH_s) / 2);
    sources.forEach(s => {
        s.y0 = curY;
        s.y1 = curY + s.h;
        curY += s.h + gap_s;
    });

    const gap_t = targets.length > 1 ? Math.min(20, Math.floor(84 / targets.length)) : 0;
    const availH_t = H - (targets.length - 1) * gap_t;
    targets.forEach(t => {
        t.h = Math.max(18, (t.amount / totalOut) * availH_t);
    });
    const sumH_t = targets.reduce((a, b) => a + b.h, 0);
    if (sumH_t > availH_t) {
        targets.forEach(t => {
            t.h = (t.h / sumH_t) * availH_t;
        });
    }
    curY = topY + Math.max(0, (availH_t - sumH_t) / 2);
    targets.forEach(t => {
        t.y0 = curY;
        t.y1 = curY + t.h;
        curY += t.h + gap_t;
    });

    let hubInY = topY;
    sources.forEach(s => {
        const sliceH = (s.amount / totalIn) * H;
        s.ribbon = { x0: xLeftBar + barW, y0_t: s.y0, y0_b: s.y1, x1: xHub, y1_t: hubInY, y1_b: hubInY + sliceH };
        hubInY += sliceH;
    });

    let hubOutY = topY;
    targets.forEach(t => {
        const sliceH = (t.amount / totalOut) * H;
        t.ribbon = { x0: xHub + hubW, y0_t: hubOutY, y0_b: hubOutY + sliceH, x1: xRightBar, y1_t: t.y0, y1_b: t.y1 };
        hubOutY += sliceH;
    });

    const bezPath = r => {
        const c0 = r.x0 + (r.x1 - r.x0) * 0.46;
        const c1 = r.x1 - (r.x1 - r.x0) * 0.46;
        return `M ${r.x0} ${r.y0_t} C ${c0} ${r.y0_t}, ${c1} ${r.y1_t}, ${r.x1} ${r.y1_t} L ${r.x1} ${r.y1_b} C ${c1} ${r.y1_b}, ${c0} ${r.y0_b}, ${r.x0} ${r.y0_b} Z`;
    };
    const midX = Math.round(W / 2);

    const gradient = (id, fromColor, fromOpacity, toColor, toOpacity) => svgNode('linearGradient',
        { id, x1: '0%', y1: '0%', x2: '100%', y2: '0%' },
        svgNode('stop', { offset: '0%', 'stop-color': fromColor, 'stop-opacity': fromOpacity }),
        svgNode('stop', { offset: '100%', 'stop-color': toColor, 'stop-opacity': toOpacity }));
    const heading = (x, y, anchor, color, label) => svgNode('text', {
        x, y, 'text-anchor': anchor, 'font-size': 11.5, 'font-weight': 700, fill: color,
        'letter-spacing': 0.8, text: label
    });
    const hover = (node, label, amount, pct) => {
        node.setAttribute('class', 'sankey-elem');
        node.setAttribute('data-label', label);
        node.setAttribute('data-amt', amount);
        node.setAttribute('data-pct', pct);
        node.setAttribute('style', 'cursor:pointer;');
        return node;
    };
    const share = (amount, total) => ((amount / total) * 100).toFixed(1);
    const ribbon = (node, kind, total) => hover(svgNode('path', {
        d: bezPath(node.ribbon), fill: `url(#grad-${kind}-${node.id})`, stroke: node.color,
        'stroke-width': 0.75, 'stroke-opacity': 0.35
    }), node.label, node.amount, share(node.amount, total));
    const bar = (node, x, total) => hover(svgNode('rect', {
        x, y: node.y0, width: barW, height: node.h, rx: 4, fill: node.color
    }), node.label, node.amount, share(node.amount, total));
    const nodeLabel = (node, x, anchor, total) => {
        const pct = share(node.amount, total);
        const midY = node.y0 + node.h / 2;
        if (node.h < 30) {
            return svgNode('text', {
                x, y: midY + 4, 'text-anchor': anchor, 'font-size': 12, fill: 'var(--text-primary)'
            },
                svgNode('tspan', { 'font-weight': 700, text: node.label }), ' ',
                svgNode('tspan', {
                    fill: 'var(--text-muted)', 'font-weight': 600, text: `${fmtShortCurrency(node.amount)} (${pct}%)`
                }));
        }
        return [
            svgNode('text', {
                x, y: midY - 3, 'text-anchor': anchor, 'font-size': 13, 'font-weight': 700,
                fill: 'var(--text-primary)', text: node.label
            }),
            svgNode('text', {
                x, y: midY + 13, 'text-anchor': anchor, 'font-size': 11.5, 'font-weight': 600,
                fill: 'var(--text-muted)', text: `${fmtShortCurrency(node.amount)} · ${pct}%`
            })
        ];
    };

    chartArea.replaceChildren(
        svgNode('svg', { viewBox: `0 0 ${W} ${H_svg}`, style: 'width:100%;height:100%;display:block;' },
            svgNode('defs', null,
                sources.map(n => gradient(`grad-s-${n.id}`, n.color, 0.52, '#3B82F6', 0.45)),
                targets.map(n => gradient(`grad-t-${n.id}`, '#3B82F6', 0.45, n.color, 0.52))),
            heading(xLeftBar + barW, 22, 'end', 'var(--status-green, #10B981)', 'SOURCES / INFLOWS'),
            heading(midX, 20, 'middle', 'var(--accent-blue, #3B82F6)', 'TOTAL ANNUAL CASH FLOW'),
            heading(xRightBar, 22, 'start', 'var(--accent-orange, #F59E0B)', 'USES & REINVESTMENT'),
            svgNode('text', { x: midX, y: 42, 'text-anchor': 'middle', 'font-size': 14.5, 'font-weight': 800,
                fill: 'var(--text-primary)', text: fmtCurrency(totalIn) }),
            sources.map(n => ribbon(n, 's', totalIn)),
            targets.map(n => ribbon(n, 't', totalOut)),
            sources.map(n => bar(n, xLeftBar, totalIn)),
            hover(svgNode('rect', { x: xHub, y: topY, width: hubW, height: H, rx: 5, fill: '#3B82F6' }),
                'Total Annual Cash Flow', totalIn, 100),
            targets.map(n => bar(n, xRightBar, totalOut)),
            sources.map(n => nodeLabel(n, xLeftBar - 10, 'end', totalIn)),
            targets.map(n => nodeLabel(n, xRightBar + barW + 10, 'start', totalOut)))
    );
    bindTooltips(chartArea, chartArea.parentElement);
}

function bindTooltips(chartArea, container) {
    let tip = container.querySelector('.sankey-tooltip');
    if (!tip) {
        tip = document.createElement('div');
        tip.className = 'sankey-tooltip';
        tip.style.cssText = 'position: absolute; display: none; pointer-events: none; background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); padding: 6px 10px; border-radius: 6px; font-size: 0.75rem; color: var(--text-primary); z-index: 20; box-shadow: 0 4px 12px rgba(0,0,0,0.25); backdrop-filter: blur(8px);';
        container.appendChild(tip);
    }
    chartArea.querySelectorAll('.sankey-elem').forEach(el => {
        el.addEventListener('mouseenter', () => {
            if (el.tagName === 'path') {
                el.setAttribute('stroke-width', '1.5');
                el.setAttribute('stroke-opacity', '0.9');
            }
            const label = el.getAttribute('data-label') || '';
            const amt = parseFloat(el.getAttribute('data-amt') || '0');
            const pct = el.getAttribute('data-pct') || '';
            tip.replaceChildren(
                h('div', { style: 'font-weight: 600; margin-bottom: 2px;', text: label }),
                h('div', { style: 'font-size: 0.8125rem; color: var(--accent-blue);' }, `${fmtCurrency(amt)} `,
                        h('span', {
                            style: 'font-size: 0.6875rem; color: var(--text-muted);', text: `(${pct}% of flow)`
                        })));
            tip.style.display = 'block';
        });
        el.addEventListener('mousemove', (e) => {
            const rect = container.getBoundingClientRect();
            tip.style.left = `${Math.min(rect.width - 180, Math.max(10, e.clientX - rect.left + 12))}px`;
            tip.style.top = `${Math.min(rect.height - 60, Math.max(10, e.clientY - rect.top + 12))}px`;
        });
        el.addEventListener('mouseleave', () => {
            if (el.tagName === 'path') {
                el.setAttribute('stroke-width', '0.75');
                el.setAttribute('stroke-opacity', '0.35');
            }
            tip.style.display = 'none';
        });
    });
}
