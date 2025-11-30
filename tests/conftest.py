"""Pytest configuration and fixtures for GearCrew tests."""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv(project_root / ".env")


@pytest.fixture(scope="session", autouse=True)
def setup_environment():
    """Ensure environment variables are loaded for all tests."""
    required_vars = ["ANTHROPIC_API_KEY", "LANGWATCH_API_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        pytest.skip(f"Missing required environment variables: {', '.join(missing)}")

    yield


@pytest.fixture
def sample_youtube_url():
    """Provide a sample YouTube URL for testing."""
    return "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def sample_gear_review_url():
    """Provide a sample gear review URL for testing."""
    return "https://www.rei.com/learn/expert-advice/backpacking-tent.html"
