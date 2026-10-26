"""Tests for controlled_vocabularies.models."""

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.utils import translation
from django.utils.functional import Promise

from controlled_vocabularies import conf
from controlled_vocabularies.models import (
    PREF_LABEL_MAX_LENGTH,
    ConceptScheme,
    Link,
    Record,
    validate_document,
)
from tests.factories import (
    ConceptSchemeFactory,
    LinkFactory,
    RecordFactory,
    SpecimenFactory,
    collection_with_members,
    labelled,
)

pytestmark = pytest.mark.django_db


class TestValidateDocument:
    @pytest.mark.parametrize(
        "document",
        [
            {},
            {"skos:prefLabel": [{"@value": "Granite", "@language": "en"}]},
            {"skos:notation": [{"@value": "GR-01"}]},
            {"dcterms:created": [{"@value": "2026-01-01", "@type": "xsd:date"}]},
            {"owl:versionInfo": [{"@value": 3}]},
            {"skos:broader": [{"@id": "https://example.org/x"}]},
            {
                "skosxl:prefLabel": [
                    {"skosxl:literalForm": [{"@value": "Granite", "@language": "en"}]}
                ]
            },
            {"skos:altLabel": []},
        ],
    )
    def test_a_well_formed_document_is_accepted(self, document):
        validate_document(document)

    @pytest.mark.parametrize("document", [[], "text", None, 3])
    def test_a_document_that_is_not_an_object_is_refused(self, document):
        with pytest.raises(ValidationError) as raised:
            validate_document(document)

        assert raised.value.code == "document_not_object"

    @pytest.mark.parametrize(
        "document",
        [
            {"skos:prefLabel": {"@value": "Granite"}},
            {"skos:prefLabel": "Granite"},
            {"skos:prefLabel": ["Granite"]},
            {"skos:prefLabel": [{"@language": "en"}]},
            {"skos:prefLabel": [{"@value": ["Granite"]}]},
            {"skos:prefLabel": [{"@value": "Granite", "@colour": "grey"}]},
            {"skos:prefLabel": [{"@value": "G", "@language": "en", "@type": "x"}]},
            {"skos:prefLabel": [{"@value": "Granite", "@language": 3}]},
            {"skos:broader": [{"@id": "https://example.org/x", "@language": "en"}]},
            {"skos:broader": [{"@id": 3}]},
            {"skosxl:prefLabel": [{"skosxl:literalForm": [{"@value": []}]}]},
        ],
    )
    def test_a_predicate_without_well_formed_entries_is_refused(self, document):
        with pytest.raises(ValidationError) as raised:
            validate_document(document)

        assert raised.value.code == "document_bad_entries"

    def test_a_stored_document_is_validated_by_full_clean(self):
        scheme = ConceptSchemeFactory.build(data={"skos:prefLabel": "Granite"})

        with pytest.raises(ValidationError) as raised:
            scheme.full_clean(exclude=["uri", "slug"])

        assert raised.value.error_dict["data"][0].code == "document_bad_entries"


