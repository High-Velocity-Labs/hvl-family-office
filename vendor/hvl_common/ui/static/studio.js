let domainEntities = [];
let forecastingEntities = [];
let forecastingPalettes = {};
let chartPalettes = {};
let registryIcons = [];
let fEventEntities = [];
let hvlLogoHarmonies = {};
let hvlLogoConcepts = [];
let assistantLogoConcepts = [];

const currentStyle = 'duotone';
const currentStroke = '1.85';
const currentColor = '#0265E8';
const activeForecastingPaletteKey = 'triadic';
let lastCopiedSvg = '';

function hexToRgba(hex, alpha) {
  if (!hex || !hex.startsWith('#')) return `rgba(2, 101, 232, ${alpha})`;
  const r = parseInt(hex.slice(1, 3), 16) || 2;
  const g = parseInt(hex.slice(3, 5), 16) || 101;
  const b = parseInt(hex.slice(5, 7), 16) || 232;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function getForecastingColorForId(id) {
  const p = forecastingPalettes[activeForecastingPaletteKey] || forecastingPalettes.triadic;
  if (!p || !p.colors) return null;
  const col = p.colors;
  if (['evt-equity', 'evt-capital-inflow', 'evt-business-sale', 'evt-inheritance', 'evt-rental-income', 'evt-pension', 'evt-trophy', 'evt-roth-ladder', 'equity', 'capital_inflow', 'fo-equity-vesting'].includes(id)) return col.equity;
  if (['evt-real-estate', 'evt-realestate', 'evt-vacation-home', 'evt-renovation', 'evt-solar', 'realestate', 'property'].includes(id)) return col.real_estate;
  if (id === 'evt-home-sale') return col.debt_payoff;
  if (['evt-college', 'evt-k12', 'evt-grad-school', 'evt-briefcase', 'evt-529-superfund', 'college', 'education', 'fo-college-529'].includes(id)) return col.college;
  if (['evt-gifting', 'evt-house-key', 'evt-philanthropy', 'evt-j-curve', 'evt-other', 'gifting', 'fo-estate', 'vault'].includes(id)) return col.gifting;
  if (['evt-eldercare', 'evt-medical', 'evt-pet', 'evt-relocation', 'evt-ltc-shield', 'ms-health', 'eldercare'].includes(id)) return col.eldercare;
  if (['evt-travel', 'evt-wedding', 'evt-celebration', 'evt-baby', 'evt-car', 'evt-yacht', 'evt-globe', 'evt-art', 'evt-mountain', 'lifestyle'].includes(id)) return col.lifestyle;
  if (['evt-debt', 'evt-refi', 'debt_payoff', 'refinance'].includes(id)) return col.debt_payoff;
  if (['evt-capital-outflow', 'evt-rocket', 'evt-tax-legal', 'evt-asset-split', 'capital_outflow'].includes(id)) return { hex: '#EA580C', bg: 'rgba(234, 88, 12, 0.14)', border: 'rgba(234, 88, 12, 0.35)' };
  if (id === 'ms-retirement' || id === 'retirement') return col.retirement;
  if (id === 'ms-ss') return col.real_estate;
  if (id === 'ms-today' || id === 'today') return { hex: '#0265E8', bg: 'rgba(2, 101, 232, 0.14)', border: 'rgba(2, 101, 232, 0.35)' };
  if (id === 'fo-tax' || id === 'tax') return col.real_estate;
  if (id === 'fo-bonds') return { hex: '#7C3AED', bg: 'rgba(124, 58, 237, 0.14)', border: 'rgba(124, 58, 237, 0.35)' };
  if (id === 'fo-advisor') return { hex: '#38BDF8', bg: 'rgba(56, 189, 248, 0.14)', border: 'rgba(56, 189, 248, 0.35)' };
  return null;
}

function getItemColor(item) {
  if (!item) return { hex: currentColor, bg: 'rgba(2, 101, 232, 0.14)', border: 'rgba(2, 101, 232, 0.35)' };
  const fCol = getForecastingColorForId(item.id);
  if (fCol) return fCol;
  if (item.app === 'hvl' || item.app === 'finances') {
    return { hex: '#0265E8', bg: 'rgba(2, 101, 232, 0.14)', border: 'rgba(2, 101, 232, 0.35)' };
  }
  return { hex: currentColor, bg: hexToRgba(currentColor, 0.14), border: hexToRgba(currentColor, 0.35) };
}

function getProcessedSvg(svgTemplate, style, customStrokeColor, customFillRgba) {
  const fill = customFillRgba || (customStrokeColor ? hexToRgba(customStrokeColor, 0.16) : 'rgba(2, 101, 232, 0.16)');
  return (svgTemplate || '').replace(/__STROKE__/g, currentStroke).replace(/__FILL__/g, fill);
}

function renderMatrixTable(tbodyId, entities, useForecastingOnly) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = '';
  entities.forEach(ent => {
    const tr = document.createElement('tr');
    const tdDomain = document.createElement('td');
    tdDomain.innerHTML = `<span class="domain-label">${ent.name}</span><span class="domain-desc">${ent.desc}</span>`;
    tr.appendChild(tdDomain);

    const itemColor = useForecastingOnly
      ? (getForecastingColorForId(ent.id) || { hex: currentColor, bg: hexToRgba(currentColor, 0.14), border: hexToRgba(currentColor, 0.35) })
      : getItemColor(ent);

    const td = document.createElement('td');
    const chip = document.createElement('div');
    chip.className = 'preview-chip';
    chip.style.color = itemColor.hex;
    chip.style.background = itemColor.bg;
    chip.style.borderColor = itemColor.border;
    chip.innerHTML = getProcessedSvg(ent.duotone, 'duotone', itemColor.hex, itemColor.bg);
    chip.onclick = () => openInspector(ent.name + ' (Duotone)', ent.duotone);
    td.appendChild(chip);
    tr.appendChild(td);

    tbody.appendChild(tr);
  });
}

