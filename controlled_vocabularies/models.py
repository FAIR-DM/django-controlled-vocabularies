"""Models for vocabularies and the records they hold, with SKOS statements in JSON."""

from typing import cast
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import connections, models, transaction
from django.db.models.expressions import RawSQL
from django.db.models.functions import Lower
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies import conf

PREF_LABEL_MAX_LENGTH = 255

#: Leaves room for a ``-12345`` suffix inside the slug column.
SLUG_BASE_LENGTH = 240


def validate_document(value: object) -> None:
    """Check that a document maps each predicate to a list of JSON-LD style entries.

    Args:
        value: The candidate document.

    Raises:
        ValidationError: The document is not an object, or a predicate's value is not a
            list of entries.
    """

    def is_statements(node: object) -> bool:
        """Return whether ``node`` maps predicates to lists of entries.

        Args:
            node: A document, or a blank node embedded in one.

        Returns:
            True when every key is a predicate and every value a list of entries.
        """
        return isinstance(node, dict) and all(
            not key.startswith("@")
            and isinstance(entries, list)
            and all(map(is_entry, entries))
            for key, entries in node.items()
        )

    def is_entry(entry: object) -> bool:
        """Return whether ``entry`` is shaped as JSON-LD writes a value.

        Args:
            entry: One item of a predicate's list.

        Returns:
            True for a link (``@id``), a literal (``@value``) with at most a language or
            a datatype, or an embedded blank node holding statements of its own.
        """
        if not isinstance(entry, dict):
            return False
        if "@id" in entry:
            return set(entry) == {"@id"} and isinstance(entry["@id"], str)
        if "@value" not in entry:
            return is_statements(entry)
        qualifiers = set(entry) - {"@value"}
        return (
            isinstance(entry["@value"], str | int | float | bool)
            and qualifiers <= {"@language", "@type"}
            and len(qualifiers) < 2
            and all(isinstance(entry[key], str) for key in qualifiers)
        )

    if not isinstance(value, dict):
        raise ValidationError(
            _("A document must be an object that maps predicates to lists."),
            code="document_not_object",
        )
    for key, entries in value.items():
        if not is_statements({key: entries}):
            raise ValidationError(
                _(
                    "The value of '%(predicate)s' must be a list of entries, each a "
                    "link, a value or an embedded node of statements."
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
            "The identifier, fixed when the row is created and never rewritten. An "
            "imported row keeps the URI its publisher gave it; leave blank to have one "
            "made from this site's address."
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
            "A copy of the preferred label in the default language, refreshed on "
            "every save."
        ),
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        validators=[validate_document],
        verbose_name=_("data"),
        help_text=_(
            "Every statement about this row. Each key is a predicate, written as a "
            "CURIE such as skos:prefLabel, and holds a list of entries like "
            '{"@value": "Granite", "@language": "en"} or '
            '{"@id": "https://example.org/x"}.'
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
        """Return the name in the active language, else the stored preferred label.

        Returns:
            The label in the active language, or ``pref_label`` when it has none.
        """
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
        """Return the URI for a row authored on this site, from its slug.

        Returns:
            The URI to store when none was given.
        """
        raise NotImplementedError

    def save(self, *args, **kwargs):
        """Refresh the derived columns, then mint the URI and slug on first write."""
        self.pref_label = self.name_in_default_language()
        self.mint_identity()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "data" in update_fields:
            kwargs["update_fields"] = {*update_fields, *self.derived_fields}
        super().save(*args, **kwargs)

    def name_in_default_language(self) -> str:
        """Return the name for ``pref_label``, cut to the column.

        Returns:
            The default-language name, or the first available one, truncated.
        """
        name = self.label(self.default_language)
        if name is None:
            # A row published without a name in the default language is still worth
            # listing.
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
        """Give the row the URI and slug it lacks, and never change one it has."""
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
        """Return the rows whose slugs must differ from this one's.

        Returns:
            A queryset of every row of this model.
        """
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
        """Return the URI for a vocabulary authored on this site.

        Returns:
            The base URI followed by the slug.
        """
        return f"{conf.get_base_uri()}/{self.slug}"


class RecordQuerySet(models.QuerySet):
    """Queries over records that read the JSON documents."""

    def linking_to(self, uri: str, *curies: str) -> "RecordQuerySet":
        """Narrow to records whose document links to ``uri``, under one of ``curies`` when given.

        Reads the ``Link`` rows, so a record that holds the URI only as a literal is not
        returned, and a record that states the link more than once is returned once.

        Args:
            uri: The URI the records link to.
            *curies: The predicates to look under, such as ``skos:member``. Any
                predicate when none is given.

        Returns:
            The records stating a link to ``uri``.
        """
        links = Link.objects.filter(source=models.OuterRef("pk"), target=uri)
        if curies:
            links = links.filter(predicate__in=curies)
        return self.filter(models.Exists(links))

    def in_branch(self, scheme_uri: str, root_uri: str) -> "RecordQuerySet":
        """Narrow to the record ``root_uri`` and every record below it in one vocabulary.

        A record is below another when its document states ``skos:broader`` the other,
        or the other's document states ``skos:narrower`` it, at any depth. Both
        directions are followed at every step, and only downward, so the root's own
        broader concept and its siblings are left out. The walk stays inside the
        vocabulary, reads the ``Link`` rows and ends on a cycle, returning each record
        once. It is one recursive query, sent as a subquery inside the filter.

        Args:
            scheme_uri: The URI of the vocabulary to walk.
            root_uri: The URI of the record the branch grows from.

        Returns:
            The root and the records below it. Empty when the vocabulary holds no
            record with that URI.
        """
        quote = connections[self.db].ops.quote_name

        def column(model, name):
            """Return the quoted database column of a model's field."""
            return quote(cast(str, model._meta.get_field(name).column))

        scheme_table = quote(ConceptScheme._meta.db_table)
        record_table = quote(self.model._meta.db_table)
        link_table = quote(Link._meta.db_table)
        scheme_pk = column(ConceptScheme, "id")
        scheme_uri_column = column(ConceptScheme, "uri")
        record_pk = column(self.model, "id")
        record_uri = column(self.model, "uri")
        record_scheme = column(self.model, "scheme")
        link_source = column(Link, "source")
        link_predicate = column(Link, "predicate")
        link_target = column(Link, "target")
        # Union rather than union all, so a cycle in the stored links ends the walk. The
        # edges are a subquery in both directions because PostgreSQL allows a recursive
        # term to refer to the walk only once. Every value is a parameter.
        sql = f"""
            WITH RECURSIVE vocabulary(id) AS (
                SELECT {scheme_pk} FROM {scheme_table} WHERE {scheme_uri_column} = %s
            ), branch(uri) AS (
                SELECT {record_uri} FROM {record_table}
                 WHERE {record_scheme} IN (SELECT id FROM vocabulary)
                   AND {record_uri} = %s
                UNION
                SELECT edge.child
                  FROM branch
                  JOIN (
                      SELECT l.{link_target} AS parent, c.{record_uri} AS child
                        FROM {link_table} l
                        JOIN {record_table} c ON c.{record_pk} = l.{link_source}
                       WHERE l.{link_predicate} = %s
                         AND c.{record_scheme} IN (SELECT id FROM vocabulary)
                      UNION ALL
                      SELECT p.{record_uri}, c.{record_uri}
                        FROM {link_table} l
                        JOIN {record_table} p ON p.{record_pk} = l.{link_source}
                        JOIN {record_table} c ON c.{record_uri} = l.{link_target}
                       WHERE l.{link_predicate} = %s
                         AND p.{record_scheme} IN (SELECT id FROM vocabulary)
                         AND c.{record_scheme} IN (SELECT id FROM vocabulary)
                  ) edge ON edge.parent = branch.uri
            )
            SELECT uri FROM branch
        """  # noqa: S608 identifiers come from model metadata
        params = [scheme_uri, root_uri, "skos:broader", "skos:narrower"]
        return self.filter(uri__in=RawSQL(sql, params))  # noqa: S611


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
        # In the order a vocabulary's concepts are listed. The trigram indexes concept
        # search uses on PostgreSQL are made by migration 0002 and not declared here,
        # because no other database can build them.
        indexes = [
            models.Index(
                models.F("scheme"),
                models.F("type"),
                Lower("pref_label"),
                name="record_scheme_type_label",
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
        """Return the URIs of a collection's members, ordered ones in their sequence.

        Returns:
            Each member URI once, ``skos:memberList`` entries first.
        """
        # A publisher may state a member both ways, so each is listed once.
        return list(
            dict.fromkeys(
                self.linked_uris("skos:memberList") + self.linked_uris("skos:member")
            )
        )

    def minted_uri(self) -> str:
        """Return the URI for a record authored on this site.

        A collection's sits under a ``collection`` segment, as its page does, so it
        never names the same address as a concept with the same slug.

        Returns:
            The URI built from the base URI, vocabulary slug and record slug.
        """
        segment = "collection/" if self.is_collection else ""
        return f"{conf.get_base_uri()}/{self.scheme.slug}/{segment}{self.slug}"

    def siblings(self) -> models.QuerySet:
        """Return the other records of the same vocabulary.

        Returns:
            A queryset of the records sharing this one's vocabulary.
        """
        return Record.objects.filter(scheme_id=self.scheme_id)

    def save(self, *args, **kwargs):
        """Refresh the search text, then save as any resource does and rebuild the links.

        The links are rebuilt, in the same transaction as the save, unless a partial
        save leaves ``data`` out.
        """
        self.search_text = "\n".join(
            str(entry["@value"])
            for curie in ("skos:prefLabel", "skos:altLabel", "skos:hiddenLabel")
            for entry in self.values(curie)
            if "@value" in entry
        )
        update_fields = kwargs.get("update_fields")
        adding = self._state.adding
        # No savepoint: an import saves thousands of records in one transaction, and a
        # failure here rolls back the caller's transaction as a failed save would.
        with transaction.atomic(savepoint=False):
            super().save(*args, **kwargs)
            if adding:
                # A new record has no rows to clear.
                Link.objects.bulk_create(self.link_rows())
            elif update_fields is None or "data" in update_fields:
                self.refresh_links()

    def link_rows(self) -> list["Link"]:
        """Return the unsaved ``Link`` rows this record's document states.

        Returns:
            One row for each top-level link entry, in stored order.
        """
        return [
            Link(source=self, predicate=curie, target=target)
            for curie in self.data
            for target in self.linked_uris(curie)
        ]

    def refresh_links(self) -> None:
        """Rebuild this record's ``Link`` rows from its document.

        ``save()`` calls this. Call it after writing documents with
        ``QuerySet.update()`` or ``bulk_create()``, which skip ``save()``, once the
        record is loaded again.
        """
        with transaction.atomic(savepoint=False):
            self.links.all().delete()
            Link.objects.bulk_create(self.link_rows())


class Link(models.Model):
    """One link a record's document states, copied into a row so it can be queried.

    The document stays the only source of truth. The rows are rebuilt from it each time
    the record is saved, so a page that asks who links to a record reads an index
    instead of every document.
    """

    source = models.ForeignKey(
        Record,
        on_delete=models.CASCADE,
        related_name="links",
        verbose_name=_("source"),
        help_text=_("The record whose document states the link."),
    )
    predicate = models.CharField(
        max_length=500,
        verbose_name=_("predicate"),
        help_text=_(
            "The key the link is stored under in the document, written as a CURIE such "
            "as skos:broader, or as a full URI."
        ),
    )
    target = models.CharField(
        max_length=500,
        verbose_name=_("target"),
        help_text=_(
            "The URI the link points at, as stored. It may name a concept this site "
            "does not hold."
        ),
    )

    class Meta:
        # The source column's own index serves rebuilding a record's rows. This one
        # answers who links to a URI, alone or under given predicates (ADR 0025).
        indexes = [
            models.Index(fields=["target", "predicate"], name="link_target_predicate")
        ]

    def __str__(self) -> str:
        """Return the link as ``source predicate target``."""
        return f"{self.source.uri} {self.predicate} {self.target}"
