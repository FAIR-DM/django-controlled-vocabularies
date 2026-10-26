"""Fixtures shared by the demo project's tests."""

import pytest

from demo import settings as demo_settings


@pytest.fixture(autouse=True)
def demo_vocabularies(settings):
    """Declare the demo's seed vocabularies, as the demo's own settings do."""
    settings.CONTROLLED_VOCABULARIES = demo_settings.CONTROLLED_VOCABULARIES
