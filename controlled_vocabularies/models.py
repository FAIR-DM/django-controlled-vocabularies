"""Models for vocabularies, concepts, labels, notes, relations and collections."""

import urllib.parse
from typing import TYPE_CHECKING, TypeVar

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import validate_unicode_slug
from django.db import models
from django.db.models import F, Max, Q
from django.utils.text import Truncator, slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies import conf

if TYPE_CHECKING:
    # Stub-only (django-stubs), not importable at runtime.
    from django.utils.functional import _StrPromise

#: Schemes that can carry executable content, refused even if a project's allowlist includes
#: one: a stored identifier is later rendered as a link, which Django's escaping does not close.
_UNSAFE_STATIC_URI_SCHEMES = frozenset({"javascript", "data", "vbscript"})

#: Far beyond any real identifier, and inside MySQL's 3072-byte unique-index cap on ``utf8mb4``.
STATIC_URI_MAX_LENGTH = 500

#: Bounds how much of a hostile value a validation message echoes.
_STATIC_URI_MESSAGE_ECHO_CHARS = 80


def _echoed_uri(value: str) -> str:
    """Return ``value`` truncated for use inside a validation message.

    Args:
        value: The offending URI, of any length.

    Returns:
        The value cut to a bounded number of characters.
    """
    return str(Truncator(value).chars(_STATIC_URI_MESSAGE_ECHO_CHARS))


def validate_static_uri(value: str) -> None:
    """Validate an externally assigned static URI.

    The length is checked before parsing, so an oversized hostile value is refused with a
    short message. The value must be an absolute identifier (a scheme plus a non-empty
    remainder) on the configured scheme allowlist and not a scheme that can carry executable
    content. It is both a field validator and called from :func:`_prepare_static_uri`,
    because ``save()`` never calls ``full_clean()``.

    Args:
        value: The candidate static URI.

    Raises:
        ValidationError: The value is too long, cannot be parsed, is not absolute, or uses a
            scheme that is not allowed.
    """
    if len(value) > STATIC_URI_MAX_LENGTH:
        raise ValidationError(
            _(
                "A static URI cannot exceed %(max_length)s characters; '%(uri)s' has %(length)s."
            ),
            params={
                "max_length": STATIC_URI_MAX_LENGTH,
                "uri": _echoed_uri(value),
                "length": len(value),
            },
            code="static_uri_too_long",
        )
    try:
        # urlsplit raises a bare ValueError on some malformed netlocs, which would surface as a 500.
        parsed = urllib.parse.urlsplit(value)
    except ValueError as exc:
        raise ValidationError(
            _("'%(uri)s' could not be parsed as a URI."),
            params={"uri": _echoed_uri(value)},
            code="static_uri_unparseable",
        ) from exc
    if not parsed.scheme or not (parsed.netloc or parsed.path):
        raise ValidationError(
            _("'%(uri)s' is not a well-formed absolute identifier with a scheme."),
            params={"uri": _echoed_uri(value)},
            code="static_uri_not_absolute",
        )
    scheme = parsed.scheme.lower()
    if scheme not in conf.get_allowed_uri_schemes():
        raise ValidationError(
            _(
                "'%(uri)s' uses the scheme '%(scheme)s', which is not one of the accepted schemes."
            ),
            params={"uri": _echoed_uri(value), "scheme": parsed.scheme},
            code="static_uri_scheme_not_allowed",
        )
    if scheme in _UNSAFE_STATIC_URI_SCHEMES:
        raise ValidationError(
            _("'%(uri)s' uses the scheme '%(scheme)s', which is not permitted."),
            params={"uri": _echoed_uri(value), "scheme": parsed.scheme},
            code="static_uri_unsafe_scheme",
        )


def _prepare_static_uri(instance: "StaticUriModel") -> None:
    """Normalise a blank ``static_uri`` to ``None`` and validate its format ahead of a write.

    An empty string is not null, so it would occupy the partial unique constraint's slot
    while :attr:`uri` and :attr:`has_static_uri` read it as absent, and a second such record
    would fail with an opaque ``IntegrityError``. The format is checked here as well as on
    the field because ``save()`` never calls ``full_clean()``, and the importer writes through
    ``save()``. It does not guard a stored identifier against later edits (ADR 0001).

    Args:
        instance: The record about to be written.

    Raises:
        ValidationError: The value fails :func:`validate_static_uri`, keyed to ``static_uri``.
    """
    if instance.static_uri == "":
        instance.static_uri = None
    if not instance.static_uri:
        return
    try:
        validate_static_uri(instance.static_uri)
    except ValidationError as exc:
        raise ValidationError({"static_uri": exc}) from exc


def _configured_language_codes() -> set[str]:
    """Return the language codes in ``settings.LANGUAGES``.

    Read at runtime rather than bound to a field's ``choices``, which would freeze the
    maintainer's language list into the shipped migration.

    Returns:
        The configured language codes.
    """
    return {code for code, _label in settings.LANGUAGES}


_ModelT = TypeVar("_ModelT", bound=models.Model)


class StaticUriLookupMixin(models.Manager[_ModelT]):
    """Add :meth:`get_by_uri` to a manager so every URI-bearing model resolves identifiers alike."""

    def get_by_uri(self, uri: str) -> _ModelT:
        """Return the record identified by ``uri``, whether its URI is static or dynamic.

        A falsy or non-``str`` ``uri`` raises ``DoesNotExist`` at once, because
        ``get(static_uri=None)`` would match every dynamic record. Otherwise an exact match on
        ``static_uri`` is tried first, then the base-relative composition in
        :meth:`_get_by_local_parse`.

        Args:
            uri: The identifier to resolve.

        Returns:
            The matching record.

        Raises:
            self.model.DoesNotExist: ``uri`` is empty or not a string.
        """
        if not uri or not isinstance(uri, str):
            # django-stubs cannot resolve .DoesNotExist off a generic type[_ModelT].
            raise self.model.DoesNotExist(  # type: ignore[attr-defined]
                f"No {self.model.__name__} matches the URI {uri!r}."
            )
        try:
            return self.get(static_uri=uri)
        except ObjectDoesNotExist:
            return self._get_by_local_parse(uri)

    def _get_by_local_parse(self, uri: str) -> _ModelT:
        """Resolve a base-relative identifier; each model implements its own composition.

        Args:
            uri: The identifier to resolve.

        Returns:
            The matching record.

        Raises:
            NotImplementedError: The model does not implement it.
        """
        raise NotImplementedError


