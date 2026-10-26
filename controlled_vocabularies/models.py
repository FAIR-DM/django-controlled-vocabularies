"""Models for vocabularies and the records they hold, each keeping its SKOS statements in JSON."""

import json
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies import conf

PREF_LABEL_MAX_LENGTH = 255

#: Leaves room for a ``-12345`` suffix inside the slug column.
SLUG_BASE_LENGTH = 240


def is_entry(entry: object) -> bool:
    """Return whether ``entry`` is shaped as JSON-LD writes a value.

    Args:
        entry: One item of a predicate's list.

    Returns:
        True for a link (``@id``), or a literal (``@value``) with at most a language or a datatype.
    """
    if not isinstance(entry, dict):
        return False
    if "@id" in entry:
        return set(entry) == {"@id"} and isinstance(entry["@id"], str)
    qualifiers = set(entry) - {"@value"}
    return (
        isinstance(entry.get("@value"), str | int | float | bool)
        and qualifiers <= {"@language", "@type"}
        and len(qualifiers) < 2
        and all(isinstance(entry[key], str) for key in qualifiers)
    )


def validate_document(value: object) -> None:
    """Check that a document maps each predicate to a list of JSON-LD style entries.

    Args:
        value: The candidate document.

    Raises:
        ValidationError: The document is not an object, or a predicate's value is not a list
            of ``{"@value": ...}`` / ``{"@id": ...}`` entries.
    """
    if not isinstance(value, dict):
        raise ValidationError(
            _("A document must be an object that maps predicates to lists."),
            code="document_not_object",
        )
    for key, entries in value.items():
        if not isinstance(entries, list) or not all(map(is_entry, entries)):
            raise ValidationError(
                _(
                    "The value of '%(predicate)s' must be a list of entries, each "
                    "with an '@id', or an '@value' and at most an '@language' or '@type'."
                ),
                params={"predicate": key},
                code="document_bad_entries",
            )


class Resource(models.Model):
    """Abstract base for a row that keeps its SKOS statements in a JSON document."""

    uri = models.CharField(
        max_length=500,
        unique=True,
        blank=True,
        verbose_name=_("URI"),
        help_text=_(
            "The identifier, fixed when the row is created and never rewritten. An imported "
            "row keeps the URI its publisher gave it; leave blank to have one made from this "
            "site's address."
        ),
    )
    slug = models.SlugField(
        max_length=255,
        allow_unicode=True,
        blank=True,
        verbose_name=_("slug"),
        help_text=_(
            "The address segment, made once when the row is created and never changed. "
            "Leave blank to derive it."
        ),
    )
    pref_label = models.CharField(
        max_length=PREF_LABEL_MAX_LENGTH,
        blank=True,
        verbose_name=_("preferred label"),
        help_text=_(
            "A copy of the preferred label in the default language, refreshed on every save."
        ),
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        validators=[validate_document],
        verbose_name=_("data"),
        help_text=_(
            "Every statement about this row. Each key is a predicate, written as a CURIE "
            "such as skos:prefLabel, and holds a list of entries like "
            '{"@value": "Granite", "@language": "en"} or {"@id": "https://example.org/x"}.'
        ),
    )

    #: Predicates whose values name the row, tried in this order.
    name_curies: tuple[str, ...] = ("skos:prefLabel",)

    #: Columns computed from ``data`` that a partial save must keep fresh.
    derived_fields: tuple[str, ...] = ("pref_label",)

    #: Annotation only: a vocabulary has the column, a record reads its vocabulary's.
    default_language: str

    class Meta:
        abstract = True

    def values(self, curie: str) -> list[dict]:
        """Return the entries stored under a predicate.

        Args:
            curie: The predicate, such as ``skos:altLabel``.

        Returns:
            The entries, empty when there are none.
        """
        entries: list[dict] = self.data.get(curie, [])
        return entries

    def label(self, language: str) -> str | None:
        """Return the name in one language.

        Args:
            language: The language tag to match, ignoring case.

        Returns:
            The first matching value, or None when the row has none in that language.
        """
        wanted = language.lower()
        for curie in self.name_curies:
            for entry in self.values(curie):
                if "@value" in entry and entry.get("@language", "").lower() == wanted:
                    return str(entry["@value"])
        return None

    def display_label(self) -> str:
        """Return the name in the active language, else the stored preferred label."""
        return self.label(get_language() or "") or self.pref_label

    def linked_uris(self, curie: str) -> list[str]:
        """Return the URIs a predicate links to, in stored order.

        Args:
            curie: The predicate, such as ``skos:broader``.

        Returns:
            The ``@id`` of each link entry.
        """
        return [entry["@id"] for entry in self.values(curie) if "@id" in entry]

    def first_value(self, curie: str) -> str:
        """Return the first value of a predicate as text, whether literal or link.

        Args:
            curie: The predicate, such as ``dcterms:publisher``.

        Returns:
            The text, or an empty string when the row has no such value.
        """
        entries = self.values(curie)
        return (
            str(entries[0].get("@value", entries[0].get("@id", ""))) if entries else ""
        )

    def minted_uri(self) -> str:
        """Return the URI for a row authored on this site, from its slug."""
        raise NotImplementedError

    def save(self, *args, **kwargs):
        """Refresh the derived columns and mint the URI and slug before the first write."""
        self.pref_label = self.name_in_default_language()
        self.mint_identity()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "data" in update_fields:
            kwargs["update_fields"] = {*update_fields, *self.derived_fields}
        super().save(*args, **kwargs)

    def name_in_default_language(self) -> str:
        """Return the name for ``pref_label``, cut to the column."""
        name = self.label(self.default_language)
        if name is None:
            # A row published without a name in the default language is still worth listing.
            name = next(
                (
                    str(entry["@value"])
                    for curie in self.name_curies
                    for entry in self.values(curie)
                    if "@value" in entry
                ),
                "",
            )
        return name[:PREF_LABEL_MAX_LENGTH]

    def mint_identity(self) -> None:
        """Give the row the URI and slug it has not got yet, and never change one it has."""
        if self.uri and self.slug:
            return
        if self.uri:
            parts = urlsplit(self.uri)
            segment = parts.fragment or parts.path.rstrip("/").rsplit("/", 1)[-1]
            self.slug = self.unique_slug(segment or self.pref_label)
            return
        self.slug = self.slug or self.unique_slug(self.pref_label)
        self.uri = self.minted_uri()

    def unique_slug(self, text: str) -> str:
        """Slugify ``text`` and add ``-2``, ``-3`` and so on until no sibling uses it.

        Args:
            text: The label or URI segment to derive the slug from.

        Returns:
            A slug unused among the row's siblings.
        """
        base = slugify(text, allow_unicode=True)[:SLUG_BASE_LENGTH]
        base = base or str(self._meta.model_name)
        taken = set(
            self.siblings()
            .exclude(pk=self.pk)
            .filter(slug__startswith=base)
            .values_list("slug", flat=True)
        )
        slug, number = base, 1
        while slug in taken:
            number += 1
            slug = f"{base}-{number}"
        return slug

    def siblings(self) -> models.QuerySet:
        """Return the rows whose slugs must differ from this one's."""
        return type(self)._default_manager.all()


