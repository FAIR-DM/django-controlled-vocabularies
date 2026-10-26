"""Tests for controlled_vocabularies.ui.rows."""

import datetime

import pytest
from django.urls import reverse
from django.utils.formats import date_format

from controlled_vocabularies.models import Record
from controlled_vocabularies.ui.rows import PropertyRows, PublicationDetails
from tests.factories import (
    ConceptSchemeFactory,
    RecordFactory,
    collection_with_members,
    labelled,
)


def text(value, language=None):
    """Return a literal entry, tagged with a language when one is given.

    Args:
        value: The literal.
        language: The language tag, or None for an untagged literal.

    Returns:
        The entry.
    """
    entry = {"@value": value}
    if language:
        entry["@language"] = language
    return entry


def terms(rows):
    """Return the predicate each row is for, in order.

    Args:
        rows: The rows built for a record.

    Returns:
        The terms.
    """
    return [row["term"] for row in rows]


def row_for(rows, term):
    """Return the row for one predicate.

    Args:
        rows: The rows built for a record.
        term: The predicate.

    Returns:
        The row.
    """
    return next(row for row in rows if row["term"] == term)


@pytest.mark.django_db
class TestPropertyRowsForABareConcept:
    def test_a_bare_concept_yields_exactly_type_preferred_label_and_vocabulary(self):
        concept = RecordFactory(label="Granite")

        rows = PropertyRows(concept, "en").build()

        assert terms(rows) == ["rdf:type", "skos:prefLabel", "skos:inScheme"]

    def test_the_type_row_carries_the_records_type_as_plain_text(self):
        concept = RecordFactory()

        rows = PropertyRows(concept, "en").build()

        assert rows[0]["entries"] == [{"text": Record.Type.CONCEPT}]

    def test_each_row_discloses_the_uri_its_term_abbreviates(self):
        concept = RecordFactory()

        rows = PropertyRows(concept, "en").build()

        assert row_for(rows, "rdf:type")["term_uri"] == (
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        )
        assert row_for(rows, "skos:prefLabel")["term_uri"] == (
            "http://www.w3.org/2004/02/skos/core#prefLabel"
        )


@pytest.mark.django_db
class TestPropertyRowsOrder:
    def test_known_predicates_come_in_the_table_order_then_the_others_as_stored(self):
        scheme = ConceptSchemeFactory()
        parent = RecordFactory(scheme=scheme, label="Igneous rock")
        other = RecordFactory(scheme=scheme, label="Basalt")
        # Stated out of order on purpose, so the order seen is the table's.
        concept = RecordFactory(
            scheme=scheme,
            data=labelled(
                "Granite",
                statements={
                    "http://example.org/zeta": [text("z")],
                    "skos:related": [{"@id": other.uri}],
                    "skos:scopeNote": [text("Used for building stone.", "en")],
                    "skos:broader": [{"@id": parent.uri}],
                    "dcterms:source": [text("Field survey")],
                    "skos:definition": [text("A coarse-grained igneous rock.", "en")],
                    "skos:altLabel": [text("granitic rock", "en")],
                },
            ),
        )
        RecordFactory(
            scheme=scheme,
            data=labelled(
                "Pink granite", statements={"skos:broader": [{"@id": concept.uri}]}
            ),
        )

        rows = PropertyRows(concept, "en").build()

        assert terms(rows) == [
            "rdf:type",
            "skos:prefLabel",
            "skos:altLabel",
            "skos:definition",
            "skos:scopeNote",
            "skos:broader",
            "skos:narrower",
            "skos:related",
            "dcterms:source",
            "http://example.org/zeta",
            "skos:inScheme",
        ]

    def test_a_full_uri_predicate_discloses_itself(self):
        concept = RecordFactory(
            data=labelled(
                "Granite", statements={"http://example.org/zeta": [text("z")]}
            )
        )

        rows = PropertyRows(concept, "en").build()

        assert row_for(rows, "http://example.org/zeta")["term_uri"] == (
            "http://example.org/zeta"
        )

    def test_a_hidden_label_contributes_no_row(self):
        concept = RecordFactory(
            data=labelled(
                "Granite", statements={"skos:hiddenLabel": [text("granate", "en")]}
            )
        )

        rows = PropertyRows(concept, "en").build()

        assert "skos:hiddenLabel" not in terms(rows)

    def test_a_stored_type_statement_is_not_shown_beside_the_type_row(self):
        concept = RecordFactory(
            data=labelled("Granite", statements={"rdf:type": [{"@id": "skos:Concept"}]})
        )

        rows = PropertyRows(concept, "en").build()

        assert terms(rows).count("rdf:type") == 1

    def test_a_vocabulary_the_record_states_is_not_added_a_second_time(self):
        scheme = ConceptSchemeFactory()
        concept = RecordFactory(
            scheme=scheme,
            data=labelled(
                "Granite", statements={"skos:inScheme": [{"@id": scheme.uri}]}
            ),
        )

        rows = PropertyRows(concept, "en").build()

        assert terms(rows).count("skos:inScheme") == 1


