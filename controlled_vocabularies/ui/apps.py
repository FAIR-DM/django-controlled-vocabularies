"""App configuration for the opt-in vocabulary-browsing front end."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ControlledVocabulariesUIConfig(AppConfig):
    """Django ``AppConfig`` for the vocabulary-browsing front end."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "controlled_vocabularies.ui"
    # Distinct from the core app's label: the registry refuses two installed apps sharing one.
    label = "controlled_vocabularies_ui"
    verbose_name = _("Controlled Vocabularies UI")

    def ready(self):
        """Register the front end's system checks."""
        from django.core.checks import register

        from .checks import check_mvp_installed, check_vocabulary_detail_route

        register(check_mvp_installed)
        register(check_vocabulary_detail_route)