class TestDocumentReaders:
    @pytest.fixture
    def record(self):
        return RecordFactory(
            data=labelled(
                "Granite",
                statements={
                    "skos:altLabel": [
                        {"@value": "Granit", "@language": "de"},
                        {"@value": "Plutonite"},
                    ],
                    "skos:notation": [{"@value": "GR-01"}],
                    "skos:broader": [
                        {"@id": "https://example.org/igneous"},
                        {"@id": "https://example.org/rock"},
                    ],
                    "dcterms:publisher": [{"@id": "https://example.org/pub"}],
                },
            )
        )

    def test_values_returns_the_entries_stored_under_a_predicate(self, record):
        assert record.values("skos:altLabel") == [
            {"@value": "Granit", "@language": "de"},
            {"@value": "Plutonite"},
        ]

    def test_values_of_an_absent_predicate_is_empty(self, record):
        assert record.values("skos:scopeNote") == []

    def test_label_returns_the_name_in_the_language_asked_for(self):
        record = RecordFactory(
            data={
                "skos:prefLabel": [
                    {"@value": "Granite", "@language": "en"},
                    {"@value": "Granit", "@language": "de"},
                ]
            }
        )

        assert record.label("de") == "Granit"

    def test_label_ignores_the_case_of_the_language_tag(self):
        record = RecordFactory(data=labelled("Granite", language="en-GB"))

        assert record.label("EN-gb") == "Granite"

    def test_label_is_none_when_the_language_has_no_name(self, record):
        assert record.label("fr") is None

    def test_a_vocabulary_is_named_by_its_title_when_it_has_no_preferred_label(self):
        scheme = ConceptSchemeFactory(
            data={"dcterms:title": [{"@value": "Rocks", "@language": "en"}]}
        )

        assert scheme.label("en") == "Rocks"

    def test_display_label_follows_the_active_language(self):
        record = RecordFactory(
            data={
                "skos:prefLabel": [
                    {"@value": "Granite", "@language": "en"},
                    {"@value": "Granit", "@language": "de"},
                ]
            }
        )

        with translation.override("de"):
            assert record.display_label() == "Granit"

    def test_display_label_falls_back_to_the_stored_preferred_label(self, record):
        with translation.override("fr"):
            assert record.display_label() == "Granite"

    def test_linked_uris_returns_the_links_in_stored_order(self, record):
        assert record.linked_uris("skos:broader") == [
            "https://example.org/igneous",
            "https://example.org/rock",
        ]

    def test_linked_uris_skips_literal_entries(self, record):
        assert record.linked_uris("skos:altLabel") == []

    def test_first_value_returns_a_literal_as_text(self, record):
        assert record.first_value("skos:notation") == "GR-01"

    def test_first_value_returns_a_link_as_its_uri(self, record):
        assert record.first_value("dcterms:publisher") == "https://example.org/pub"

    def test_first_value_of_an_absent_predicate_is_empty(self, record):
        assert record.first_value("dcterms:license") == ""

    def test_first_value_returns_a_number_as_text(self):
        record = RecordFactory(
            data=labelled("Granite", statements={"owl:versionInfo": [{"@value": 3}]})
        )

        assert record.first_value("owl:versionInfo") == "3"


class TestDerivedColumns:
    def test_pref_label_is_the_name_in_the_default_language(self):
        scheme = ConceptSchemeFactory(default_language="de")
        record = RecordFactory(
            scheme=scheme,
            data={
                "skos:prefLabel": [
                    {"@value": "Granite", "@language": "en"},
                    {"@value": "Granit", "@language": "de"},
                ]
            },
        )

        assert record.pref_label == "Granit"

    def test_pref_label_falls_back_to_the_first_name_in_any_language(self):
        record = RecordFactory(data=labelled("Granit", language="de"))

        assert record.pref_label == "Granit"

    def test_pref_label_is_empty_for_a_record_with_no_name(self):
        record = RecordFactory(data={})

        assert record.pref_label == ""

    def test_pref_label_is_cut_to_the_column(self):
        record = RecordFactory(data=labelled("x" * (PREF_LABEL_MAX_LENGTH + 20)))

        assert len(record.pref_label) == PREF_LABEL_MAX_LENGTH

    def test_a_vocabulary_keeps_its_pref_label_in_step_with_its_data(self):
        scheme = ConceptSchemeFactory()

        scheme.data = labelled("Minerals")
        scheme.save()

        assert ConceptScheme.objects.get(pk=scheme.pk).pref_label == "Minerals"

    def test_search_text_holds_every_preferred_alternative_and_hidden_label(self):
        record = RecordFactory(
            data=labelled(
                "Granite",
                statements={
                    "skos:altLabel": [{"@value": "Granit", "@language": "de"}],
                    "skos:hiddenLabel": [{"@value": "granyte"}],
                    "skos:definition": [{"@value": "A coarse rock."}],
                },
            )
        )

        assert record.search_text.split("\n") == ["Granite", "Granit", "granyte"]

    def test_a_save_changing_the_data_refreshes_pref_label_and_search_text(self):
        record = RecordFactory(label="Granite")

        record.data = labelled(
            "Basalt", statements={"skos:altLabel": [{"@value": "Trap"}]}
        )
        record.save()

        stored = Record.objects.get(pk=record.pk)
        assert stored.pref_label == "Basalt"
        assert stored.search_text == "Basalt\nTrap"

    def test_a_partial_save_of_the_data_refreshes_pref_label_and_search_text(self):
        record = RecordFactory(label="Granite")

        record.data = labelled(
            "Basalt", statements={"skos:altLabel": [{"@value": "Trap"}]}
        )
        record.save(update_fields=["data"])

        stored = Record.objects.get(pk=record.pk)
        assert stored.pref_label == "Basalt"
        assert stored.search_text == "Basalt\nTrap"

    def test_a_partial_save_of_the_data_refreshes_a_vocabularys_pref_label(self):
        scheme = ConceptSchemeFactory()

        scheme.data = labelled("Minerals")
        scheme.save(update_fields=["data"])

        assert ConceptScheme.objects.get(pk=scheme.pk).pref_label == "Minerals"


