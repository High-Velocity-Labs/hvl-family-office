'use strict';
// Client domain-version contract: versions come only from the server header; no client-invented bumps;
// a server-driven morph never overwrites a section with unsaved local edits (the unsaved what-if bug).
const { describe, it } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const HVL_COMMON = require('./hvl_common_root.js');

function load() {
    const dom = new JSDOM('<!doctype html><body></body>', { runScripts: 'outside-only', url: 'http://localhost/' });
    const { window } = dom;
    window.eval('window.SECTION_TO_PATH = {};');
    window.document.body.innerHTML = `
        <section id="section-scenarios" class="page-section" data-fragment="scenarios" data-depends="scenarios,accounts" data-loaded="true">
            <button id="btn-save-to-plan" disabled>Save</button>
        </section>
        <section id="section-gifting" class="page-section" data-fragment="gifting" data-depends="gifting" data-loaded="true" style="display:none"></section>`;
    window.currentSectionId = 'section-scenarios';
    window.currentViewMode = 'focused';
    const morphs = [];
    window.htmx = { ajax: async (_m, url) => { morphs.push(url); } };
    for (const rel of [path.join(HVL_COMMON, 'ui/static/reactive-signals.js'), '../../static/js/app_sync.js', '../../static/js/app_hydration.js']) {
        window.eval(fs.readFileSync(path.resolve(__dirname, rel), 'utf8'));
    }
    return { window, morphs };
}

describe('client domain versions', () => {
    it('has no client-side version invention', () => {
        const { window } = load();
        assert.strictEqual(window.bumpDomains, undefined);
        assert.strictEqual(window.inferDomainsFromMutationUrl, undefined);
    });

    it('reads section dependencies only from data-depends', () => {
        const { window } = load();
        assert.deepStrictEqual([...window.getSectionDomains('section-scenarios')], ['scenarios', 'accounts']);
        assert.strictEqual(window.getSectionDomains('section-unknown').length, 0);
    });

    it('defers a morph over unsaved edits and flushes it once they are saved', async () => {
        const { window, morphs } = load();
        const btn = window.document.getElementById('btn-save-to-plan');
        btn.disabled = false; // unsaved what-if
        await window.applyDomainVersions({ scenarios: 2 });
        assert.strictEqual(morphs.length, 0, 'unsaved section must not be morphed');
        btn.disabled = true; // saved
        await window.flushDeferredSectionMorphs();
        assert.strictEqual(morphs.length, 1);
        assert.ok(morphs[0].includes('/fragments/scenarios'));
    });

    it('morphs immediately when nothing is unsaved', async () => {
        const { window, morphs } = load();
        await window.applyDomainVersions({ scenarios: 2 });
        assert.strictEqual(morphs.length, 1);
    });
});
