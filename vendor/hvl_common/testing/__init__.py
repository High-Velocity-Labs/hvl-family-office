"""
High Velocity Labs Testing Utilities.
Provides shared test fixtures, JSDOM test harness, Pytest-to-Node test runners,
and Server-Side Rendering (SSR) parity auditing.
"""

from hvl_common.testing.layout_overflow import (
    SHARED_RUNNER_JS,
    is_playwright_chrome_available,
    live_flask_server,
    resolve_playwright_node_path,
    run_playwright_overflow_suite,
)
from hvl_common.testing.pytest_node import run_node_tests
from hvl_common.testing.ssr_parity import KPIElementExtractor, SSRParityAuditor

__all__ = [
    "run_node_tests",
    "SSRParityAuditor",
    "KPIElementExtractor",
    "SHARED_RUNNER_JS",
    "is_playwright_chrome_available",
    "live_flask_server",
    "resolve_playwright_node_path",
    "run_playwright_overflow_suite",
]