def _static_uri_field(help_text: "str | _StrPromise") -> models.CharField:
    """Build a ``static_uri`` field whose attributes every concrete model shares.

    Args:
        help_text: The model's own help text, the only attribute that differs per model.

    Returns:
        The configured field.
    """
    return models.CharField(
        max_length=STATIC_URI_MAX_LENGTH,
        null=True,
        blank=True,
        verbose_name=_("static URI"),
        help_text=help_text,
        validators=[validate_static_uri],
    )


def _slug_is_manual_field(help_text: "str | _StrPromise") -> models.BooleanField:
    """Build a ``slug_is_manual`` field whose attributes every concrete model shares.

    Args:
        help_text: The model's own help text, the only attribute that differs per model.

    Returns:
        The configured field.
    """
    # No db_index: a low-cardinality flag never filtered or ordered on.
    return models.BooleanField(
        default=False,
        verbose_name=_("slug set manually"),
        help_text=help_text,
    )


class StaticUriModel(models.Model):
    """Abstract base for a model whose URI is dynamic until an identifier is assigned.

    Holds ``static_uri``, ``uri`` and ``has_static_uri`` (ADR 0001). A concrete subclass
    supplies its own ``local_url``, its own ``static_uri`` constraint name and its own slug
    field.
    """

    static_uri = _static_uri_field(
        _(
            "The identifier once it is fixed — assigned by this record's publisher, "
            "or frozen when this vocabulary is published — held exactly as given and "
            "never recomputed. Leave blank while this record is authored here: its "
            "identifier is computed from this site's address until then. Editing this "
            "after publication breaks references to the record and should be prevented "
            "wherever the field is exposed."
        )
    )
    slug_is_manual = _slug_is_manual_field(
        _(
            "Whether the slug was set explicitly rather than derived automatically. "
            "A manual slug is left untouched when the record is later renamed."
        )
    )

    #: Annotation only, so the base can reference ``self.slug``. Each subclass declares its own
    #: SlugField because its uniqueness scope differs.
    slug: str

    class Meta:
        abstract = True

    @property
    def uri(self) -> str:
        """The record's URI: ``static_uri`` when held, otherwise :attr:`local_url`."""
        return self.static_uri or self.local_url

    @property
    def local_url(self) -> str:
        """Where this record is viewed on this site, composed by each model."""
        raise NotImplementedError

    @property
    def has_static_uri(self) -> bool:
        """Whether ``static_uri`` is set, never inferred from the configured base address."""
        return bool(self.static_uri)

    def set_slug(self, slug: str) -> None:
        """Set an explicit slug that survives a later rename, and save.

        The slug is stored as given, not re-slugified. Each subclass's :meth:`save` still
        checks that it is non-empty and unique.

        Args:
            slug: The slug to hold.
        """
        self.slug = slug
        self.slug_is_manual = True
        self.save()

    def _validate_manual_slug(self) -> None:
        """Refuse an empty or malformed manual slug.

        Applied explicitly because ``save()`` never runs the ``SlugField`` validator, and a
        slug with spaces or ``/`` would corrupt the composed URI (Article IX).

        Raises:
            ValidationError: The slug is empty or not a valid slug.
        """
        if not self.slug:
            raise ValidationError({"slug": _("An explicit slug must not be empty.")})
        try:
            validate_unicode_slug(self.slug)
        except ValidationError as exc:
            raise ValidationError(
                {
                    "slug": ValidationError(
                        _(
                            "An explicit slug must be a valid slug — letters, numbers, "
                            "hyphens or underscores, with no spaces or slashes."
                        ),
                    )
                }
            ) from exc

    def clean(self):
        """Normalise a blank ``static_uri`` to ``None`` and check its format."""
        super().clean()
        _prepare_static_uri(self)

    def save(self, *args, **kwargs):
        """Normalise and validate ``static_uri`` before writing, unless the save leaves it alone."""
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "static_uri" not in update_fields:
            super().save(*args, **kwargs)
            return
        if "static_uri" not in self.get_deferred_fields():
            _prepare_static_uri(self)
        super().save(*args, **kwargs)


class ConceptSchemeManager(StaticUriLookupMixin["ConceptScheme"]):
    """Default manager for :class:`ConceptScheme`, adding static-URI-based lookup."""

    def _get_by_local_parse(self, uri: str) -> "ConceptScheme":
        """Resolve ``{base}/{slug}`` to a vocabulary, refusing a remainder with a further ``/``.

        Args:
            uri: The identifier to resolve.

        Returns:
            The vocabulary with that slug.

        Raises:
            self.model.DoesNotExist: The identifier is outside the base address or malformed.
        """
        prefix = f"{conf.get_base_uri()}/"
        if not uri.startswith(prefix):
            raise self.model.DoesNotExist(f"No vocabulary matches the URI {uri!r}.")
        slug = uri[len(prefix) :].strip("/")
        if not slug or "/" in slug:
            raise self.model.DoesNotExist(f"No vocabulary matches the URI {uri!r}.")
        return self.get(slug=slug)