@pytest.mark.django_db
class TestPropertyRowsLinks:
    def test_a_link_to_a_record_held_here_points_at_its_page(self):
        parent = RecordFactory(label="Igneous rock")
        concept = RecordFactory(
            scheme=parent.scheme,
            data=labelled(
                "Granite", statements={"skos:broader": [{"@id": parent.uri}]}
            ),
        )

        rows = PropertyRows(concept, "en").build()

        (entry,) = row_for(rows, "skos:broader")["entries"]
        assert entry["text"] == f"{parent.scheme.slug}:{parent.slug}"
        assert entry["uri"] == parent.uri
        assert entry["href"] == reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": parent.scheme.slug, "concept_slug": parent.slug},
        )

    def test_a_link_to_a_collection_points_at_the_collections_page(self):
        scheme = ConceptSchemeFactory()
        collection, (member,) = collection_with_members(
            scheme=scheme, labels=("Granite",)
        )

        rows = PropertyRows(collection, "en").build()

        (entry,) = row_for(rows, "skos:member")["entries"]
        assert entry["href"] == reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": scheme.slug, "concept_slug": member.slug},
        )
        concept = RecordFactory(
            scheme=scheme,
            data=labelled(
                "Granite 2", statements={"skos:related": [{"@id": collection.uri}]}
            ),
        )
        (link,) = row_for(PropertyRows(concept, "en").build(), "skos:related")[
            "entries"
        ]
        assert link["href"] == reverse(
            "controlled_vocabularies_ui:collection-detail",
            kwargs={"slug": scheme.slug, "collection_slug": collection.slug},
        )

    def test_the_vocabulary_row_links_to_the_vocabularys_own_page(self):
        concept = RecordFactory(label="Granite")

        rows = PropertyRows(concept, "en").build()

        (entry,) = row_for(rows, "skos:inScheme")["entries"]
        assert entry["text"] == concept.scheme.display_label()
        assert entry["uri"] == concept.scheme.uri
        assert entry["href"] == reverse(
            "controlled_vocabularies_ui:vocabulary-detail",
            kwargs={"slug": concept.scheme.slug},
        )

    def test_a_link_to_a_web_address_held_elsewhere_points_at_that_address(self):
        concept = RecordFactory(
            data=labelled(
                "Granite",
                statements={
                    "skos:exactMatch": [{"@id": "https://other.example.org/granite"}]
                },
            )
        )

        rows = PropertyRows(concept, "en").build()

        (entry,) = row_for(rows, "skos:exactMatch")["entries"]
        assert entry["text"] == "https://other.example.org/granite"
        assert entry["href"] == "https://other.example.org/granite"

    def test_a_link_to_something_that_is_not_a_web_address_is_plain_text(self):
        concept = RecordFactory(
            data=labelled(
                "Granite",
                statements={"skos:exactMatch": [{"@id": "urn:isbn:0451450523"}]},
            )
        )

        rows = PropertyRows(concept, "en").build()

        assert row_for(rows, "skos:exactMatch")["entries"] == [
            {"text": "urn:isbn:0451450523"}
        ]

    def test_each_link_on_a_page_gets_an_identifier_id_of_its_own(self):
        scheme = ConceptSchemeFactory()
        broader = RecordFactory(scheme=scheme, label="Igneous rock")
        related = RecordFactory(scheme=scheme, label="Basalt")
        concept = RecordFactory(
            scheme=scheme,
            data=labelled(
                "Granite",
                statements={
                    "skos:broader": [{"@id": broader.uri}],
                    "skos:related": [{"@id": related.uri}],
                },
            ),
        )

        rows = PropertyRows(concept, "en").build()

        ids = [
            entry["identifier_id"]
            for row in rows
            for entry in row["entries"]
            if "identifier_id" in entry
        ]
        assert len(ids) == 3
        assert len(set(ids)) == 3


