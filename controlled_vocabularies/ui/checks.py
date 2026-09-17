"""System checks for the opt-in vocabulary-browsing front end.

Both are registered from
:meth:`~controlled_vocabularies.ui.apps.ControlledVocabulariesUIConfig.ready`.
"""

from urllib.parse import urlparse

from django.core import checks
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies import conf

CHECK_ID = "controlled_vocabularies.ui.E001"
CHECK_ID_ROUTE_MISMATCH = "controlled_vocabularies.ui.W001"


def check_mvp_installed(app_configs, **kwargs):
    """Report an error when ``django-mvp`` cannot be imported (013-find-a-vocabulary,
    FR-012's neighbour, plan.md Key design decisions #5).

    Without it the first symptom is a bare ``ModuleNotFoundError: mvp`` raised from URL
    loading, which names neither the extra nor the app that needs it. A real ``import mvp``
    rather than an ``importlib.util.find_spec`` probe, so the check behaves exactly like the
    URL loading it replaces the failure of.
    """
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
    """Warn when the ``vocabulary-detail`` route is mounted somewhere that disagrees with the
    configured base address (014-look-inside-a-vocabulary T005, FR-004's precondition,
    Article IX, plan.md Key design decision #2).

    A vocabulary's identifier is composed from ``CONTROLLED_VOCABULARIES_BASE_URI``, a
    setting, never a URL reversal — the ``ui`` app is mounted wherever the project chooses,
    and nothing has ever compared the two. When they disagree, a locally held vocabulary's
    identifier does not lead back to its own page (FR-004).

    A warning, not an error: a project may serve its identifiers through a reverse proxy that
    resolves them correctly, which this check cannot see, so it reports what it sees rather
    than refusing to boot. Silent when the browsing routes are not mounted at all — a project
    that installed the app and has not yet wired its URLs gets nothing from this check.
    """
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
