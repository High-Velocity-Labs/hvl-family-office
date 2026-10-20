(function() {
    var themeBtn = document.getElementById('btn-theme-toggle-features');
    var sunIcon = document.getElementById('theme-icon-sun');
    var moonIcon = document.getElementById('theme-icon-moon');

    function updateThemeIcons(theme) {
        if (theme === 'dark') {
            if (sunIcon) sunIcon.style.display = 'block';
            if (moonIcon) moonIcon.style.display = 'none';
        } else {
            if (sunIcon) sunIcon.style.display = 'none';
            if (moonIcon) moonIcon.style.display = 'block';
        }
    }

    var currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    updateThemeIcons(currentTheme);

    if (themeBtn) {
        themeBtn.addEventListener('click', function() {
            var activeTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', activeTheme);
            localStorage.setItem('fo_theme', activeTheme);
            updateThemeIcons(activeTheme);
        });
    }

    var planData = {
        'baseline': {
            nw: '$14,280,000',
            nwSub: 'Baseline trajectory at 7.0% nominal return',
            retire: 'Age 55.0',
            retireColor: 'var(--status-green)',
            retireSub: '100% Monte Carlo success probability',
            edu529: '$385,000',
            edu529Sub: 'Segregated custodial wealth for 2 children',
            outflow: '$0 / yr',
            outflowSub: 'Living expenses funded from ordinary cash flow',
            badge: 'Baseline Plan',
            badgeClass: 'badge-blue',
            title: 'Baseline Current Trajectory',
            desc: 'Your core scenario. Every what-if plan starts from this foundation—automatically using your accounts, salary, and savings rates while letting you test individual decisions.',
            note: 'Click the tabs above to see how each what-if scenario changes your retirement timeline without altering your baseline.'
        },
        'harvard': {
            nw: '$13,420,000',
            nwSub: '-$860k lifetime impact after 4-yr private tuition',
            retire: 'Age 56.5',
            retireColor: 'var(--accent-orange)',
            retireSub: '+1.5 yr career extension to preserve retirement safety',
            edu529: '$0',
            edu529Sub: '100% of 529 funds depleted; $177k drawn from brokerage',
            outflow: '-$98,000 / yr',
            outflowSub: '4-year college tuition spike (2029–2033)',
            badge: 'What-If Plan A',
            badgeClass: 'badge-orange',
            title: 'What-If: Private College ($98k/yr)',
            desc: 'Starts from your baseline to model private college tuition. The engine automatically exhausts the child\'s 529 reserves first, then calculates portfolio liquid shortfalls and pushes retirement by 1.5 years.',
            note: 'Shows the exact retirement impact of private college tuition.'
        },
        'instate': {
            nw: '$13,950,000',
            nwSub: '-$330k lifetime impact; 529 covers 100% of costs',
            retire: 'Age 55.2',
            retireColor: 'var(--status-green)',
            retireSub: '+0.2 yr delay (near-zero retirement impact)',
            edu529: '$145,000',
            edu529Sub: '$140k drawn; $245k leftover for grad school or Roth rollover',
            outflow: '$0 / yr',
            outflowSub: '100% covered by 529; zero parent cash flow drag',
            badge: 'What-If Plan B',
            badgeClass: 'badge-green',
            title: 'What-If: In-State Public ($35k/yr)',
            desc: 'Tests attending an in-state public university. Because tuition is fully covered by existing 529 custodial reserves, personal brokerage accounts remain untouched and retirement age is completely preserved.',
            note: 'Leftover 529 funds can be rolled tax-free into child Roth IRAs under SECURE 2.0.'
        },
        'realestate': {
            nw: '$12,100,000',
            nwSub: '-$2.18M liquid net worth ($1.8M converted to illiquid property)',
            retire: 'Age 58.0',
            retireColor: 'var(--status-red)',
            retireSub: '+3.0 yr career extension to service debt & carrying drag',
            edu529: '$385,000',
            edu529Sub: 'Education reserves completely untouched',
            outflow: '-$82,000 / yr',
            outflowSub: '20% down payment + mortgage + taxes & maintenance',
            badge: 'What-If Plan C',
            badgeClass: 'badge-blue',
            title: 'What-If: Vacation Home ($1.8M)',
            desc: 'Models purchasing a second home in 2028 with 20% down and a 30-year fixed loan. Accounts for mortgage debt service, real estate tax drag, and maintenance costs without touching college funds.',
            note: 'Shows how major lifestyle purchases alter liquid compounding over 30 years.'
        }
    };

    var tabButtons = document.querySelectorAll('.hero-sim-tab-btn');
    tabButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            tabButtons.forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            var planKey = btn.getAttribute('data-plan');
            var d = planData[planKey];
            if (!d) return;

            document.getElementById('sim-metric-nw').textContent = d.nw;
            document.getElementById('sim-metric-nw-sub').textContent = d.nwSub;

            var retEl = document.getElementById('sim-metric-retire');
            retEl.textContent = d.retire;
            retEl.style.color = d.retireColor;
            document.getElementById('sim-metric-retire-sub').textContent = d.retireSub;

            document.getElementById('sim-metric-529').textContent = d.edu529;
            document.getElementById('sim-metric-529-sub').textContent = d.edu529Sub;

            document.getElementById('sim-metric-outflow').textContent = d.outflow;
            document.getElementById('sim-metric-outflow-sub').textContent = d.outflowSub;

            var badgeEl = document.getElementById('sim-diff-badge');
            badgeEl.textContent = d.badge;
            badgeEl.className = 'badge ' + d.badgeClass;

            document.getElementById('sim-diff-title').textContent = d.title;
            document.getElementById('sim-diff-desc').textContent = d.desc;
            document.getElementById('sim-diff-note').textContent = d.note;
        });
    });

    var mobileMenuBtn = document.getElementById('btn-features-mobile-menu');
    var mobileDrawer = document.getElementById('features-mobile-drawer');
    var mobileDrawerBackdrop = document.getElementById('mobile-drawer-backdrop');
    var mobileDrawerClose = document.getElementById('btn-mobile-drawer-close');
    var mobileMenuLinks = document.querySelectorAll('.mobile-menu-link');

    function openMobileDrawer() {
        if (!mobileDrawer) return;
        mobileDrawer.classList.add('open');
        mobileDrawer.setAttribute('aria-hidden', 'false');
        if (mobileMenuBtn) {
            mobileMenuBtn.setAttribute('aria-expanded', 'true');
            var iconOpen = mobileMenuBtn.querySelector('.icon-menu-open');
            var iconClose = mobileMenuBtn.querySelector('.icon-menu-close');
            if (iconOpen) iconOpen.style.display = 'none';
            if (iconClose) iconClose.style.display = 'block';
        }
        document.body.style.overflow = 'hidden';
    }

    function closeMobileDrawer() {
        if (!mobileDrawer) return;
        mobileDrawer.classList.remove('open');
        mobileDrawer.setAttribute('aria-hidden', 'true');
        if (mobileMenuBtn) {
            mobileMenuBtn.setAttribute('aria-expanded', 'false');
            var iconOpen = mobileMenuBtn.querySelector('.icon-menu-open');
            var iconClose = mobileMenuBtn.querySelector('.icon-menu-close');
            if (iconOpen) iconOpen.style.display = 'block';
            if (iconClose) iconClose.style.display = 'none';
        }
        document.body.style.overflow = '';
    }

    if (mobileMenuBtn) {
        mobileMenuBtn.addEventListener('click', function() {
            if (mobileDrawer && mobileDrawer.classList.contains('open')) {
                closeMobileDrawer();
            } else {
                openMobileDrawer();
            }
        });
    }

    if (mobileDrawerClose) {
        mobileDrawerClose.addEventListener('click', closeMobileDrawer);
    }

    if (mobileDrawerBackdrop) {
        mobileDrawerBackdrop.addEventListener('click', closeMobileDrawer);
    }

    mobileMenuLinks.forEach(function(link) {
        link.addEventListener('click', function() {
            closeMobileDrawer();
        });
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && mobileDrawer && mobileDrawer.classList.contains('open')) {
            closeMobileDrawer();
        }
    });
})();