@pytest.mark.django_db
class TestPropertyRowsInferredLinks:
    def test_a_concept_another_states_as_its_broader_shows_it_as_narrower(self):
        parent = RecordFactory(label="Igneous rock")
        child_one = RecordFactory(
            scheme=parent.scheme,
            data=labelled(
                "Granite", statements={"skos:broader": [{"@id": parent.uri}]}
            ),
        )
        child_two = RecordFactory(
            scheme=parent.scheme,
            data=labelled("Basalt", statements={"skos:broader": [{"@id": parent.uri}]}),
        )

        rows = PropertyRows(parent, "en").build()

        assert [
            entry["uri"] for entry in row_for(rows, "skos:narrower")["entries"]
        ] == [
            child_two.uri,
            child_one.uri,
        ]

    def test_a_concept_another_states_as_its_narrower_shows_it_as_broader(self):
        child = RecordFactory(label="Granite")
        parent = RecordFactory(
            scheme=child.scheme,
            data=labelled(
                "Igneous rock", statements={"skos:narrower": [{"@id": child.uri}]}
            ),
        )

        rows = PropertyRows(child, "en").build()

        assert [entry["uri"] for entry in row_for(rows, "skos:broader")["entries"]] == [
            parent.uri
        ]

    def test_a_concept_another_states_as_related_shows_it_as_related_too(self):
        right = RecordFactory(label="Basalt")
        RecordFactory(
            scheme=right.scheme,
            data=labelled("Granite", statements={"skos:related": [{"@id": right.uri}]}),
        )

        rows = PropertyRows(right, "en").build()

        assert len(row_for(rows, "skos:related")["entries"]) == 1

    def test_a_link_stated_from_both_ends_is_shown_once(self):
        parent = RecordFactory(label="Igneous rock")
        child = RecordFactory(
            scheme=parent.scheme,
            data=labelled(
                "Granite", statements={"skos:broader": [{"@id": parent.uri}]}
            ),
        )
        parent.data = labelled(
            "Igneous rock", statements={"skos:narrower": [{"@id": child.uri}]}
        )
        parent.save()

        rows = PropertyRows(parent, "en").build()

        assert len(row_for(rows, "skos:narrower")["entries"]) == 1

    def test_a_concept_of_another_vocabulary_is_not_inferred(self):
        parent = RecordFactory(label="Igneous rock")
        RecordFactory(
            data=labelled("Granite", statements={"skos:broader": [{"@id": parent.uri}]})
        )

        rows = PropertyRows(parent, "en").build()

        assert "skos:narrower" not in terms(rows)

    def test_a_collection_shows_no_inferred_links(self):
        scheme = ConceptSchemeFactory()
        collection, (member,) = collection_with_members(
            scheme=scheme, labels=("Granite",)
        )
        RecordFactory(
            scheme=scheme,
            data=labelled(
                "Basalt", statements={"skos:broader": [{"@id": collection.uri}]}
            ),
        )

        rows = PropertyRows(collection, "en").build()

        assert "skos:narrower" not in terms(rows)


@pytest.mark.django_db
class TestPropertyRowsOfACollection:
    def test_an_unordered_collection_has_one_row_holding_every_member(self):
        collection, members = collection_with_members(
            labels=("Granite", "Basalt", "Gabbro")
        )

        rows = PropertyRows(collection, "en").build()

        assert "skos:memberList" not in terms(rows)
        assert [entry["uri"] for entry in row_for(rows, "skos:member")["entries"]] == [
            member.uri for member in members
        ]

    def test_an_ordered_collection_has_one_row_holding_its_members_in_sequence(self):
        collection, members = collection_with_members(
            labels=("Granite", "Basalt", "Gabbro"), ordered=True
        )

        rows = PropertyRows(collection, "en").build()

        assert "skos:member" not in terms(rows)
        assert [
            entry["uri"] for entry in row_for(rows, "skos:memberList")["entries"]
        ] == [member.uri for member in members]

    def test_the_type_row_names_the_kind_of_collection(self):
        ordered, _ = collection_with_members(ordered=True)

        rows = PropertyRows(ordered, "en").build()

        assert rows[0]["entries"] == [{"text": Record.Type.ORDERED_COLLECTION}]


