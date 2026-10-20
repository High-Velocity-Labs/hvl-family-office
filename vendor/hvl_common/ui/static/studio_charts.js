let currentChartPalette = 'gemstone';
let chartDoughnutInstance = null;
let chartStackedInstance = null;
let chartWaterfallInstance = null;
let chartMonteCarloInstance = null;

function initCharts(palKey = 'gemstone') {
  currentChartPalette = palKey;
  if (typeof Chart === 'undefined') return;
  const pal = chartPalettes[palKey] || chartPalettes.gemstone;
  if (!pal) return;

  const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
  const textColor = isDark ? '#94A3B8' : '#475569';
  const gridColor = isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.06)';

  const ctxDoughnut = document.getElementById('chart-doughnut-alloc');
  if (ctxDoughnut) {
    if (chartDoughnutInstance) chartDoughnutInstance.destroy();
    chartDoughnutInstance = new Chart(ctxDoughnut, {
      type: 'doughnut',
      data: {
        labels: ['Public Equities', 'Fixed Income', 'Real Estate', 'Private Equity', 'Cash / Liquid', 'Alts / Digital'],
        datasets: [{
          data: [42, 18, 15, 12, 8, 5],
          backgroundColor: pal.doughnut,
          borderWidth: 2,
          borderColor: isDark ? '#212631' : '#FFFFFF'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'right',
            labels: { color: textColor, font: { family: "'Inter', sans-serif", size: 11 }, boxWidth: 12, padding: 8 }
          }
        },
        cutout: '68%'
      }
    });
  }

  const ctxStacked = document.getElementById('chart-stacked-trajectory');
  if (ctxStacked) {
    if (chartStackedInstance) chartStackedInstance.destroy();
    const years = ['Age 45', 'Age 50', 'Age 55', 'Age 60', 'Age 65', 'Age 70', 'Age 75'];
    chartStackedInstance = new Chart(ctxStacked, {
      type: 'bar',
      data: {
        labels: years,
        datasets: [
          { label: pal.stacked[0].label, data: [0.8, 1.1, 1.4, 1.6, 1.8, 1.9, 2.0], backgroundColor: pal.stacked[0].color },
          { label: pal.stacked[1].label, data: [3.2, 4.8, 6.9, 9.4, 12.2, 14.5, 16.8], backgroundColor: pal.stacked[1].color },
          { label: pal.stacked[2].label, data: [1.5, 2.3, 3.4, 4.6, 5.8, 6.7, 7.4], backgroundColor: pal.stacked[2].color },
          { label: pal.stacked[3].label, data: [2.0, 2.6, 3.1, 3.5, 3.9, 4.2, 4.5], backgroundColor: pal.stacked[3].color }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { color: textColor, font: { size: 10 } } },
          y: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 }, callback: v => '$' + v + 'M' } }
        },
        plugins: {
          legend: { position: 'bottom', labels: { color: textColor, font: { size: 10 }, boxWidth: 10, padding: 6 } }
        }
      }
    });
  }

  const ctxWaterfall = document.getElementById('chart-bar-waterfall');
  if (ctxWaterfall) {
    if (chartWaterfallInstance) chartWaterfallInstance.destroy();
    chartWaterfallInstance = new Chart(ctxWaterfall, {
      type: 'bar',
      data: {
        labels: ['W-2 Income', 'RSU Vesting', 'Dividends', 'Expenses', 'Fed Tax', 'State Tax', 'Net Retained'],
        datasets: [{
          label: 'Cash Flow ($k)',
          data: [420, 680, 110, -260, -320, -75, 555],
          backgroundColor: [
            pal.waterfall.inflows,
            pal.waterfall.inflows,
            pal.waterfall.inflows,
            pal.waterfall.outflows,
            pal.waterfall.outflows,
            pal.waterfall.outflows,
            pal.waterfall.net
          ],
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 } } },
          y: { grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 }, callback: v => '$' + v + 'k' } }
        },
        plugins: {
          legend: { display: false }
        }
      }
    });
  }

  const ctxMonteCarlo = document.getElementById('chart-line-montecarlo');
  if (ctxMonteCarlo) {
    if (chartMonteCarloInstance) chartMonteCarloInstance.destroy();
    const yearsMC = ['Yr 0', 'Yr 5', 'Yr 10', 'Yr 15', 'Yr 20', 'Yr 25', 'Yr 30'];
    chartMonteCarloInstance = new Chart(ctxMonteCarlo, {
      type: 'line',
      data: {
        labels: yearsMC,
        datasets: [
          {
            label: '95th Percentile (Optimistic)',
            data: [14.8, 22.4, 34.2, 51.0, 74.5, 108.0, 152.0],
            borderColor: pal.monteCarlo.p95,
            backgroundColor: 'rgba(2, 132, 199, 0.08)',
            fill: '+1',
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 0
          },
          {
            label: '50th Percentile (Median)',
            data: [14.8, 19.2, 25.1, 32.8, 42.6, 54.8, 70.2],
            borderColor: pal.monteCarlo.p50,
            fill: false,
            tension: 0.35,
            borderWidth: 2.5,
            pointRadius: 0
          },
          {
            label: '10th Percentile (Stress Test)',
            data: [14.8, 15.6, 17.2, 19.8, 22.5, 26.0, 30.1],
            borderColor: pal.monteCarlo.p10,
            backgroundColor: 'rgba(225, 29, 72, 0.08)',
            fill: '-1',
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 0
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 } } },
          y: { grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 }, callback: v => '$' + v + 'M' } }
        },
        plugins: {
          legend: { position: 'bottom', labels: { color: textColor, font: { size: 10 }, boxWidth: 10, padding: 6 } }
        }
      }
    });
  }
}

