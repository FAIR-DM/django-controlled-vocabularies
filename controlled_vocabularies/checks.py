"""System checks for the wiring and declarations of the concept fields."""

from django.apps import apps
from django.conf import settings
from django.core import checks
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _

from .fields import ConceptField, ConceptsField
from .models import ConceptScheme

CHECK_ID = "controlled_vocabularies.W001"
CHECK_ID_MISSING_ROUTE = "controlled_vocabularies.W002"
CHECK_ID_MISSING_INSTALLED_APP = "controlled_vocabularies.W003"
CHECK_ID_MISSING_MIDDLEWARE = "controlled_vocabularies.W004"
# Its own id rather than W001: projects silence checks by id, and silencing "vocabulary not
# imported" says nothing about a mistyped collection slug (FS-016).
CHECK_ID_MISSING_RESTRICTION_TARGET = "controlled_vocabularies.W005"

#: The middleware the control's widget needs on the page (``forms.py``). Named
#: once here for the same reason as :data:`AUTOCOMPLETE_URL_NAME`.
TOMSELECT_MIDDLEWARE = "django_tomselect.middleware.TomSelectMiddleware"

#: The name the control's widget reverses at render time (``forms.py``'s
#: ``_config()``). Named once here so the check and the widget cannot drift
#: apart about which route is being asked for.
AUTOCOMPLETE_URL_NAME = "controlled_vocabularies:concept-autocomplete"


def check_concept_field_vocabularies(app_configs, **kwargs):
    """Warn about every vocabulary a concept field names that is absent from the database."""
    fields = [
        field
        for model in apps.get_models()
        for field in model._meta.get_fields()
        if isinstance(field, (ConceptField, ConceptsField))
    ]
    slugs = {slug for field in fields for slug in field.vocabulary}
    if not slugs:
        return []

    # Checks run before migrate, and a missing table is not evidence that a vocabulary is absent.
    try:
        existing = set(
            ConceptScheme.objects.filter(slug__in=slugs).values_list("slug", flat=True)
        )
    except DatabaseError:
        return []

    return [
        checks.Warning(
            _(
                "%(model)s.%(field)s names vocabulary '%(vocabulary)s', which has no matching ConceptScheme yet."
            )
            % {
                "model": field.model._meta.label,
                "field": field.name,
                "vocabulary": slug,
            },
            hint=_(
                "Import this vocabulary, or silence this check with SILENCED_SYSTEM_CHECKS."
            ),
            obj=field,
            id=CHECK_ID,
        )
        for field in fields
        for slug in field.vocabulary
        if slug not in existing
    ]


def check_concept_field_restriction_targets(app_configs, **kwargs):
    """Warn about every collection, concept or branch restriction naming a target absent from its vocabulary."""
    fields = [
        field
        for model in apps.get_models()
        for field in model._meta.get_fields()
        if isinstance(field, (ConceptField, ConceptsField))
    ]

    # Targets are (vocabulary, slug) pairs, never flat slugs: a collection or concept slug is unique
    # only within its vocabulary, so a flat set would call a mistyped slug present whenever
    # another vocabulary uses it.
    collection_targets = []
    concepts_targets = []
    branch_targets = []
    for field in fields:
        if field.collection is not None:
            (vocabulary,) = field.vocabulary
            collection_targets.append((field, vocabulary, field.collection))
        if field.concepts is not None:
            (vocabulary,) = field.vocabulary
            concepts_targets.extend(
                (field, vocabulary, slug) for slug in field.concepts
            )
        if field.branch is not None:
            (vocabulary,) = field.vocabulary
            branch_targets.append((field, vocabulary, field.branch))

    if not (collection_targets or concepts_targets or branch_targets):
        return []

    from .models import Collection, Concept

    def _existing_pairs(model, targets):
        """Return the ``(vocabulary slug, slug)`` pairs of ``targets`` that exist.

        Args:
            model: ``Collection`` or ``Concept``.
            targets: ``(field, vocabulary slug, target slug)`` tuples to look up.

        Returns:
            The pairs found in the database.
        """
        if not targets:
            return set()
        return set(
            model.objects.filter(
                scheme__slug__in={vocabulary for _, vocabulary, _ in targets},
                slug__in={slug for _, _, slug in targets},
            ).values_list("scheme__slug", "slug")
        )

    # Same DatabaseError guard as check_concept_field_vocabularies.
    try:
        existing_collections = _existing_pairs(Collection, collection_targets)
        existing_concepts = _existing_pairs(Concept, concepts_targets)
        existing_branch_roots = _existing_pairs(Concept, branch_targets)
    except DatabaseError:
        return []

    messages = {
        "collection": (
            _(
                "%(model)s.%(field)s names collection '%(target)s', which does not exist in the '%(vocabulary)s' vocabulary."
            ),
            _("Create this collection, or correct the name."),
        ),
        "concepts": (
            _(
                "%(model)s.%(field)s names concept '%(target)s', which does not exist in the '%(vocabulary)s' vocabulary."
            ),
            _("Create this concept, or correct the name."),
        ),
        "branch": (
            _(
                "%(model)s.%(field)s names branch root '%(target)s', which does not exist in the "
                "'%(vocabulary)s' vocabulary."
            ),
            _("Create this concept, or correct the name."),
        ),
    }

    warnings = []
    for kind, targets, existing in (
        ("collection", collection_targets, existing_collections),
        ("concepts", concepts_targets, existing_concepts),
        ("branch", branch_targets, existing_branch_roots),
    ):
        message, hint = messages[kind]
        for field, vocabulary, slug in targets:
            if (vocabulary, slug) in existing:
                continue
            warnings.append(
                checks.Warning(
                    message
                    % {
                        "model": field.model._meta.label,
                        "field": field.name,
                        "target": slug,
                        "vocabulary": vocabulary,
                    },
                    hint=hint,
                    obj=field,
                    id=CHECK_ID_MISSING_RESTRICTION_TARGET,
                )
            )
    return warnings


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