class TestInReadingLanguage:
    ENTRIES = [text("Granite", "en"), text("Granit", "de"), text("Granito", "es")]

    def test_the_entries_in_the_reading_language_are_chosen(self):
        chosen = PropertyRows.in_reading_language(self.ENTRIES, "de", "en")

        assert chosen == [text("Granit", "de")]

    def test_the_reading_language_is_matched_ignoring_case(self):
        chosen = PropertyRows.in_reading_language([text("Granit", "DE")], "de", "en")

        assert chosen == [text("Granit", "DE")]

    def test_the_default_language_is_used_when_the_reading_language_has_none(self):
        chosen = PropertyRows.in_reading_language(self.ENTRIES, "fr", "en")

        assert chosen == [text("Granite", "en")]

    def test_entries_without_a_language_are_used_when_neither_language_has_any(self):
        entries = [text("Granite"), text("Granito", "es")]

        chosen = PropertyRows.in_reading_language(entries, "fr", "en")

        assert chosen == [text("Granite")]

    def test_nothing_is_chosen_when_no_entry_fits(self):
        assert PropertyRows.in_reading_language(self.ENTRIES, "fr", "it") == []


@pytest.mark.django_db
class TestPropertyRowsLanguage:
    def test_a_translatable_value_shows_only_the_reading_languages_entries(self):
        concept = RecordFactory(
            data={
                "skos:prefLabel": [
                    text("Granite", "en"),
                    text("Kristallgestein", "de"),
                ],
                "skos:altLabel": [
                    text("granite stone", "en"),
                    text("Granitstein", "de"),
                ],
            }
        )

        rows = PropertyRows(concept, "de").build()

        assert row_for(rows, "skos:prefLabel")["entries"] == [
            {"text": "Kristallgestein"}
        ]
        assert row_for(rows, "skos:altLabel")["entries"] == [{"text": "Granitstein"}]

    def test_a_value_missing_in_the_reading_language_falls_back_to_the_default(self):
        concept = RecordFactory(label="Granite")

        rows = PropertyRows(concept, "de").build()

        assert row_for(rows, "skos:prefLabel")["entries"] == [{"text": "Granite"}]

    def test_a_value_that_is_not_translatable_shows_every_entry(self):
        concept = RecordFactory(
            data=labelled(
                "Granite",
                statements={"skos:notation": [text("GR-01"), text("GR-02", "de")]},
            )
        )

        rows = PropertyRows(concept, "en").build()

        assert row_for(rows, "skos:notation")["entries"] == [
            {"text": "GR-01"},
            {"text": "GR-02"},
        ]


@pytest.mark.django_db
class TestPublicationDetails:
    def test_each_detail_is_read_from_its_statement(self):
        scheme = ConceptSchemeFactory(
            data=labelled(
                "Rocks",
                statements={
                    "dcterms:publisher": [text("Gem Survey")],
                    "dcterms:creator": [text("A. Lapidary")],
                    "dcterms:license": [{"@id": "https://example.org/licence"}],
                    "owl:versionInfo": [text("2.1")],
                },
            )
        )

        details = PublicationDetails.of(scheme)

        assert details.publisher == "Gem Survey"
        assert details.creator == "A. Lapidary"
        assert details.license == "https://example.org/licence"
        assert details.version == "2.1"

    def test_a_vocabulary_giving_none_has_an_empty_string_for_each(self):
        details = PublicationDetails.of(ConceptSchemeFactory())

        assert details == PublicationDetails("", "", "", "", "")

    def test_a_modified_date_is_formatted(self):
        scheme = ConceptSchemeFactory(
            data=labelled(
                "Rocks", statements={"dcterms:modified": [text("2026-03-14")]}
            )
        )

        details = PublicationDetails.of(scheme)

        assert details.modified == date_format(datetime.date(2026, 3, 14))

    @pytest.mark.parametrize("stated", ["last spring", "2026-02-30"])
    def test_a_modified_value_that_is_not_a_date_is_kept_as_stated(self, stated):
        scheme = ConceptSchemeFactory(
            data=labelled("Rocks", statements={"dcterms:modified": [text(stated)]})
        )

        details = PublicationDetails.of(scheme)

        assert details.modified == stated
