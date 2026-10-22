// =========================================================
// COMPENSATION, W-2, SAFE HARBOR & TRANSCRIPTS ENGINE (SSR + HTMX MORPHING)
// =========================================================

let compensationRawData = null;
let chartCompTrends = null;
let safeHarborDebounceTimer = null;

function getActiveCompTaxpayer() {
    const sec = document.getElementById('section-compensation');
    return (sec && sec.dataset.activeTaxpayer) || 'all';
}

function getActiveCompSubtab() {
    const sec = document.getElementById('section-compensation');
    return (sec && sec.dataset.activeSubtab) || 'comp-subtab-career';
}

function switchCompensationSubtab(targetId) {
    if (!targetId) return;
    const sec = document.getElementById('section-compensation');
    if (sec) sec.dataset.activeSubtab = targetId;
    document.querySelectorAll('.comp-subtab').forEach(b => {
        b.classList.toggle('active', b.getAttribute('data-subtab') === targetId);
    });
    document.querySelectorAll('.comp-subtab-pane').forEach(p => {
        p.style.display = p.id === targetId ? 'block' : 'none';
    });
    if (targetId === 'comp-subtab-career') {
        renderCompensationChart();
    }
}

async function morphCompensationSection(optionsOrTaxpayer) {
    let opts = {};
    if (typeof optionsOrTaxpayer === 'string' || typeof optionsOrTaxpayer === 'number') {
        opts = { taxpayer: String(optionsOrTaxpayer) };
    } else if (optionsOrTaxpayer && typeof optionsOrTaxpayer === 'object') {
        opts = optionsOrTaxpayer;
    }

    const taxpayer = String(opts.taxpayer || getActiveCompTaxpayer());
    const subtab = String(opts.subtab || getActiveCompSubtab());
    const params = new URLSearchParams({ taxpayer, subtab });

    if (opts.ytdWithheld !== undefined && opts.ytdWithheld !== null && String(opts.ytdWithheld).trim() !== '') {
        params.set('ytd_withheld', String(opts.ytdWithheld));
    }
    if (opts.remainingPaychecks !== undefined && opts.remainingPaychecks !== null && String(opts.remainingPaychecks).trim() !== '') {
        params.set('remaining_paychecks', String(opts.remainingPaychecks));
    }

    const url = `/fragments/compensation?${params.toString()}`;
    await window.htmx.ajax('GET', url, { target: '#section-compensation', swap: 'morph' });
    renderCompensationChart();
}

async function loadCompensationData() {
    initCompensationControls();
    try {
        const res = await fetch('/api/compensation');
        const json = await res.json();
        if (json.success) {
            compensationRawData = json;
            renderCompensationChart();
        }
    } catch (e) {
        console.error('Failed to load compensation chart data:', e);
    }
}

function renderCompensationChart() {
    const ctx = document.getElementById('chart-compensation-trends');
    const emptyEl = document.getElementById('chart-compensation-empty');
    if (!ctx || typeof Chart === 'undefined' || !compensationRawData) return;

    if (chartCompTrends) {
        chartCompTrends.destroy();
        chartCompTrends = null;
    }

    const activeTaxpayer = getActiveCompTaxpayer();
    const allHistory = compensationRawData.history || [];
    const filtered = activeTaxpayer === 'all'
        ? allHistory
        : allHistory.filter(h => String(h.user_id || 1) === String(activeTaxpayer));

    if (!filtered || filtered.length === 0) {
        ctx.style.display = 'none';
        if (emptyEl) emptyEl.style.display = 'flex';
        return;
    }

    ctx.style.display = 'block';
    if (emptyEl) emptyEl.style.display = 'none';

    const byYear = {};
    filtered.forEach(item => {
        const yr = String(item.year);
        if (!byYear[yr]) {
            byYear[yr] = { year: Number(item.year), salary: 0, bonus: 0, companies: new Set() };
        }
        const b = Number(item.salary || item.base_salary || 0);
        const bo = Number(item.bonus || 0);
        byYear[yr].salary += b;
        byYear[yr].bonus += bo;
        if (item.company || item.employer) byYear[yr].companies.add(item.company || item.employer);
    });

    const sorted = Object.values(byYear).sort((a, b) => a.year - b.year);
    const labels = sorted.map(r => String(r.year));
    const baseData = sorted.map(r => r.salary);
    const bonusData = sorted.map(r => r.bonus);

    chartCompTrends = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Base Salary',
                    data: baseData,
                    backgroundColor: '#3b82f6',
                    borderRadius: 4,
                    stack: 'comp',
                },
                {
                    label: 'Realized Bonus',
                    data: bonusData,
                    backgroundColor: '#10b981',
                    borderRadius: 4,
                    stack: 'comp',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'top',
                    align: 'end',
                    labels: { color: '#94a3b8', font: { size: 11 }, boxWidth: 12, padding: 14 },
                },
                tooltip: {
                    callbacks: {
                        afterTitle: (items) => {
                            const idx = items[0].dataIndex;
                            const rec = sorted[idx];
                            if (rec && rec.companies && rec.companies.size > 0) {
                                return `Employer: ${Array.from(rec.companies).join(' + ')}`;
                            }
                            return '';
                        },
                        label: (item) => ` ${item.dataset.label}: ${fmtCurrency(item.raw, 0)}`,
                        footer: (items) => {
                            const sum = items.reduce((a, b) => a + (Number(b.raw) || 0), 0);
                            return `Total Cash W-2: ${fmtCurrency(sum, 0)}`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    stacked: true,
                    grid: { display: false },
                    ticks: { color: '#94a3b8', font: { size: 11 } },
                },
                y: {
                    stacked: true,
                    grid: { color: 'rgba(255,255,255,0.06)' },
                    ticks: {
                        color: '#94a3b8',
                        font: { size: 11 },
                        callback: (val) => fmtShortCurrency(val),
                    },
                },
            },
        },
    });
}

