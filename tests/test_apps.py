"""Tests for ``controlled_vocabularies.apps`` — the app is installed and its
configuration loads with a lazily translatable display name.
"""

from django.apps import apps
from django.utils.functional import Promise


class TestAppConfig:
    """The application registers under its label and exposes a translatable
    ``verbose_name`` (FR-009 extends the metadata standard to the AppConfig)."""

    def test_app_is_installed(self):
        assert apps.is_installed("controlled_vocabularies")

    def test_app_config_loads_with_expected_verbose_name(self):
        config = apps.get_app_config("controlled_vocabularies")
        assert config.verbose_name == "Controlled Vocabularies"

    def test_app_config_verbose_name_is_lazy(self):
        verbose_name = apps.get_app_config("controlled_vocabularies").verbose_name
        assert isinstance(verbose_name, Promise), (
            "AppConfig.verbose_name is not lazily translatable"
        )