class ConceptScheme(StaticUriModel):
    """A controlled vocabulary, a named container for concepts (a SKOS concept scheme).

    The ``slug`` is derived from ``name`` on every save unless :attr:`slug_is_manual` is set,
    and is unique app-wide.
    """

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_(
            "The human-readable name of the vocabulary. Its slug is derived automatically from this."
        ),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("description"),
        help_text=_("Optional explanation of what this vocabulary covers."),
    )
    slug = models.SlugField(
        max_length=255,
        unique=True,
        allow_unicode=True,
        verbose_name=_("slug"),
        help_text=_(
            "A URL-safe identifier derived automatically from the name. A slug must be unique across all vocabularies."
        ),
    )
    slug_is_manual = _slug_is_manual_field(
        _(
            "Whether the slug was set explicitly rather than derived from the name. "
            "A manual slug is left untouched when the name later changes."
        )
    )
    default_language = models.CharField(
        max_length=16,
        blank=True,
        verbose_name=_("default language"),
        help_text=_(
            "The language whose preferred label anchors this vocabulary's concepts' identity. "
            "Leave blank to fall back to the application's configured default language. "
            "Must be one of the application's configured languages."
        ),
    )
    static_uri = _static_uri_field(
        _(
            "The identifier once it is fixed — assigned by this vocabulary's publisher, "
            "or frozen when this vocabulary is published — held exactly as given and "
            "never recomputed. Leave blank while this vocabulary is authored here: its identifier "
            "is computed from this site's address until then. Editing this after "
            "publication breaks references to the record and should be prevented "
            "wherever the field is exposed."
        )
    )

    objects = ConceptSchemeManager()

    class Meta:
        verbose_name = _("vocabulary")
        verbose_name_plural = _("vocabularies")
        constraints = [
            models.UniqueConstraint(
                fields=["static_uri"],
                condition=Q(static_uri__isnull=False),
                name="conceptscheme_static_uri_unique",
            ),
        ]

    def __str__(self) -> str:
        """Return the name."""
        return self.name

    @property
    def local_url(self) -> str:
        """This site's address for the vocabulary: the configured base address and its slug."""
        return f"{conf.get_base_uri()}/{self.slug}"

    @property
    def effective_default_language(self) -> str:
        """The language anchoring concept identity: :attr:`default_language`, else ``LANGUAGE_CODE``."""
        return self.default_language or settings.LANGUAGE_CODE

    def save(self, *args, **kwargs):
        """Derive the slug, freeze the default language once concepts exist, and refuse a bad slug."""
        # Each concept's identity anchor is its label in this language, so changing it after
        # concepts exist would silently reinterpret every anchor.
        if self.pk is not None:
            stored = (
                ConceptScheme.objects.filter(pk=self.pk)
                .values_list("default_language", flat=True)
                .first()
            )
            if (
                stored is not None
                and stored != self.default_language
                and self.concepts.exists()
            ):
                raise ValidationError(
                    {
                        "default_language": _(
                            "A vocabulary's default language cannot be changed once it has concepts, "
                            "because it would reinterpret their identity."
                        )
                    }
                )
        if (
            self.default_language
            and self.default_language not in _configured_language_codes()
        ):
            raise ValidationError(
                {
                    "default_language": ValidationError(
                        _(
                            "'%(language)s' is not one of the application's configured languages."
                        ),
                        params={"language": self.default_language},
                    )
                }
            )
        if not self.slug_is_manual:
            self.slug = slugify(self.name, allow_unicode=True)
            if not self.slug:
                raise ValidationError(
                    {"name": _("Name must produce a non-empty slug.")}
                )
        else:
            self._validate_manual_slug()
        # A collision is refused, never auto-suffixed, so a duplicate identifier is not minted.
        if ConceptScheme.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
            raise ValidationError(
                {
                    "slug": ValidationError(
                        _("A vocabulary with the slug '%(slug)s' already exists."),
                        params={"slug": self.slug},
                    )
                }
            )
        super().save(*args, **kwargs)


class ConceptManager(StaticUriLookupMixin["Concept"]):
    """Default manager for :class:`Concept`, adding static-URI-based lookup."""

    def _get_by_local_parse(self, uri: str) -> "Concept":
        """Resolve ``{base}/{scheme-slug}/{concept-slug}`` to a concept.

        Args:
            uri: The identifier to resolve.

        Returns:
            The concept with that scheme slug and slug.

        Raises:
            self.model.DoesNotExist: The identifier is outside the base address or malformed.
        """
        # A '/'-terminated base stops a sibling path like '<base>X/a/b' matching as in-base.
        prefix = f"{conf.get_base_uri()}/"
        if not uri.startswith(prefix):
            raise self.model.DoesNotExist(f"No concept matches the URI {uri!r}.")
        remainder = uri[len(prefix) :].strip("/")
        parts = remainder.split("/")
        if len(parts) != 2:
            raise self.model.DoesNotExist(f"No concept matches the URI {uri!r}.")
        scheme_slug, concept_slug = parts
        return self.get(scheme__slug=scheme_slug, slug=concept_slug)


