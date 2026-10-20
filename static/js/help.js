(function() {
    const btnTheme = document.getElementById('btn-theme-toggle-help');
    const sunIcon = document.getElementById('theme-icon-sun');
    const moonIcon = document.getElementById('theme-icon-moon');

    function syncIcons() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        if (sunIcon) sunIcon.style.display = isDark ? 'block' : 'none';
        if (moonIcon) moonIcon.style.display = isDark ? 'none' : 'block';
    }
    syncIcons();

    if (btnTheme) {
        btnTheme.addEventListener('click', function() {
            const current = document.documentElement.getAttribute('data-theme');
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            try { localStorage.setItem('fo_theme', next); } catch (e) {}
            syncIcons();
        });
    }

    const searchInput = document.getElementById('help-search-input');
    const searchStatus = document.getElementById('help-search-status');
    const chapters = Array.from(document.querySelectorAll('.help-chapter'));

    if (searchInput) {
        searchInput.addEventListener('input', function() {
            const q = (searchInput.value || '').trim().toLowerCase();
            if (!q) {
                chapters.forEach(ch => {
                    ch.style.display = '';
                    ch.querySelectorAll('.help-article-card').forEach(c => { c.style.display = ''; });
                });
                if (searchStatus) searchStatus.textContent = 'Type a keyword to filter chapters below.';
                return;
            }
            let visibleChapters = 0;
            chapters.forEach(ch => {
                const cards = Array.from(ch.querySelectorAll('.help-article-card'));
                const chapterText = (ch.textContent || '').toLowerCase();
                let cardMatched = false;
                cards.forEach(c => {
                    const match = (c.textContent || '').toLowerCase().includes(q);
                    c.style.display = match ? '' : 'none';
                    if (match) cardMatched = true;
                });
                const showChapter = cardMatched || chapterText.includes(q);
                if (showChapter && !cardMatched) {
                    cards.forEach(c => { c.style.display = ''; });
                }
                ch.style.display = showChapter ? '' : 'none';
                if (showChapter) visibleChapters += 1;
            });
            if (searchStatus) {
                searchStatus.textContent = visibleChapters > 0
                    ? 'Showing ' + visibleChapters + ' matching section' + (visibleChapters === 1 ? '' : 's') + '.'
                    : 'No matching help articles found.';
            }
        });
    }
})();
