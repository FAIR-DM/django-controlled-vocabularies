"""Tests for controlled_vocabularies.models."""

import pytest
import rdflib
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.utils import translation
from django.utils.functional import Promise
from rdflib.namespace import RDF, SKOS

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
    concept_below,
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


class TestRecordLinks:
    def stored(self, record):
        return sorted(record.links.values_list("predicate", "target"))

    def test_saving_gives_one_row_per_top_level_link_entry(self):
        record = RecordFactory(
            data=labelled(
                "Child",
                statements={
                    "skos:broader": [{"@id": "https://example.org/a"}],
                    "skos:related": [
                        {"@id": "https://example.org/b"},
                        {"@id": "https://example.org/c"},
                    ],
                },
            )
        )

        assert self.stored(record) == [
            ("skos:broader", "https://example.org/a"),
            ("skos:related", "https://example.org/b"),
            ("skos:related", "https://example.org/c"),
        ]

    def test_a_predicate_written_as_a_full_uri_is_stored_as_written(self):
        predicate = "https://example.org/vocab#sameAs"
        record = RecordFactory(
            data=labelled(
                "X", statements={predicate: [{"@id": "https://example.org/a"}]}
            )
        )

        assert self.stored(record) == [(predicate, "https://example.org/a")]

    def test_a_literal_entry_gives_no_row(self):
        record = RecordFactory(
            data=labelled(
                "X", statements={"skos:note": [{"@value": "https://example.org/a"}]}
            )
        )

        assert self.stored(record) == []

    def test_a_link_inside_an_embedded_node_gives_no_row(self):
        record = RecordFactory(
            data=labelled(
                "X",
                statements={
                    "skosxl:prefLabel": [
                        {"skosxl:literalForm": [{"@id": "https://example.org/a"}]}
                    ]
                },
            )
        )

        assert self.stored(record) == []

    def test_a_link_stated_twice_gives_two_rows(self):
        record = RecordFactory(
            data=labelled(
                "X",
                statements={
                    "skos:related": [
                        {"@id": "https://example.org/a"},
                        {"@id": "https://example.org/a"},
                    ]
                },
            )
        )

        assert self.stored(record) == [("skos:related", "https://example.org/a")] * 2

    def test_saving_a_changed_document_replaces_the_rows(self):
        record = RecordFactory(
            data=labelled(
                "X", statements={"skos:broader": [{"@id": "https://example.org/old"}]}
            )
        )

        record.data = labelled(
            "X", statements={"skos:related": [{"@id": "https://example.org/new"}]}
        )
        record.save()

        assert self.stored(record) == [("skos:related", "https://example.org/new")]

    def test_saving_again_leaves_one_set_of_rows(self):
        record = RecordFactory(
            data=labelled(
                "X", statements={"skos:broader": [{"@id": "https://example.org/a"}]}
            )
        )

        record.save()

        assert Link.objects.filter(source=record).count() == 1

    def test_a_save_that_leaves_data_out_keeps_the_rows(self):
        record = RecordFactory(
            data=labelled(
                "X", statements={"skos:broader": [{"@id": "https://example.org/a"}]}
            )
        )

        record.data = labelled("X")
        record.type = Record.Type.COLLECTION
        record.save(update_fields=["type"])

        assert self.stored(record) == [("skos:broader", "https://example.org/a")]

    def test_a_save_that_includes_data_replaces_the_rows(self):
        record = RecordFactory(
            data=labelled(
                "X", statements={"skos:broader": [{"@id": "https://example.org/a"}]}
            )
        )

        record.data = labelled("X")
        record.save(update_fields=["data"])

        assert self.stored(record) == []

    def test_refresh_links_brings_rows_in_line_with_a_document_written_by_update(
        self,
    ):
        record = RecordFactory(
            data=labelled(
                "X", statements={"skos:broader": [{"@id": "https://example.org/old"}]}
            )
        )
        document = labelled(
            "X", statements={"skos:broader": [{"@id": "https://example.org/new"}]}
        )
        Record.objects.filter(pk=record.pk).update(data=document)
        record.refresh_from_db()

        record.refresh_links()

        assert self.stored(record) == [("skos:broader", "https://example.org/new")]

    def test_deleting_a_record_deletes_its_rows(self):
        record = RecordFactory(
            data=labelled(
                "X", statements={"skos:broader": [{"@id": "https://example.org/a"}]}
            )
        )

        record.delete()

        assert not Link.objects.exists()


class TestRecordQuerySet:
    def test_linking_to_finds_a_record_linking_to_the_uri(self):
        target = RecordFactory()
        linking = RecordFactory(
            data=labelled("Child", statements={"skos:broader": [{"@id": target.uri}]})
        )

        assert list(Record.objects.linking_to(target.uri)) == [linking]

    def test_linking_to_leaves_out_records_that_do_not_link_to_the_uri(self):
        target = RecordFactory()
        RecordFactory()

        assert not Record.objects.linking_to(target.uri).exists()

    def test_linking_to_leaves_out_a_record_holding_the_uri_only_as_a_literal(self):
        target = RecordFactory()
        RecordFactory(
            data=labelled("Note", statements={"skos:note": [{"@value": target.uri}]})
        )

        assert not Record.objects.linking_to(target.uri).exists()

    def test_linking_to_with_predicates_leaves_out_a_link_under_another_predicate(self):
        target = RecordFactory()
        related = RecordFactory(
            data=labelled("Rel", statements={"skos:related": [{"@id": target.uri}]})
        )
        RecordFactory(
            data=labelled("Child", statements={"skos:broader": [{"@id": target.uri}]})
        )

        found = Record.objects.linking_to(target.uri, "skos:related", "skos:member")

        assert list(found) == [related]

    def test_linking_to_lists_a_record_once_however_often_it_links(self):
        target = RecordFactory()
        linking = RecordFactory(
            data=labelled(
                "Child",
                statements={
                    "skos:broader": [{"@id": target.uri}, {"@id": target.uri}],
                    "skos:related": [{"@id": target.uri}],
                },
            )
        )

        assert list(Record.objects.linking_to(target.uri)) == [linking]


