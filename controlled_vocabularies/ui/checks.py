"""System checks for the opt-in vocabulary-browsing front end."""

from urllib.parse import urlparse

from django.core import checks
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies import conf

CHECK_ID = "controlled_vocabularies.ui.E001"
CHECK_ID_ROUTE_MISMATCH = "controlled_vocabularies.ui.W001"


def check_mvp_installed(app_configs, **kwargs):
    """Report an error when ``django-mvp`` cannot be imported."""
    # Without it the first symptom is a bare ModuleNotFoundError from URL loading. A real import
    # rather than find_spec, so the check fails exactly as that loading would.
    try:
        import mvp  # noqa: F401
    except ImportError:
        return [
            checks.Error(
                _(
                    "django-mvp is not installed, but controlled_vocabularies.ui requires it. "
                    "Install the 'ui' extra: pip install django-controlled-vocabularies[ui]."
                ),
                id=CHECK_ID,
            )
        ]
    return []


def check_vocabulary_detail_route(app_configs, **kwargs):
    """Warn when the ``vocabulary-detail`` route is mounted away from the base URI's path."""
    # Identifiers come from CONTROLLED_VOCABULARIES_BASE_URI, never a URL reversal, so nothing else
    # compares the two (FS-014). A warning because a reverse proxy may resolve them correctly.
    placeholder = "check-placeholder-slug"
    try:
        detail_path = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": placeholder}
        )
    except NoReverseMatch:
        return []

    mount_path = detail_path[: -len(f"{placeholder}/")]
    base_path = urlparse(conf.get_base_uri()).path

    if mount_path.rstrip("/") != base_path.rstrip("/"):
        return [
            checks.Warning(
                _(
                    "The 'vocabulary-detail' route is mounted at '%(mount_path)s', which does not "
                    "match the path of CONTROLLED_VOCABULARIES_BASE_URI ('%(base_path)s'). A "
                    "vocabulary's identifier will not lead to its page until the two agree."
                )
                % {"mount_path": mount_path, "base_path": base_path},
                id=CHECK_ID_ROUTE_MISMATCH,
            )
        ]
    return []
