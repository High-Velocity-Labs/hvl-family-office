let registryIcons = [];
let currentStyle = 'duotone';
let currentStroke = 1.85;
let currentFilter = 'all';
let currentSearch = '';
let currentView = 'cards';

function escapeAttr(str) {
  if (typeof window.escapeHtml === 'function') return window.escapeHtml(str || '');
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function getItemColor(item) {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const defaultHex = '#0265E8';
  const defaultBg = isDark ? 'rgba(2, 101, 232, 0.16)' : 'rgba(2, 101, 232, 0.08)';
  const defaultBorder = isDark ? 'rgba(2, 101, 232, 0.35)' : 'rgba(2, 101, 232, 0.25)';

  if (!item) return { hex: defaultHex, bg: defaultBg, border: defaultBorder };
  const themed = isDark ? item.colorDark : item.colorLight;
  if (themed) return themed;
  return { hex: defaultHex, bg: defaultBg, border: defaultBorder };
}

function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function getProcessedSvg(svgTemplate, style, customStrokeColor, customFillRgba) {
  const stroke = currentStroke;
  let fill;
  if (style === 'monoline') {
    fill = 'none';
  } else if (style === 'facet') {
    fill = customFillRgba ? customFillRgba.replace(/0\.[0-9]+/g, '0.08') : 'rgba(2, 101, 232, 0.08)';
  } else {
    fill = customFillRgba || (customStrokeColor ? hexToRgba(customStrokeColor, 0.16) : 'rgba(2, 101, 232, 0.16)');
  }
  return (svgTemplate || '').replace(/__STROKE__/g, stroke).replace(/__FILL__/g, fill);
}

function alignTooltipEdge(tileEl) {
  if (!tileEl) return;
  tileEl.classList.remove('tooltip-dismissed', 'tooltip-edge-left', 'tooltip-edge-right');
  const rect = tileEl.getBoundingClientRect();
  const halfTooltip = 130;
  const center = rect.left + rect.width / 2;
  if (center < halfTooltip + 12) {
    tileEl.classList.add('tooltip-edge-left');
  } else if (window.innerWidth - center < halfTooltip + 12) {
    tileEl.classList.add('tooltip-edge-right');
  }
}
window.alignTooltipEdge = alignTooltipEdge;

function renderIcons() {
  const grid = document.getElementById('icons-grid');
  const countEl = document.getElementById('filter-result-count');
  if (!grid) return;

  grid.classList.toggle('icons-only-grid', currentView === 'icons');

  const q = currentSearch.toLowerCase().trim();
  const filtered = registryIcons.filter(item => {
    const matchesApp = (currentFilter === 'all') || (item.app === currentFilter);
    const matchesQuery = !q ||
      item.name.toLowerCase().includes(q) ||
      item.desc.toLowerCase().includes(q) ||
      (item.tags && item.tags.toLowerCase().includes(q));
    return matchesApp && matchesQuery;
  });

  if (countEl) {
    countEl.textContent = `Showing ${filtered.length} of ${registryIcons.length} icons`;
  }

  if (filtered.length === 0) {
    grid.innerHTML = `
      <div style="grid-column: 1 / -1; padding: 3rem; text-align: center; color: var(--text-muted); background: var(--bg-surface); border: 1px dashed var(--border-color); border-radius: 12px; box-shadow: var(--card-shadow);">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom: 8px; opacity: 0.6;"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <div style="font-size: 0.9375rem; font-weight: 600; color: var(--text-primary);">No matching icons found</div>
        <div style="font-size: 0.78125rem; margin-top: 4px;">Try clearing your search query or selecting "All Subsystems".</div>
      </div>
    `;
    return;
  }

  if (currentView === 'icons') {
    grid.innerHTML = filtered.map(item => {
      const itemColor = getItemColor(item);
      const svgMarkup = getProcessedSvg(item.svg, currentStyle, itemColor.hex, itemColor.bg);
      const safeName = escapeAttr(item.name);
      const safeDesc = escapeAttr(item.desc);
      return `
        <button type="button" class="icon-only-tile" data-icon-id="${item.id}"
          aria-label="${safeName}: ${safeDesc}"
          onmouseenter="alignTooltipEdge(this)" onfocus="alignTooltipEdge(this)"
          onclick="openInspector('${item.id}')">
          <span class="preview-chip" style="color: ${itemColor.hex}; background: ${itemColor.bg}; border: 1px solid ${itemColor.border};">
            ${svgMarkup}
          </span>
          <span class="icon-hover-tooltip" role="tooltip">
            <span class="icon-tooltip-header">
              <strong class="icon-tooltip-name">${safeName}</strong>
              <span class="badge ${item.badgeClass}">${escapeAttr(item.appLabel)}</span>
            </span>
            <span class="icon-tooltip-desc" style="display: block;">${safeDesc}</span>
          </span>
        </button>
      `;
    }).join('');
    return;
  }

  grid.innerHTML = filtered.map(item => {
    const itemColor = getItemColor(item);
    const svgMarkup = getProcessedSvg(item.svg, currentStyle, itemColor.hex, itemColor.bg);
    return `
      <div class="card-glass">
        <div>
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
            <div class="preview-chip" style="color: ${itemColor.hex}; background: ${itemColor.bg}; border: 1px solid ${itemColor.border};" onclick="openInspector('${item.id}')" title="${escapeAttr(item.name)} — ${escapeAttr(item.desc)}">
              ${svgMarkup}
            </div>
            <span class="badge ${item.badgeClass}">${item.appLabel}</span>
          </div>
          <h4 style="font-size: 0.9375rem; font-weight: 700; margin: 0 0 4px 0; color: var(--text-primary);">${item.name}</h4>
          <p style="font-size: 0.75rem; color: var(--text-secondary); line-height: 1.45; margin: 0 0 10px 0;">${item.desc}</p>
        </div>
        <div style="display: flex; gap: 6px; align-items: center; border-top: 1px solid var(--border-color); padding-top: 10px;">
          <button type="button" class="btn btn-secondary" style="flex: 1; padding: 4px 8px; font-size: 0.6875rem;" onclick="copySvg('${item.id}')">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            <span>Copy SVG</span>
          </button>
          <button type="button" class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.6875rem;" onclick="openInspector('${item.id}')">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            <span>Code</span>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

function copySvg(iconId) {
  const item = registryIcons.find(i => i.id === iconId);
  if (!item) return;
  const itemColor = getItemColor(item);
  const processed = getProcessedSvg(item.svg, currentStyle, itemColor.hex, itemColor.bg);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(processed).then(() => {
      showCatalogToast('SVG Markup copied to clipboard!');
    }).catch(() => {
      openInspector(item.id);
    });
  } else {
    openInspector(item.id);
  }
}

function openInspector(iconId) {
  const item = registryIcons.find(i => i.id === iconId);
  if (!item) return;

  const itemColor = getItemColor(item);
  const processed = getProcessedSvg(item.svg, currentStyle, itemColor.hex, itemColor.bg);

  document.getElementById('modal-icon-title').textContent = item.name;
  const appEl = document.getElementById('modal-icon-app');
  appEl.textContent = item.appLabel;
  appEl.className = 'badge ' + item.badgeClass;

  const chip = document.getElementById('modal-preview-chip');
  chip.style.color = itemColor.hex;
  chip.style.background = itemColor.bg;
  chip.style.borderColor = itemColor.border;
  chip.innerHTML = processed;

  document.getElementById('modal-svg-code').textContent = processed;
  document.getElementById('inspector-modal').classList.add('open');
}

function closeInspectorModal() {
  document.getElementById('inspector-modal').classList.remove('open');
}
window.closeModal = closeInspectorModal;

document.getElementById('modal-copy-btn').addEventListener('click', () => {
  const code = document.getElementById('modal-svg-code').textContent;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(code).then(() => {
      showCatalogToast('SVG copied to clipboard!');
      closeInspectorModal();
    });
  }
});

function showCatalogToast(msg) {
  const toast = document.getElementById('toast-msg');
  const text = document.getElementById('toast-text');
  if (!toast) return;
  if (text) text.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => { toast.classList.remove('show'); }, 2200);
}

document.querySelectorAll('#seg-view .segment-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#seg-view .segment-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentView = btn.getAttribute('data-view') || 'cards';
    renderIcons();
  });
});

document.querySelectorAll('#seg-app-filter .segment-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#seg-app-filter .segment-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentFilter = btn.getAttribute('data-filter');
    renderIcons();
  });
});

document.querySelectorAll('#seg-style .segment-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#seg-style .segment-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentStyle = btn.getAttribute('data-style');
    renderIcons();
  });
});

document.querySelectorAll('#seg-stroke .segment-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#seg-stroke .segment-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentStroke = parseFloat(btn.getAttribute('data-stroke'));
    renderIcons();
  });
});

const searchEl = document.getElementById('search-input');
if (searchEl) {
  searchEl.addEventListener('input', (e) => {
    currentSearch = e.target.value;
    renderIcons();
  });
}

const themeBtn = document.getElementById('btn-theme-toggle');
if (themeBtn) {
  themeBtn.addEventListener('click', () => {
    if (typeof window.toggleTheme === 'function') {
      window.toggleTheme();
    }
    renderIcons();
  });
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeInspectorModal();
    document.querySelectorAll('.icon-only-tile').forEach(el => el.classList.add('tooltip-dismissed'));
  }
});

if (typeof window.initTheme === 'function') {
  window.initTheme({ defaultTheme: 'dark' });
}

const iconsJsonUrl = window.location.protocol === 'file:' ? './common/icons.json' : '/common/icons.json';
fetch(iconsJsonUrl)
  .then(r => r.json())
  .then(data => {
    registryIcons = Array.isArray(data) ? data : [];
    renderIcons();
  })
  .catch(() => {
    renderIcons();
  });
