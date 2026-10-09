"""Pytest configuration and shared fixtures.

The Databricks Connect session is created lazily: only tests that request the
``spark`` fixture contact Databricks. Pure-Python tests run fully offline.
Tests that need a live workspace are marked ``integration`` so CI can skip them
with ``pytest -m "not integration"``.
"""

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: needs a live Databricks workspace (serverless)"
    )


@pytest.fixture(scope="session")
def spark():
    """One serverless Spark session shared by all tests that need it."""
    from databricks.connect import DatabricksSession

    return DatabricksSession.builder.serverless(True).getOrCreate()
