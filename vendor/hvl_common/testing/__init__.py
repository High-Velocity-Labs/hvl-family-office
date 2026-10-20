"""
High Velocity Labs Testing Utilities.
Provides shared test fixtures, JSDOM test harness, Pytest-to-Node test runners,
and Server-Side Rendering (SSR) parity auditing.
"""

from hvl_common.testing.pytest_node import run_node_tests
from hvl_common.testing.ssr_parity import SSRParityAuditor, KPIElementExtractor

__all__ = ["run_node_tests", "SSRParityAuditor", "KPIElementExtractor"]
