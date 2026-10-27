"""Fixtures shared by the demo project's tests."""

import pytest

from controlled_vocabularies.management.commands import sync_vocabularies
from demo import settings as demo_settings


@pytest.fixture(autouse=True)
def demo_vocabularies(settings):
    """Declare the demo's seed vocabularies, as the demo's own settings do."""
    settings.CONTROLLED_VOCABULARIES = demo_settings.CONTROLLED_VOCABULARIES


@pytest.fixture(autouse=True)
def demo_models(monkeypatch):
    """Leave out the test app's concept fields, since the demo installs no model carrying one."""
    monkeypatch.setattr(sync_vocabularies, "concept_fields", lambda: [])