function renderForecastingPaletteGrid() {
  const container = document.getElementById('f-events-grid');
  if (!container) return;
  const p = forecastingPalettes[activeForecastingPaletteKey] || forecastingPalettes.triadic;
  if (!p) return;

  container.innerHTML = fEventEntities.map(ent => {
    const c = p.colors[ent.key] || { hex: '#0265E8', label: 'Cobalt', bg: 'rgba(2, 101, 232, 0.15)', border: 'rgba(2, 101, 232, 0.3)' };
    return `
      <div class="f-event-card">
        <div style="display: flex; align-items: flex-start; gap: 10px;">
          <div class="icon-box" style="width: 34px; height: 34px; border-radius: 8px; background: ${c.bg}; border: 1px solid ${c.border}; color: ${c.hex}; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
            ${ent.svg}
          </div>
          <div style="min-width: 0; flex: 1;">
            <div style="font-size: 0.8125rem; font-weight: 700; color: var(--text-primary); line-height: 1.25;">${ent.name}</div>
            <div style="font-size: 0.65rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em;">${ent.category}</div>
          </div>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px dashed var(--border-subtle); padding-top: 8px;">
          <span class="f-shelf-pill" style="background: ${c.bg}; border: 1px solid ${c.border}; color: ${c.hex}; font-size: 0.6875rem; padding: 2px 7px;">
            ${ent.svg.replace('width="18" height="18"', 'width="12" height="12"')}
            <span>${ent.name.split(' ')[0]}</span>
          </span>
          <span style="font-family: var(--font-mono); font-size: 0.6875rem; font-weight: 600; color: ${c.hex}; display: inline-flex; align-items: center; gap: 4px;">
            <span style="width: 8px; height: 8px; border-radius: 50%; background: ${c.hex};"></span>
            <span>${c.hex}</span>
          </span>
        </div>
      </div>
    `;
  }).join('');
}

function updateForecastingCanvasPins() {
  const p = forecastingPalettes[activeForecastingPaletteKey] || forecastingPalettes.triadic;
  if (!p) return;
  const pinMap = {
    'f-pin-equity': p.colors.equity,
    'f-pin-realestate': p.colors.real_estate,
    'f-pin-college': p.colors.college,
    'f-pin-retire': p.colors.retirement
  };

  Object.entries(pinMap).forEach(([pinId, c]) => {
    const g = document.getElementById(pinId);
    if (!g) return;
    const line = g.querySelector('line');
    const circle = g.querySelector('circle');
    const svgGroup = g.querySelectorAll('g')[0];
    if (line) line.setAttribute('stroke', c.hex);
    if (circle) circle.setAttribute('stroke', c.hex);
    if (svgGroup) {
      svgGroup.setAttribute('stroke', c.hex);
      svgGroup.setAttribute('fill', c.hex);
    }
  });
}