class Concept(StaticUriModel):
    """A single term within a vocabulary (a SKOS concept).

    The ``slug`` is derived from ``label`` on every save unless :attr:`slug_is_manual` is
    set, and is unique within its scheme. ``label`` is the preferred label in the scheme's
    effective default language.
    """

    scheme = models.ForeignKey(
        ConceptScheme,
        on_delete=models.CASCADE,
        related_name="concepts",
        verbose_name=_("vocabulary"),
        help_text=_("The vocabulary this concept belongs to."),
    )
    label = models.CharField(
        max_length=255,
        verbose_name=_("preferred label"),
        help_text=_(
            "The preferred label in the vocabulary's effective default language. "
            "It is the concept's identity anchor: the slug is derived from it, and "
            "preferred labels in other languages are held as separate labels."
        ),
    )
    slug = models.SlugField(
        max_length=255,
        allow_unicode=True,
        verbose_name=_("slug"),
        help_text=_(
            "A URL-safe identifier derived automatically from the label. A slug must be unique within a given vocabulary."
        ),
    )
    slug_is_manual = _slug_is_manual_field(
        _(
            "Whether the slug was set explicitly rather than derived from the label. "
            "A manual slug is left untouched when the label later changes."
        )
    )
    static_uri = _static_uri_field(
        _(
            "The identifier once it is fixed — assigned by this concept's publisher, or "
            "frozen when its vocabulary is published — held exactly as given and never "
            "recomputed. "
            "Leave blank while this concept is authored here: its identifier is "
            "computed from this site's address until then. Editing this after "
            "publication breaks references to the record and should be prevented "
            "wherever the field is exposed."
        )
    )

    objects = ConceptManager()

    class Meta:
        verbose_name = _("concept")
        verbose_name_plural = _("concepts")
        constraints = [
            models.UniqueConstraint(
                fields=["scheme", "slug"], name="unique_concept_slug_per_scheme"
            ),
            models.UniqueConstraint(
                fields=["static_uri"],
                condition=Q(static_uri__isnull=False),
                name="concept_static_uri_unique",
            ),
        ]

    def __str__(self) -> str:
        """Return the preferred label."""
        return self.label

    @property
    def local_url(self) -> str:
        """This site's address for the concept, composed from its scheme's :attr:`~ConceptScheme.local_url`."""
        return f"{self.scheme.local_url}/{self.slug}"

    def save(self, *args, **kwargs):
        """Derive the slug from ``label`` unless set manually, and refuse an empty or colliding slug."""
        if not self.slug_is_manual:
            self.slug = slugify(self.label, allow_unicode=True)
            if not self.slug:
                # A named placeholder keeps the msgid static and translatable (Article XII).
                raise ValidationError(
                    {
                        "label": ValidationError(
                            _(
                                "A preferred label in the default language '%(language)s' is required."
                            ),
                            params={"language": self.scheme.effective_default_language},
                        )
                    }
                )
        else:
            self._validate_manual_slug()
        if (
            Concept.objects.filter(scheme=self.scheme, slug=self.slug)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                {
                    "slug": ValidationError(
                        _(
                            "A concept with the slug '%(slug)s' already exists in this vocabulary."
                        ),
                        params={"slug": self.slug},
                    )
                }
            )
        super().save(*args, **kwargs)

    def preferred_label(self, language: str | None = None) -> str | None:
        """Return this concept's preferred label in ``language``.

        Args:
            language: The language code, or ``None`` for the scheme's effective default
                language, whose preferred label is :attr:`label`.

        Returns:
            The label text, or ``None`` when the concept has none in that language.
        """
        if language is None or language == self.scheme.effective_default_language:
            return self.label
        # Iterating the cached related set (not .filter()) lets prefetch_related('labels') save queries.
        for row in self.labels.all():
            if row.language == language and row.kind == ConceptLabel.Kind.PREFERRED:
                return row.text
        return None

    def display_label(self) -> str:
        """Return the preferred label in the active language, falling back to :attr:`label`.

        Returns:
            The label text, never empty.
        """
        return self.preferred_label(get_language()) or self.label

    def alt_labels(self, language: str) -> list[str]:
        """Return this concept's alternative label texts in ``language``.

        Reads the cached related set, so it stays cheap under ``prefetch_related``.

        Args:
            language: The language code.

        Returns:
            The texts in label order, empty when there are none.
        """
        return [
            row.text
            for row in self.labels.all()
            if row.language == language and row.kind == ConceptLabel.Kind.ALTERNATIVE
        ]

    def hidden_labels(self, language: str) -> list[str]:
        """Return this concept's hidden label texts in ``language``.

        Hidden labels are misspellings and search-only variants. Reads the cached related
        set, so it stays cheap under ``prefetch_related``.

        Args:
            language: The language code.

        Returns:
            The texts in label order, empty when there are none.
        """
        return [
            row.text
            for row in self.labels.all()
            if row.language == language and row.kind == ConceptLabel.Kind.HIDDEN
        ]

    def add_label(self, language: str, kind: str, text: str) -> "ConceptLabel":
        """Add a label of any kind and return the created row.

        The row is validated first: a second preferred label in a language, or a preferred
        label in the effective default language (which lives on :attr:`label`), is refused
        with a ``ValidationError``. Adding a label never touches the slug or URI.

        Args:
            language: The language code.
            kind: A :class:`ConceptLabel.Kind` value.
            text: The label text.

        Returns:
            The saved label.
        """
        row = ConceptLabel(concept=self, language=language, kind=kind, text=text)
        row.full_clean()
        row.save()
        return row

    def definition(self, language: str) -> str | None:
        """Return this concept's first definition in ``language``.

        Args:
            language: The language code.

        Returns:
            The first definition by note order, or ``None`` when there is none.
        """
        for row in self.concept_notes.all():
            if row.language == language and row.kind == ConceptNote.Kind.DEFINITION:
                return row.value
        return None

    def notes(self, language: str, kind: str | None = None) -> list[str]:
        """Return this concept's documentary note values in ``language``.

        Args:
            language: The language code.
            kind: A :class:`ConceptNote.Kind` value to narrow to, or ``None`` for every kind.

        Returns:
            The values in note order, empty when none match.
        """
        return [
            row.value
            for row in self.concept_notes.all()
            if row.language == language and (kind is None or row.kind == kind)
        ]

    def add_note(self, language: str, kind: str, value: str) -> "ConceptNote":
        """Add a documentary note of any kind and return the created row.

        The row is validated first: ``language`` and ``kind`` must be configured choices and
        ``value`` non-empty, else a ``ValidationError`` is raised. Notes may repeat per kind
        and language.

        Args:
            language: The language code.
            kind: A :class:`ConceptNote.Kind` value.
            value: The note text.

        Returns:
            The saved note.
        """
        row = ConceptNote(concept=self, language=language, kind=kind, value=value)
        row.full_clean()
        row.save()
        return row

    def broader(self) -> "models.QuerySet[Concept]":
        """Return the concepts one step broader than this one.

        Returns:
            A queryset of the targets of this concept's ``BROADER`` rows.
        """
        return Concept.objects.filter(
            relations_as_target__source=self,
            relations_as_target__kind=ConceptRelation.Kind.BROADER,
        )

    def narrower(self) -> "models.QuerySet[Concept]":
        """Return the concepts one step narrower, read back from the stored ``BROADER`` edges.

        Returns:
            A queryset of the sources of ``BROADER`` rows whose target is this concept.
        """
        return Concept.objects.filter(
            relations_as_source__target=self,
            relations_as_source__kind=ConceptRelation.Kind.BROADER,
        )

    def add_broader(self, other: "Concept") -> "ConceptRelation":
        """Give this concept a broader concept and return the created relation.

        The relation is validated first: a self, cross-vocabulary, duplicate or
        disjointness-violating edge is refused with a ``ValidationError``.

        Args:
            other: The broader concept.

        Returns:
            The saved relation.
        """
        return self._add_relation(other, ConceptRelation.Kind.BROADER)

    def remove_broader(self, other: "Concept") -> None:
        """Remove the broader edge to ``other``, doing nothing when absent.

        Args:
            other: The broader concept.
        """
        ConceptRelation.objects.filter(
            source=self, target=other, kind=ConceptRelation.Kind.BROADER
        ).delete()

    def related(self) -> "models.QuerySet[Concept]":
        """Return the concepts related to this one.

        A related row is stored once, so this concept may sit in either column, and the
        other endpoint is returned each time.

        Returns:
            A queryset of the related concepts.
        """
        as_source = Concept.objects.filter(
            relations_as_target__source=self,
            relations_as_target__kind=ConceptRelation.Kind.RELATED,
        )
        as_target = Concept.objects.filter(
            relations_as_source__target=self,
            relations_as_source__kind=ConceptRelation.Kind.RELATED,
        )
        return (as_source | as_target).distinct()

    def add_related(self, other: "Concept") -> "ConceptRelation":
        """Relate this concept to ``other`` and return the created relation.

        The association is symmetric and stored once, so asserting it in the mirror order is
        refused as a duplicate. A self, cross-vocabulary or disjointness-violating edge is
        refused with a ``ValidationError``.

        Args:
            other: The concept to relate to.

        Returns:
            The saved relation.
        """
        return self._add_relation(other, ConceptRelation.Kind.RELATED)

    def remove_related(self, other: "Concept") -> None:
        """Remove the related edge with ``other``, in either stored order, doing nothing when absent.

        Args:
            other: The related concept.
        """
        ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED).filter(
            Q(source=self, target=other) | Q(source=other, target=self)
        ).delete()

    def _add_relation(self, other: "Concept", kind: str) -> "ConceptRelation":
        """Validate and save a relation of ``kind`` from this concept to ``other``.

        Runs ``full_clean`` so the curator-facing messages fire.

        Args:
            other: The target concept.
            kind: A :class:`ConceptRelation.Kind` value.

        Returns:
            The saved relation.
        """
        row = ConceptRelation(source=self, target=other, kind=kind)
        row.full_clean()
        row.save()
        return row

    def collections(self) -> list["Collection"]:
        """Return the collections this concept is a member of.

        Returns:
            The collections, empty when the concept belongs to none.
        """
        return list(Collection.objects.filter(memberships__concept=self).distinct())