class TestRecordQuerySetInBranch:
    def test_in_branch_returns_the_root_and_every_concept_below_it_at_any_depth(self):
        scheme = ConceptSchemeFactory()
        top = RecordFactory(scheme=scheme)
        root = concept_below(top, "Igneous")
        child = concept_below(root, "Volcanic")
        grandchild = concept_below(child, "Basalt")

        found = Record.objects.in_branch(scheme.uri, root.uri)

        assert set(found) == {root, child, grandchild}

    def test_in_branch_follows_a_link_stated_from_either_side_at_every_step(self):
        scheme = ConceptSchemeFactory()
        root = RecordFactory(scheme=scheme)
        child = concept_below(root, "Volcanic", stated_by="parent")
        grandchild = concept_below(child, "Basalt")
        great_grandchild = concept_below(grandchild, "Scoria", stated_by="parent")

        found = Record.objects.in_branch(scheme.uri, root.uri)

        assert set(found) == {root, child, grandchild, great_grandchild}

    def test_in_branch_leaves_out_the_roots_broader_concept_and_its_siblings(self):
        scheme = ConceptSchemeFactory()
        top = RecordFactory(scheme=scheme)
        root = concept_below(top, "Igneous")
        concept_below(top, "Sedimentary")

        found = Record.objects.in_branch(scheme.uri, root.uri)

        assert set(found) == {root}

    def test_in_branch_ends_on_a_cycle_and_returns_each_record_once(self):
        scheme = ConceptSchemeFactory()
        root = RecordFactory(scheme=scheme)
        child = concept_below(root, "Volcanic")
        root.data["skos:broader"] = [{"@id": child.uri}]
        root.save()

        found = list(Record.objects.in_branch(scheme.uri, root.uri))

        assert sorted(record.pk for record in found) == sorted([root.pk, child.pk])

    def test_in_branch_does_not_cross_into_another_vocabulary(self):
        scheme = ConceptSchemeFactory()
        root = RecordFactory(scheme=scheme)
        foreign = concept_below(root, "Quartz", scheme=ConceptSchemeFactory())
        below_foreign = concept_below(foreign, "Alpha quartz")
        local = concept_below(root, "Basalt")

        found = Record.objects.in_branch(scheme.uri, root.uri)

        assert set(found) == {root, local}
        assert not {foreign, below_foreign} & set(found)

    def test_in_branch_is_empty_when_the_root_is_in_another_vocabulary(self):
        scheme = ConceptSchemeFactory()
        foreign = RecordFactory(scheme=ConceptSchemeFactory())

        assert not Record.objects.in_branch(scheme.uri, foreign.uri).exists()

    def test_in_branch_is_empty_when_no_record_has_the_root_uri(self):
        scheme = ConceptSchemeFactory()

        assert not Record.objects.in_branch(
            scheme.uri, "https://example.org/x"
        ).exists()

    def test_in_branch_chains_with_other_filters(self):
        scheme = ConceptSchemeFactory()
        root = RecordFactory(scheme=scheme)
        child = concept_below(root, "Volcanic")

        found = Record.objects.filter(pk=child.pk).in_branch(scheme.uri, root.uri)

        assert list(found) == [child]


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


class TestToGraph:
    def test_vocabulary_without_a_stated_type_is_a_concept_scheme(self):
        scheme = ConceptSchemeFactory()

        graph = scheme.to_graph()

        assert (rdflib.URIRef(scheme.uri), RDF.type, SKOS.ConceptScheme) in graph

    def test_ordered_collection_states_its_type(self):
        collection, _members = collection_with_members(ordered=True)

        graph = collection.to_graph()

        assert (
            rdflib.URIRef(collection.uri),
            RDF.type,
            SKOS.OrderedCollection,
        ) in graph

    def test_concept_without_a_stated_type_is_a_concept(self):
        concept = RecordFactory()

        graph = concept.to_graph()

        assert (rdflib.URIRef(concept.uri), RDF.type, SKOS.Concept) in graph

    @pytest.mark.parametrize("make", [ConceptSchemeFactory, RecordFactory])
    def test_subject_is_the_rows_uri(self, make):
        row = make()

        assert set(row.to_graph().subjects()) == {rdflib.URIRef(row.uri)}

    def test_graph_holds_only_the_rows_own_statements(self):
        scheme = ConceptSchemeFactory()
        parent = RecordFactory(scheme=scheme)
        child = RecordFactory(
            scheme=scheme,
            data=labelled("Child", statements={"skos:broader": [{"@id": parent.uri}]}),
        )

        graph = child.to_graph()

        assert set(graph.subjects()) == {rdflib.URIRef(child.uri)}

    def test_rdf_class_of_a_record_follows_its_type_column(self):
        record = RecordFactory(type=Record.Type.COLLECTION)

        assert record.rdf_class == "skos:Collection"
