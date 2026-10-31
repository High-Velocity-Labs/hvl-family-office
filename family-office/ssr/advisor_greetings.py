"""
Advisor welcome-message greetings per page section. The text is trusted, author-written markup (rendered with |safe).
"""

from __future__ import annotations

ADVISOR_TAB_GREETINGS: dict[str, dict[str, str]] = {
    'section-overview': {
        'text': (
            "I see you're currently on the <strong>Overview &amp; Net Worth</strong> dashboard. I have "
            'your household balance sheet, equity grants (NSOs &amp; RSUs), and Investment Policy '
            'Statement (IPS) loaded and ready.'
        ),
        'prompt': (
            'How can I help you optimize your portfolio, review '
            'equity options, or plan your wealth trajectory today?'
        ),
    },
    'section-equity': {
        'text': (
            "I see you're currently analyzing <strong>Company Equity &amp; RSUs</strong>. I am tracking"
            ' your vested/unvested grants, current 409A valuation, strike exercise capital '
            'requirements, and tax withholding considerations.'
        ),
        'prompt': 'How can I help you model cashless exercises, AMT exposure, or RSU tax planning today?',
    },
    'section-scenarios': {
        'text': (
            "I see you're currently in <strong>Forecasting &amp; Longevity</strong>. I have your Monte "
            'Carlo engine, spending rate assumptions, and retirement milestones ready to test.'
        ),
        'prompt': (
            'How can I help you stress-test your plan, evaluate sequence of returns risk, or test '
            'market crisis replays today?'
        ),
    },
    'section-holdings': {
        'text': (
            "I see you're currently examining <strong>Investments &amp; Asset Allocation</strong>. I am"
            ' monitoring your portfolio against your Investment Policy Statement (IPS) anchor preset '
            'and rebalancing drift tolerance.'
        ),
        'prompt': 'How can I help you review asset drift, index tracking, or plan tax-free rebalancing today?',
    },
    'section-arbitrage': {
        'text': (
            "I see you're currently evaluating <strong>Multi-State Tax Arbitrage</strong>. Using your "
            'home state as the baseline, I can help calculate net savings and domicile transition '
            'requirements.'
        ),
        'prompt': 'How can I help you analyze tax savings across states today?',
    },
    'section-withholding': {
        'text': (
            "I see you're currently reviewing <strong>Taxes &amp; Safe Harbor Withholding</strong>. I "
            'can help evaluate quarterly estimated tax obligations and safe harbor compliance.'
        ),
        'prompt': 'How can I help you plan your quarterly tax payments today?',
    },
    'section-philanthropy': {
        'text': (
            "I see you're currently modeling <strong>Philanthropic Gifting &amp; DAFs</strong>. I can "
            'assist with charitable deductions, bunching strategies, and appreciated asset donations.'
        ),
        'prompt': 'How can I help you optimize your charitable impact today?',
    },
    'section-gifting': {
        'text': (
            "I see you're currently viewing <strong>Family Gifting &amp; Annual Exclusion</strong>. I "
            'can help track your annual exclusion gifts per recipient and lifetime exemption shields.'
        ),
        'prompt': 'How can I help you plan intergenerational wealth transfers today?',
    },
    'section-college': {
        'text': (
            "I see you're currently planning <strong>Education Funding &amp; 529s</strong>. I can help "
            'project 4-year tuition trajectories and tax-free growth.'
        ),
        'prompt': 'How can I help you optimize your education savings today?',
    },
    'section-transcripts': {
        'text': (
            "I see you're currently analyzing <strong>IRS Transcripts &amp; Audit Logs</strong>. I can "
            'help verify W-2s, withholding records, and tax year reconciliations.'
        ),
        'prompt': 'How can I help you review your IRS records today?',
    },
    'section-compensation': {
        'text': (
            "I see you're currently reviewing <strong>Career Compensation</strong>. Using your base "
            'salary, bonus targets, and career history, I can help you model future earnings and total '
            'compensation.'
        ),
        'prompt': 'How can I help you analyze career compensation today?',
    },
    'section-accounts': {
        'text': (
            "I see you're currently viewing <strong>Accounts &amp; Assets</strong>. Using your synced "
            'account balances, institutions, and asset classifications, I can help you review liquidity'
            ' and distribution.'
        ),
        'prompt': 'How can I help you review your accounts and assets today?',
    },
    'section-estate': {
        'text': (
            "I see you're currently reviewing <strong>Estate Planning &amp; Wealth Transfer</strong>. I"
            ' can help model federal and state estate tax liabilities, a federal-exemption rollback '
            'stress test, and trust shielding.'
        ),
        'prompt': 'How can I help you optimize your estate structure today?',
    },
}