class ConceptLabel(models.Model):
    """A language-tagged label for a concept, other than the identity anchor.

    The preferred label in the vocabulary's effective default language is
    :attr:`Concept.label`. Every other label is one of these rows, with at most one
    ``PREFERRED`` per (concept, language).
    """

    class Kind(models.TextChoices):
        """The lexical role of a label (SKOS ``prefLabel`` / ``altLabel`` / ``hiddenLabel``)."""

        PREFERRED = "preferred", _("preferred")
        ALTERNATIVE = "alternative", _("alternative")
        HIDDEN = "hidden", _("hidden")

    concept = models.ForeignKey(
        Concept,
        on_delete=models.CASCADE,
        related_name="labels",
        verbose_name=_("concept"),
        help_text=_("The concept this label names."),
    )
    language = models.CharField(
        max_length=16,
        verbose_name=_("language"),
        help_text=_(
            "The language this label is written in, from the application's configured languages."
        ),
    )
    kind = models.CharField(
        max_length=16,
        choices=Kind.choices,
        verbose_name=_("kind"),
        help_text=_(
            "Whether this is the language's preferred label or an alternative or hidden one."
        ),
    )
    text = models.CharField(
        max_length=255,
        verbose_name=_("text"),
        help_text=_("The label text, as it reads in this language."),
    )

    class Meta:
        verbose_name = _("label")
        verbose_name_plural = _("labels")
        ordering = ("language", "kind", "text")
        indexes = [
            # Backs label lookup and search; the concept FK is auto-indexed (Article XIII).
            models.Index(
                fields=["language", "kind", "text"], name="cv_label_lang_kind_text_idx"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["concept", "language"],
                # The string value, because a nested class body cannot see its sibling Kind.
                condition=Q(kind="preferred"),
                name="one_preferred_label_per_language",
            ),
        ]

    def __str__(self) -> str:
        """Return the label text."""
        return self.text

    def clean(self):
        """Check the language is configured and refuse a duplicate or default-language preferred label."""
        super().clean()
        if self.language and self.language not in _configured_language_codes():
            raise ValidationError(
                {
                    "language": ValidationError(
                        _(
                            "'%(language)s' is not one of the application's configured languages."
                        ),
                        params={"language": self.language},
                    )
                }
            )
        if self.kind != self.Kind.PREFERRED:
            return
        self._reject_default_language_preferred()
        already_preferred = (
            ConceptLabel.objects.filter(
                concept=self.concept, language=self.language, kind=self.Kind.PREFERRED
            )
            .exclude(pk=self.pk)
            .exists()
        )
        if already_preferred:
            raise ValidationError(
                {
                    "language": ValidationError(
                        _(
                            "A preferred label in the language '%(language)s' already exists for this concept."
                        ),
                        params={"language": self.language},
                    )
                }
            )

    def _reject_default_language_preferred(self) -> None:
        """Refuse a ``PREFERRED`` row in the scheme's effective default language.

        That language's preferred label is :attr:`Concept.label`. The rule is re-checked in
        :meth:`save` because no database constraint can compare against another table's column.

        Raises:
            ValidationError: The row would be a second identity anchor.
        """
        if (
            self.kind == self.Kind.PREFERRED
            and self.language == self.concept.scheme.effective_default_language
        ):
            raise ValidationError(
                {
                    "language": ValidationError(
                        _(
                            "The preferred label in the default language '%(language)s' is the "
                            "concept's own label, not a separate label."
                        ),
                        params={"language": self.language},
                    )
                }
            )

    def save(self, *args, **kwargs):
        """Refuse a default-language preferred label, then write."""
        self._reject_default_language_preferred()
        super().save(*args, **kwargs)


