"""System check surfacing a :class:`~controlled_vocabularies.fields.ConceptField` or
:class:`~controlled_vocabularies.fields.ConceptsField` naming a vocabulary that has not been
imported yet.

Registered untagged in :meth:`~controlled_vocabularies.apps.ControlledVocabulariesConfig.ready`
(FR-004, ``research.md`` R3): ``Tags.database`` checks are skipped unless ``--database`` is
passed to ``manage.py check``, which is exactly the bare invocation this check exists to make
useful.
"""

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
CHECK_ID_MISSING_RESTRICTION_TARGET = "controlled_vocabularies.W005"

#: The middleware the control's widget needs on the page (``forms.py``). Named
#: once here for the same reason as :data:`AUTOCOMPLETE_URL_NAME`.
TOMSELECT_MIDDLEWARE = "django_tomselect.middleware.TomSelectMiddleware"

#: The name the control's widget reverses at render time (``forms.py``'s
#: ``_config()``). Named once here so the check and the widget cannot drift
#: apart about which route is being asked for.
AUTOCOMPLETE_URL_NAME = "controlled_vocabularies:concept-autocomplete"


def check_concept_field_vocabularies(app_configs, **kwargs):
    """Warn about every named vocabulary absent from the database.

    Walks every installed model for declared ``ConceptField`` and ``ConceptsField`` instances
    and resolves the distinct vocabulary slugs those fields name in **one** query, rather than
    one per field. Both fields hold ``vocabulary`` as a tuple naming zero, one or several
    (``decisions.md`` D9, #111), so each contributes every slug it names to the flattened
    distinct set rather than one. A field naming no vocabulary (the empty tuple) names nothing
    that could be missing, so it contributes nothing and is never warned about. Where a field
    names several and only one is absent, the warning names that slug rather than the field's
    whole declaration, so a developer reading ``manage.py check`` learns which vocabulary to
    import.

    The check runs before ``migrate`` (``BaseCommand.requires_system_checks`` defaults to
    ``"__all__"``), so on a fresh install it runs against a database with no tables yet. A
    missing table is not evidence that a vocabulary is absent, so that state — surfaced as
    ``ProgrammingError``, ``OperationalError`` or an unreachable database, all subclasses of
    ``DatabaseError`` — yields no warnings rather than raising (FR-003, ``research.md`` R3).
    """
    fields = [
        field
        for model in apps.get_models()
        for field in model._meta.get_fields()
        if isinstance(field, (ConceptField, ConceptsField))
    ]
    slugs = {slug for field in fields for slug in field.vocabulary}
    if not slugs:
        return []

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
    """Warn about every ``collection``, ``concepts`` or ``branch`` restriction
    naming a target absent from the vocabulary the field itself names
    (FR-009, ``plan.md`` A6, ``research.md`` R8).

    A restriction always names exactly one vocabulary (FR-005), so every
    declared target is a ``(vocabulary slug, target slug)`` pair. **The
    resolved set is built on that pair, never on a flat set of target
    slugs**: a collection slug is unique only within its own scheme
    (``unique_collection_slug_per_scheme``) and the same holds for a
    concept's (``unique_concept_slug_per_scheme``), unlike a vocabulary slug,
    which is unique app-wide. A flat set of slugs would report a mistyped
    name "present" whenever some other vocabulary happens to use it — exactly
    the state this check exists to surface (``decisions.md`` D7).

    Walks every installed model's fields once and batches the lookups by
    target kind: three queries total — one for ``collection`` targets, one
    for ``concepts`` targets and one for ``branch`` targets — never one per
    field, the same batching :func:`check_concept_field_vocabularies` already
    uses. A collection or concept that exists and holds no members is a
    curator's legitimate state, not a declaration error: only existence of
    the row is tested, never its membership.

    The check runs before ``migrate``, so on a fresh install it runs against
    a database with no tables yet. A missing table is not evidence that a
    target is absent, so that state — the same ``DatabaseError`` guard
    :func:`check_concept_field_vocabularies` already applies — yields no
    warnings rather than raising.

    A new id (``W005``) rather than folding into ``W001``: a project that has
    silenced "this vocabulary is not imported yet" has not thereby said
    anything about a mistyped collection slug, and a project silences by id.
    """
    fields = [
        field
        for model in apps.get_models()
        for field in model._meta.get_fields()
        if isinstance(field, (ConceptField, ConceptsField))
    ]

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
        if not targets:
            return set()
        return set(
            model.objects.filter(
                scheme__slug__in={vocabulary for _, vocabulary, _ in targets},
                slug__in={slug for _, _, slug in targets},
            ).values_list("scheme__slug", "slug")
        )

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
    """Warn when the project has not included this package's URL configuration
    (FR-002, FR-010, ``decisions.md`` D6, D10).

    ``reverse()`` resolves entirely against the already-loaded URLconf module, so
    this never queries the database — unlike :func:`check_concept_field_vocabularies`,
    it costs nothing to run on every invocation regardless of migration state.
    """
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
    """Warn when ``django_tomselect`` is not among the project's installed
    applications (FR-010, ``decisions.md`` D10).

    Django finds another package's templates and static assets only inside an
    installed application, so without this entry the control has a route to call
    but nothing to render it with. ``apps.is_installed()`` reads the already-loaded
    app registry, so this never queries the database either.
    """
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
    """Warn when ``TomSelectMiddleware`` is not in the project's ``MIDDLEWARE``
    (FR-002, FR-010, ``decisions.md`` D10, D15).

    The third wiring step, and the one that fails most quietly. The control's
    widget builds its full context — the part carrying the JavaScript that turns
    the ``<select>`` into a search-as-you-type box — only when
    ``django_tomselect``'s thread-local request is set, and only this middleware
    ever sets it (``middleware.py``, the sole assignment to ``_request_local``).
    Without it, ``TomSelectModelWidget.get_context()`` returns its base context
    (``widgets.py:626-629``), which renders an empty ``<select>`` carrying no
    control at all: measured on this package's own form at 36,232 characters
    against 67,519 with the middleware present, and with no ``new TomSelect(``
    anywhere in the page.

    Nothing raises in that state, so the check is the only thing that reports it.
    Reads ``settings.MIDDLEWARE`` only, so it never queries the database.
    """
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
