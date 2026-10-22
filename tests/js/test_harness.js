const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { createTestDomEnvironment } = require('../../vendor/hvl_common/testing/js/dom_harness.js');

describe('AI Advisor & Settings Clientside JavaScript Test Suite', () => {
    let dom;
    let window;
    let document;

    const baseHtml = `
    <!DOCTYPE html>
    <html>
    <head><title>Test</title></head>
    <body data-is-demo="false">
        <header class="top-header">
            <h1 id="page-header-title">Overview & Net Worth</h1>
            <div class="mobile-nav-dropdown-wrapper">
                <select id="mobile-nav-select" class="mobile-nav-select">
                    <option value="section-overview">Overview & Net Worth</option>
                    <option value="section-equity">Company Equity</option>
                    <option value="section-scenarios">Forecasting</option>
                </select>
            </div>
            <!-- Header / Sidebar Triggers -->
            <button id="btn-open-ai-advisor" aria-label="Ask AI Financial Advisor">✨ Ask AI</button>
            <button id="btn-sidebar-advisor" aria-label="Ask AI Financial Advisor">✨ Sidebar Advisor</button>
            <button id="btn-open-settings" aria-label="Settings & Assumptions">⚙️ Settings</button>
            <button id="btn-sidebar-settings" aria-label="Settings & Assumptions">⚙️ Sidebar Settings</button>
            <button type="button" id="btn-view-tabs" class="pill-btn active">Focused Page</button>
            <button type="button" id="btn-view-all" class="pill-btn">View All (Scroll)</button>
            <button type="button" id="btn-sync"><span id="sync-btn-text">Sync Monarch</span></button>
            <button type="button" id="btn-mobile-sync"><span id="mobile-sync-btn-text">Sync</span></button>
            <button type="button" id="btn-logout">Sign Out</button>
            <button type="button" id="btn-mobile-logout">Sign Out</button>
            <!-- Badge orange element from unrelated section -->
            <span class="badge badge-orange">Active Year: 2026</span>
        </header>

        <main class="main-content">
            <div class="content-body">
                <section id="section-overview" class="page-section" style="height: 500px; display: block;">Overview Content</section>
                <section id="section-equity" class="page-section" style="height: 500px; display: none;">Equity Content</section>
                <section id="section-scenarios" class="page-section" style="height: 500px; display: none;">Scenarios Content</section>
            </div>
            ${fs.readFileSync(path.join(__dirname, '../../templates/components/ai_advisor_drawer.html'), 'utf8')}
            ${fs.readFileSync(path.join(__dirname, '../../templates/components/settings.html'), 'utf8')
                .replace(/{{\s*hvl_settings_subnav\([\s\S]*?\)\s*}}/, `
                    <div class="hvl-subnav-container" id="settings-subnav-container">
                        <div class="hvl-subnav-inner" id="settings-subnav-inner">
                            <div class="hvl-subnav-links">
                                <button type="button" id="tab-btn-members" data-tab="members" class="hvl-subnav-link settings-tab-btn active">Household &amp; Access</button>
                                <button type="button" id="tab-btn-assumptions" data-tab="assumptions" class="hvl-subnav-link settings-tab-btn">Tax &amp; Legal Profile</button>
                                <button type="button" id="tab-btn-roles" data-tab="roles" class="hvl-subnav-link settings-tab-btn">Account Classifications</button>
                                <button type="button" id="tab-btn-monarch" data-tab="monarch" class="hvl-subnav-link settings-tab-btn">Account Connections</button>
                                <button type="button" id="tab-btn-appearance" data-tab="appearance" class="hvl-subnav-link settings-tab-btn">Appearance</button>
                                <button type="button" id="tab-btn-advisor-history" data-tab="advisor-history" class="hvl-subnav-link settings-tab-btn">AI Advisor History</button>
                            </div>
                        </div>
                    </div>
                `)}
        </main>
    </body>
    </html>
    `;

    beforeEach(() => {
        const env = createTestDomEnvironment({
            html: baseHtml,
            url: 'https://finances.highvelocitylabs.dev/#overview',
            fetchHandlers: [
                {
                    matcher: (url, opts) => opts.method === 'PATCH',
                    handler: async () => ({ ok: true, json: async () => ({ success: true }) }),
                },
                {
                    matcher: (url) => url.includes('/api/ai-advisor/conversations') && !url.includes('/api/ai-advisor/conversations/'),
                    handler: async () => ({
                        ok: true,
                        json: async () => ({
                            success: true,
                            conversations: [
                                {
                                    conversation_id: 'conv-equity-01',
                                    title: 'Option Exercise Planning',
                                    page_section: 'section-equity',
                                    created_by: 'Primary Member',
                                    is_pinned: 1,
                                    created_at: '2026-10-10 14:00:00',
                                    updated_at: '2026-10-10 14:05:00',
                                    message_count: 2,
                                    last_message: 'Strike capital is $87,500'
                                },
                                {
                                    conversation_id: 'conv-holdings-02',
                                    title: 'Portfolio Drift Review',
                                    page_section: 'section-holdings',
                                    created_by: 'Primary Member',
                                    is_pinned: 0,
                                    created_at: '2026-10-11 09:00:00',
                                    updated_at: '2026-10-11 09:10:00',
                                    message_count: 2,
                                    last_message: 'US Equities at 53.2%'
                                },
                                {
                                    conversation_id: 'conv-arbitrage-03',
                                    title: 'State Tax Domicile Planning',
                                    page_section: 'section-arbitrage',
                                    created_by: 'Primary Member',
                                    is_pinned: 0,
                                    created_at: '2026-10-12 11:00:00',
                                    updated_at: '2026-10-12 11:15:00',
                                    message_count: 2,
                                    last_message: '183-day statutory rule'
                                }
                            ]
                        })
                    }),
                },
                {
                    matcher: '/api/ai-advisor/conversations/conv-equity-01',
                    handler: async () => ({
                        ok: true,
                        json: async () => ({
                            success: true,
                            conversation: {
                                conversation_id: 'conv-equity-01',
                                title: 'Option Exercise Planning',
                                page_section: 'section-equity',
                                created_by: 'Primary Member',
                                is_pinned: 1,
                                created_at: '2026-10-10 14:00:00',
                                updated_at: '2026-10-10 14:05:00',
                                messages: [
                                    { message_id: 1, role: 'user', content: 'What are my options?' },
                                    { message_id: 2, role: 'model', content: 'Here is your option breakdown.' }
                                ]
                            }
                        })
                    }),
                },
                {
                    matcher: '/api/ai-advisor/conversations/conv-invalid',
                    handler: async () => ({
                        ok: false,
                        json: async () => ({ success: false, error: 'Conversation not found' })
                    }),
                },
                {
                    matcher: '/api/ai-advisor/context',
                    handler: async () => ({
                        ok: true,
                        json: async () => ({
                            success: true,
                            family_name: 'The Jones Family',
                            policy_anchor: 'core_satellite',
                            suggestions: ['How to exercise options?', 'Review portfolio drift']
                        })
                    }),
                },
                {
                    matcher: '/api/ai-advisor/chat',
                    handler: async () => ({
                        ok: true,
                        json: async () => ({
                            success: true,
                            reply: 'Simulated fiduciary reply.',
                            conversation_id: 'conv-new-789',
                            conversation_title: 'New Chat Thread'
                        })
                    }),
                },
                {
                    matcher: '/api/sync',
                    handler: async () => ({
                        ok: true,
                        json: async () => ({
                            success: true,
                            message: 'Monarch sync successful! Updated 12 accounts.',
                            accounts_count: 12
                        })
                    }),
                },
                {
                    matcher: (url) => String(url).includes('/fragments/settings'),
                    handler: async (url) => {
                        const u = new URL(url, 'https://finances.highvelocitylabs.dev');
                        const q = (u.searchParams.get('adv_search') || '').toLowerCase();
                        const page = u.searchParams.get('adv_page') || '';
                        const pinnedOnly = u.searchParams.get('adv_pinned_only') === '1';
                        const allConvs = [
                            {
                                id: 'conv-equity-01',
                                title: 'Option Exercise Planning',
                                page_section: 'section-equity',
                                page_label: 'Company Equity & RSUs',
                                created_by: 'Primary Member',
                                is_pinned: true,
                                updated_at: '2026-10-10 14:05',
                                last_message: 'Strike capital is $87,500'
                            },
                            {
                                id: 'conv-holdings-02',
                                title: 'Portfolio Drift Review',
                                page_section: 'section-holdings',
                                page_label: 'Investments & IPS',
                                created_by: 'Primary Member',
                                is_pinned: false,
                                updated_at: '2026-10-11 09:10',
                                last_message: 'US Equities at 53.2%'
                            },
                            {
                                id: 'conv-arbitrage-03',
                                title: 'State Tax Domicile Planning',
                                page_section: 'section-arbitrage',
                                page_label: 'Multi-State Tax Arbitrage',
                                created_by: 'Primary Member',
                                is_pinned: false,
                                updated_at: '2026-10-12 11:15',
                                last_message: '183-day statutory rule'
                            }
                        ];
                        const filtered = allConvs.filter(c => {
                            if (pinnedOnly && !c.is_pinned) return false;
                            if (page && c.page_section !== page) return false;
                            if (q && !(`${c.title} ${c.last_message}`.toLowerCase().includes(q))) return false;
                            return true;
                        });
                        const rowsHtml = filtered.map(c => `
                            <tr class="settings-conv-row" data-conv-id="${c.id}" data-page="${c.page_section}" data-pinned="${c.is_pinned ? '1' : '0'}" data-search="${(c.title + ' ' + c.last_message).toLowerCase()}">
                                <td style="text-align: center;"><input type="checkbox" class="settings-conv-checkbox" value="${c.id}"></td>
                                <td style="text-align: center;">
                                    <button type="button" class="btn-toggle-pin-conv" data-conv-id="${c.id}" data-pinned="${c.is_pinned ? '1' : '0'}">${c.is_pinned ? '★' : '☆'}</button>
                                </td>
                                <td><div style="font-weight: 600;">${c.title}</div><div>${c.last_message}</div></td>
                                <td><span class="badge badge-blue">${c.page_label}</span></td>
                                <td>${c.created_by}</td>
                                <td>${c.updated_at}</td>
                                <td class="text-right">
                                    <button type="button" class="btn btn-secondary btn-sm btn-open-advisor-from-settings" data-conv-id="${c.id}" data-page="${c.page_section}">Open</button>
                                    <button type="button" class="btn btn-secondary btn-sm btn-delete-conv-from-settings" data-conv-id="${c.id}" data-title="${c.title}">✕</button>
                                </td>
                            </tr>
                        `).join('');
                        const rawSettings = fs.readFileSync(path.join(__dirname, '../../templates/components/settings.html'), 'utf8');
                        const renderedSettings = rawSettings
                            .replace(/<tbody id="settings-advisor-conversations-tbody">[\s\S]*?<\/tbody>/, () => `<tbody id="settings-advisor-conversations-tbody">${rowsHtml}</tbody>`)
                            .replace(/id="settings-tab-advisor-history"([^>]*?)style="[^"]*"/, 'id="settings-tab-advisor-history"$1style="display: block;"');
                        return {
                            ok: true,
                            text: async () => renderedSettings
                        };
                    }
                },
                {
                    matcher: '/api/auth/logout',
                    handler: async () => ({ ok: true, json: async () => ({ success: true }) }),
                }
            ]
        });

        dom = env.dom;
        window = env.window;
        document = env.document;

        window.Idiomorph = {
            morph(target, newContent) {
                const el = typeof target === 'string' ? document.querySelector(target) : target;
                if (!el) return;
                if (typeof newContent === 'string') {
                    const temp = document.createElement('div');
                    temp.innerHTML = newContent.trim();
                    const nextEl = (el.id && temp.querySelector(`#${el.id}`)) || temp.firstElementChild;
                    if (nextEl) {
                        Array.from(nextEl.attributes).forEach(attr => el.setAttribute(attr.name, attr.value));
                        el.replaceChildren(...Array.from(nextEl.childNodes));
                    } else {
                        el.innerHTML = newContent;
                    }
                } else if (newContent && newContent.childNodes) {
                    if (newContent.attributes) {
                        Array.from(newContent.attributes).forEach(attr => el.setAttribute(attr.name, attr.value));
                    }
                    el.replaceChildren(...Array.from(newContent.childNodes));
                }
            }
        };
        window.htmx = {
            async ajax(method, url, context = {}) {
                const resp = await window.fetch(url, { method });
                if (resp && resp.ok && typeof resp.text === 'function') {
                    const html = await resp.text();
                    if (context.target) {
                        window.Idiomorph.morph(context.target, html);
                    }
                }
            }
        };

        // Load scripts via real DOM <script> elements (matching real browser evaluation)
        const loadScript = (code) => {
            const scriptEl = document.createElement('script');
            scriptEl.textContent = code;
            document.body.appendChild(scriptEl);
        };

        const utilsJs = fs.readFileSync(path.join(__dirname, '../../vendor/hvl_common/ui/static/utils.js'), 'utf8');
        const toastJs = fs.readFileSync(path.join(__dirname, '../../vendor/hvl_common/ui/static/toast.js'), 'utf8');
        const reactiveSignalsJs = fs.readFileSync(path.join(__dirname, '../../vendor/hvl_common/ui/static/reactive-signals.js'), 'utf8');
        const chatDrawerJs = fs.readFileSync(path.join(__dirname, '../../vendor/hvl_common/ui/static/chat-drawer.js'), 'utf8');
        const appSyncJs = fs.readFileSync(path.join(__dirname, '../../static/js/app_sync.js'), 'utf8');
        const appNavJs = fs.readFileSync(path.join(__dirname, '../../static/js/app_navigation.js'), 'utf8');
        const appHydrationJs = fs.readFileSync(path.join(__dirname, '../../static/js/app_hydration.js'), 'utf8');
        const appJs = fs.readFileSync(path.join(__dirname, '../../static/js/app.js'), 'utf8');
        const aiAdvisorUiJs = fs.readFileSync(path.join(__dirname, '../../static/js/ai_advisor_ui.js'), 'utf8');
        const aiAdvisorThreadsJs = fs.readFileSync(path.join(__dirname, '../../static/js/ai_advisor_threads.js'), 'utf8');
        const aiAdvisorChatJs = fs.readFileSync(path.join(__dirname, '../../static/js/ai_advisor_chat.js'), 'utf8');
        const aiAdvisorJs = fs.readFileSync(path.join(__dirname, '../../static/js/ai_advisor.js'), 'utf8');
        const settingsAccountsJs = fs.readFileSync(path.join(__dirname, '../../static/js/settings_accounts.js'), 'utf8');
        const settingsMembersJs = fs.readFileSync(path.join(__dirname, '../../static/js/settings_members.js'), 'utf8');
        const settingsIntegrationsJs = fs.readFileSync(path.join(__dirname, '../../static/js/settings_integrations.js'), 'utf8');
        const settingsSecurityJs = fs.readFileSync(path.join(__dirname, '../../static/js/settings_security.js'), 'utf8');
        const settingsDesktopJs = fs.readFileSync(path.join(__dirname, '../../static/js/settings_desktop.js'), 'utf8');
        const settingsAdminJs = fs.readFileSync(path.join(__dirname, '../../static/js/settings_admin.js'), 'utf8');
        const settingsJs = fs.readFileSync(path.join(__dirname, '../../static/js/settings.js'), 'utf8');

        loadScript(utilsJs);
        loadScript(toastJs);
        loadScript(reactiveSignalsJs);
        loadScript(chatDrawerJs);
        loadScript(appSyncJs);
        loadScript(appNavJs);
        loadScript(appHydrationJs);
        loadScript(appJs);
        loadScript(aiAdvisorUiJs);
        loadScript(aiAdvisorThreadsJs);
        loadScript(aiAdvisorChatJs);
        loadScript(aiAdvisorJs);
        loadScript(settingsAccountsJs);
        loadScript(settingsMembersJs);
        loadScript(settingsIntegrationsJs);
        loadScript(settingsSecurityJs);
        loadScript(settingsDesktopJs);
        loadScript(settingsAdminJs);
        loadScript(settingsJs);
    });

    it('1. should initialize without uncaught errors', () => {
        assert.ok(typeof window.initAiAdvisor === 'function');
        assert.ok(typeof window.toggleAiAdvisorDrawer === 'function');
        assert.ok(typeof window.openAdvisorConversation === 'function');
    });

    it('2. should verify close button consistency and placement', () => {
        const drawerClose = document.getElementById('btn-close-ai-advisor');
        const panelClose = document.getElementById('btn-close-conversations-panel');
        const settingsClose = document.getElementById('btn-close-settings-modal');

        assert.ok(drawerClose, 'Drawer close button exists');
        assert.ok(panelClose, 'Panel close button exists');
        assert.ok(settingsClose, 'Settings close button exists');

        assert.strictEqual(drawerClose.classList.contains('modal-close-btn'), true, 'Drawer close button uses modal-close-btn');
        assert.strictEqual(panelClose.classList.contains('modal-close-btn'), true, 'Panel close button uses modal-close-btn');
        assert.strictEqual(settingsClose.classList.contains('modal-close-btn'), true, 'Settings close button uses modal-close-btn');
    });

    it('3. should toggle drawer open, closed, and dismiss via backdrop', () => {
        const drawer = document.getElementById('ai-advisor-drawer');
        const backdrop = document.getElementById('ai-advisor-backdrop');

        window.toggleAiAdvisorDrawer(true);
        assert.strictEqual(drawer.style.display, 'flex');
        assert.strictEqual(backdrop.style.display, 'block');

        // Test backdrop click dismiss
        backdrop.click();
        assert.strictEqual(drawer.classList.contains('open'), false);
    });

    it('4. should open conversations switcher and render threads with proper metadata', async () => {
        window.toggleAiAdvisorDrawer(true);
        const panelBtn = document.getElementById('btn-toggle-conversations');
        panelBtn.click();

        const panel = document.getElementById('advisor-conversations-panel');
        assert.strictEqual(panel.style.display, 'flex');

        await new Promise(r => setTimeout(r, 60));

        const cards = document.querySelectorAll('.advisor-conv-card');
        assert.strictEqual(cards.length, 3, 'Rendered 3 conversation cards');

        // Check card content
        const firstCardTitle = cards[0].querySelector('.advisor-conv-card-title').textContent;
        assert.ok(firstCardTitle.includes('Option Exercise Planning'));
    });

    it('5. should search conversations case-insensitively without throwing TypeError', async () => {
        window.toggleAiAdvisorDrawer(true);
        const panelBtn = document.getElementById('btn-toggle-conversations');
        panelBtn.click();

        await new Promise(r => setTimeout(r, 60));

        const searchInput = document.getElementById('advisor-conv-search');
        assert.ok(searchInput, 'Search input exists');

        // Search in uppercase to ensure .toLowerCase() works properly
        searchInput.value = 'DRIFT';
        searchInput.dispatchEvent(new window.Event('input'));

        const filteredCards = document.querySelectorAll('.advisor-conv-card');
        assert.strictEqual(filteredCards.length, 1, 'Only 1 card matches DRIFT');
        assert.ok(filteredCards[0].textContent.includes('Portfolio Drift Review'));

        // Reset search
        searchInput.value = '';
        searchInput.dispatchEvent(new window.Event('input'));
        assert.strictEqual(document.querySelectorAll('.advisor-conv-card').length, 3);
    });

    it('6. should filter conversations by pinned status', async () => {
        window.toggleAiAdvisorDrawer(true);
        const panelBtn = document.getElementById('btn-toggle-conversations');
        panelBtn.click();

        await new Promise(r => setTimeout(r, 60));

        const pinnedPill = document.querySelector('.advisor-conv-filter-pill[data-filter="pinned"]');
        assert.ok(pinnedPill, 'Pinned filter pill exists');

        pinnedPill.click();

        const pinnedCards = document.querySelectorAll('.advisor-conv-card');
        assert.strictEqual(pinnedCards.length, 1, 'Only 1 pinned conversation');
        assert.ok(pinnedCards[0].textContent.includes('Option Exercise Planning'));
    });

    it('7. should open selected conversation and populate messages cleanly', async () => {
        window.toggleAiAdvisorDrawer(true);
        const panelBtn = document.getElementById('btn-toggle-conversations');
        panelBtn.click();

        await new Promise(r => setTimeout(r, 60));

        const cards = document.querySelectorAll('.advisor-conv-card');
        cards[0].click(); // click Option Exercise Planning

        await new Promise(r => setTimeout(r, 80));

        const threadTitle = document.getElementById('advisor-thread-title-display');
        assert.strictEqual(threadTitle.textContent, 'Option Exercise Planning');

        const messages = document.querySelectorAll('#ai-advisor-messages .advisor-msg');
        assert.ok(messages.length >= 2, 'Loaded at least 2 chat turns');
    });

    it('8. should gracefully handle failed conversation load with user alert', async () => {
        window.toggleAiAdvisorDrawer(true);
        await window.openAdvisorConversation('conv-invalid');

        assert.strictEqual(window.__lastAlert.includes('Conversation not found'), true);
    });

    it('9. should switch tabs in settings modal to AI Advisor History and open conversation', async () => {
        const tabBtn = document.getElementById('tab-btn-advisor-history');
        const tabContent = document.getElementById('settings-tab-advisor-history');

        tabBtn.click();
        assert.strictEqual(tabContent.style.display, 'block');

        await new Promise(r => setTimeout(r, 60));

        const rows = document.querySelectorAll('.settings-conv-row');
        assert.strictEqual(rows.length, 3, 'Rendered 3 rows in settings history');

        // Test clicking open button on row 0
        const openBtn = rows[0].querySelector('.btn-open-advisor-from-settings');
        assert.ok(openBtn, 'Open button exists on row');
        openBtn.click();

        await new Promise(r => setTimeout(r, 80));

        const drawer = document.getElementById('ai-advisor-drawer');
        assert.strictEqual(drawer.style.display, 'flex');

        const threadTitle = document.getElementById('advisor-thread-title-display');
        assert.strictEqual(threadTitle.textContent, 'Option Exercise Planning');
    });

    it('10. should support mobile pull bar tap dismissal', () => {
        const drawer = document.getElementById('ai-advisor-drawer');
        const pullBar = document.getElementById('advisor-mobile-pull-bar');

        assert.ok(pullBar, 'Mobile pull bar exists');

        window.toggleAiAdvisorDrawer(true);
        assert.strictEqual(drawer.style.display, 'flex');

        pullBar.click();
        assert.strictEqual(drawer.classList.contains('open'), false);
    });

    it('11. should open AI advisor and Settings modals via button click triggers', () => {
        const btnAdvisor = document.getElementById('btn-open-ai-advisor');
        const drawer = document.getElementById('ai-advisor-drawer');
        const btnSettings = document.getElementById('btn-open-settings');
        const settingsModal = document.getElementById('settings-modal');

        assert.ok(btnAdvisor, 'btn-open-ai-advisor exists');
        assert.ok(btnSettings, 'btn-open-settings exists');

        // Click AI Advisor trigger
        btnAdvisor.click();
        assert.strictEqual(drawer.style.display, 'flex', 'AI advisor opened on button click');

        // Close advisor
        window.toggleAiAdvisorDrawer(false);
        assert.strictEqual(drawer.classList.contains('open'), false);

        // Click Settings trigger
        btnSettings.click();
        assert.strictEqual(settingsModal.style.display, 'flex', 'Settings opened on button click');
    });

    it('12. should prevent sticky tooltips by ensuring buttons do not possess native title attributes on touch interaction', () => {
        const btnAdvisor = document.getElementById('btn-open-ai-advisor');
        const btnSettings = document.getElementById('btn-open-settings');
        const btnCloseAdvisor = document.getElementById('btn-close-ai-advisor');

        // Neither button should have native title attribute that causes sticky mobile OS tooltips
        assert.strictEqual(btnAdvisor.hasAttribute('title'), false, 'btn-open-ai-advisor has no title attribute');
        assert.strictEqual(btnSettings.hasAttribute('title'), false, 'btn-open-settings has no title attribute');
        assert.strictEqual(btnCloseAdvisor.hasAttribute('title'), false, 'btn-close-ai-advisor has no title attribute');

        // All should have aria-label for accessibility
        assert.ok(btnAdvisor.getAttribute('aria-label'), 'btn-open-ai-advisor has aria-label');
        assert.ok(btnSettings.getAttribute('aria-label'), 'btn-open-settings has aria-label');
        assert.ok(btnCloseAdvisor.getAttribute('aria-label'), 'btn-close-ai-advisor has aria-label');
    });

    it('13. should ask to sign out of portal (not demo) when logged in even if badge-orange is in DOM', async () => {
        // Confirm DOM contains .badge-orange
        assert.ok(document.querySelector('.badge-orange'), 'A .badge-orange element is present in DOM');
        assert.strictEqual(window.isDemoSession(), false, 'isDemoSession correctly identifies not demo');

        await window.doLogout();
        assert.strictEqual(window.__lastConfirmTitle, 'Sign Out');
        assert.strictEqual(window.__lastConfirmMsg, 'Sign out of Family Office portal?');
    });

    it('14. should trigger Monarch sync via mobile sync button and notify user', async () => {
        const btnMobileSync = document.getElementById('btn-mobile-sync');
        assert.ok(btnMobileSync, 'Mobile sync button exists');

        await window.triggerMonarchSync();
        assert.strictEqual(window.__lastToastVariant, 'success');
        assert.ok(window.__lastToastMsg.includes('Monarch sync successful'));

        const toastEl = document.querySelector('.hvl-toast');
        assert.ok(toastEl, 'Dismissible toast is rendered in DOM');
        const closeBtn = toastEl.querySelector('.hvl-toast-close');
        assert.ok(closeBtn, 'Toast has a dismiss close button');
        closeBtn.click();
        assert.strictEqual(document.querySelector('.hvl-toast'), null, 'Clicking close button removes toast from DOM');
    });

    it('15. should update mobile dropdown header as user scrolls through sections in View All mode', () => {
        const btnAll = document.getElementById('btn-view-all');
        const mobileNavSelect = document.getElementById('mobile-nav-select');
        const headerTitle = document.getElementById('page-header-title');

        btnAll.click();

        // Simulate active section change
        window.syncActiveSectionHeader('section-equity');
        assert.strictEqual(mobileNavSelect.value, 'section-equity', 'Mobile nav dropdown updated to Company Equity');
        assert.ok(headerTitle.textContent.includes('Company Equity'), 'Page header title updated to Company Equity');

        window.syncActiveSectionHeader('section-scenarios');
        assert.strictEqual(mobileNavSelect.value, 'section-scenarios', 'Mobile nav dropdown updated to Forecasting');
        assert.ok(headerTitle.textContent.includes('Forecasting'), 'Page header title updated to Forecasting');
    });

    it('16. should poll /api/ai-advisor/jobs/<job_id> when chat endpoint returns status=processing', async () => {
        let pollCalls = 0;
        const origFetch = window.fetch;
        window.fetch = async (url, opts) => {
            if (String(url).includes('/api/ai-advisor/jobs/job-bg-999')) {
                pollCalls += 1;
                return {
                    ok: true,
                    json: async () => ({
                        success: true,
                        status: 'completed',
                        reply: 'Background executor completed fiduciary analysis.',
                        conversation_id: 'conv-bg-999',
                        conversation_title: 'Background Job Thread'
                    })
                };
            }
            if (String(url).includes('/api/ai-advisor/chat')) {
                return {
                    ok: true,
                    json: async () => ({
                        success: true,
                        status: 'processing',
                        job_id: 'job-bg-999',
                        conversation_id: 'conv-bg-999',
                        conversation_title: 'Background Job Thread'
                    })
                };
            }
            return origFetch(url, opts);
        };

        const inputEl = document.getElementById('ai-advisor-input');
        inputEl.value = 'Analyze portfolio drift';
        await window.submitAiAdvisorMessage();
        assert.ok(pollCalls >= 1, 'Polled /api/ai-advisor/jobs/job-bg-999 at least once');
        const msgList = document.getElementById('ai-advisor-messages');
        assert.ok(msgList.innerHTML.includes('Background executor completed fiduciary analysis.'), 'Rendered background job reply into chat DOM');
    });
});