class ConceptNote(models.Model):
    """A language-tagged documentary note on a concept (a SKOS documentary property).

    Covers the definition and the six SKOS documentary notes. Each is free prose that may
    recur any number of times per (concept, language, kind).
    """

    class Kind(models.TextChoices):
        """The SKOS documentary property a note fills (``definition`` / ``scopeNote`` / …)."""

        DEFINITION = "definition", _("definition")
        SCOPE = "scope", _("scope note")
        EXAMPLE = "example", _("example")
        EDITORIAL = "editorial", _("editorial note")
        HISTORY = "history", _("history note")
        CHANGE = "change", _("change note")
        NOTE = "note", _("note")

    concept = models.ForeignKey(
        Concept,
        on_delete=models.CASCADE,
        related_name="concept_notes",
        verbose_name=_("concept"),
        help_text=_("The concept this note describes."),
    )
    language = models.CharField(
        max_length=16,
        verbose_name=_("language"),
        help_text=_(
            "The language this note is written in, from the application's configured languages."
        ),
    )
    kind = models.CharField(
        max_length=16,
        choices=Kind.choices,
        verbose_name=_("kind"),
        help_text=_(
            "Which SKOS documentary property this note fills — its definition, a scope note, an example, and so on."
        ),
    )
    # Unindexed on purpose: no lookup path reads it (Article XIII).
    value = models.TextField(
        verbose_name=_("value"),
        help_text=_("The note text, as it reads in this language."),
    )

    class Meta:
        verbose_name = _("note")
        verbose_name_plural = _("notes")
        ordering = ("language", "kind")

    def __str__(self) -> str:
        """Return the note text."""
        return self.value

    def clean(self):
        """Check that ``language`` is one of the application's configured languages."""
        super().clean()
        if self.language and self.language not in _configured_language_codes():
            raise ValidationError(
                {
                    "language": ValidationError(
                        _(
                            "'%(language)s' is not one of the application's configured languages."
                        ),
                        params={"language": self.language},
                    )
                }
            )


class ConceptRelation(models.Model):
    """A directed, intra-vocabulary link between two concepts (a SKOS semantic relation).

    Only one direction of the hierarchy is stored, a ``BROADER`` row where :attr:`source` is
    the narrower concept and :attr:`target` the broader, so the data cannot assert one
    direction without the other. A ``related`` row is symmetric and stored once, its
    endpoints ordered by primary key. Both concepts must belong to the same vocabulary.
    """

    class Kind(models.TextChoices):
        """The stored relation kind; ``narrower`` is the inverse read of ``broader``."""

        BROADER = "broader", _("broader")
        RELATED = "related", _("related")

    source = models.ForeignKey(
        Concept,
        on_delete=models.CASCADE,
        related_name="relations_as_source",
        verbose_name=_("source concept"),
        help_text=_(
            "One end of the relation. For a broader link this is the narrower (child) concept; "
            "for a related link it is the lower-numbered of the pair."
        ),
    )
    target = models.ForeignKey(
        Concept,
        on_delete=models.CASCADE,
        related_name="relations_as_target",
        verbose_name=_("target concept"),
        help_text=_(
            "The other end of the relation. For a broader link this is the broader (parent) concept; "
            "for a related link it is the higher-numbered of the pair."
        ),
    )
    kind = models.CharField(
        max_length=16,
        choices=Kind.choices,
        verbose_name=_("kind"),
        help_text=_(
            "The kind of link: a broader/narrower hierarchy edge, or a symmetric related association."
        ),
    )

    class Meta:
        verbose_name = _("concept relation")
        verbose_name_plural = _("concept relations")
        ordering = ("source", "kind", "target")
        constraints = [
            # Ordered on purpose: a reversed broader edge is a different, permitted edge.
            models.UniqueConstraint(
                fields=["source", "target", "kind"], name="unique_concept_relation"
            ),
            models.CheckConstraint(
                condition=~Q(source=F("target")), name="concept_relation_not_self"
            ),
        ]
        indexes = [
            # Backs the reverse reads (derived narrower, incoming related); the unique
            # constraint covers source-leading reads (Article XIII).
            models.Index(fields=["target", "kind"], name="cv_relation_target_kind_idx"),
        ]

    def __str__(self) -> str:
        """Return the relation as "source kind target"."""
        return f"{self.source} {self.kind} {self.target}"

    def _canonicalise(self) -> None:
        """Order a ``related`` row's endpoints by primary key so a mirror-order duplicate is caught.

        Broader rows are directional and left untouched.
        """
        if (
            self.kind == self.Kind.RELATED
            and self.source_id is not None
            and self.target_id is not None
            and self.source_id > self.target_id
        ):
            self.source_id, self.target_id = self.target_id, self.source_id

    def _reject_self(self) -> None:
        """Refuse a relation from a concept to itself, with a curator-facing message.

        Raises:
            ValidationError: Source and target are the same concept.
        """
        if self.source_id is not None and self.source_id == self.target_id:
            raise ValidationError(_("A concept cannot be in a relation with itself."))

    def _reject_cross_scheme(self) -> None:
        """Refuse a relation whose two concepts belong to different vocabularies.

        No database constraint can express this, so it is re-checked in :meth:`save`.

        Raises:
            ValidationError: The concepts belong to different vocabularies.
        """
        if self.source_id is None or self.target_id is None:
            return
        if self.source.scheme_id != self.target.scheme_id:
            raise ValidationError(
                _(
                    "A relation can only join concepts in the same vocabulary; "
                    "'%(source)s' and '%(target)s' are in different vocabularies."
                ),
                params={
                    "source": self.source.scheme.name,
                    "target": self.target.scheme.name,
                },
            )

    def _reject_disjointness_violation(self) -> None:
        """Refuse a pair already joined by the other kind of relation.

        SKOS makes ``related`` disjoint from the hierarchy. Only directly asserted pairs are
        checked, with no hierarchy traversal. No database constraint can express this, so it
        is re-checked in :meth:`save`.

        Raises:
            ValidationError: A relation of the other kind already joins the pair.
        """
        if self.source_id is None or self.target_id is None:
            return
        other_kind = (
            self.Kind.RELATED if self.kind == self.Kind.BROADER else self.Kind.BROADER
        )
        conflict = (
            ConceptRelation.objects.filter(kind=other_kind)
            .filter(
                Q(source_id=self.source_id, target_id=self.target_id)
                | Q(source_id=self.target_id, target_id=self.source_id)
            )
            .exclude(pk=self.pk)
            .exists()
        )
        if conflict:
            raise ValidationError(
                _(
                    "These concepts are already joined as '%(kind)s'; a broader/narrower "
                    "pair and a related pair are mutually exclusive."
                ),
                params={"kind": self.Kind(other_kind).label},
            )

    def clean(self):
        """Canonicalise the endpoints and check the relation invariants."""
        super().clean()
        self._canonicalise()
        self._reject_self()
        self._reject_cross_scheme()
        self._reject_disjointness_violation()

    def save(self, *args, **kwargs):
        """Canonicalise the endpoints and re-check the invariants, then write."""
        self._canonicalise()
        self._reject_self()
        self._reject_cross_scheme()
        self._reject_disjointness_violation()
        super().save(*args, **kwargs)


