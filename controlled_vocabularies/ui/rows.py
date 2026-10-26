"""Reading a record's JSON document into what the browsing pages show."""

from dataclasses import dataclass
from itertools import count
from typing import ClassVar
from urllib.parse import urlsplit

from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.formats import date_format

from controlled_vocabularies.models import ConceptScheme, Record
from controlled_vocabularies.predicates import PREDICATES, Namespaces

#: Never shown, as the hidden label exists to be searched and not read.
_HIDDEN_CURIES = frozenset({"skos:hiddenLabel", "rdf:type"})


class PropertyRows:
    """Build the property rows of a concept's or collection's own page.

    One row per predicate the record states, in the order of the predicate table and then
    any other predicate as stored. A link to a record or vocabulary held here is a link to
    its page. Each row is a dict of ``term``, ``term_uri`` and ``entries``, where an entry
    holds ``text`` and, for a link, ``uri``, ``href`` and ``identifier_id``.

    Args:
        record: The record to describe, with its vocabulary loaded.
        language: The language being read.
    """

    def __init__(self, record: Record, language: str) -> None:
        self.record = record
        self.scheme = record.scheme
        self.language = language
        self.identifier_ids = count()
        self.narrower = (
            self._narrower_uris() if record.type == Record.Type.CONCEPT else []
        )
        linked = {
            entry["@id"]
            for entries in record.data.values()
            for entry in entries
            if "@id" in entry
        } | set(self.narrower)
        self.records = {
            found.uri: found
            for found in Record.objects.filter(uri__in=linked).select_related("scheme")
        }
        self.schemes = {
            found.uri: found for found in ConceptScheme.objects.filter(uri__in=linked)
        }

    @staticmethod
    def in_reading_language(
        entries: list[dict], language: str, default_language: str
    ) -> list[dict]:
        """Pick the entries to show of a translatable predicate.

        Args:
            entries: Every entry stored under the predicate.
            language: The language being read.
            default_language: The vocabulary's default, used when there is no entry in ``language``.

        Returns:
            The entries in the reading language, else in the default language, else the
            ones that carry no language.
        """
        for wanted in (language, default_language):
            found = [
                e for e in entries if e.get("@language", "").lower() == wanted.lower()
            ]
            if found:
                return found
        return [entry for entry in entries if "@language" not in entry]

    def build(self) -> list[dict]:
        """Return the rows in display order.

        Returns:
            The type row, a row for each stated predicate, and the vocabulary row if the
            document does not state one.
        """
        stored = self.record.data
        curies = [*PREDICATES, *sorted(set(stored) - set(PREDICATES))]
        rows = [self._row("rdf:type", [{"text": self.record.type}])]
        for curie in curies:
            if curie in _HIDDEN_CURIES:
                continue
            entries = self._entries(curie)
            if entries:
                rows.append(self._row(curie, entries))
        if "skos:inScheme" not in stored:
            rows.append(self._row("skos:inScheme", [self._link(self.scheme.uri)]))
        return rows

    def _row(self, curie: str, entries: list[dict]) -> dict:
        """Build one row.

        Args:
            curie: The predicate.
            entries: The row's entries.

        Returns:
            The row.
        """
        # A hovered CURIE answers which URI it abbreviates; a key with no prefix is a URI already.
        return {"term": curie, "term_uri": Namespaces.expand(curie), "entries": entries}

    def _entries(self, curie: str) -> list[dict]:
        """Build the entries a predicate shows.

        Args:
            curie: The predicate.

        Returns:
            The entries to display, empty when there is nothing to show.
        """
        stored = self.record.values(curie)
        predicate = PREDICATES.get(curie)
        if predicate and predicate.translatable:
            stored = self.in_reading_language(
                stored, self.language, self.scheme.default_language
            )
        if curie == "skos:narrower":
            # A file usually states a hierarchy from the narrower side only.
            stated = {entry.get("@id") for entry in stored}
            stored = stored + [
                {"@id": uri} for uri in self.narrower if uri not in stated
            ]
        return [
            self._link(entry["@id"])
            if "@id" in entry
            else {"text": str(entry["@value"])}
            for entry in stored
        ]

    def _link(self, uri: str) -> dict:
        """Build an entry for a link, pointing at the page of a record held here.

        Args:
            uri: The URI linked to.

        Returns:
            The entry. A link to something not held here points at the URI itself when it is
            a web address, and is plain text otherwise.
        """
        entry = {"text": uri, "uri": uri, "href": None}
        found = self.records.get(uri)
        if found is not None:
            entry["text"] = f"{found.scheme.slug}:{found.slug}"
            if found.type == Record.Type.CONCEPT:
                route, kwarg = "concept-detail", "concept_slug"
            else:
                route, kwarg = "collection-detail", "collection_slug"
            entry["href"] = reverse(
                f"controlled_vocabularies_ui:{route}",
                kwargs={"slug": found.scheme.slug, kwarg: found.slug},
            )
        elif uri in self.schemes:
            entry["text"] = self.schemes[uri].display_label()
            entry["href"] = reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": self.schemes[uri].slug},
            )
        elif urlsplit(uri).scheme in ("http", "https"):
            entry["href"] = uri
        else:
            return {"text": uri}
        # Only a link has a hidden span for aria-describedby to name, and its id must be unique.
        entry["identifier_id"] = f"identifier-{next(self.identifier_ids)}"
        return entry

    def _narrower_uris(self) -> list[str]:
        """Return the URIs of the concepts that name this one as their broader concept."""
        candidates = Record.objects.filter(
            scheme=self.scheme, type=Record.Type.CONCEPT
        ).mentioning(self.record.uri)
        return [
            candidate.uri
            for candidate in candidates.order_by("pref_label", "pk")
            if self.record.uri in candidate.linked_uris("skos:broader")
        ]


@dataclass(frozen=True)
class PublicationDetails:
    """The publication details a vocabulary gives, as text.

    Attributes:
        publisher: Who published it, as a name or an address.
        creator: Who made it.
        license: Its licence, as an address or a name.
        version: Its version.
        modified: When it last changed, formatted when it is a date.
    """

    publisher: str
    creator: str
    license: str
    version: str
    modified: str

    CURIES: ClassVar[dict[str, str]] = {
        "publisher": "dcterms:publisher",
        "creator": "dcterms:creator",
        "license": "dcterms:license",
        "version": "owl:versionInfo",
        "modified": "dcterms:modified",
    }

    @classmethod
    def of(cls, scheme: ConceptScheme) -> "PublicationDetails":
        """Read a vocabulary's publication details.

        Args:
            scheme: The vocabulary.

        Returns:
            The details; an empty string stands for one the vocabulary does not give.
        """
        values = {name: scheme.first_value(curie) for name, curie in cls.CURIES.items()}
        try:
            modified = parse_date(values["modified"])
        except ValueError:
            modified = None
        if modified is not None:
            values["modified"] = date_format(modified)
        return cls(**values)
