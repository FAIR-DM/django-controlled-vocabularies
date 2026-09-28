"""Tests for controlled_vocabularies.apps."""

from django.apps import apps
from django.utils.functional import Promise


class TestAppConfig:
    def test_app_is_installed(self):
        assert apps.is_installed("controlled_vocabularies")

    def test_app_config_verbose_name_is_lazy(self):
        verbose_name = apps.get_app_config("controlled_vocabularies").verbose_name
        assert isinstance(verbose_name, Promise), (
            "AppConfig.verbose_name is not lazily translatable"
        )