class CollectionManager(StaticUriLookupMixin["Collection"]):
    """Default manager for :class:`Collection`, adding static-URI-based lookup."""

    def _get_by_local_parse(self, uri: str) -> "Collection":
        """Resolve ``{base}/{scheme-slug}/collection/{slug}`` to a collection.

        The literal ``collection`` segment is required, so a concept's identifier is never
        mistaken for one.

        Args:
            uri: The identifier to resolve.

        Returns:
            The collection with that scheme slug and slug.

        Raises:
            self.model.DoesNotExist: The identifier is outside the base address or malformed.
        """
        prefix = f"{conf.get_base_uri()}/"
        if not uri.startswith(prefix):
            raise self.model.DoesNotExist(f"No collection matches the URI {uri!r}.")
        remainder = uri[len(prefix) :].strip("/")
        parts = remainder.split("/")
        if len(parts) != 3 or parts[1] != "collection":
            raise self.model.DoesNotExist(f"No collection matches the URI {uri!r}.")
        scheme_slug, _collection_segment, collection_slug = parts
        return self.get(scheme__slug=scheme_slug, slug=collection_slug)


class Collection(StaticUriModel):
    """A named grouping of concepts within one vocabulary (a SKOS collection).

    A collection groups concepts of the *same* vocabulary without asserting a semantic
    relation between them (FS-004). When :attr:`ordered`, its members carry a deliberate
    sequence read back by :meth:`members`. The ``slug`` is derived from ``name`` on every
    save unless :attr:`slug_is_manual` is set, and is unique within the scheme.
    """

    scheme = models.ForeignKey(
        ConceptScheme,
        on_delete=models.CASCADE,
        related_name="collections",
        verbose_name=_("vocabulary"),
        help_text=_(
            "The vocabulary this collection belongs to. Its members are concepts of this vocabulary."
        ),
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_(
            "The human-readable name of the collection. Its slug is derived automatically from this."
        ),
    )
    slug = models.SlugField(
        max_length=255,
        allow_unicode=True,
        verbose_name=_("slug"),
        help_text=_(
            "A URL-safe identifier derived automatically from the name. A slug must be unique within a given vocabulary."
        ),
    )
    slug_is_manual = _slug_is_manual_field(
        _(
            "Whether the slug was set explicitly rather than derived from the name. "
            "A manual slug is left untouched when the name later changes."
        )
    )
    ordered = models.BooleanField(
        default=False,
        verbose_name=_("ordered"),
        help_text=_(
            "Whether the collection's members carry a deliberate sequence (a SKOS ordered collection). "
            "An unordered collection is a plain set."
        ),
    )
    static_uri = _static_uri_field(
        _(
            "The identifier once it is fixed — assigned by this collection's publisher, "
            "or frozen when its vocabulary is published — held exactly as given and "
            "never recomputed. Leave blank while this collection is authored here: its identifier "
            "is computed from this site's address until then. Editing this after "
            "publication breaks references to the record and should be prevented "
            "wherever the field is exposed."
        )
    )

    objects = CollectionManager()

    class Meta:
        verbose_name = _("collection")
        verbose_name_plural = _("collections")
        constraints = [
            models.UniqueConstraint(
                fields=["scheme", "slug"], name="unique_collection_slug_per_scheme"
            ),
            models.UniqueConstraint(
                fields=["static_uri"],
                condition=Q(static_uri__isnull=False),
                name="collection_static_uri_unique",
            ),
        ]

    def __str__(self) -> str:
        """Return the name."""
        return self.name

    @property
    def local_url(self) -> str:
        """This site's address for the collection, under a ``/collection/`` segment so it never collides with a concept's."""
        return f"{self.scheme.local_url}/collection/{self.slug}"

    def save(self, *args, **kwargs):
        """Derive the slug from ``name`` unless set manually, and refuse an empty or colliding slug."""
        if not self.slug_is_manual:
            self.slug = slugify(self.name, allow_unicode=True)
            if not self.slug:
                raise ValidationError(
                    {"name": _("Name must produce a non-empty slug.")}
                )
        else:
            self._validate_manual_slug()
        if (
            Collection.objects.filter(scheme=self.scheme, slug=self.slug)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                {
                    "slug": ValidationError(
                        _(
                            "A collection with the slug '%(slug)s' already exists in this vocabulary."
                        ),
                        params={"slug": self.slug},
                    )
                }
            )
        super().save(*args, **kwargs)

    def add(self, concept: "Concept") -> "CollectionMember":
        """Add ``concept`` as the last member and return its membership.

        A concept already in the collection keeps its existing membership. A concept from
        another vocabulary is refused with a ``ValidationError``.

        Args:
            concept: The concept to add.

        Returns:
            The new or existing membership.
        """
        existing = self.memberships.filter(concept=concept).first()
        if existing is not None:
            return existing
        highest = self.memberships.aggregate(highest=Max("position"))["highest"]
        position = 0 if highest is None else highest + 1
        member = CollectionMember(collection=self, concept=concept, position=position)
        member.full_clean()
        member.save()
        return member

    def remove(self, concept: "Concept") -> None:
        """Remove ``concept``'s membership, doing nothing when absent.

        Args:
            concept: The concept to remove.
        """
        self.memberships.filter(concept=concept).delete()

    def members(self) -> list["Concept"]:
        """Return the collection's member concepts.

        Returns:
            The members in ascending ``position`` when :attr:`ordered`, otherwise in no
            promised sequence. Empty when there are none.
        """
        memberships = self.memberships.select_related("concept")
        memberships = (
            memberships.order_by("position", "id")
            if self.ordered
            else memberships.order_by("id")
        )
        return [membership.concept for membership in memberships]

    def set_member_order(self, concepts: "list[Concept]") -> None:
        """Reassign the members' positions to the given sequence.

        Args:
            concepts: Exactly the collection's current members, in the new order.

        Raises:
            ValidationError: The collection is not ordered, or ``concepts`` is not exactly its
                current member set.
        """
        if not self.ordered:
            raise ValidationError(
                _(
                    "Only an ordered collection can have its members ordered; '%(name)s' is not ordered."
                ),
                params={"name": self.name},
            )
        current = {membership.concept_id for membership in self.memberships.all()}
        given = [concept.pk for concept in concepts]
        if len(given) != len(current) or set(given) != current:
            raise ValidationError(
                _(
                    "The given concepts must be exactly this collection's current members."
                )
            )
        position_of = {concept_id: index for index, concept_id in enumerate(given)}
        for membership in self.memberships.all():
            new_position = position_of[membership.concept_id]
            if membership.position != new_position:
                membership.position = new_position
                membership.save(update_fields=["position"])


