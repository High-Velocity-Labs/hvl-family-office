/**
 * HVL Family Office - Shared Idiomorph defaults for every HTMX `morph` swap.
 * Nothing in the app binds listeners to individual nodes (all handlers are delegated from `document`), so morphs
 * need no per-node bookkeeping. The one default kept is that a canvas keeps its drawn bitmap.
 */
function installMorphDefaults(idiomorph) {
    if (idiomorph.defaults.hvlInstalled) return false;
    idiomorph.defaults.callbacks.beforeNodeMorphed = (oldNode) => oldNode.tagName !== 'CANVAS';
    idiomorph.defaults.hvlInstalled = true;
    return true;
}

window.installMorphDefaults = installMorphDefaults;
installMorphDefaults(window.Idiomorph);
