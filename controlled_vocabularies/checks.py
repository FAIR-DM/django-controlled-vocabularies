"""System checks for the wiring and declarations of the concept fields."""

from django.apps import apps
from django.conf import settings
from django.core import checks
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _

from .fields import ConceptField, MultiConceptField
from .models import ConceptScheme, Record

CHECK_ID = "controlled_vocabularies.W001"
CHECK_ID_MISSING_ROUTE = "controlled_vocabularies.W002"
CHECK_ID_MISSING_INSTALLED_APP = "controlled_vocabularies.W003"
CHECK_ID_MISSING_MIDDLEWARE = "controlled_vocabularies.W004"
# Its own id rather than W001: projects silence checks by id, and silencing "vocabulary not
# loaded" says nothing about a mistyped collection URI (FS-016).
CHECK_ID_MISSING_RESTRICTION_TARGET = "controlled_vocabularies.W005"

#: The middleware the control's widget needs on the page (``forms.py``). Named
#: once here for the same reason as :data:`AUTOCOMPLETE_URL_NAME`.
TOMSELECT_MIDDLEWARE = "django_tomselect.middleware.TomSelectMiddleware"

#: The name the control's widget reverses at render time (``forms.py``'s
#: ``tomselect_config()``). Named once here so the check and the widget cannot drift
#: apart about which route is being asked for.
AUTOCOMPLETE_URL_NAME = "controlled_vocabularies:concept-autocomplete"


def concept_fields():
    """Return every concept field declared on an installed model."""
    return [
        field
        for model in apps.get_models()
        for field in model._meta.get_fields()
        if isinstance(field, (ConceptField, MultiConceptField))
    ]


def check_concept_field_vocabularies(app_configs, **kwargs):
    """Warn about every vocabulary a concept field names that is not in the database."""
    fields = concept_fields()
    uris = {uri for field in fields for uri in field.vocabulary_uris()}
    if not uris:
        return []

    # Checks run before migrate, and a missing table is not evidence that a vocabulary is absent.
    try:
        existing = set(
            ConceptScheme.objects.filter(uri__in=uris).values_list("uri", flat=True)
        )
    except DatabaseError:
        return []

    return [
        checks.Warning(
            _(
                "%(model)s.%(field)s names vocabulary '%(vocabulary)s', which has not been loaded yet."
            )
            % {
                "model": field.model._meta.label,
                "field": field.name,
                "vocabulary": uri,
            },
            hint=_(
                "Run manage.py sync_vocabularies, or silence this check with SILENCED_SYSTEM_CHECKS."
            ),
            obj=field,
            id=CHECK_ID,
        )
        for field in fields
        for uri in field.vocabulary_uris()
        if uri not in existing
    ]


def check_concept_field_restriction_targets(app_configs, **kwargs):
    """Warn about every collection restriction naming a collection that is missing."""
    targets = [
        (field, field.vocabulary[0].uri, field.collection)
        for field in concept_fields()
        if field.collection is not None
    ]
    if not targets:
        return []

    # The pair is the key: a collection held in some other vocabulary is not this one's.
    # Same DatabaseError guard as check_concept_field_vocabularies.
    try:
        existing = set(
            Record.objects.filter(
                scheme__uri__in={vocabulary for _, vocabulary, _ in targets},
                uri__in={uri for _, _, uri in targets},
                type__in=Record.COLLECTION_TYPES,
            ).values_list("scheme__uri", "uri")
        )
    except DatabaseError:
        return []

    return [
        checks.Warning(
            _(
                "%(model)s.%(field)s names collection '%(target)s', which does not exist in the '%(vocabulary)s' vocabulary."
            )
            % {
                "model": field.model._meta.label,
                "field": field.name,
                "target": uri,
                "vocabulary": vocabulary,
            },
            hint=_(
                "Correct the URI, or load a version of the vocabulary that holds this collection."
            ),
            obj=field,
            id=CHECK_ID_MISSING_RESTRICTION_TARGET,
        )
        for field, vocabulary, uri in targets
        if (vocabulary, uri) not in existing
    ]


def check_concept_autocomplete_route_included(app_configs, **kwargs):
    """Warn when the project has not included this package's URL configuration."""
    try:
        reverse(AUTOCOMPLETE_URL_NAME)
    except NoReverseMatch:
        return [
            checks.Warning(
                _(
                    "controlled_vocabularies's URL configuration is not included in the project's URLconf."
                ),
                hint=_(
                    'Add path("<prefix>/", include("controlled_vocabularies.urls")) to the project\'s root URLconf.'
                ),
                id=CHECK_ID_MISSING_ROUTE,
            )
        ]
    return []


def check_django_tomselect_installed(app_configs, **kwargs):
    """Warn when ``django_tomselect`` is not in ``INSTALLED_APPS``."""
    # Django finds another package's templates and static files only inside an installed app.
    if apps.is_installed("django_tomselect"):
        return []
    return [
        checks.Warning(
            _("django_tomselect is not in the project's INSTALLED_APPS."),
            hint=_('Add "django_tomselect" to INSTALLED_APPS.'),
            id=CHECK_ID_MISSING_INSTALLED_APP,
        )
    ]


def check_tomselect_middleware_installed(app_configs, **kwargs):
    """Warn when ``TomSelectMiddleware`` is not in ``MIDDLEWARE``."""
    # Nothing raises without it: the widget renders an empty <select> with no search control, so
    # this check is the only report (FS-011).
    if TOMSELECT_MIDDLEWARE in settings.MIDDLEWARE:
        return []
    return [
        checks.Warning(
            _(
                "django_tomselect's TomSelectMiddleware is not in the project's MIDDLEWARE."
            ),
            hint=_(
                'Add "django_tomselect.middleware.TomSelectMiddleware" to MIDDLEWARE. Without it '
                "the concept field renders as an empty select carrying no search control."
            ),
            id=CHECK_ID_MISSING_MIDDLEWARE,
        )
    ]
