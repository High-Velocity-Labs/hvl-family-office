let activeAppFilter = 'all';
let iconSearchQuery = '';
let activeRegistryView = 'cards';
let activeHvlLogoId = 'm0-mach-solid-reference';
let activeHvlHarmony = 'white-ostro';
let activeHvlSurface = 'graphite';
let activeAssistantLogoId = 's1-pulse-hex';
let activeAssistantSurface = 'graphite';
let activeAssistantTrack = 'all';

function setRegistryView(viewMode) {
  activeRegistryView = viewMode || 'cards';
  document.querySelectorAll('#seg-registry-view .segment-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-view') === activeRegistryView);
  });
  renderIconRegistry();
}
window.setRegistryView = setRegistryView;

function alignStudioTooltipEdge(tileEl) {
  if (!tileEl) return;
  tileEl.classList.remove('tooltip-dismissed', 'tooltip-edge-left', 'tooltip-edge-right');
  const rect = tileEl.getBoundingClientRect();
  const center = rect.left + rect.width / 2;
  if (center < 142) tileEl.classList.add('tooltip-edge-left');
  else if (window.innerWidth - center < 142) tileEl.classList.add('tooltip-edge-right');
}
window.alignStudioTooltipEdge = alignStudioTooltipEdge;

function ensureStudioRegistryControls() {
  if (!document.getElementById('studio-icons-css-link')) {
    const link = document.createElement('link');
    link.id = 'studio-icons-css-link';
    link.rel = 'stylesheet';
    link.href = '/common/icons.css?v=3';
    document.head.appendChild(link);
  }
  const filterSeg = document.getElementById('seg-registry-filter');
  if (filterSeg && !document.getElementById('seg-registry-view')) {
    const viewSeg = document.createElement('div');
    viewSeg.className = 'segmented';
    viewSeg.id = 'seg-registry-view';
    viewSeg.innerHTML = `
      <button type="button" class="segment-btn active" data-view="cards" onclick="setRegistryView('cards')" title="Detailed Cards View">Cards</button>
      <button type="button" class="segment-btn" data-view="icons" onclick="setRegistryView('icons')" title="Compact Icons-Only View">Icons Only</button>
    `;
    filterSeg.parentElement.insertBefore(viewSeg, filterSeg);
  }
}

function setAppFilter(filterKey) {
  activeAppFilter = filterKey;
  document.querySelectorAll('#seg-registry-filter .segment-btn').forEach(btn => {
    if (btn.getAttribute('data-app-filter') === filterKey) btn.classList.add('active');
    else btn.classList.remove('active');
  });
  renderIconRegistry();
}

function filterRegistryIcons() {
  const input = document.getElementById('icon-search-input');
  iconSearchQuery = (input ? input.value : '').toLowerCase().trim();
  renderIconRegistry();
}