async function pollTranscriptJobUntilDone(jobId) {
    const maxAttempts = 60;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 600));
        const res = await fetch(`/api/transcripts/status/${encodeURIComponent(jobId)}`);
        const data = await res.json();
        if (data.status === 'processing') {
            continue;
        }
        return data;
    }
    return { success: false, error: 'Document parsing timed out.' };
}

function setUploadStatus(el, color, text) {
    if (!el) return;
    el.style.color = color;
    el.textContent = text;
}

function initCompensationControls() {
    if (typeof window.initCompensationModals === 'function') {
        window.initCompensationModals();
    }
    if (!document.body || document.body.dataset.compensationDelegated === 'true') return;
    document.body.dataset.compensationDelegated = 'true';

    document.addEventListener('click', async (e) => {
        const subtabBtn = e.target.closest('.comp-subtab');
        if (subtabBtn) {
            const targetId = subtabBtn.getAttribute('data-subtab');
            switchCompensationSubtab(targetId);
            return;
        }

        const adultPill = e.target.closest('.comp-adult-pill[data-user-id]');
        if (adultPill) {
            const uid = adultPill.getAttribute('data-user-id') || 'all';
            await morphCompensationSection({ taxpayer: uid, subtab: getActiveCompSubtab() });
            return;
        }

        const uploadBtn = e.target.closest('#btn-upload-w2-trigger');
        if (uploadBtn) {
            const fileInput = document.getElementById('input-w2-pdf');
            if (fileInput) fileInput.click();
            return;
        }

        const transcriptUploadBtn = e.target.closest('#btn-upload-pdf-trigger');
        if (transcriptUploadBtn) {
            const fileInput = document.getElementById('input-transcript-pdf');
            if (fileInput) fileInput.click();
            return;
        }
    });

    document.addEventListener('input', (e) => {
        const shInput = e.target.closest('#input-ytd-withheld, #input-paychecks');
        if (!shInput) return;
        if (safeHarborDebounceTimer) clearTimeout(safeHarborDebounceTimer);
        safeHarborDebounceTimer = setTimeout(() => {
            const ytdEl = document.getElementById('input-ytd-withheld');
            const payEl = document.getElementById('input-paychecks');
            morphCompensationSection({
                taxpayer: getActiveCompTaxpayer(),
                subtab: 'comp-subtab-safeharbor',
                ytdWithheld: ytdEl ? ytdEl.value : undefined,
                remainingPaychecks: payEl ? payEl.value : undefined,
            });
        }, 250);
    });

    document.addEventListener('change', async (e) => {
        const w2Input = e.target.closest('#input-w2-pdf');
        if (w2Input && w2Input.files && w2Input.files.length > 0) {
            const file = w2Input.files[0];
            const statusBanner = document.getElementById('w2-upload-status') || document.getElementById('compensation-status-banner');
            setUploadStatus(statusBanner, 'var(--accent-blue)', `Parsing "${file.name}" in memory (0 disk storage)...`);

            const formData = new FormData();
            formData.append('file', file);
            const activeTp = getActiveCompTaxpayer();
            if (activeTp !== 'all') {
                formData.append('user_id', String(activeTp));
            }

            try {
                const res = await fetch('/api/compensation/upload_w2', { method: 'POST', body: formData });
                let json = await res.json();
                if (res.ok && json.status === 'processing' && json.job_id) {
                    json = await pollTranscriptJobUntilDone(json.job_id);
                }
                if (!res.ok || !json.success) {
                    setUploadStatus(statusBanner, 'var(--status-red)', json.error || 'Could not parse W-2 PDF.');
                    await window.showModalAlert(json.error || 'Failed to upload W-2.', { title: 'Upload Error', type: 'error' });
                } else if (!window.__DOMAIN_VERSIONS__) {
                    await loadCompensationData();
                    await morphCompensationSection();
                }
            } catch (err) {
                console.error('W-2 upload failed:', err);
                setUploadStatus(statusBanner, 'var(--status-red)', `Upload failed: ${err.message}`);
                await window.showModalAlert(err.message || 'Failed to upload W-2.', { title: 'Upload Error', type: 'error' });
            } finally {
                w2Input.value = '';
            }
            return;
        }

        const transcriptInput = e.target.closest('#input-transcript-pdf');
        if (transcriptInput && transcriptInput.files && transcriptInput.files.length > 0) {
            const file = transcriptInput.files[0];
            const statusEl = document.getElementById('transcript-upload-status');
            const selectAdult = document.getElementById('select-upload-adult');
            const targetAdult = (selectAdult && selectAdult.value) ? selectAdult.value : '';

            setUploadStatus(statusEl, 'var(--accent-orange)', `Processing "${file.name}" in memory (0 disk storage)...`);

            const formData = new FormData();
            formData.append('file', file);
            if (targetAdult) {
                formData.append('adult', targetAdult);
            }

            try {
                const sec = document.getElementById('section-compensation');
                if (sec) sec.dataset.activeSubtab = 'comp-subtab-transcripts';
                const res = await fetch('/api/transcripts/upload', {
                    method: 'POST',
                    body: formData,
                });
                let json = await res.json();
                if (res.ok && json.status === 'processing' && json.job_id) {
                    json = await pollTranscriptJobUntilDone(json.job_id);
                    if (json && json.success) {
                        await loadCompensationData();
                        await morphCompensationSection({ subtab: 'comp-subtab-transcripts' });
                    }
                } else if (res.ok && json.success && !window.__DOMAIN_VERSIONS__) {
                    await loadCompensationData();
                    await morphCompensationSection({ subtab: 'comp-subtab-transcripts' });
                }
                if (!res.ok || !json.success) {
                    setUploadStatus(statusEl, 'var(--status-red)', json.error || 'Could not parse transcript PDF.');
                    await window.showModalAlert(json.error || 'Failed to upload tax transcript.', { title: 'Upload Error', type: 'error' });
                } else {
                    const updatedStatus = document.getElementById('transcript-upload-status');
                    setUploadStatus(updatedStatus, 'var(--status-green)', `✓ Encrypted ${json.data?.year || ''} transcript (${json.adult || targetAdult}). Zero disk files.`);
                }
            } catch (err) {
                console.error('Transcript upload failed:', err);
                setUploadStatus(statusEl, 'var(--status-red)', `Upload failed: ${err.message}`);
                await window.showModalAlert(err.message || 'Failed to upload tax transcript.', { title: 'Upload Error', type: 'error' });
            } finally {
                transcriptInput.value = '';
            }
        }
    });
}