class TestIdentity:
    def test_a_record_authored_here_gets_a_uri_under_the_base_and_its_slugs(self):
        record = RecordFactory(label="Granite")

        expected = f"{conf.get_base_uri()}/{record.scheme.slug}/granite"
        assert record.uri == expected

    def test_a_collection_authored_here_gets_a_uri_under_a_collection_segment(self):
        collection = RecordFactory(label="Igneous", type=Record.Type.COLLECTION)

        expected = f"{conf.get_base_uri()}/{collection.scheme.slug}/collection/igneous"
        assert collection.uri == expected

    def test_a_vocabulary_authored_here_gets_a_uri_under_the_base(self):
        scheme = ConceptSchemeFactory(name="Rock types")

        assert scheme.uri == f"{conf.get_base_uri()}/rock-types"

    def test_the_slug_is_made_from_the_name(self):
        record = RecordFactory(label="Igneous Rock")

        assert record.slug == "igneous-rock"

    def test_a_name_with_no_slug_characters_still_gets_a_slug(self):
        record = RecordFactory(label="!!!")

        assert record.slug == "record"

    def test_the_uri_and_slug_survive_a_rename(self):
        record = RecordFactory(label="Granite")
        uri, slug = record.uri, record.slug

        record.data = labelled("Basalt")
        record.save()

        stored = Record.objects.get(pk=record.pk)
        assert (stored.uri, stored.slug) == (uri, slug)

    def test_a_vocabularys_uri_and_slug_survive_a_rename(self):
        scheme = ConceptSchemeFactory(name="Rocks")
        uri, slug = scheme.uri, scheme.slug

        scheme.data = labelled("Stones")
        scheme.save()

        stored = ConceptScheme.objects.get(pk=scheme.pk)
        assert (stored.uri, stored.slug) == (uri, slug)

    def test_a_supplied_uri_is_kept_verbatim(self):
        uri = "https://publisher.example/Vocab/Granite"

        record = RecordFactory(uri=uri)

        assert record.uri == uri

    def test_the_slug_of_a_supplied_uri_comes_from_its_last_path_segment(self):
        record = RecordFactory(uri="https://publisher.example/vocab/Granite-Rock")

        assert record.slug == "granite-rock"

    def test_a_trailing_slash_on_a_supplied_uri_is_ignored_for_the_slug(self):
        record = RecordFactory(uri="https://publisher.example/vocab/basalt/")

        assert record.slug == "basalt"

    def test_the_slug_of_a_supplied_uri_prefers_its_fragment(self):
        record = RecordFactory(uri="https://publisher.example/vocab#gabbro")

        assert record.slug == "gabbro"

    def test_a_supplied_slug_is_kept(self):
        record = RecordFactory(slug="custom-slug", label="Granite")

        assert record.slug == "custom-slug"

    def test_records_with_the_same_name_get_numbered_slugs_within_a_vocabulary(self):
        scheme = ConceptSchemeFactory()

        slugs = [RecordFactory(scheme=scheme, label="Granite").slug for _ in range(3)]

        assert slugs == ["granite", "granite-2", "granite-3"]

    def test_records_with_the_same_name_may_share_a_slug_across_vocabularies(self):
        first = RecordFactory(label="Granite")
        second = RecordFactory(label="Granite")

        assert first.slug == second.slug == "granite"

    def test_a_record_does_not_clash_with_itself_when_saved_again(self):
        record = RecordFactory(uri="https://publisher.example/vocab/granite")

        record.save()

        assert record.slug == "granite"

    def test_vocabularies_with_the_same_name_get_numbered_slugs(self):
        slugs = [ConceptSchemeFactory(name="Rocks").slug for _ in range(3)]

        assert slugs == ["rocks", "rocks-2", "rocks-3"]


class TestLink:
    def test_it_names_the_source_the_predicate_and_the_target(self):
        link = LinkFactory(predicate="skos:related", target="https://example.org/x")

        text = str(link)

        assert link.source.uri in text
        assert "skos:related" in text
        assert "https://example.org/x" in text