class CollectionMember(models.Model):
    """The membership edge joining a :class:`Collection` to one member :class:`Concept`.

    A through model because the edge carries a ``position`` and must be validated for
    scheme-confinement, which a bare ``ManyToManyField`` offers neither of. Held once per
    ``(collection, concept)``, and both ends must belong to the same vocabulary. Both FKs
    cascade because a membership is not consumer data and means nothing without both ends.
    """

    collection = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("collection"),
        help_text=_("The collection this membership belongs to."),
    )
    concept = models.ForeignKey(
        Concept,
        on_delete=models.CASCADE,
        related_name="collection_memberships",
        verbose_name=_("concept"),
        help_text=_(
            "The member concept. It must belong to the collection's own vocabulary."
        ),
    )
    position = models.PositiveIntegerField(
        default=0,
        verbose_name=_("position"),
        help_text=_(
            "The member's place in an ordered collection's sequence. Meaningful only when the "
            "collection is ordered; ignored otherwise."
        ),
    )

    class Meta:
        verbose_name = _("collection member")
        verbose_name_plural = _("collection members")
        ordering = ("collection", "position", "id")
        constraints = [
            # Doubles as the collection-leading membership index.
            models.UniqueConstraint(
                fields=["collection", "concept"], name="unique_collection_member"
            ),
        ]
        indexes = [
            # Backs the ordered members() read; the concept FK's auto-index covers the reverse (Article XIII).
            models.Index(
                fields=["collection", "position"], name="cv_collection_member_order_idx"
            ),
        ]

    def __str__(self) -> str:
        """Return the membership as "concept in collection"."""
        return f"{self.concept} in {self.collection}"

    def _reject_cross_scheme(self) -> None:
        """Refuse a member from a different vocabulary than the collection's.

        No database constraint can express this, so it is re-checked in :meth:`save`.

        Raises:
            ValidationError: The concept belongs to another vocabulary.
        """
        if self.collection_id is None or self.concept_id is None:
            return
        if self.collection.scheme_id != self.concept.scheme_id:
            raise ValidationError(
                _(
                    "A collection can only group concepts from its own vocabulary; "
                    "'%(concept_scheme)s' is not '%(collection_scheme)s'."
                ),
                params={
                    "concept_scheme": self.concept.scheme.name,
                    "collection_scheme": self.collection.scheme.name,
                },
            )

    def clean(self):
        """Refuse a member from a different vocabulary than the collection's."""
        super().clean()
        self._reject_cross_scheme()

    def save(self, *args, **kwargs):
        """Refuse a cross-vocabulary member, then write."""
        self._reject_cross_scheme()
        super().save(*args, **kwargs)
