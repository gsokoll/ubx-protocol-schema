"""Pytest configuration and fixtures for UBX testing."""

import sys
from pathlib import Path

import pytest

# Ensure lib is in path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def all_messages():
    """Load all message definitions."""
    from lib.schema_loader import get_all_messages
    return get_all_messages()


@pytest.fixture(scope="session")
def fixed_length_messages(all_messages):
    """Get only fixed-length messages."""
    fixed = []
    for msg in all_messages:
        payload = msg.get("payload", {})
        length = payload.get("length", {})
        if isinstance(length, dict) and "fixed" in length:
            fixed.append(msg)
        elif isinstance(length, int):
            fixed.append(msg)
    return fixed


@pytest.fixture(scope="session")
def pyubx2_available():
    """Check if pyubx2 is available."""
    try:
        import pyubx2
        return True
    except ImportError:
        return False


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "pyubx2: marks tests that require pyubx2"
    )
