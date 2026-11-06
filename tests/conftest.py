"""Pytest configuration for Tipping Point.

Applies the isolated test-database environment before collection and
restores the original environment afterwards. Unrelated environment
configuration is never modified.
"""

from tests.harness import apply_test_database_env, restore_database_env


def pytest_configure(config):
    """Inject the isolated test database into the process environment."""
    apply_test_database_env()


def pytest_unconfigure(config):
    """Restore the original environment exactly as it was found."""
    restore_database_env()