async function cycleTaxDocStatus(itemId, nextStatus) {
    if (!itemId) return;
    try {
        const resp = await fetch('/api/tax/checklist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_id: itemId, status: nextStatus || 'cycle' }),
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            await morphCompensationSection({ subtab: 'comp-subtab-transcripts' });
        } else if (typeof window.showModalAlert === 'function') {
            await window.showModalAlert(res.error || 'Failed to update document status.', { title: 'Checklist Notice', type: 'error' });
        }
    } catch (err) {
        console.error('Checklist status update error:', err);
    }
}

if (typeof window !== 'undefined') {
    Object.assign(window, {
        getActiveCompTaxpayer,
        getActiveCompSubtab,
        loadCompensationData,
        fetchCompensationData: loadCompensationData,
        morphCompensationSection,
        switchCompensationSubtab,
        renderCompensationChart,
        pollTranscriptJobUntilDone,
        initCompensationControls,
        cycleTaxDocStatus,
        openCompForm: (...args) => (window.openCompForm ? window.openCompForm(...args) : undefined),
        closeCompForm: (...args) => (window.closeCompForm ? window.closeCompForm(...args) : undefined),
    });
    if (typeof window.registerSectionHydrator === 'function') {
        window.registerSectionHydrator('section-compensation', loadCompensationData, {
            morphFn: () => morphCompensationSection()
        });
    }
}