class ConceptScheme(Resource):
    """A controlled vocabulary: the SKOS concept scheme holding a set of records."""

    slug = models.SlugField(
        max_length=255,
        unique=True,
        allow_unicode=True,
        blank=True,
        verbose_name=_("slug"),
        help_text=_(
            "The address segment, made once when the vocabulary is created and never "
            "changed. It is unique across vocabularies. Leave blank to derive it."
        ),
    )
    default_language = models.CharField(
        max_length=16,
        verbose_name=_("default language"),
        help_text=_(
            "The language of the preferred label copied into each row's own column, "
            "for example en."
        ),
    )
    name_curies = ("skos:prefLabel", "dcterms:title")

    def __str__(self) -> str:
        """Return the vocabulary's name."""
        return self.display_label() or self.uri

    def minted_uri(self) -> str:
        """Return the URI for a vocabulary authored on this site."""
        return f"{conf.get_base_uri()}/{self.slug}"


class RecordQuerySet(models.QuerySet):
    """Queries over records that read the JSON documents."""

    def mentioning(self, uri: str) -> "RecordQuerySet":
        """Narrow to records whose document may link to ``uri``.

        A cheap pre-filter on the stored text, which can match a record that holds the URI
        as a plain literal; callers check the links in Python.

        Args:
            uri: The URI to look for.

        Returns:
            The candidate records.
        """
        # The stored text is JSON, so the quoted, escaped form is what appears in it.
        return self.filter(data__icontains=json.dumps(uri))


class Record(Resource):
    """A concept or collection of a vocabulary."""

    class Type(models.TextChoices):
        """The SKOS class a record is an instance of."""

        CONCEPT = "skos:Concept", _("Concept")
        COLLECTION = "skos:Collection", _("Collection")
        ORDERED_COLLECTION = "skos:OrderedCollection", _("Ordered collection")

    COLLECTION_TYPES = (Type.COLLECTION, Type.ORDERED_COLLECTION)

    scheme = models.ForeignKey(
        ConceptScheme,
        on_delete=models.CASCADE,
        related_name="records",
        verbose_name=_("vocabulary"),
        help_text=_("The vocabulary this record belongs to."),
    )
    type = models.CharField(
        max_length=32,
        choices=Type.choices,
        verbose_name=_("type"),
        help_text=_(
            "Whether this is a concept, a collection or an ordered collection."
        ),
    )
    search_text = models.TextField(
        blank=True,
        verbose_name=_("search text"),
        help_text=_(
            "Every preferred, alternative and hidden label, one per line, "
            "refreshed on every save so a search needs no join."
        ),
    )

    derived_fields = ("pref_label", "search_text")

    objects = RecordQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scheme", "slug"], name="unique_record_slug_per_scheme"
            )
        ]
        indexes = [
            models.Index(
                fields=["scheme", "type", "pref_label"], name="record_scheme_type_label"
            )
        ]

    def __str__(self) -> str:
        """Return the record's name."""
        return self.display_label() or self.uri

    @property
    def default_language(self) -> str:  # type: ignore[override]
        """The default language of the record's vocabulary."""
        return self.scheme.default_language

    @property
    def is_collection(self) -> bool:
        """Whether the record is a collection, ordered or not."""
        return self.type in self.COLLECTION_TYPES

    def member_uris(self) -> list[str]:
        """Return the URIs of a collection's members, ordered ones in their sequence."""
        return self.linked_uris("skos:member") + self.linked_uris("skos:memberList")

    def minted_uri(self) -> str:
        """Return the URI for a record authored on this site.

        A collection's sits under a ``collection`` segment, as its page does, so it never
        names the same address as a concept with the same slug.
        """
        segment = "collection/" if self.is_collection else ""
        return f"{conf.get_base_uri()}/{self.scheme.slug}/{segment}{self.slug}"

    def siblings(self) -> models.QuerySet:
        """Return the other records of the same vocabulary."""
        return Record.objects.filter(scheme_id=self.scheme_id)

    def save(self, *args, **kwargs):
        """Refresh the search text, then save as any resource does."""
        self.search_text = "\n".join(
            str(entry["@value"])
            for curie in ("skos:prefLabel", "skos:altLabel", "skos:hiddenLabel")
            for entry in self.values(curie)
            if "@value" in entry
        )
        super().save(*args, **kwargs)