function renderMatrix() {
  renderMatrixTable('matrix-tbody', domainEntities, false);
  renderMatrixTable('forecasting-matrix-tbody', forecastingEntities, true);
}

const themeBtn = document.getElementById('btn-theme-toggle');
if (themeBtn) {
  themeBtn.addEventListener('click', () => {
    const target = typeof window.toggleTheme === 'function' ? window.toggleTheme() : 'light';
    if (target === 'light') {
      document.documentElement.setAttribute('data-light-preset', 'azure');
    }
    if (typeof initCharts === 'function') {
      initCharts(currentChartPalette);
    }
  });
}

function forceLightMode() {
  if (typeof window.setThemePreference === 'function') {
    window.setThemePreference('light');
  }
  document.documentElement.setAttribute('data-light-preset', 'azure');
  if (typeof initCharts === 'function') {
    initCharts(currentChartPalette);
  }
  showStudioToast('Switched to Light Mode (Azure & Ice)');
}

function openInspector(title, svgTemplate) {
  const modal = document.getElementById('code-modal');
  const titleEl = document.getElementById('modal-icon-title');
  const codeEl = document.getElementById('modal-code-snippet');
  if (titleEl) titleEl.textContent = title;
  lastCopiedSvg = getProcessedSvg(svgTemplate, currentStyle);
  if (codeEl) codeEl.textContent = lastCopiedSvg;
  if (modal) modal.classList.add('active');
}

function closeModalDirect() {
  const modal = document.getElementById('code-modal');
  if (modal) modal.classList.remove('active');
}
window.closeModal = closeModalDirect;

function copyModalCode() {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(lastCopiedSvg).then(() => {
      showStudioToast('SVG copied to clipboard!');
      closeModalDirect();
    });
  }
}

function showStudioToast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

const basePrefix = window.location.protocol === 'file:' ? './common/' : '/common/';
function loadStudioModule(file) {
  if (typeof document === 'undefined' || !document.head) return Promise.resolve();
  return new Promise((resolve) => {
    const s = document.createElement('script');
    s.src = basePrefix + file + '?v=10';
    s.onload = () => resolve();
    s.onerror = () => resolve();
    document.head.appendChild(s);
  });
}

Promise.all([
  loadStudioModule('studio_charts.js'),
  loadStudioModule('studio_labs.js'),
  fetch(basePrefix + 'studio_data.json?v=10').then(r => r.json()).catch(() => ({})),
  fetch(basePrefix + 'icons.json?v=10').then(r => r.json()).catch(() => ([]))
]).then(([_, __, studioData, iconsData]) => {
  domainEntities = studioData.domainEntities || [];
  forecastingEntities = studioData.forecastingEntities || [];
  forecastingPalettes = studioData.forecastingPalettes || {};
  chartPalettes = studioData.chartPalettes || {};
  fEventEntities = studioData.fEventEntities || [];
  hvlLogoHarmonies = studioData.hvlLogoHarmonies || {};
  hvlLogoConcepts = studioData.hvlLogoConcepts || [];
  assistantLogoConcepts = studioData.assistantLogoConcepts || [];
  registryIcons = Array.isArray(iconsData) ? iconsData : [];

  if (typeof renderHvlLogoLab === 'function') renderHvlLogoLab();
  if (typeof renderAssistantLogoLab === 'function') renderAssistantLogoLab();
  renderMatrix();
  if (typeof initCharts === 'function') initCharts('gemstone');
  if (typeof renderForecastingPaletteGrid === 'function') renderForecastingPaletteGrid();
  if (typeof updateForecastingCanvasPins === 'function') updateForecastingCanvasPins();
  if (typeof renderIconRegistry === 'function') renderIconRegistry();
});