function renderIconRegistry() {
  const grid = document.getElementById('registry-grid');
  if (!grid) return;
  ensureStudioRegistryControls();

  const filtered = registryIcons.filter(item => {
    const matchesApp = (activeAppFilter === 'all' || item.app === activeAppFilter);
    const matchesQuery = !iconSearchQuery ||
      item.name.toLowerCase().includes(iconSearchQuery) ||
      item.desc.toLowerCase().includes(iconSearchQuery) ||
      item.tags.toLowerCase().includes(iconSearchQuery) ||
      item.id.toLowerCase().includes(iconSearchQuery);
    return matchesApp && matchesQuery;
  });

  const countEl = document.getElementById('count-all');
  if (countEl) countEl.textContent = registryIcons.length;
  const countShared = document.getElementById('count-shared');
  if (countShared) countShared.textContent = registryIcons.filter(i => i.app === 'shared').length;
  const countHvl = document.getElementById('count-hvl');
  if (countHvl) countHvl.textContent = registryIcons.filter(i => i.app === 'hvl').length;
  const countFin = document.getElementById('count-finances');
  if (countFin) countFin.textContent = registryIcons.filter(i => i.app === 'finances').length;
  const countFore = document.getElementById('count-forecasting');
  if (countFore) countFore.textContent = registryIcons.filter(i => i.app === 'forecasting').length;

  grid.style.gridTemplateColumns = activeRegistryView === 'icons'
    ? 'repeat(auto-fill, minmax(68px, 1fr))'
    : 'repeat(auto-fill, minmax(260px, 1fr))';

  if (filtered.length === 0) {
    grid.innerHTML = `<div style="grid-column: 1 / -1; padding: 2.5rem; text-align: center; color: var(--text-muted); background: var(--bg-surface); border-radius: 8px; border: 1px dashed var(--border-subtle);">No icons found matching "<strong>${escapeHtml(iconSearchQuery)}</strong>" in this scope.</div>`;
    return;
  }

  if (activeRegistryView === 'icons') {
    grid.innerHTML = filtered.map(item => {
      const itemColor = getItemColor(item);
      const svgMarkup = getProcessedSvg(item.svg, currentStyle, itemColor.hex, itemColor.bg);
      const safeName = escapeHtml(item.name);
      const safeDesc = escapeHtml(item.desc);
      return `
        <button type="button" class="icon-only-tile" data-icon-id="${item.id}"
          aria-label="${safeName}: ${safeDesc}"
          onmouseenter="alignStudioTooltipEdge(this)" onfocus="alignStudioTooltipEdge(this)"
          onclick="openRegistryInspector('${item.id}')">
          <span class="preview-chip" style="color: ${itemColor.hex}; background: ${itemColor.bg}; border: 1px solid ${itemColor.border};">
            ${svgMarkup}
          </span>
          <span class="icon-hover-tooltip" role="tooltip">
            <span class="icon-tooltip-header">
              <strong class="icon-tooltip-name">${safeName}</strong>
              <span class="badge ${item.badgeClass}">${escapeHtml(item.appLabel)}</span>
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
      <div class="card-glass" style="display: flex; flex-direction: column; justify-content: space-between; padding: 14px; border-radius: 10px; background: var(--bg-surface); border: 1px solid var(--border-subtle); transition: transform 0.15s ease, border-color 0.15s ease;">
        <div>
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
            <div class="preview-chip" style="color: ${itemColor.hex}; background: ${itemColor.bg}; border: 1px solid ${itemColor.border}; width: 44px; height: 44px; border-radius: 8px; cursor: pointer;" onclick="openRegistryInspector('${item.id}')" title="Click to inspect SVG code">
              ${svgMarkup}
            </div>
            <span class="badge ${item.badgeClass}" style="font-size: 0.6875rem; text-transform: uppercase;">${item.appLabel}</span>
          </div>
          <h4 style="font-size: 0.9375rem; font-weight: 700; margin: 0 0 4px 0; color: var(--text-primary);">${item.name}</h4>
          <p style="font-size: 0.75rem; color: var(--text-secondary); line-height: 1.45; margin: 0 0 10px 0;">${item.desc}</p>
        </div>
        <div style="display: flex; gap: 6px; align-items: center; border-top: 1px solid var(--border-subtle); padding-top: 10px;">
          <button type="button" class="btn btn-secondary" style="flex: 1; padding: 4px 8px; font-size: 0.6875rem;" onclick="copyRegistrySvg('${item.id}')">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            <span>Copy SVG</span>
          </button>
          <button type="button" class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.6875rem;" onclick="openRegistryInspector('${item.id}')" title="Inspect code">
            <span>Inspect</span>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

function openRegistryInspector(iconId) {
  const item = registryIcons.find(i => i.id === iconId);
  if (item) {
    openInspector(item.name, item.svg);
  }
}

function copyRegistrySvg(iconId) {
  const item = registryIcons.find(i => i.id === iconId);
  if (!item) return;
  const itemColor = getItemColor(item);
  const processed = getProcessedSvg(item.svg, currentStyle, itemColor.hex, itemColor.bg);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(processed).then(() => {
      showStudioToast('SVG Markup copied to clipboard!');
    }).catch(() => {
      openInspector(item.name, item.svg);
    });
  } else {
    openInspector(item.name, item.svg);
  }
}

function renderConceptInnerSvg(concept, uid, c, isLightBg) {
  if (typeof concept.renderInner === 'function') {
    return concept.renderInner(uid, c, isLightBg);
  }
  const wCol = isLightBg ? c.whiteOnLight : c.whiteOnDark;
  return (concept.svgTemplate || '')
    .replace(/__WCOL__/g, wCol)
    .replace(/__DEEP__/g, c.deep)
    .replace(/__SKY__/g, c.sky)
    .replace(/__PRIMARY__/g, c.primary)
    .replace(/__SECONDARY__/g, c.secondary)
    .replace(/__UID__/g, uid);
}

function buildHvlLogoSvg(concept, uid, sizePx, surfaceMode, harmonyKey) {
  const c = hvlLogoHarmonies[harmonyKey || activeHvlHarmony] || hvlLogoHarmonies['white-ostro'];
  if (!concept || !c) return '';
  const surf = surfaceMode || activeHvlSurface;
  const isLightBg = surf === 'azure';

  let bgStops = `<stop offset="0%" stop-color="#242935"/><stop offset="100%" stop-color="#181b22"/>`;
  let borderCol = '#2e3544';
  if (surf === 'azure') {
    bgStops = `<stop offset="0%" stop-color="#FFFFFF"/><stop offset="100%" stop-color="#EDF3FA"/>`;
    borderCol = '#B8CFE8';
  }

  const badgeRects = surf === 'bare' ? '' : `
    <rect width="100" height="100" rx="20" fill="url(#${uid}-bg)"/>
    <rect x="1" y="1" width="98" height="98" rx="19" fill="none" stroke="${borderCol}" stroke-width="1.75"/>
  `;

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="${sizePx}" height="${sizePx}" style="display: block; flex-shrink: 0;">
    <defs>
      <linearGradient id="${uid}-bg" x1="0%" y1="0%" x2="100%" y2="100%">${bgStops}</linearGradient>
      <linearGradient id="${uid}-pri" x1="0%" y1="100%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="${c.primary}"/>
        <stop offset="100%" stop-color="${c.sky}"/>
      </linearGradient>
      <linearGradient id="${uid}-sec" x1="0%" y1="100%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="${c.deep}"/>
        <stop offset="100%" stop-color="${c.secondary}"/>
      </linearGradient>
    </defs>
    ${badgeRects}
    ${renderConceptInnerSvg(concept, uid, c, isLightBg)}
  </svg>`;
}

function renderHvlLogoLab() {
  updateHvlLiveStage();
}

function updateHvlLiveStage() {
  if (!hvlLogoConcepts.length) return;
  const concept = hvlLogoConcepts.find(c => c.id === activeHvlLogoId) || hvlLogoConcepts[0];
  const harmony = hvlLogoHarmonies[activeHvlHarmony] || hvlLogoHarmonies['white-ostro'];

  const titleEl = document.getElementById('hvl-stage-active-name');
  const harmonyEl = document.getElementById('hvl-stage-active-harmony');
  if (titleEl && concept) titleEl.textContent = `${concept.code}: ${concept.title}`;
  if (harmonyEl && harmony) harmonyEl.textContent = harmony.name;

  const heroSlot = document.getElementById('hvl-stage-hero-logo');
  if (heroSlot) heroSlot.innerHTML = buildHvlLogoSvg(concept, 'stage-hero', 60, activeHvlSurface, activeHvlHarmony);

  const navSlot = document.getElementById('hvl-stage-nav-logo');
  if (navSlot) navSlot.innerHTML = buildHvlLogoSvg(concept, 'stage-nav', 28, activeHvlSurface, activeHvlHarmony);

  const topBarLogo = document.getElementById('studio-top-brand-logo');
  if (topBarLogo) topBarLogo.innerHTML = buildHvlLogoSvg(concept, 'top-navbar', 26, activeHvlSurface, activeHvlHarmony);

  const scale64 = document.getElementById('hvl-stage-scale-64');
  const scale24 = document.getElementById('hvl-stage-scale-24');
  const scale16 = document.getElementById('hvl-stage-scale-16');
  if (scale64) scale64.innerHTML = buildHvlLogoSvg(concept, 'stage-s64', 56, activeHvlSurface, activeHvlHarmony);
  if (scale24) scale24.innerHTML = buildHvlLogoSvg(concept, 'stage-s24', 24, activeHvlSurface, activeHvlHarmony);
  if (scale16) scale16.innerHTML = buildHvlLogoSvg(concept, 'stage-s16', 16, activeHvlSurface, activeHvlHarmony);
}

function inspectHvlLogoSvg(conceptId) {
  const concept = hvlLogoConcepts.find(c => c.id === (conceptId || activeHvlLogoId)) || hvlLogoConcepts[0];
  if (!concept) return;
  const svgMarkup = buildHvlLogoSvg(concept, 'hvl-mark', 512, activeHvlSurface, activeHvlHarmony);
  openInspector(`${concept.code}: ${concept.title} (${activeHvlHarmony})`, svgMarkup);
}

function updateAssistantLiveStage() {
  if (!assistantLogoConcepts || !assistantLogoConcepts.length) return;
  const concept = assistantLogoConcepts.find(c => c.id === activeAssistantLogoId) || assistantLogoConcepts[0];
  const titleEl = document.getElementById('asst-stage-active-name');
  const tagEl = document.getElementById('asst-stage-active-tag');
  if (titleEl && concept) titleEl.textContent = `${concept.code}: ${concept.title}`;
  if (tagEl && concept) tagEl.textContent = concept.tag;

  const heroSlot = document.getElementById('asst-stage-hero-logo');
  if (heroSlot) heroSlot.innerHTML = buildHvlLogoSvg(concept, 'asst-hero', 60, activeAssistantSurface, 'white-ostro');

  const navSlot = document.getElementById('asst-stage-nav-logo');
  if (navSlot) navSlot.innerHTML = buildHvlLogoSvg(concept, 'asst-nav', 28, activeAssistantSurface, 'white-ostro');

  const s64 = document.getElementById('asst-stage-scale-64');
  const s24 = document.getElementById('asst-stage-scale-24');
  const s16 = document.getElementById('asst-stage-scale-16');
  if (s64) s64.innerHTML = buildHvlLogoSvg(concept, 'asst-s64', 56, activeAssistantSurface, 'white-ostro');
  if (s24) s24.innerHTML = buildHvlLogoSvg(concept, 'asst-s24', 24, activeAssistantSurface, 'white-ostro');
  if (s16) s16.innerHTML = buildHvlLogoSvg(concept, 'asst-s16', 16, activeAssistantSurface, 'white-ostro');
}

function renderAssistantLogoLab() {
  const grid = document.getElementById('assistant-brand-concepts-grid');
  if (!grid || !assistantLogoConcepts || !assistantLogoConcepts.length) return;
  updateAssistantLiveStage();

  const filtered = assistantLogoConcepts.filter(c => activeAssistantTrack === 'all' || c.track === activeAssistantTrack);
  grid.innerHTML = filtered.map((c, idx) => {
    const isSelected = c.id === activeAssistantLogoId;
    const heroSvg = buildHvlLogoSvg(c, `asst-card-${idx}`, 96, activeAssistantSurface, 'white-ostro');
    const tabIcon = (c.icon24 || '').replace('<svg ', '<svg class="sim-tab-icon" ');
    const navIcon = (c.icon24 || '').replace('<svg ', '<svg width="18" height="18" ');
    return `
      <div class="brand-concept-card" id="asst-concept-card-${c.id}" style="${isSelected ? 'border-color: var(--brand-primary); box-shadow: 0 0 0 2px var(--brand-primary-border), 0 8px 24px rgba(2, 101, 232, 0.22);' : ''}">
        <div class="concept-hero-badge" style="cursor: pointer;" onclick="selectAssistantLogoConcept('${c.id}')" title="Click to preview on Live Context Stage">
          ${heroSvg}
        </div>
        <div>
          <div class="concept-meta-theme">${escapeHtml(c.tag)}</div>
          <div class="concept-meta-title">
            <span>${escapeHtml(c.title)}</span>
            <span class="badge ${c.badgeClass || 'badge-blue'}">${escapeHtml(c.badgeText)}</span>
          </div>
        </div>
        <p class="concept-rationale">${escapeHtml(c.rationale)}</p>
        <div class="concept-preview-row">
          <span class="preview-context-label">Contextual Previews (Ostro Blue #0265E8)</span>
          <div class="sim-tab-bar">
            ${tabIcon}
            <span class="sim-tab-title">HVL Assistant | Chief of Staff</span>
            <span class="sim-tab-close">&times;</span>
          </div>
          <div class="sim-sidebar-brand">
            <div style="background: rgba(2, 101, 232, 0.14); padding: 5px; border-radius: 6px; display: flex; border: 1px solid rgba(2, 101, 232, 0.3);">
              ${navIcon}
            </div>
            <div style="flex: 1; min-width: 0;">
              <div class="sim-sidebar-title">Assistant</div>
              <div class="sim-sidebar-sub">assistant.highvelocitylabs.dev</div>
            </div>
            <span class="badge badge-blue" style="font-size: 0.625rem;">FAMILY VIEW</span>
          </div>
        </div>
        <div style="display: flex; gap: 8px; margin-top: auto;">
          <button type="button" class="btn ${isSelected ? 'btn-primary' : 'btn-secondary'}" style="flex: 1; font-size: 0.75rem; padding: 6px 10px;" onclick="selectAssistantLogoConcept('${c.id}')">
            <span>${isSelected ? 'Active on Stage' : 'Preview on Stage'}</span>
          </button>
          <button type="button" class="btn btn-secondary" style="font-size: 0.75rem; padding: 6px 10px;" onclick="inspectAssistantLogoSvg('${c.id}')">
            <span>Inspect SVG</span>
          </button>
        </div>
      </div>
    `;
  }).join('');
}
window.renderAssistantLogoLab = renderAssistantLogoLab;

function selectAssistantLogoConcept(conceptId) {
  activeAssistantLogoId = conceptId;
  renderAssistantLogoLab();
  const concept = assistantLogoConcepts.find(c => c.id === conceptId);
  if (concept) showStudioToast(`Previewing ${concept.code}: ${concept.title}`);
}
window.selectAssistantLogoConcept = selectAssistantLogoConcept;

function setAssistantSurface(surfaceMode) {
  activeAssistantSurface = surfaceMode || 'graphite';
  document.querySelectorAll('#seg-asst-surface .segment-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-surf') === activeAssistantSurface);
  });
  renderAssistantLogoLab();
}
window.setAssistantSurface = setAssistantSurface;

function setAssistantTrack(trackKey) {
  activeAssistantTrack = trackKey || 'all';
  document.querySelectorAll('#seg-asst-track .segment-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-track') === activeAssistantTrack);
  });
  if (activeAssistantTrack !== 'all') {
    const firstInTrack = assistantLogoConcepts.find(c => c.track === activeAssistantTrack);
    if (firstInTrack) activeAssistantLogoId = firstInTrack.id;
  }
  renderAssistantLogoLab();
}
window.setAssistantTrack = setAssistantTrack;

function inspectAssistantLogoSvg(conceptId) {
  const concept = assistantLogoConcepts.find(c => c.id === (conceptId || activeAssistantLogoId)) || assistantLogoConcepts[0];
  if (!concept) return;
  const svgMarkup = buildHvlLogoSvg(concept, 'asst-mark', 512, activeAssistantSurface, 'white-ostro');
  openInspector(`${concept.code}: ${concept.title} (Ostro Blue)`, svgMarkup);
}
window.inspectAssistantLogoSvg = inspectAssistantLogoSvg;
