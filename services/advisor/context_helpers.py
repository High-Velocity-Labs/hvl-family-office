"""
Off-topic guardrails, domain keyword classifiers, and context-aware prompt suggestion
builders for the AI Financial Advisor.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_FINANCE_DOMAIN_KEYWORDS = (
    "tax", "taxes", "irs", "1040", "w-2", "w2", "withholding", "safe harbor", "amt", "capital gain", "ltcg", "stcg", "niit", "irmaa", "rmd",
    "roth", "ira", "401k", "401\\(k\\)", "403b", "403\\(b\\)", "hsa", "529", "530a", "college", "tuition", "education", "scholarship",
    "equity", "rsu", "rsus", "nso", "nsos", "iso", "isos", "option", "options", "strike", "vest", "vesting", "409a", "83\\(b\\)", "83b", "qsbs",
    "grant", "grants", "shares", "stock", "stocks", "buyback", "tender", "ipo", "portfolio", "allocation", "rebalance", "rebalancing",
    "holdings", "holding", "boglehead", "index", "bond", "bonds", "treasury", "treasuries", "etf", "mutual fund", "reit", "asset", "assets",
    "liability", "liabilities", "debt", "mortgage", "heloc", "loan", "net worth", "cash", "spending", "burn", "savings", "budget", "income",
    "salary", "bonus", "compensation", "career", "retire", "retirement", "fire", "swr", "withdrawal", "monte carlo", "simulation", "scenario",
    "forecast", "forecasting", "solvency", "drawdown", "crash", "stagflation", "event", "events", "plan", "plans", "assistant", "nanny",
    "vacation", "travel", "galapagos", "lifestyle", "sabbatical", "sequence", "estate", "trust", "slat", "idgt", "grat", "ilit", "inheritance",
    "heir", "heirs", "gift", "gifting", "709", "exclusion", "exemption", "tcja", "sunset", "philanthropy", "charity", "charitable", "daf",
    "donor", "deduction", "bunching", "arbitrage", "relocate", "relocation", "washington", "california", "new york", "texas", "florida",
    "nevada", "oregon", "wyoming", "fiduciary", "ips", "policy", "drift", "dividend", "yield", "interest", "inflation", "compounding",
    "wealth", "financial", "finance", "finances", "money", "account", "accounts", "brokerage", "monarch", "simplefin", "household", "family",
    "balance sheet", "liquidity", "proceeds", "spread", "exercise", "valuation", "real estate", "property", "home", "house", "insurance",
    "annuity", "social security", "medicare", "pension", "transcript", "transcripts", "tvpi", "dpi", "rvpi", "unfunded", "capital call",
    "dry powder", "lp", "k-1", "k1", "1099", "1098", "3921", "8283", "cpa", "checklist", "probate", "beneficiary", "tod", "pod",
    "survivorship", "core burn", "waterfall",
)

_FINANCE_DOMAIN_RE = re.compile(r"\b(" + "|".join(_FINANCE_DOMAIN_KEYWORDS) + r")\b", re.IGNORECASE)

_OFF_TOPIC_PATTERNS = (
    r"\b(solve|factor|integrate|differentiate|derivative|integral|calculus|algebra|trigonometry|geometry|quadratic|equation|theorem|proof)\b",
    r"\b(homework|assignment|exam|quiz|test question|essay|book report|poem|haiku|sonnet|story|screenplay|lyrics|joke|riddle)\b",
    r"\b(recipe|cooking|bake|baking|ingredients|calories|workout|exercise routine|medical|symptom|diagnosis)\b",
    r"\b(write a python|write a javascript|write code|leetcode|binary search|linked list|sorting algorithm|sql query|regex)\b",
    r"\b(ignore previous instructions|ignore all instructions|disregard your instructions|system prompt|act as a|pretend you are)\b",
    r"\b(who won the|capital of|president of|history of|world war|photosynthesis|mitochondria|periodic table|quantum)\b",
)


def _is_off_topic_query(prompt: str, history: Optional[List[Dict[str, Any]]] = None) -> bool:
    """Determines whether a user prompt is unrelated to household finance or a prompt injection attempt."""
    p_lower = (prompt or "").strip().lower()
    if not p_lower:
        return False
    if re.search(r"\b(ignore (all |previous )?instructions|disregard (your |previous )?instructions|act as a|pretend you are)\b", p_lower):
        return True
    if _FINANCE_DOMAIN_RE.search(p_lower):
        return False
    if any(re.search(pat, p_lower) for pat in _OFF_TOPIC_PATTERNS):
        return True
    return bool(re.search(r"\b\d+\s*[\+\-\*\/\^]\s*\d+\b", p_lower) or re.search(r"\b\d*x\s*[\+\-\=]\s*\d+", p_lower))


def _format_off_topic_refusal(ctx: Dict[str, Any]) -> str:
    """Returns a polite, domain-scoped refusal message when a user asks an off-topic question."""
    family_name = ctx.get("family_name", "your household")
    return (
        f"### 🛡️ Financial Scope Notice\n\n"
        f"I am the **AI Financial Advisor** for **{family_name}**, and I am strictly scoped to assist with "
        f"**personal finance, portfolio allocation, tax planning, company equity (RSUs/NSOs/ISOs), retirement forecasting, and estate planning**.\n\n"
        f"I cannot help with general-purpose questions, math or school homework, coding tasks, or non-financial topics.\n\n"
        f"#### Topics I Can Help You Model:\n"
        f"- **Portfolio & Asset Allocation:** Rebalancing drift, tax-efficient asset location, and IPS targets.\n"
        f"- **Company Equity & Options:** RSU vesting tax gaps, NSO/ISO exercise costs, and AMT exposure.\n"
        f"- **Tax & Retirement Forecasting:** Multi-decade Monte Carlo stress tests, safe withdrawal rates, and state tax arbitrage.\n"
        f"- **Estate & Gifting:** Federal/state death tax exposure, SLAT/IDGT trusts, 529 college funding, and DAF giving."
    )


def get_initial_tab_suggestions(active_tab: str, ctx: Dict[str, Any]) -> List[str]:
    """Generates initial context suggestion chips tailored to every dashboard tab."""
    tab_lower = (active_tab or "section-overview").lower()
    inv_pol = ctx.get("investment_policy", {})
    comp = ctx.get("equity", {}).get("company_name", "Company")
    if "holding" in tab_lower or "investment" in tab_lower:
        return [
            f"How does our portfolio compare to our {inv_pol.get('anchor_preset', 'policy')} target?",
            "Which asset classes are currently drifting outside our tolerance band?",
            "Review our private LP fund commitments, unfunded dry powder, and TVPI performance.",
            "How do we rebalance tax-free using 401(k) and cash sweeps?",
        ]
    if "equity" in tab_lower:
        return [
            f"Review our {comp} equity grants and 5-year projections.",
            "What is the difference between our NSOs and RSUs?",
            "What strike capital do I need to exercise my vested options?",
            "Estimate the tax bill if I exercise 1,000 NSO options this year.",
        ]
    if "scenario" in tab_lower or "forecast" in tab_lower:
        return [
            "Model our drawdown order across taxable/Roth and accelerated LP capital calls.",
            "Run a 1,000-trial Monte Carlo simulation of my plan.",
            "How would my portfolio survive a 2008 crash at retirement?",
            "What life events are modeled in our active scenario?",
        ]
    if "estate" in tab_lower:
        return [
            "Audit household survivorship risk, probate exposure, and beneficiary designations.",
            "How does Washington state estate tax compare to California and Texas?",
            "Explain how a SLAT or IDGT can shield millions from the 40% federal estate tax.",
            "How much wealth will each of our children inherit after estate taxes?",
        ]
    if "account" in tab_lower:
        return [
            "Break down all our synced and manual accounts by category.",
            "How much liquid cash vs. retirement and brokerage assets do we hold?",
            "Review our mortgages, credit cards, and total liabilities.",
            "Which institutions hold the largest share of our net worth?",
        ]
    if any(k in tab_lower for k in ("compensation", "withholding", "transcript", "tax")):
        return [
            "Are we on track to meet our 110% IRS Safe Harbor withholding target?",
            "How much extra federal tax should we withhold per remaining paycheck?",
            "Summarize our career W-2 base salary and bonus progression.",
            "Review our tax season document checklist, K-1s, and 110% safe harbor status.",
        ]
    if "arbitrage" in tab_lower:
        return [
            "Compare our 5-year tax and lifestyle cost in WA vs. CA, NV, and TX.",
            "How much state tax would we save by relocating before a major liquidity event?",
            "Review our historical spending benchmarks and top expense drivers.",
            "What are the domicile rules for establishing residency in a 0%-tax state?",
        ]
    if "college" in tab_lower or "education" in tab_lower:
        return [
            "Are our children's 529 plans on track for 4-year university tuition?",
            "Compare our projected 529 balances against In-State, Out-of-State, and Private Elite costs.",
            "How much K-12 and college tuition is covered by 529 vs. out-of-pocket cashflow?",
            "Summarize each child's current 529 balance and matriculation timeline.",
        ]
    if "philanthropy" in tab_lower:
        return [
            "Summarize our lifetime charitable giving and this year's DAF grant budget.",
            "How much of our annual charitable budget is allocated vs. remaining?",
            "List the organizations and grants in our active philanthropy ledger.",
            "How can we optimize tax deductions by donating appreciated shares to a DAF?",
        ]
    if "gifting" in tab_lower:
        return [
            "How much have we gifted this year vs. our annual IRS Form 709 exclusion limits?",
            "How much tax-exempt gifting headroom do we have left per recipient group?",
            "Do any of our family gifts this year require filing IRS Form 709?",
            "How can we combine annual exclusion gifting with 529 superfunding?",
        ]
    return [
        "Provide an executive strategic overview of our family balance sheet.",
        "What are the top 3 financial priorities for our household right now?",
        "How should we optimize our tax-free investment rebalancing?",
        "Summarize our company equity holdings and vesting status.",
    ]


def _generate_follow_up_suggestions(prompt: str, active_tab: str, ctx: Dict[str, Any]) -> List[str]:
    """Generates context-aware follow-up question chips based on the active topic or tab."""
    p_lower = (prompt or "").lower()
    topic_map = [
        (("529", "college", "tuition", "university", "k-12", "k12"), "section-college"),
        (("philanthropy", "charity", "charitable", "daf", "donation"), "section-philanthropy"),
        (("709", "exclusion", "family gift", "gifting"), "section-gifting"),
        (("arbitrage", "relocate", "california", "nevada", "texas", "florida"), "section-arbitrage"),
        (("safe harbor", "withholding", "w-2", "w2", "transcript", "salary", "bonus", "compensation"), "section-compensation"),
        (("account", "monarch", "simplefin", "institution", "mortgage"), "section-accounts"),
        (("equity", "rsu", "nso", "grant", "strike", "option", "vest"), "section-equity"),
        (("allocation", "holdings", "policy", "drift", "boglehead", "rebalance", "satellite"), "section-holdings"),
        (("monte carlo", "crash", "2008", "stress", "sequence", "drawdown", "solvency", "scenario", "forecast"), "section-scenarios"),
        (("estate", "trust", "slat", "idgt", "inheritance", "sunset"), "section-estate"),
    ]
    for keywords, section_id in topic_map:
        if any(k in p_lower for k in keywords):
            return get_initial_tab_suggestions(section_id, ctx)
    return get_initial_tab_suggestions(active_tab, ctx)