class TestRecordQuerySet:
    def test_mentioning_finds_a_record_linking_to_the_uri(self):
        target = RecordFactory()
        linking = RecordFactory(
            data=labelled("Child", statements={"skos:broader": [{"@id": target.uri}]})
        )

        assert list(Record.objects.mentioning(target.uri)) == [linking]

    def test_mentioning_leaves_out_records_that_do_not_hold_the_uri(self):
        target = RecordFactory()
        RecordFactory()

        assert not Record.objects.mentioning(target.uri).exists()

    def test_mentioning_matches_a_uri_that_needs_escaping_in_json(self):
        uri = 'https://example.org/a"b\\c'
        linking = RecordFactory(
            data=labelled("Child", statements={"skos:broader": [{"@id": uri}]})
        )

        assert list(Record.objects.mentioning(uri)) == [linking]

    def test_mentioning_matches_a_uri_with_non_ascii_characters(self):
        uri = "https://example.org/géologie/granit"
        linking = RecordFactory(
            data=labelled("Child", statements={"skos:broader": [{"@id": uri}]})
        )

        assert list(Record.objects.mentioning(uri)) == [linking]


class TestRecord:
    def test_default_language_is_the_vocabularys(self):
        record = RecordFactory(scheme=ConceptSchemeFactory(default_language="de"))

        assert record.default_language == "de"

    @pytest.mark.parametrize(
        ("record_type", "expected"),
        [
            (Record.Type.CONCEPT, False),
            (Record.Type.COLLECTION, True),
            (Record.Type.ORDERED_COLLECTION, True),
        ],
    )
    def test_is_collection_is_true_for_both_kinds_of_collection(
        self, record_type, expected
    ):
        record = RecordFactory(type=record_type)

        assert record.is_collection is expected

    def test_str_of_a_record_is_its_name(self):
        record = RecordFactory(label="Granite")

        assert str(record) == "Granite"

    def test_str_of_a_record_with_no_name_is_its_uri(self):
        record = RecordFactory(data={})

        assert str(record) == record.uri

    def test_str_of_a_vocabulary_is_its_name(self):
        scheme = ConceptSchemeFactory(name="Rock types")

        assert str(scheme) == "Rock types"

    def test_str_of_a_vocabulary_with_no_name_is_its_uri(self):
        scheme = ConceptSchemeFactory(data={})

        assert str(scheme) == scheme.uri

    def test_member_uris_of_a_collection_are_its_members(self):
        collection, members = collection_with_members()

        assert collection.member_uris() == [member.uri for member in members]

    def test_member_uris_of_an_ordered_collection_keep_their_sequence(self):
        collection, members = collection_with_members(
            labels=("Third", "First", "Second"), ordered=True
        )

        assert collection.member_uris() == [member.uri for member in members]

    def test_a_member_stated_both_in_sequence_and_as_a_member_is_listed_once(self):
        first, second = "https://example.org/first", "https://example.org/second"
        collection = RecordFactory(
            type=Record.Type.ORDERED_COLLECTION,
            data=labelled(
                "Both",
                statements={
                    "skos:member": [{"@id": first}, {"@id": second}],
                    "skos:memberList": [{"@id": second}, {"@id": first}],
                },
            ),
        )

        assert collection.member_uris() == [second, first]

    def test_member_uris_of_a_concept_is_empty(self):
        assert RecordFactory().member_uris() == []

    def test_deleting_a_vocabulary_deletes_its_records(self):
        record = RecordFactory()

        record.scheme.delete()

        assert not Record.objects.filter(pk=record.pk).exists()


class TestConsumingModelProtection:
    def test_a_record_a_consuming_model_references_cannot_be_deleted(self):
        specimen = SpecimenFactory()

        with pytest.raises(ProtectedError):
            specimen.rock_type.delete()

    def test_a_record_nothing_references_can_be_deleted(self):
        record = RecordFactory()

        record.delete()

        assert not Record.objects.filter(pk=record.pk).exists()


class TestFieldMetadata:
    @pytest.mark.parametrize("model", [ConceptScheme, Record, Link])
    def test_every_field_has_a_translatable_verbose_name_and_help_text(self, model):
        fields = [
            field
            for field in model._meta.concrete_fields
            if field.editable and not field.auto_created
        ]

        assert fields
        for field in fields:
            assert isinstance(field.verbose_name, Promise), field.name
            assert isinstance(field.help_text, Promise), field.name
            assert field.help_text, field.name
