"""App configuration that registers the system checks."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ControlledVocabulariesConfig(AppConfig):
    """Application configuration for controlled_vocabularies."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "controlled_vocabularies"
    verbose_name = _("Controlled Vocabularies")

    def ready(self):
        """Register the package's system checks."""
        from django.core.checks import register

        from .checks import (
            check_concept_autocomplete_route_included,
            check_concept_field_restriction_targets,
            check_concept_field_vocabularies,
            check_django_tomselect_installed,
            check_tomselect_middleware_installed,
        )

        register(check_concept_field_vocabularies)
        register(check_concept_field_restriction_targets)
        register(check_concept_autocomplete_route_included)
        register(check_django_tomselect_installed)
        register(check_tomselect_middleware_installed)