describe('All SSR Component Templates & Client-Side JS Modules Suite', () => {
    let window;
    let document;
    let requestedUrls;
    let chartCallbacksExecuted;

    const readTpl = (relPath) => {
        const full = path.join(__dirname, '../../templates', relPath);
        if (!fs.existsSync(full)) return '';
        let content = fs.readFileSync(full, 'utf8');
        return content.replace(/\{%\s*include\s+['"]([^'"]+)['"]\s*%\}/g, (_, incPath) => readTpl(incPath));
    };

    const fullPortalHtml = `
    <!DOCTYPE html>
    <html>
    <head><title>Full Portal SSR Suite</title></head>
    <body data-is-demo="false">
        <div class="app-wrapper">
            <aside class="sidebar">
                <a href="/" class="nav-link active" data-target="section-overview">Overview</a>
                <a href="/equity" class="nav-link" data-target="section-equity">Equity</a>
                <a href="/scenarios" class="nav-link" data-target="section-scenarios">Scenarios</a>
                <a href="/holdings" class="nav-link" data-target="section-holdings">Holdings</a>
                <a href="/arbitrage" class="nav-link" data-target="section-arbitrage">Arbitrage</a>
                <a href="/compensation" class="nav-link" data-target="section-compensation">Compensation</a>
                <a href="/philanthropy" class="nav-link" data-target="section-philanthropy">Philanthropy</a>
                <a href="/gifting" class="nav-link" data-target="section-gifting">Gifting</a>
                <a href="/estate" class="nav-link" data-target="section-estate">Estate</a>
                <a href="/college" class="nav-link" data-target="section-college">College</a>
                <a href="/accounts" class="nav-link" data-target="section-accounts">Accounts</a>
            </aside>
            <main class="main-content">
                <header class="top-header">
                    <h1 id="page-header-title">Overview & Net Worth</h1>
                </header>
                <div class="content-body">
                    ${readTpl('components/overview.html')}
                    ${readTpl('components/compensation.html')}
                    ${readTpl('components/arbitrage.html')}
                    ${readTpl('components/philanthropy.html')}
                    ${readTpl('components/gifting.html')}
                    ${readTpl('components/holdings_breakdown.html')}
                    ${readTpl('components/estate.html')}
                    ${readTpl('components/college.html')}
                    ${readTpl('components/accounts.html')}
                    ${readTpl('components/equity.html')}
                </div>
                ${readTpl('components/settings.html')}
                ${readTpl('components/ai_advisor_drawer.html')}
            </main>
        </div>
    </body>
    </html>
    `;

    const mockDashboardPayload = {
        success: true,
        snapshot: {
            true_net_worth: 5000000,
            last_monarch_sync: '2026-10-10T12:00:00Z',
            detailed_asset_allocation: {
                totals: {
                    us_equity: 1500000,
                    intl_equity: 500000,
                    bonds: 400000,
                    cash_liquid: 300000,
                    real_estate_reits: 800000,
                    private_investments: 500000
                },
                items: [
                    { key: 'us_equity', label: 'US Equities', value: 1500000, color: '#059669' },
                    { key: 'intl_equity', label: 'Intl Equities', value: 500000, color: '#0284C7' }
                ]
            },
            company_equity: {
                company_id: 1,
                company_name: 'Acme Corp',
                share_price: 120,
                current_409a_price: 120,
                true_net_post_tax_value: 1000000,
                nominal_gross_equity_value: 1500000,
                total_strike_cost_needed: 100000,
                total_tax_drag: 400000,
                include_wa_millionaire_tax: false,
                companies: [
                    { company_id: 1, company_name: 'Acme Corp', current_fmv: 120 }
                ],
                grants: [
                    { id: 1, company_id: 1, grant_type: 'ISO', vested_shares: 5000, total_shares: 10000, strike_price: 20 }
                ],
                fmv_history: [
                    { date: '2024-01', price: 80, percentage_increase: 15, is_projected: false },
                    { date: '2025-01', price: 100, percentage_increase: 25, is_projected: false },
                    { date: '2026-01', price: 120, percentage_increase: 20, is_projected: false },
                    { date: '2027-01', price: 132.6, is_projected: true }
                ]
            }
        },
        private_investments: {
            total_value: 500000
        },
        multi_year_projections: [
            { year: 2026, total_true_net_worth: 5000000, gross_equity: 1500000, true_net_equity: 1000000, non_equity_net_worth: 4000000, unvested_net_value: 300000, total_tax_drag: 400000 },
            { year: 2027, total_true_net_worth: 5500000, gross_equity: 1700000, true_net_equity: 1150000, non_equity_net_worth: 4350000, unvested_net_value: 200000, total_tax_drag: 450000 }
        ]
    };

    beforeEach(() => {
        requestedUrls = [];
        chartCallbacksExecuted = {
            instantiations: 0,
            tickCallbacks: 0,
            tooltipLabels: 0
        };

        const env = createTestDomEnvironment({
            html: fullPortalHtml,
            url: 'https://finances.highvelocitylabs.dev/',
            fetchHandlers: [
                {
                    matcher: (url) => {
                        requestedUrls.push(String(url));
                        return false;
                    },
                    handler: async () => ({ ok: true, json: async () => ({ success: true }) })
                },
                {
                    matcher: '/api/dashboard',
                    handler: async () => ({ ok: true, json: async () => mockDashboardPayload })
                },
                {
                    matcher: '/api/compensation',
                    handler: async () => ({
                        ok: true,
                        json: async () => ({
                            success: true,
                            history: [
                                { year: 2025, user_id: 1, company: 'Acme Corp', salary: 250000, bonus: 50000 },
                                { year: 2026, user_id: 1, company: 'Acme Corp', salary: 275000, bonus: 60000 }
                            ]
                        })
                    })
                },
                {
                    matcher: '/api/philanthropy',
                    handler: async () => ({
                        ok: true,
                        json: async () => ({
                            success: true,
                            total_lifetime_charity: 300000,
                            annual_budgets: { '2026': 150000 },
                            lifetime_history: [{ year: 2025, amount: 120000 }, { year: 2026, amount: 145000 }],
                            donations_by_year: {
                                '2026': {
                                    total: 100000,
                                    budget: 150000,
                                    donations: [
                                        { organization: 'Food Bank', amount: 60000 },
                                        { organization: 'Scholarship Fund', amount: 40000 }
                                    ]
                                }
                            }
                        })
                    })
                },
                {
                    matcher: (url) => String(url).includes('/fragments/'),
                    handler: async (url) => {
                        const u = new URL(url, 'https://finances.highvelocitylabs.dev');
                        const fragName = u.pathname.split('/fragments/')[1] || 'overview';
                        const secId = fragName === 'settings' ? 'settings-modal' : `section-${fragName}`;
                        return {
                            ok: true,
                            text: async () => `<section id="${secId}" class="page-section"></section>`
                        };
                    }
                }
            ]
        });

        window = env.window;
        document = env.document;

        // Stub canvas getContext('2d') for JSDOM
        window.HTMLCanvasElement.prototype.getContext = function () {
            return {
                canvas: this,
                clearRect: () => {},
                fillRect: () => {},
                beginPath: () => {},
                moveTo: () => {},
                lineTo: () => {},
                stroke: () => {},
                fill: () => {},
                arc: () => {},
                save: () => {},
                restore: () => {},
                createLinearGradient: () => ({ addColorStop: () => {} })
            };
        };

        // Active callback-invoking Chart stub: executes all scales.*.ticks.callback and plugins.tooltip.callbacks.label
        class StubChart {
            constructor(ctx, config) {
                this.ctx = ctx;
                this.config = config || {};
                this.data = (config && config.data) || { labels: [], datasets: [] };
                this.options = (config && config.options) || {};
                chartCallbacksExecuted.instantiations += 1;

                const scales = this.options.scales || {};
                for (const scaleKey of Object.keys(scales)) {
                    const scaleCfg = scales[scaleKey] || {};
                    if (scaleCfg.ticks && typeof scaleCfg.ticks.callback === 'function') {
                        const out = scaleCfg.ticks.callback(100000, 0, [{ value: 100000 }]);
                        assert.notStrictEqual(out, undefined, `Scale '${scaleKey}' ticks.callback returned undefined`);
                        chartCallbacksExecuted.tickCallbacks += 1;
                    }
                }

                const plugins = this.options.plugins || {};
                const tooltipCbs = (plugins.tooltip && plugins.tooltip.callbacks) || {};
                const sampleItem = {
                    raw: 100000,
                    dataset: (this.data.datasets && this.data.datasets[0]) || { label: 'Test', data: [100000] },
                    datasetIndex: 0,
                    dataIndex: 0,
                    parsed: { y: 100000, x: 100000 },
                    formattedValue: '100,000',
                    label: (this.data.labels && this.data.labels[0]) || '2026'
                };
                if (typeof tooltipCbs.label === 'function') {
                    tooltipCbs.label(sampleItem);
                    chartCallbacksExecuted.tooltipLabels += 1;
                }
                if (typeof tooltipCbs.title === 'function') {
                    tooltipCbs.title([sampleItem]);
                }
                if (typeof tooltipCbs.afterTitle === 'function') {
                    tooltipCbs.afterTitle([sampleItem]);
                }
                if (typeof tooltipCbs.afterBody === 'function') {
                    tooltipCbs.afterBody([sampleItem]);
                }
                if (typeof tooltipCbs.footer === 'function') {
                    tooltipCbs.footer([sampleItem]);
                }
                if (plugins.legend && plugins.legend.labels && typeof plugins.legend.labels.generateLabels === 'function') {
                    plugins.legend.labels.generateLabels(this);
                }
            }
            destroy() {}
            update() {}
            getDatasetMeta() {
                return { data: [{ hidden: false }, { hidden: false }, { hidden: false }, { hidden: false }, { hidden: false }, { hidden: false }] };
            }
        }

        window.Chart = StubChart;
        globalThis.Chart = StubChart;

        window.Idiomorph = {
            morph(target, newContent) {
                const el = typeof target === 'string' ? document.querySelector(target) : target;
                if (!el) return;
                if (typeof newContent === 'string') {
                    const temp = document.createElement('div');
                    temp.innerHTML = newContent.trim();
                    const nextEl = (el.id && temp.querySelector(`#${el.id}`)) || temp.firstElementChild;
                    if (nextEl) {
                        Array.from(nextEl.attributes).forEach(attr => el.setAttribute(attr.name, attr.value));
                        el.replaceChildren(...Array.from(nextEl.childNodes));
                    } else {
                        el.innerHTML = newContent;
                    }
                } else if (newContent && newContent.childNodes) {
                    if (newContent.attributes) {
                        Array.from(newContent.attributes).forEach(attr => el.setAttribute(attr.name, attr.value));
                    }
                    el.replaceChildren(...Array.from(newContent.childNodes));
                }
            }
        };
        window.htmx = {
            async ajax(method, url, context = {}) {
                const resp = await window.fetch(url, { method });
                if (resp && resp.ok && typeof resp.text === 'function') {
                    const html = await resp.text();
                    if (context.target) {
                        window.Idiomorph.morph(context.target, html);
                    }
                }
            }
        };

        const loadScriptFile = (relFile) => {
            const code = fs.readFileSync(path.join(__dirname, '../../static/js', relFile), 'utf8');
            const scriptEl = document.createElement('script');
            scriptEl.textContent = code;
            document.body.appendChild(scriptEl);
        };

        const sharedUtilsEl = document.createElement('script');
        sharedUtilsEl.textContent = fs.readFileSync(path.join(__dirname, '../../vendor/hvl_common/ui/static/utils.js'), 'utf8');
        document.body.appendChild(sharedUtilsEl);

        const sharedToastEl = document.createElement('script');
        sharedToastEl.textContent = fs.readFileSync(path.join(__dirname, '../../vendor/hvl_common/ui/static/toast.js'), 'utf8');
        document.body.appendChild(sharedToastEl);

        const sharedModalEl = document.createElement('script');
        sharedModalEl.textContent = fs.readFileSync(path.join(__dirname, '../../vendor/hvl_common/ui/static/modal-dialog.js'), 'utf8');
        document.body.appendChild(sharedModalEl);

        const sharedChatDrawerEl = document.createElement('script');
        sharedChatDrawerEl.textContent = fs.readFileSync(path.join(__dirname, '../../vendor/hvl_common/ui/static/chat-drawer.js'), 'utf8');
        document.body.appendChild(sharedChatDrawerEl);

        const sharedReactiveSignalsEl = document.createElement('script');
        sharedReactiveSignalsEl.textContent = fs.readFileSync(path.join(__dirname, '../../vendor/hvl_common/ui/static/reactive-signals.js'), 'utf8');
        document.body.appendChild(sharedReactiveSignalsEl);

        const scriptFiles = [
            'chart_theme.js',
            'app_sync.js',
            'app_navigation.js',
            'app_hydration.js',
            'app.js',
            'overview_charts.js',
            'overview_drag.js',
            'overview_helpers.js',
            'overview.js',
            'holdings.js',
            'equity_chart_helpers.js',
            'equity_chart.js',
            'equity_simulator.js',
            'equity_modals.js',
            'equity.js',
            'arbitrage.js',
            'philanthropy_modals.js',
            'philanthropy.js',
            'gifting.js',
            'estate.js',
            'college.js',
            'compensation_modals.js',
            'compensation.js',
            'accounts.js',
            'settings_accounts.js',
            'settings_members.js',
            'settings_integrations.js',
            'settings_security.js',
            'settings_desktop.js',
            'settings_admin.js',
            'settings.js',
            'ai_advisor_ui.js',
            'ai_advisor_threads.js',
            'ai_advisor_chat.js',
            'ai_advisor.js'
        ];
        const indexTplRaw = readTpl('index.html');
        const deferredSet = new Set();
        const deferRe = /<script\b[^>]*\bdefer\b[^>]*\bsrc="\/static\/js\/([^"?]+)\b/gi;
        let dMatch;
        while ((dMatch = deferRe.exec(indexTplRaw)) !== null) {
            deferredSet.add(dMatch[1]);
        }
        const immediateScripts = scriptFiles.filter(f => !deferredSet.has(f));
        const deferredScripts = scriptFiles.filter(f => deferredSet.has(f));
        immediateScripts.forEach(loadScriptFile);
        deferredScripts.forEach(loadScriptFile);
    });

    it('1. should load all client-side JS modules against all SSR component templates and invoke every Chart.js callback without ReferenceError', async () => {
        // Render Overview charts (Projection + Allocation Doughnut) and verify Widget Edit Mode toggle
        window.renderOverview(mockDashboardPayload);
        window.setWidgetEditMode('overview', true);
        window.setWidgetEditMode('overview', false);
        assert.ok(chartCallbacksExecuted.instantiations >= 2, 'Overview charts instantiated');

        // Render Holdings allocation chart
        window.renderHoldings(mockDashboardPayload);
        assert.ok(chartCallbacksExecuted.instantiations >= 3, 'Holdings chart instantiated');

        // Render Equity Simulator charts across all 3 graph modes (fmv, trajectory, curve)
        window.renderEquitySimulator(mockDashboardPayload);
        window.setGraphMode('trajectory');
        window.setGraphMode('curve');
        window.setGraphMode('fmv');
        assert.ok(chartCallbacksExecuted.instantiations >= 6, 'Equity charts across all 3 modes instantiated');

        // Render Compensation trends chart
        await window.loadCompensationData();
        assert.ok(chartCallbacksExecuted.instantiations >= 7, 'Compensation chart instantiated');

        // Render Philanthropy organization doughnut and multi-year trends charts
        await window.loadPhilanthropyData();
        assert.ok(chartCallbacksExecuted.instantiations >= 9, 'Philanthropy charts instantiated');

        assert.ok(chartCallbacksExecuted.tickCallbacks >= 5, 'Scale ticks.callback functions actively executed');
        assert.ok(chartCallbacksExecuted.tooltipLabels >= 7, 'Tooltip label callbacks actively executed');
    });

    it('2. should route interactive section state updates through GET /fragments/<name> morph controllers', async () => {
        requestedUrls.length = 0;

        await window.morphArbitrageSection({ home_state: 'CA', mode: 'tax_only', scenario: 'liquidity' });
        assert.ok(
            requestedUrls.some(u => u.includes('/fragments/arbitrage?') && u.includes('home_state=CA') && u.includes('mode=tax_only') && u.includes('scenario=liquidity')),
            'morphArbitrageSection requested parameterized /fragments/arbitrage'
        );

        await window.morphCompensationSection({ taxpayer: '1', subtab: 'comp-subtab-safeharbor' });
        assert.ok(
            requestedUrls.some(u => u.includes('/fragments/compensation?') && u.includes('taxpayer=1')),
            'morphCompensationSection requested parameterized /fragments/compensation'
        );

        await window.morphPhilanthropySection({ year: '2025', sort: 'amount', dir: 'desc' });
        assert.ok(
            requestedUrls.some(u => u.includes('/fragments/philanthropy?') && u.includes('year=2025') && u.includes('sort=amount')),
            'morphPhilanthropySection requested parameterized /fragments/philanthropy'
        );

        await window.morphGiftingSection('2025');
        assert.ok(
            requestedUrls.some(u => u.includes('/fragments/gifting?year=2025')),
            'morphGiftingSection requested parameterized /fragments/gifting'
        );

        await window.morphHoldingsSection({ preset: 'three_fund', horizon: '20', drift: '0.03' });
        assert.ok(
            requestedUrls.some(u => u.includes('/fragments/holdings?') && u.includes('preset=three_fund')),
            'morphHoldingsSection requested parameterized /fragments/holdings'
        );

        await window.morphEstateSection({ state: 'OR', apply_tcja_sunset: true, charitable_pct: 0.1 });
        assert.ok(
            requestedUrls.some(u => u.includes('/fragments/estate?') && u.includes('state=OR') && u.includes('apply_tcja_sunset=true')),
            'morphEstateSection requested parameterized /fragments/estate'
        );

        await window.morphCollegeSection({ horizon: 'projected', enable_529_k12: false });
        assert.ok(
            requestedUrls.some(u => u.includes('/fragments/college?') && u.includes('horizon=projected') && u.includes('enable_529_k12=false')),
            'morphCollegeSection requested parameterized /fragments/college'
        );

        await window.morphSettingsModal({ tab: 'roles' });
        assert.ok(
            requestedUrls.some(u => u.includes('/fragments/settings?') && u.includes('tab=roles')),
            'morphSettingsModal requested parameterized /fragments/settings'
        );
    });

    it('3. should execute Scenarios Chart.js lenses (networth, cashflow, longevity, montecarlo) and morphScenariosSection without ReferenceError', async () => {
        const { pathToFileURL } = require('node:url');
        globalThis.window = window;
        globalThis.document = document;
        globalThis.localStorage = window.localStorage;
        globalThis.fetch = window.fetch;
        globalThis.CustomEvent = window.CustomEvent;
        globalThis.Event = window.Event;
        globalThis.Image = window.Image;

        // Mount scenarios canvas lenses container into DOM
        const scenSec = document.createElement('section');
        scenSec.id = 'section-scenarios';
        scenSec.className = 'portal-card page-section';
        scenSec.innerHTML = `
            <canvas id="chart-scenarios-comparison"></canvas>
            <div id="chart-curve-toggles"></div>
            <p id="chart-lens-caption"></p>
            <div id="container-monte-carlo-details"></div>
            <div id="scenarios-chart-loading"></div>
            <script id="ssr-scenarios-data" type="application/json"></script>
        `;
        document.querySelector('.content-body').appendChild(scenSec);

        const mockScenData = {
            active_scenario_id: 'scen_baseline',
            selected_scenario_id: 'scen_baseline',
            scenarios: [
                { id: 'scen_baseline', name: 'Baseline Plan', color: '#10b981', is_active: true, event_ids: [] },
                { id: 'scen_retired_now', name: 'Retire Today', color: '#3b82f6', is_active: false, event_ids: [] }
            ],
            comparison_curves: [
                { year: 2026, age: 45, age_primary: 45, scen_baseline: 5000000, scen_retired_now: 4800000 },
                { year: 2027, age: 46, age_primary: 46, scen_baseline: 5400000, scen_retired_now: 5000000 }
            ],
            active_schedule: [
                { year: 2026, age_primary: 45, age_spouse: 45, total_net_worth: 5000000, liquid_portfolio: 2500000, retirement_accounts: 1500000, real_estate_equity: 800000, children_529: 200000, yearly_inflow: 500000, yearly_outflow: 300000, joint_survival_prob: 0.99 },
                { year: 2027, age_primary: 46, age_spouse: 46, total_net_worth: 5400000, liquid_portfolio: 2700000, retirement_accounts: 1650000, real_estate_equity: 830000, children_529: 220000, yearly_inflow: 520000, yearly_outflow: 310000, joint_survival_prob: 0.98 }
            ],
            active_cash_flow_series: [
                { year: 2026, age_primary: 45, salary_income: 350000, equity_vesting: 150000, living_expenses: 200000, taxes: 100000, total_inflow: 500000, total_outflow: 300000, net_cash_flow: 200000 },
                { year: 2027, age_primary: 46, salary_income: 360000, equity_vesting: 160000, living_expenses: 205000, taxes: 105000, total_inflow: 520000, total_outflow: 310000, net_cash_flow: 210000 }
            ],
            active_monte_carlo: {
                scenario_id: 'scen_baseline',
                success_rate: 0.96,
                iterations: 500,
                percentiles_timeline: [
                    { year: 2026, age: 45, p10: 4600000, p25: 4800000, p50: 5000000, p75: 5200000, p90: 5400000 },
                    { year: 2027, age: 46, p10: 4800000, p25: 5100000, p50: 5400000, p75: 5700000, p90: 6000000 }
                ]
            },
            scenario_schedules: {},
            scenario_cash_flows: {},
            scenario_monte_carlo: {}
        };
        document.getElementById('ssr-scenarios-data').textContent = JSON.stringify(mockScenData);

        const stateMod = await import(pathToFileURL(path.join(__dirname, '../../static/js/scenarios/state.js')).href);
        const chartsMod = await import(pathToFileURL(path.join(__dirname, '../../static/js/scenarios/charts/index.js')).href);
        const cfMod = await import(pathToFileURL(path.join(__dirname, '../../static/js/scenarios/charts/cash_flow.js')).href);
        const mainMod = await import(pathToFileURL(path.join(__dirname, '../../static/js/scenarios/main.js')).href);

        stateMod.state.scenariosData = mockScenData;
        stateMod.state.selectedScenarioId = 'scen_baseline';

        assert.strictEqual(cfMod.getCfSubMode(), 'sankey', 'Cash Flow widget defaults to Single-Year Sankey');
        chartsMod.switchToLens('cashflow');
        cfMod.setCfSubMode('timeline');

        const beforeInst = chartCallbacksExecuted.instantiations;
        for (const lens of ['networth', 'cashflow', 'longevity', 'montecarlo']) {
            chartsMod.switchToLens(lens);
        }
        assert.ok(chartCallbacksExecuted.instantiations >= beforeInst + 4, 'All 4 Scenarios Chart.js lenses instantiated and callbacks executed');
        cfMod.setCfSubMode('sankey');

        requestedUrls.length = 0;
        await mainMod.morphScenariosSection({ scenario_id: 'scen_retired_now', view_mode: 'real' });
        assert.ok(
            requestedUrls.some(u => u.includes('/fragments/scenarios?') && u.includes('scenario_id=scen_retired_now') && u.includes('view_mode=real')),
            'morphScenariosSection requested parameterized /fragments/scenarios'
        );

        // Mount Event Wizard modal template and verify Icon Picker + new event templates
        const wizardWrap = document.createElement('div');
        wizardWrap.innerHTML = readTpl('components/scenarios/modals/event_wizard.html');
        document.body.appendChild(wizardWrap);

        const eventModals = await import(pathToFileURL(path.join(__dirname, '../../static/js/scenarios/event_modals.js')).href);
        eventModals.initEventWizardControls();
        eventModals.renderEventIconPickerGrid();

        const iconButtons = document.querySelectorAll('#grid-event-icon-picker .btn-icon-picker-choice');
        assert.ok(iconButtons.length >= 42, `Expected at least 42 curated icons in picker grid, found ${iconButtons.length}`);

        // Verify live search filter in the Icon Picker drawer (#input-search-event-icon)
        const iconSearch = document.getElementById('input-search-event-icon');
        assert.ok(iconSearch, 'Icon picker search input exists');
        iconSearch.value = 'roth';
        iconSearch.dispatchEvent(new window.Event('input', { bubbles: true }));
        const filteredIcons = document.querySelectorAll('#grid-event-icon-picker .btn-icon-picker-choice');
        assert.strictEqual(filteredIcons.length, 1, 'Icon search for "roth" narrows grid to 1 matching icon');
        assert.strictEqual(filteredIcons[0].dataset.iconId, 'evt-roth-ladder');
        iconSearch.value = '';
        iconSearch.dispatchEvent(new window.Event('input', { bubbles: true }));

        // Verify live search filter in the Wizard Event Type selector (#input-search-wizard-template)
        const tmplSearch = document.getElementById('input-search-wizard-template');
        assert.ok(tmplSearch, 'Wizard template search input exists');
        tmplSearch.value = 'relocate';
        tmplSearch.dispatchEvent(new window.Event('input', { bubbles: true }));
        const selTmpl = document.getElementById('select-event-template');
        assert.strictEqual(selTmpl.value, 'state_relocation', 'Wizard search for "relocate" auto-selects state_relocation');
        assert.strictEqual(document.getElementById('fields-state-relocation').style.display, 'block');
        tmplSearch.value = '';
        tmplSearch.dispatchEvent(new window.Event('input', { bubbles: true }));

        // Verify automatic icon & panel updates across all new templates
        for (const tmpl of [
            'state_relocation', 'roth_conversion', 'superfund_529', 'pe_capital_call',
            'ltc_insurance', 'marital_settlement', 'home_renovation', 'sabbatical',
            'grad_school', 'philanthropy_daf', 'real_estate', 'capital_outflow', 'capital_inflow'
        ]) {
            selTmpl.value = tmpl;
            selTmpl.dispatchEvent(new window.Event('change', { bubbles: true }));
        }
        assert.strictEqual(document.getElementById('input-event-icon').value, 'evt-trophy');

        // Verify manual icon selection in the Icon Picker
        eventModals.setSelectedEventIcon('evt-wedding', true);
        assert.strictEqual(document.getElementById('input-event-icon').value, 'evt-wedding');
        assert.strictEqual(document.getElementById('input-event-icon').dataset.manualOverride, 'true');
        assert.ok(stateMod.resolveEventIcon({ category: 'capital_outflow', icon: 'evt-wedding' }, 14).includes('<polygon points="12 3'), 'resolveEventIcon returns wedding ring SVG');
    });

    it('4. should expose showAlertModal/showConfirmModal aliases and display error modal dialogs when 400 resource limits are hit', async () => {
        assert.strictEqual(typeof window.showModalAlert, 'function', 'window.showModalAlert is defined');
        assert.strictEqual(window.showAlertModal, window.showModalAlert, 'window.showAlertModal aliases showModalAlert');
        assert.strictEqual(window.showConfirmModal, window.showModalConfirm, 'window.showConfirmModal aliases showModalConfirm');

        const alertsShown = [];
        const origAlert = window.showModalAlert;
        const trackedAlert = (msg, opts) => {
            alertsShown.push({ msg: String(msg), opts: opts || {} });
            return Promise.resolve();
        };
        window.showModalAlert = trackedAlert;
        window.showAlertModal = trackedAlert;
        window.alert = trackedAlert;

        const origFetch = window.fetch;
        window.fetch = async (url) => ({
            ok: false,
            status: 400,
            json: async () => ({
                success: false,
                error: `Maximum limit reached for ${url}`
            })
        });

        try {
            // 1. Gifting add recipient form submit
            if (typeof window.initGiftingControls === 'function') {
                window.initGiftingControls();
            }
            const recNameInput = document.getElementById('input-new-recipient-name');
            const recForm = document.getElementById('form-add-recipient');
            if (recNameInput && recForm) {
                recNameInput.value = 'Overflow Family';
                recForm.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
                await new Promise(r => setTimeout(r, 20));
                assert.ok(alertsShown.some(a => a.msg.includes('/api/gifting/recipient')), 'Gifting recipient limit error surfaced in modal dialog');
            }

            // 2. Philanthropy add grant form submit
            const orgInput = document.getElementById('add-grant-org');
            const amtInput = document.getElementById('add-grant-amount');
            const grantForm = document.getElementById('form-add-grant');
            if (orgInput && amtInput && grantForm) {
                orgInput.value = 'Overflow Charity';
                amtInput.value = '1000';
                grantForm.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
                await new Promise(r => setTimeout(r, 20));
                assert.ok(alertsShown.some(a => a.msg.includes('/api/philanthropy/grant')), 'Philanthropy grant limit error surfaced in modal dialog');
            }

            // 3. Manual Account creation
            const accName = document.getElementById('manual-acc-name');
            const accBal = document.getElementById('manual-acc-balance');
            if (accName && accBal && typeof window.saveManualAccount === 'function') {
                accName.value = 'Overflow Account';
                accBal.value = '50000';
                await window.saveManualAccount();
                assert.ok(alertsShown.some(a => a.msg.includes('/api/accounts/manual')), 'Manual account limit error surfaced in modal dialog');
            }

            // 4. AI Advisor message limit
            const advInput = document.getElementById('ai-advisor-input');
            if (advInput && typeof window.submitAiAdvisorMessage === 'function') {
                advInput.value = 'Test limit';
                await window.submitAiAdvisorMessage();
                assert.ok(alertsShown.some(a => a.msg.includes('/api/ai-advisor/chat')), 'AI Advisor limit error surfaced in modal dialog');
            }
        } finally {
            window.fetch = origFetch;
            window.showModalAlert = origAlert;
            window.showAlertModal = origAlert;
            window.alert = origAlert;
        }
    });

    it('5. should support Overview quarterly/monthly projection granularity & Edit/Delete icon buttons', () => {
        const granControls = document.getElementById('hist-granularity-controls');
        assert.ok(granControls, '#hist-granularity-controls should exist on Overview');
        assert.notStrictEqual(granControls.style.display, 'none', '#hist-granularity-controls should be visible by default');

        assert.strictEqual(typeof window.buildProjectionSeriesForGranularity, 'function', 'buildProjectionSeriesForGranularity should be exposed');
        const sampleProj = [
            { year: 2026, total_true_net_worth: 1000000, true_net_equity: 400000, non_equity_net_worth: 600000, unvested_net_value: 200000 },
            { year: 2027, total_true_net_worth: 1400000, true_net_equity: 600000, non_equity_net_worth: 800000, unvested_net_value: 100000 }
        ];
        const qSeries = window.buildProjectionSeriesForGranularity(sampleProj, 'quarterly');
        assert.strictEqual(qSeries.length, 5, '1-year span should produce 5 quarterly points (2026 Q1..Q4 + 2027 Q1)');
        assert.strictEqual(qSeries[0].label, '2026 Q1');
        assert.strictEqual(qSeries[2].label, '2026 Q3');
        assert.strictEqual(qSeries[2].total_true_net_worth, 1200000);

        const mSeries = window.buildProjectionSeriesForGranularity(sampleProj, 'monthly');
        assert.strictEqual(mSeries.length, 13, '1-year span should produce 13 monthly points');
        assert.strictEqual(mSeries[0].label, '2026-01');
        assert.strictEqual(mSeries[12].label, '2027-01');
    });

    it('6. should dismiss loading overlays when loading overview and forecasting with empty/zero data', () => {
        // 1. Overview loaders dismissal with empty profile
        const pLoader = document.getElementById('overview-chart-loading');
        const aLoader = document.getElementById('overview-alloc-loading');
        assert.ok(pLoader, '#overview-chart-loading should exist');
        assert.ok(aLoader, '#overview-alloc-loading should exist');

        pLoader.classList.remove('hidden');
        pLoader.style.display = 'flex';
        aLoader.classList.remove('hidden');
        aLoader.style.display = 'flex';

        // Call renderOverview with empty snapshot & projections (brand new/blank tenant state)
        if (typeof window.renderOverview === 'function') {
            window.renderOverview({
                snapshot: {
                    detailed_asset_allocation: { items: [], totals: {} },
                    categories: {},
                    company_equity: null
                },
                multi_year_projections: []
            });
            assert.strictEqual(pLoader.style.display, 'none', '#overview-chart-loading should be hidden');
            assert.ok(pLoader.classList.contains('hidden'), '#overview-chart-loading should have hidden class');
            assert.strictEqual(aLoader.style.display, 'none', '#overview-alloc-loading should be hidden');
            assert.ok(aLoader.classList.contains('hidden'), '#overview-alloc-loading should have hidden class');
        }

        // 2. Scenarios loader dismissal with empty/null data
        const sLoader = document.getElementById('scenarios-chart-loading');
        if (sLoader) {
            sLoader.classList.remove('hidden');
            sLoader.style.display = 'flex';

            if (typeof window.renderActiveLensChart === 'function') {
                window.renderActiveLensChart();
                assert.strictEqual(sLoader.style.display, 'none', '#scenarios-chart-loading should be dismissed');
                assert.ok(sLoader.classList.contains('hidden'), '#scenarios-chart-loading should have hidden class');
            }
        }
    });
});


