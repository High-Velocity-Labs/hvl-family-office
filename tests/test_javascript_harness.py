"""
Pytest integration runner for clientside JavaScript tests.
Powered by hvl_common.testing.run_node_tests.
"""

from hvl_common.testing import run_node_tests


def test_clientside_javascript_harness():
    """Runs the Node.js / JSDOM test harness for clientside JS modules (AI advisor, Settings, modals)."""
    run_node_tests("tests/js/test_harness.js")


def test_v030_ui_javascript_harness():
    """Runs the Node.js / JSDOM test harness for v0.3.0 UI modules (SandboxManager, .fovault portability, BugReporter)."""
    run_node_tests("tests/js/test_v030_ui_harness.js")


def test_interactions_javascript_harness():
    """Runs the Node.js / JSDOM test harness for user interactions (range sliders, subtabs, pills, keyboard)."""
    run_node_tests("tests/js/test_interactions_harness.js")

