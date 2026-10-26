"""Tests for controlled_vocabularies.fields."""

import inspect
import warnings
from pathlib import Path

import pytest
from django import forms
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection, models, transaction
from django.db.models import CASCADE, PROTECT, ProtectedError, Q
from django.test.utils import CaptureQueriesContext, isolate_apps
from django.utils import translation
from django.utils.functional import Promise
from django.utils.module_loading import import_string

from controlled_vocabularies import fields as fields_module
from controlled_vocabularies.fields import (
    ConceptField,
    ConceptFieldMixin,
    ConceptsField,
)
from controlled_vocabularies.models import ConceptScheme, Record
from tests.factories import (
    ArtifactFactory,
    BoreholeFactory,
    ConceptSchemeFactory,
    DepositFactory,
    DrillCoreFactory,
    FieldNoteFactory,
    OutcropFactory,
    PhotographFactory,
    RecordFactory,
    RockSampleFactory,
    SampleFactory,
    SketchFactory,
    SpecimenFactory,
    SurveyFactory,
    collection_with_members,
)
from tests.i18n_sweep import visit_fields_checks_source
from tests.testapp.models import (
    Artifact,
    Borehole,
    CoreSample,
    Deposit,
    FieldNote,
    Outcrop,
    Photograph,
    RockSample,
    Sample,
    Sketch,
    Specimen,
    Survey,
)


def admitted_by(field):
    """Return the records a field's restriction admits, read from the database now.

    Args:
        field: A concept field.

    Returns:
        The set of admitted records.
    """
    return set(Record.objects.complex_filter(field.get_limit_choices_to()))


def bilingual(english, german):
    """Return a document naming its subject in English and in German.

    Args:
        english: The English preferred label.
        german: The German preferred label.

    Returns:
        The document.
    """
    return {
        "skos:prefLabel": [
            {"@value": english, "@language": "en"},
            {"@value": german, "@language": "de"},
        ]
    }


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedVocabularyContract:
    def test_inherits_the_shared_contract(self, field_class):
        assert issubclass(field_class, ConceptFieldMixin)

    def test_one_slug_normalises_to_a_one_element_tuple(self, field_class):
        field = field_class(vocabulary="rock-type")

        assert field.vocabulary == ("rock-type",)

    def test_several_slugs_normalise_to_their_union_with_duplicates_collapsed(
        self, field_class
    ):
        field = field_class(vocabulary=["rock-type", "mineral", "rock-type"])

        assert field.vocabulary == ("rock-type", "mineral")

    def test_an_omitted_vocabulary_is_an_empty_tuple(self, field_class):
        assert field_class().vocabulary == ()

    def test_an_empty_slug_is_refused_by_name(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="")

    def test_a_non_string_slug_is_refused_by_name(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary=["mineral", 42])

    def test_a_consumer_supplied_limit_choices_to_is_refused(self, field_class):
        with pytest.raises(TypeError, match="limit_choices_to"):
            field_class(
                vocabulary="rock-type", limit_choices_to=Q(pref_label="Granite")
            )

    def test_help_text_defaults_to_a_translatable_string_and_stays_overridable(
        self, field_class
    ):
        assert isinstance(field_class(vocabulary="rock-type").help_text, Promise)
        assert (
            field_class(vocabulary="rock-type", help_text="Pick one.").help_text
            == "Pick one."
        )

    @pytest.mark.parametrize(
        "vocabulary", [None, "rock-type", ["rock-type", "mineral"]]
    )
    def test_deconstruct_records_the_normalised_vocabulary_and_strips_the_fixed_kwargs(
        self, field_class, vocabulary
    ):
        field = field_class(vocabulary=vocabulary)
        path, args, kwargs = field.deconstruct()[1:]

        assert kwargs["vocabulary"] == field.vocabulary
        assert "to" not in kwargs
        assert "limit_choices_to" not in kwargs
        assert "on_delete" not in kwargs
        assert "through" not in kwargs

        rebuilt = import_string(path)(*args, **kwargs)
        assert rebuilt.vocabulary == field.vocabulary

    def test_clone_rebuilds_an_equivalent_field(self, field_class):
        field = field_class(vocabulary=["rock-type", "mineral"])

        assert field.clone().vocabulary == ("rock-type", "mineral")


@pytest.mark.django_db
@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedVocabularyRestriction:
    def test_a_named_vocabulary_admits_only_its_concepts(self, field_class):
        rock = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        mineral = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        admitted = admitted_by(field_class(vocabulary="rock-type"))

        assert admitted == {rock}
        assert mineral not in admitted

    def test_several_named_vocabularies_admit_the_concepts_of_each(self, field_class):
        rock = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        mineral = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        fossil = RecordFactory(scheme=ConceptSchemeFactory(name="Fossil"))

        admitted = admitted_by(field_class(vocabulary=["rock-type", "mineral"]))

        assert admitted == {rock, mineral}
        assert fossil not in admitted

    def test_no_named_vocabulary_admits_the_concepts_of_every_vocabulary(
        self, field_class
    ):
        rock = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        mineral = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        assert admitted_by(field_class()) == {rock, mineral}

    @pytest.mark.parametrize("vocabulary", [None, "rock-type"])
    def test_a_collection_is_never_admitted(self, field_class, vocabulary):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(scheme=scheme)

        admitted = admitted_by(field_class(vocabulary=vocabulary))

        assert collection not in admitted
        assert set(members) <= admitted

    def test_construction_issues_no_query(self, field_class):
        with CaptureQueriesContext(connection) as ctx:
            field_class(vocabulary="rock-type")

        assert len(ctx.captured_queries) == 0


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedLimitChoicesToCallable:
    def test_limit_choices_to_is_a_callable_resolved_on_demand(self, field_class):
        assert callable(
            field_class(vocabulary="rock-type").remote_field.limit_choices_to
        )
        assert callable(field_class().remote_field.limit_choices_to)


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedCollectionArgument:
    def test_collection_defaults_to_none(self, field_class):
        assert field_class(vocabulary="rock-type").collection is None

    def test_collection_stores_the_slug(self, field_class):
        field = field_class(vocabulary="rock-type", collection="core-samples")

        assert field.collection == "core-samples"

    def test_collection_rejects_a_non_string(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", collection=42)

    def test_collection_rejects_an_empty_string(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", collection="")

    def test_a_collection_naming_no_vocabulary_is_refused(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(collection="core-samples")

    def test_a_collection_naming_several_vocabularies_is_refused(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary=["rock-type", "mineral"], collection="core-samples")

    def test_several_vocabularies_without_a_collection_are_accepted(self, field_class):
        field = field_class(vocabulary=["rock-type", "mineral"])

        assert field.vocabulary == ("rock-type", "mineral")

    def test_collection_is_emitted_and_survives_the_round_trip(self, field_class):
        field = field_class(vocabulary="rock-type", collection="core-samples")
        path, args, kwargs = field.deconstruct()[1:]

        assert kwargs["collection"] == "core-samples"
        assert "limit_choices_to" not in kwargs

        rebuilt = import_string(path)(*args, **kwargs)
        assert rebuilt.collection == "core-samples"

    def test_no_collection_is_not_emitted(self, field_class):
        kwargs = field_class(vocabulary="rock-type").deconstruct()[3]

        assert "collection" not in kwargs

    def test_clone_rebuilds_a_collection_restricted_field(self, field_class):
        field = field_class(vocabulary="rock-type", collection="core-samples")

        assert field.clone().collection == "core-samples"


# Both defaults stay static gettext_lazy strings: % on a lazy proxy evaluates it
# immediately.
@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedRestrictedHelpText:
    def test_an_unrestricted_field_keeps_the_unrestricted_default(self, field_class):
        field = field_class(vocabulary="rock-type")

        assert field.help_text == field_class.default_help_text

    def test_a_collection_restricted_field_gets_the_restricted_default(
        self, field_class
    ):
        field = field_class(vocabulary="rock-type", collection="core-samples")

        assert field.help_text == field_class.default_restricted_help_text
        assert field.help_text != field_class.default_help_text

    def test_restricted_help_text_is_a_lazy_translatable_string(self, field_class):
        field = field_class(vocabulary="rock-type", collection="core-samples")

        assert isinstance(field.help_text, Promise)

    def test_help_text_does_not_vary_with_the_restrictions_target(self, field_class):
        first = field_class(vocabulary="rock-type", collection="core-samples")
        second = field_class(vocabulary="rock-type", collection="all-samples")

        assert str(first.help_text) == str(second.help_text)

    def test_a_consumers_own_help_text_wins_over_the_restricted_default(
        self, field_class
    ):
        field = field_class(
            vocabulary="rock-type",
            collection="core-samples",
            help_text="Pick a sample rock.",
        )

        assert field.help_text == "Pick a sample rock."


# Q objects wrapping a subquery compare by identity, so every test evaluates the
# resolved Q against real rows instead of comparing Qs.
@pytest.mark.django_db
@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestCollectionRestrictionResolves:
    def test_resolves_to_exactly_the_collection_members(self, field_class):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite", "Basalt")
        )
        outsider = RecordFactory(scheme=scheme, label="Marble")

        admitted = admitted_by(
            field_class(vocabulary="rock-type", collection=collection.slug)
        )

        assert admitted == set(members)
        assert outsider not in admitted

    def test_an_ordered_collections_members_are_admitted(self, field_class):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite", "Basalt"), ordered=True
        )

        admitted = admitted_by(
            field_class(vocabulary="rock-type", collection=collection.slug)
        )

        assert admitted == set(members)

    def test_a_collection_that_does_not_exist_admits_nothing(self, field_class):
        ConceptSchemeFactory(name="Rock Type")
        RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        admitted = admitted_by(
            field_class(vocabulary="rock-type", collection="no-such-collection")
        )

        assert admitted == set()

    def test_a_same_named_collection_in_another_vocabulary_does_not_widen_the_field(
        self, field_class
    ):
        rock_collection, rock_members = collection_with_members(
            scheme=ConceptSchemeFactory(name="Rock Type"),
            name="Core Samples",
            labels=("Granite",),
        )
        mineral_collection, mineral_members = collection_with_members(
            scheme=ConceptSchemeFactory(name="Mineral"),
            name="Core Samples",
            labels=("Quartz",),
        )
        assert mineral_collection.slug == rock_collection.slug

        admitted = admitted_by(
            field_class(vocabulary="rock-type", collection=rock_collection.slug)
        )

        assert admitted == set(rock_members)
        assert not set(mineral_members) & admitted


# limit_choices_to is re-resolved on every read, so a restriction cached at
# construction fails here.
@pytest.mark.django_db
@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestCollectionRestrictionResolvesLive:
    def test_a_concept_added_to_the_collection_after_construction_appears_on_the_next_read(
        self, field_class
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite",)
        )
        field = field_class(vocabulary="rock-type", collection=collection.slug)
        assert admitted_by(field) == set(members)

        newcomer = RecordFactory(scheme=scheme, label="Basalt")
        collection.data["skos:member"].append({"@id": newcomer.uri})
        collection.save()

        assert admitted_by(field) == {*members, newcomer}


class TestConceptFieldConstruction:
    def test_fixes_to_record(self):
        field = ConceptField(vocabulary="rock-type")

        assert field.remote_field.model == "controlled_vocabularies.Record"

    def test_fixes_on_delete_to_protect(self):
        field = ConceptField(vocabulary="rock-type")

        assert field.remote_field.on_delete is PROTECT

    def test_rejects_consumer_supplied_on_delete(self):
        with pytest.raises(TypeError, match="on_delete"):
            ConceptField(vocabulary="rock-type", on_delete=PROTECT)

    def test_help_text_has_a_translatable_default(self):
        field = ConceptField(vocabulary="rock-type")

        assert isinstance(field.help_text, Promise)
        assert str(field.help_text)

    def test_help_text_default_is_overridable(self):
        field = ConceptField(vocabulary="rock-type", help_text="Pick a rock type.")

        assert field.help_text == "Pick a rock type."

    def test_error_messages_invalid_carries_named_vocabulary_placeholder(self):
        field = ConceptField(vocabulary="rock-type")

        assert "%(vocabulary)s" in field.error_messages["invalid"]

    def test_error_messages_carry_a_second_message_for_the_unrestricted_shape(self):
        field = ConceptField()

        assert "%(vocabulary)s" not in field.error_messages["invalid_unrestricted"]


# Field.clone() rebuilds a field from deconstruct(), and ModelState.from_model()
# clones every field, so migrations and test-database builds fail without it.
class TestConceptFieldDeconstruct:
    @pytest.mark.parametrize(
        "vocabulary", [None, "rock-type", ["rock-type", "mineral"]]
    )
    def test_round_trip_rebuilds_an_equivalent_field(self, vocabulary):
        # A migration written before #111 records vocabulary as a bare string and has to
        # keep replaying.
        field = ConceptField(vocabulary=vocabulary)
        path, args, kwargs = field.deconstruct()[1:]

        rebuilt = import_string(path)(*args, **kwargs)

        assert rebuilt.vocabulary == field.vocabulary
        assert rebuilt.remote_field.on_delete is PROTECT


class TestConceptsFieldConstruction:
    def test_fixes_to_record(self):
        field = ConceptsField(vocabulary="rock-type")

        assert field.remote_field.model == "controlled_vocabularies.Record"

    @pytest.mark.django_db
    def test_construction_issues_no_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            ConceptsField(vocabulary="rock-type")
            ConceptsField(vocabulary=["gcmd", "agu-index"])
            ConceptsField()

        assert len(ctx.captured_queries) == 0

    def test_rejects_consumer_supplied_through(self):
        # A consumer-supplied through model would silently drop the PROTECT guard.
        with pytest.raises(TypeError, match="through"):
            ConceptsField(
                vocabulary="rock-type", through="controlled_vocabularies.Record"
            )

    def test_help_text_has_a_translatable_default(self):
        field = ConceptsField(vocabulary="rock-type")

        assert isinstance(field.help_text, Promise)
        assert str(field.help_text)

    def test_help_text_default_is_overridable(self):
        field = ConceptsField(vocabulary="rock-type", help_text="Pick some rock types.")

        assert field.help_text == "Pick some rock types."


class TestConceptsFieldMembershipModel:
    def test_membership_model_is_named_owner_fieldname(self):
        field = Deposit._meta.get_field("rock_types")

        assert field.remote_field.through._meta.object_name == "Deposit_rock_types"

    def test_membership_models_concept_fk_is_protect(self):
        field = Deposit._meta.get_field("rock_types")
        concept_fk = field.remote_field.through._meta.get_field("record")

        assert concept_fk.remote_field.on_delete is PROTECT

    def test_membership_models_owner_fk_is_cascade(self):
        field = Deposit._meta.get_field("rock_types")
        owner_fk = field.remote_field.through._meta.get_field("deposit")

        assert owner_fk.remote_field.on_delete is CASCADE

    def test_deconstruct_still_emits_no_through_once_bound(self):
        # Meta.auto_created keeps ManyToManyField.deconstruct() from emitting it.
        field = Deposit._meta.get_field("rock_types")
        kwargs = field.deconstruct()[3]

        assert "through" not in kwargs

    def test_two_declarations_on_one_model_produce_two_distinct_tables(self):
        primary = Survey._meta.get_field("primary_minerals")
        secondary = Survey._meta.get_field("secondary_minerals")

        assert primary.remote_field.through is not secondary.remote_field.through
        assert (
            primary.remote_field.through._meta.db_table
            != secondary.remote_field.through._meta.db_table
        )

    def test_two_hidden_related_names_are_rewritten_distinctly(self):
        primary = Survey._meta.get_field("primary_minerals")
        secondary = Survey._meta.get_field("secondary_minerals")

        assert primary.remote_field.related_name != "+"
        assert secondary.remote_field.related_name != "+"
        assert primary.remote_field.related_name != secondary.remote_field.related_name

    def test_two_declarations_on_one_model_do_not_clash_reverse_accessors(self):
        errors = Survey.check()

        assert not any(error.id in {"fields.E304", "fields.E305"} for error in errors)

    @isolate_apps("tests.testapp")
    def test_declaring_two_concepts_fields_on_one_model_warns_of_nothing(self):
        # Skipping ManyToManyField's through generation must skip it, not call it and
        # then generate again: that registers the through model twice and Django
        # warns "was already registered".
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            class DoubleConceptsField(models.Model):
                a = ConceptsField(vocabulary="mineral", related_name="+")
                b = ConceptsField(vocabulary="mineral", related_name="+")

                class Meta:
                    app_label = "testapp"

        assert not any(
            "was already registered" in str(warning.message) for warning in caught
        )


class TestConsumingModelMigrations:
    @pytest.mark.django_db
    def test_every_consuming_model_is_queryable(self):
        for model in (
            Specimen,
            Sample,
            Artifact,
            CoreSample,
            Deposit,
            Survey,
            Outcrop,
            RockSample,
            FieldNote,
            Photograph,
        ):
            assert model.objects.count() == 0

    @pytest.mark.django_db
    def test_makemigrations_check_is_clean(self):
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)

    @pytest.mark.django_db
    def test_makemigrations_check_stays_clean_after_declaring_and_saving(self):
        RecordFactory()
        SpecimenFactory()

        call_command("makemigrations", "--check", "--dry-run", verbosity=0)


@pytest.mark.django_db
class TestConceptsFieldConsumingModels:
    def test_all_seven_factories_build_valid_saved_rows(self):
        assert DepositFactory().pk is not None
        assert SurveyFactory().pk is not None
        assert OutcropFactory().pk is not None
        assert RockSampleFactory().pk is not None
        assert FieldNoteFactory().pk is not None
        assert PhotographFactory().pk is not None
        assert DrillCoreFactory().pk is not None

    def test_optional_field_with_related_name_reads_back_from_both_sides(self):
        outcrop = OutcropFactory()
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        outcrop.minerals.add(concept)

        assert concept in outcrop.minerals.all()
        assert outcrop in concept.outcrops.all()

    def test_both_field_types_on_one_model_coexist_without_clashing(self):
        scheme = ConceptSchemeFactory(name="Mineral")
        primary = RecordFactory(scheme=scheme)
        associated = RecordFactory(scheme=scheme)
        sample = RockSampleFactory(primary_mineral=primary)

        sample.associated_minerals.add(associated)

        reloaded = RockSample.objects.get(pk=sample.pk)
        assert reloaded.primary_mineral == primary
        assert associated in reloaded.associated_minerals.all()

    def test_field_naming_two_vocabularies_restricts_to_their_union(self):
        rock = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        mineral = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        fossil = RecordFactory(scheme=ConceptSchemeFactory(name="Fossil"))

        admitted = admitted_by(FieldNote._meta.get_field("keywords"))

        assert admitted == {rock, mineral}
        assert fossil not in admitted

    def test_field_naming_no_vocabulary_still_attaches_a_concept_from_any_scheme(self):
        photograph = PhotographFactory()
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Anything"))

        photograph.keywords.add(concept)

        assert concept in photograph.keywords.all()


class TestConceptsFieldMetadata:
    @pytest.mark.parametrize(
        ("model", "field_name"),
        [
            (Deposit, "rock_types"),
            (Survey, "primary_minerals"),
            (Survey, "secondary_minerals"),
            (Outcrop, "minerals"),
            (RockSample, "associated_minerals"),
            (FieldNote, "keywords"),
            (Photograph, "keywords"),
        ],
    )
    def test_every_concepts_field_has_translatable_help_text_and_a_verbose_name(
        self, model, field_name
    ):
        field = model._meta.get_field(field_name)

        assert isinstance(field.help_text, Promise)
        assert str(field.help_text)
        assert field.verbose_name


@pytest.mark.django_db
class TestConceptsFieldAttachAndReadBack:
    def test_two_attached_concepts_are_returned_and_no_third(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        first = RecordFactory(scheme=scheme)
        second = RecordFactory(scheme=scheme)
        third = RecordFactory(scheme=scheme)
        deposit = DepositFactory()

        deposit.rock_types.add(first, second)

        reloaded = Deposit.objects.get(pk=deposit.pk)
        assert set(reloaded.rock_types.all()) == {first, second}
        assert third not in reloaded.rock_types.all()

    def test_attaching_an_already_held_concept_holds_it_exactly_once(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        deposit = DepositFactory()
        deposit.rock_types.add(concept)

        deposit.rock_types.add(concept)

        assert list(deposit.rock_types.all()) == [concept]

    def test_removing_one_of_two_leaves_the_other_attached_and_the_concept_intact(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        kept = RecordFactory(scheme=scheme)
        removed = RecordFactory(scheme=scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(kept, removed)

        deposit.rock_types.remove(removed)

        assert set(deposit.rock_types.all()) == {kept}
        assert Record.objects.filter(pk=removed.pk).exists()

    def test_reverse_accessor_from_the_concept_side_returns_the_row(self):
        outcrop = OutcropFactory()
        scheme = ConceptSchemeFactory(name="Mineral")
        concept = RecordFactory(scheme=scheme)
        other_concept = RecordFactory(scheme=scheme)

        outcrop.minerals.add(concept)

        assert outcrop in concept.outcrops.all()
        assert outcrop not in other_concept.outcrops.all()


@pytest.mark.django_db
class TestConceptsFieldWritePathVocabularyCheck:
    def test_add_of_a_concept_from_an_unnamed_vocabulary_is_refused_and_the_set_is_unchanged(
        self,
    ):
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        deposit = DepositFactory()

        # ManyRelatedManager.add() runs in transaction.atomic(savepoint=False), so a
        # raise poisons the test's own transaction unless the call has a savepoint
        # of its own to roll back to.
        with pytest.raises(ValidationError) as excinfo, transaction.atomic():
            deposit.rock_types.add(other_concept)

        assert excinfo.value.code == "invalid"
        assert list(deposit.rock_types.all()) == []

    def test_refusal_names_the_expected_vocabulary(self):
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        deposit = DepositFactory()

        with pytest.raises(ValidationError) as excinfo:
            deposit.rock_types.add(other_concept)

        assert any("rock-type" in message for message in excinfo.value.messages)

    def test_set_carrying_a_mix_is_refused_whole_and_the_set_is_unchanged_afterwards(
        self,
    ):
        kept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        deposit = DepositFactory()
        deposit.rock_types.add(kept)

        with pytest.raises(ValidationError), transaction.atomic():
            deposit.rock_types.set([kept, other_concept])

        assert set(deposit.rock_types.all()) == {kept}

    def test_several_concepts_all_from_the_named_vocabulary_are_attached(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        first = RecordFactory(scheme=scheme)
        second = RecordFactory(scheme=scheme)
        deposit = DepositFactory()

        deposit.rock_types.add(first, second)

        assert set(deposit.rock_types.all()) == {first, second}

    def test_the_default_reverse_accessor_refuses_a_concept_from_an_unnamed_vocabulary(
        self,
    ):
        # Django gives every relation a live reverse accessor unless the declaration
        # hides it, so this path reaches the same through model and must be refused
        # on the same terms. Deposit.rock_types names no related_name.
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        deposit = DepositFactory()

        with pytest.raises(ValidationError), transaction.atomic():
            other_concept.deposit_set.add(deposit)

        assert list(deposit.rock_types.all()) == []

    def test_a_named_reverse_accessor_refuses_a_concept_from_an_unnamed_vocabulary(
        self,
    ):
        outcrop = OutcropFactory()
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))

        with pytest.raises(ValidationError), transaction.atomic():
            other_concept.outcrops.add(outcrop)

        assert list(outcrop.minerals.all()) == []

    def test_the_reverse_accessor_attaches_a_concept_from_the_named_vocabulary(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        deposit = DepositFactory()

        concept.deposit_set.add(deposit)

        assert list(deposit.rock_types.all()) == [concept]

    def test_a_collection_is_refused_even_by_a_field_naming_no_vocabulary(self):
        collection, members = collection_with_members()
        photograph = PhotographFactory()

        with pytest.raises(ValidationError) as excinfo, transaction.atomic():
            photograph.keywords.add(collection)

        assert excinfo.value.code == "invalid"
        assert list(photograph.keywords.all()) == []


@pytest.mark.django_db
class TestConceptsFieldCollectionRestrictionWritePath:
    def test_forward_add_of_a_non_member_is_refused_and_the_set_is_unchanged(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite",)
        )
        outsider = RecordFactory(scheme=scheme, label="Marble")
        drill_core = DrillCoreFactory()
        drill_core.rock_types.add(members[0])

        with pytest.raises(ValidationError) as excinfo, transaction.atomic():
            drill_core.rock_types.add(outsider)

        assert excinfo.value.code == "invalid"
        assert list(drill_core.rock_types.all()) == [members[0]]

    def test_the_refusal_names_the_collection(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core Samples", labels=("Granite",))
        outsider = RecordFactory(scheme=scheme, label="Marble")
        drill_core = DrillCoreFactory()

        with pytest.raises(ValidationError) as excinfo:
            drill_core.rock_types.add(outsider)

        assert any("core-samples" in message for message in excinfo.value.messages)

    def test_the_reverse_accessor_refuses_a_non_member(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core Samples", labels=("Granite",))
        outsider = RecordFactory(scheme=scheme, label="Marble")
        drill_core = DrillCoreFactory()

        with pytest.raises(ValidationError), transaction.atomic():
            outsider.drill_cores.add(drill_core)

        assert list(drill_core.rock_types.all()) == []

    def test_the_reverse_accessor_attaches_a_member(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite",)
        )
        drill_core = DrillCoreFactory()

        members[0].drill_cores.add(drill_core)

        assert list(drill_core.rock_types.all()) == [members[0]]

    def test_a_set_carrying_a_mix_is_refused_whole_and_the_set_is_unchanged_afterwards(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite", "Basalt")
        )
        outsider = RecordFactory(scheme=scheme, label="Marble")
        drill_core = DrillCoreFactory()
        drill_core.rock_types.add(members[0])

        with pytest.raises(ValidationError), transaction.atomic():
            drill_core.rock_types.set([members[1], outsider])

        assert set(drill_core.rock_types.all()) == {members[0]}

    def test_several_members_all_attach(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite", "Basalt")
        )
        drill_core = DrillCoreFactory()

        drill_core.rock_types.add(*members)

        assert set(drill_core.rock_types.all()) == set(members)


@pytest.mark.django_db
class TestConceptsFieldSeveralVocabulariesWritePath:
    def test_a_concept_from_either_named_vocabulary_attaches(self):
        rock_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        mineral_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        field_note = FieldNoteFactory()

        field_note.keywords.add(rock_concept, mineral_concept)

        assert set(field_note.keywords.all()) == {rock_concept, mineral_concept}

    def test_a_concept_from_an_unnamed_third_vocabulary_is_refused_naming_both_expected_vocabularies(
        self,
    ):
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Fossil"))
        field_note = FieldNoteFactory()

        with pytest.raises(ValidationError) as excinfo, transaction.atomic():
            field_note.keywords.add(other_concept)

        message = " ".join(excinfo.value.messages)
        assert "rock-type" in message
        assert "mineral" in message
        assert list(field_note.keywords.all()) == []


@pytest.mark.django_db
class TestConceptsFieldNoVocabularyWritePath:
    def test_concepts_from_several_distinct_vocabularies_all_attach_and_none_is_refused(
        self,
    ):
        concepts = [
            RecordFactory(scheme=ConceptSchemeFactory(name=name))
            for name in ("Rock Type", "Mineral", "Fossil")
        ]
        photograph = PhotographFactory()

        photograph.keywords.add(*concepts)

        assert set(photograph.keywords.all()) == set(concepts)


class DepositForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``Deposit``."""

    class Meta:
        model = Deposit
        fields = ["name", "rock_types"]


@pytest.mark.django_db
class TestConceptsFieldFormChoices:
    def test_form_field_offers_only_the_named_vocabularys_concepts(self):
        matching_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        choices = list(DepositForm().fields["rock_types"].queryset)

        assert matching_concept in choices
        assert other_concept not in choices

    def test_submission_carrying_a_concept_from_an_unnamed_vocabulary_is_rejected(self):
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        form = DepositForm(
            data={"name": "Wrong vocabulary", "rock_types": [other_concept.pk]}
        )

        assert not form.is_valid()
        assert form.has_error("rock_types")
        assert Deposit.objects.count() == 0

    def test_valid_submission_saves_and_the_memberships_appear(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))

        form = DepositForm(data={"name": "Granite deposit", "rock_types": [concept.pk]})

        assert form.is_valid(), form.errors
        deposit = form.save()
        assert concept in deposit.rock_types.all()


class FieldNoteForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``FieldNote``."""

    class Meta:
        model = FieldNote
        fields = ["name", "keywords"]


@pytest.mark.django_db
class TestConceptsFieldSeveralVocabulariesFormChoices:
    def test_form_field_offers_the_concepts_of_both_named_vocabularies_and_no_others(
        self,
    ):
        rock_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        mineral_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Fossil"))

        choices = list(FieldNoteForm().fields["keywords"].queryset)

        assert rock_concept in choices
        assert mineral_concept in choices
        assert other_concept not in choices


class PhotographForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``Photograph``."""

    class Meta:
        model = Photograph
        fields = ["name", "keywords"]


@pytest.mark.django_db
class TestConceptsFieldNoVocabularyFormChoices:
    def test_form_field_offers_every_concept_in_the_database_and_no_collection(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(scheme=scheme)
        mineral_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        choices = list(PhotographForm().fields["keywords"].queryset)

        assert set(choices) == {*members, mineral_concept}
        assert collection not in choices


@pytest.mark.django_db
class TestConceptsFieldDeleteGuard:
    def test_deleting_a_held_concept_is_refused(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        deposit = DepositFactory()
        deposit.rock_types.add(concept)

        with pytest.raises(ProtectedError):
            concept.delete()

        assert Record.objects.filter(pk=concept.pk).exists()
        assert Deposit.objects.filter(pk=deposit.pk).exists()
        assert concept in deposit.rock_types.all()

    def test_bulk_queryset_delete_of_a_held_concept_is_refused(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        deposit = DepositFactory()
        deposit.rock_types.add(concept)

        with pytest.raises(ProtectedError):
            Record.objects.filter(pk=concept.pk).delete()

        assert Record.objects.filter(pk=concept.pk).exists()
        assert concept in deposit.rock_types.all()

    def test_deleting_the_scheme_holding_a_held_concept_is_refused(self):
        # Record.scheme cascades, so deleting the scheme tries to cascade-delete the
        # record and meets the same PROTECT on the way down.
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = RecordFactory(scheme=scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(concept)

        with pytest.raises(ProtectedError):
            scheme.delete()

        assert ConceptScheme.objects.filter(pk=scheme.pk).exists()
        assert Record.objects.filter(pk=concept.pk).exists()
        assert concept in deposit.rock_types.all()

    def test_a_concept_no_row_holds_deletes_cleanly(self, concept):
        concept.delete()

        assert not Record.objects.filter(pk=concept.pk).exists()

    def test_deleting_the_consuming_row_removes_only_its_memberships_not_concepts(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        first = RecordFactory(scheme=scheme)
        second = RecordFactory(scheme=scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(first, second)
        through = Deposit._meta.get_field("rock_types").remote_field.through

        deposit.delete()

        assert not Deposit.objects.filter(pk=deposit.pk).exists()
        assert not through.objects.filter(record__in=[first, second]).exists()
        assert Record.objects.filter(pk=first.pk).exists()
        assert Record.objects.filter(pk=second.pk).exists()

    def test_a_concept_detached_from_every_row_that_held_it_then_deletes_cleanly(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        deposit = DepositFactory()
        deposit.rock_types.add(concept)

        deposit.rock_types.remove(concept)
        concept.delete()

        assert not Record.objects.filter(pk=concept.pk).exists()

    def test_deleting_a_concept_held_by_a_field_naming_no_vocabulary_is_refused(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Anything"))
        photograph = PhotographFactory()
        photograph.keywords.add(concept)

        with pytest.raises(ProtectedError):
            concept.delete()

        assert Record.objects.filter(pk=concept.pk).exists()
        assert Photograph.objects.filter(pk=photograph.pk).exists()
        assert concept in photograph.keywords.all()


@pytest.mark.django_db
class TestConceptsFieldLabelAndUriAccessors:
    def test_labels_accessor_returns_the_active_languages_label_for_each_attached_concept(
        self, multilingual_scheme
    ):
        granite = multilingual_scheme.records.get(pref_label="Granite")
        other_concept = multilingual_scheme.records.exclude(pk=granite.pk).get()
        photograph = PhotographFactory()
        photograph.keywords.add(granite, other_concept)

        with translation.override("de"):
            labels = set(photograph.get_keywords_labels())

        assert labels == {"Granit", other_concept.pref_label}

    def test_labels_accessor_falls_back_to_the_vocabulary_default(self):
        concept = RecordFactory(label="Basalt")
        photograph = PhotographFactory()
        photograph.keywords.add(concept)

        with translation.override("fr"):
            assert photograph.get_keywords_labels() == ["Basalt"]

    def test_uris_accessor_returns_each_attached_concepts_own_uri_unchanged(
        self, multilingual_scheme
    ):
        concepts = list(multilingual_scheme.records.all())
        photograph = PhotographFactory()
        photograph.keywords.add(*concepts)

        assert set(photograph.get_keywords_uris()) == {
            concept.uri for concept in concepts
        }

    def test_both_accessors_return_an_empty_list_when_nothing_is_attached(self):
        photograph = PhotographFactory()

        assert photograph.get_keywords_labels() == []
        assert photograph.get_keywords_uris() == []


class TestConceptsFieldAccessorsWithoutADatabase:
    def test_both_accessors_return_an_empty_list_on_an_unsaved_row_rather_than_raising(
        self,
    ):
        # Touching a many-to-many manager before the instance has a primary key
        # raises ValueError; both accessors return an empty list instead.
        deposit = Deposit(name="not yet surveyed")

        assert deposit.get_rock_types_labels() == []
        assert deposit.get_rock_types_uris() == []

    @isolate_apps("tests.testapp")
    def test_a_models_own_definition_survives_the_contribution_guard(self):
        class OwnLabelsConceptsFieldModel(models.Model):
            keywords = ConceptsField(blank=True, related_name="+")

            class Meta:
                app_label = "testapp"

            def get_keywords_labels(self):
                return ["this model's own labels, not the field's"]

        instance = OwnLabelsConceptsFieldModel()

        assert instance.get_keywords_labels() == [
            "this model's own labels, not the field's"
        ]


class OutcropForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``Outcrop``."""

    class Meta:
        model = Outcrop
        fields = ["name", "minerals"]


@pytest.mark.django_db
class TestConceptsFieldRequiredSet:
    @pytest.mark.django_db
    def test_an_optional_field_with_an_empty_set_validates(self):
        outcrop = OutcropFactory()

        outcrop.full_clean()

    @pytest.mark.django_db
    def test_a_required_field_with_an_empty_set_is_refused_naming_the_field(self):
        deposit = DepositFactory()

        with pytest.raises(ValidationError) as excinfo:
            deposit.full_clean()

        assert [error.code for error in excinfo.value.error_dict["rock_types"]] == [
            "required"
        ]

    @pytest.mark.django_db
    def test_two_required_fields_both_empty_report_both(self):
        survey = SurveyFactory()

        with pytest.raises(ValidationError) as excinfo:
            survey.full_clean()

        assert set(excinfo.value.message_dict) >= {
            "primary_minerals",
            "secondary_minerals",
        }

    @pytest.mark.django_db
    def test_two_required_fields_the_first_empty_the_second_populated_reports_only_the_first(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concept = RecordFactory(scheme=scheme)
        survey = SurveyFactory()
        survey.secondary_minerals.add(concept)

        with pytest.raises(ValidationError) as excinfo:
            survey.full_clean()

        assert "primary_minerals" in excinfo.value.message_dict
        assert "secondary_minerals" not in excinfo.value.message_dict

    @pytest.mark.django_db
    def test_two_required_fields_the_second_empty_the_first_populated_reports_only_the_second(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Mineral")
        concept = RecordFactory(scheme=scheme)
        survey = SurveyFactory()
        survey.primary_minerals.add(concept)

        with pytest.raises(ValidationError) as excinfo:
            survey.full_clean()

        assert "secondary_minerals" in excinfo.value.message_dict
        assert "primary_minerals" not in excinfo.value.message_dict

    def test_an_unsaved_instance_passes_full_clean_without_raising_value_error(self):
        # Touching Deposit.rock_types before the instance has a primary key raises
        # ValueError, which full_clean() does not catch, so the check must not reach it.
        deposit = Deposit(name="not yet surveyed")

        deposit.full_clean()

    @pytest.mark.django_db
    def test_a_bad_character_field_and_an_empty_required_set_report_both_errors(self):
        deposit = Deposit(name="")
        deposit.save()

        with pytest.raises(ValidationError) as excinfo:
            deposit.full_clean()

        assert "name" in excinfo.value.message_dict
        assert "rock_types" in excinfo.value.message_dict

    @isolate_apps("tests.testapp")
    def test_an_inheriting_model_does_not_get_a_second_wrapper(self):
        # The wrapper resolves the instance's own class at call time, so a
        # subclass is already covered by the one it inherits. Installing a
        # second around it would report every empty required field twice.
        class Parent(models.Model):
            firsts = ConceptsField(
                vocabulary="rock-type", verbose_name="firsts", help_text="the first set"
            )

            class Meta:
                app_label = "testapp"

        class Child(Parent):
            seconds = ConceptsField(
                vocabulary="rock-type",
                verbose_name="seconds",
                help_text="the second set",
            )

            class Meta:
                app_label = "testapp"

        assert Parent.__dict__["full_clean"].concepts_field_required_set_check
        assert "full_clean" not in Child.__dict__
        assert {
            field.name
            for field in Child._meta.get_fields()
            if isinstance(field, ConceptsField)
        } == {
            "firsts",
            "seconds",
        }

    def test_a_required_fields_form_half_rejects_an_empty_selection(self):
        form = DepositForm(data={"name": "Granite deposit", "rock_types": []})

        assert not form.is_valid()
        assert form.has_error("rock_types", code="required")

    def test_an_optional_fields_form_half_accepts_an_empty_selection(self):
        form = OutcropForm(data={"name": "Bare outcrop", "minerals": []})

        assert form.is_valid(), form.errors

    def test_a_saved_rows_valid_submission_is_accepted_with_its_relation_empty(
        self,
    ):
        # #124: ModelForm calls instance.full_clean() before save_m2m(), so a saved
        # row's relation is still empty when it validates.
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        deposit = DepositFactory()
        assert not deposit.rock_types.exists()

        form = DepositForm(
            data={"name": deposit.name, "rock_types": [concept.pk]}, instance=deposit
        )

        assert form.is_valid(), form.errors

    def test_a_saved_rows_empty_submission_is_still_refused(self):
        deposit = DepositFactory()

        form = DepositForm(
            data={"name": deposit.name, "rock_types": []}, instance=deposit
        )

        assert not form.is_valid()
        assert form.has_error("rock_types", code="required")


@pytest.mark.django_db
class TestConceptFieldFactories:
    def test_borehole_factory_leaves_the_optional_field_unset_by_default(self):
        borehole = BoreholeFactory()

        assert borehole.pk is not None
        assert borehole.dominant_material is None

    def test_sketch_factory_leaves_the_optional_field_unset_by_default(self):
        sketch = SketchFactory()

        assert sketch.pk is not None
        assert sketch.subject is None

    def test_specimen_factory_builds_a_required_concept(self):
        specimen = SpecimenFactory()

        assert specimen.pk is not None
        assert specimen.rock_type is not None

    def test_sample_factory_leaves_the_optional_field_unset_by_default(self):
        sample = SampleFactory()

        assert sample.pk is not None
        assert sample.mineral is None

    def test_artifact_factory_leaves_the_optional_field_unset_by_default(self):
        artifact = ArtifactFactory()

        assert artifact.pk is not None
        assert artifact.mineral is None


class TestConceptVocabularyFixtures:
    @pytest.mark.django_db
    def test_multilingual_scheme_has_one_concept_with_a_second_language_label(
        self, multilingual_scheme
    ):
        concepts = list(multilingual_scheme.records.all())

        assert len(concepts) == 2
        assert len([c for c in concepts if c.label("de")]) == 1


@pytest.mark.django_db
class TestConceptFieldRoundTrip:
    def test_saving_and_reloading_returns_the_same_concept(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        specimen = SpecimenFactory(rock_type=concept)

        reloaded = Specimen.objects.get(pk=specimen.pk)

        assert reloaded.rock_type == concept

    def test_optional_field_with_nothing_attached_validates_and_saves(self):
        sample = Sample(name="Unclassified sample")

        sample.full_clean()
        sample.save()

        assert sample.pk is not None
        assert sample.mineral is None


class TestConceptFieldOrdinaryOptions:
    def test_related_name_produces_the_reverse_accessor(self):
        field = Sample._meta.get_field("mineral")

        assert field.remote_field.get_accessor_name() == "samples"

    def test_required_field_is_not_null_or_blank(self):
        field = Specimen._meta.get_field("rock_type")

        assert field.null is False
        assert field.blank is False

    def test_optional_field_is_null_and_blank(self):
        field = Sample._meta.get_field("mineral")

        assert field.null is True
        assert field.blank is True

    def test_the_fks_index_is_present(self):
        field = Specimen._meta.get_field("rock_type")

        assert field.db_index is True


@pytest.mark.django_db
class TestConceptFieldValidation:
    def test_full_clean_rejects_a_concept_from_another_vocabulary(self):
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        specimen = Specimen(name="Wrong vocabulary", rock_type=other_concept)

        with pytest.raises(ValidationError) as excinfo:
            specimen.full_clean()

        errors = excinfo.value.error_dict["rock_type"]
        assert [error.code for error in errors] == ["invalid"]
        assert any("rock-type" in message for message in excinfo.value.messages)

    def test_full_clean_accepts_a_concept_from_the_correct_vocabulary(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        specimen = Specimen(name="Correct vocabulary", rock_type=concept)

        specimen.full_clean()

    def test_full_clean_accepts_an_optional_field_with_nothing_attached(self):
        Sample(name="Unclassified sample").full_clean()

    def test_the_re_raise_keeps_the_foreign_keys_own_params(self):
        # error_messages is an ordinary field kwarg, so a consumer's message may use
        # any placeholder a plain ForeignKey supplies. The override adds `vocabulary`
        # to those params and must not replace them, or .messages raises KeyError.
        field = Specimen._meta.get_field("rock_type")
        original = field.error_messages["invalid"]
        field.error_messages["invalid"] = (
            "%(model)s pk=%(pk)s field=%(field)s in %(vocabulary)s"
        )
        try:
            other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
            specimen = Specimen(name="Wrong vocabulary", rock_type=other_concept)

            with pytest.raises(ValidationError) as excinfo:
                specimen.full_clean()

            assert any("rock-type" in message for message in excinfo.value.messages)
        finally:
            field.error_messages["invalid"] = original

    def test_a_collection_is_refused_by_a_field_naming_no_vocabulary(self):
        collection, members = collection_with_members()
        sketch = Sketch(name="Mislabelled", subject=collection)

        with pytest.raises(ValidationError) as excinfo:
            sketch.full_clean()

        assert [error.code for error in excinfo.value.error_dict["subject"]] == [
            "invalid"
        ]


@pytest.mark.django_db
class TestConceptFieldCollectionRestrictionValidation:
    def test_a_collection_member_validates(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite",)
        )

        CoreSample(name="Sample A", rock_type=members[0]).full_clean()

    def test_a_non_member_of_the_same_vocabulary_is_refused(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core Samples", labels=("Granite",))
        outsider = RecordFactory(scheme=scheme, label="Marble")
        core_sample = CoreSample(name="Sample B", rock_type=outsider)

        with pytest.raises(ValidationError) as excinfo:
            core_sample.full_clean()

        assert [error.code for error in excinfo.value.error_dict["rock_type"]] == [
            "invalid"
        ]

    def test_the_refusal_names_the_collection(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core Samples", labels=("Granite",))
        outsider = RecordFactory(scheme=scheme, label="Marble")
        core_sample = CoreSample(name="Sample B", rock_type=outsider)

        with pytest.raises(ValidationError) as excinfo:
            core_sample.full_clean()

        assert any("core-samples" in message for message in excinfo.value.messages)

    def test_a_consumers_own_error_messages_override_still_works(self):
        field = CoreSample._meta.get_field("rock_type")
        original = field.error_messages["invalid_restricted"]
        field.error_messages["invalid_restricted"] = (
            "%(model)s pk=%(pk)s field=%(field)s in %(restriction)s"
        )
        try:
            scheme = ConceptSchemeFactory(name="Rock Type")
            collection_with_members(
                scheme=scheme, name="Core Samples", labels=("Granite",)
            )
            outsider = RecordFactory(scheme=scheme, label="Marble")
            core_sample = CoreSample(name="Sample C", rock_type=outsider)

            with pytest.raises(ValidationError) as excinfo:
                core_sample.full_clean()

            assert any("core-samples" in message for message in excinfo.value.messages)
        finally:
            field.error_messages["invalid_restricted"] = original


class SpecimenForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``Specimen``."""

    class Meta:
        model = Specimen
        fields = ["name", "rock_type"]


@pytest.mark.django_db
class TestConceptFieldFormChoices:
    def test_form_field_offers_only_the_named_vocabularys_concepts(self):
        matching_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        choices = list(SpecimenForm().fields["rock_type"].queryset)

        assert matching_concept in choices
        assert other_concept not in choices

    def test_form_submission_with_another_vocabularys_concept_is_rejected(self):
        other_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        form = SpecimenForm(
            data={"name": "Wrong vocabulary", "rock_type": other_concept.pk}
        )

        assert not form.is_valid()
        assert form.has_error("rock_type")
        assert Specimen.objects.count() == 0


@pytest.mark.django_db
class TestConceptFieldDeleteGuard:
    def test_deleting_a_referenced_concept_is_refused(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        specimen = SpecimenFactory(rock_type=concept)

        with pytest.raises(ProtectedError):
            concept.delete()

        assert Record.objects.filter(pk=concept.pk).exists()
        assert Specimen.objects.filter(pk=specimen.pk).exists()

    def test_bulk_queryset_delete_of_a_referenced_concept_is_refused(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        specimen = SpecimenFactory(rock_type=concept)

        with pytest.raises(ProtectedError):
            Record.objects.filter(pk=concept.pk).delete()

        assert Record.objects.filter(pk=concept.pk).exists()
        assert Specimen.objects.filter(pk=specimen.pk).exists()

    def test_deleting_the_scheme_holding_a_referenced_concept_is_refused(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = RecordFactory(scheme=scheme)
        specimen = SpecimenFactory(rock_type=concept)

        with pytest.raises(ProtectedError):
            scheme.delete()

        assert ConceptScheme.objects.filter(pk=scheme.pk).exists()
        assert Record.objects.filter(pk=concept.pk).exists()
        assert Specimen.objects.filter(pk=specimen.pk).exists()

    def test_an_unreferenced_concept_deletes_normally(self, concept):
        concept.delete()

        assert not Record.objects.filter(pk=concept.pk).exists()

    def test_deleting_the_consuming_row_leaves_the_concept_in_place(self, concept):
        specimen = SpecimenFactory(rock_type=concept)

        specimen.delete()

        assert not Specimen.objects.filter(pk=specimen.pk).exists()
        assert Record.objects.filter(pk=concept.pk).exists()


@pytest.mark.django_db
class TestConceptFieldLabelAndUriAccessors:
    def test_label_accessor_returns_the_active_languages_preferred_label(self):
        concept = RecordFactory(
            scheme=ConceptSchemeFactory(name="Rock Type"),
            data=bilingual("Basalt", "Basalt (de)"),
        )
        specimen = SpecimenFactory(rock_type=concept)

        with translation.override("de"):
            assert specimen.get_rock_type_label() == "Basalt (de)"

    def test_label_accessor_falls_back_to_the_vocabulary_default(self):
        concept = RecordFactory(
            scheme=ConceptSchemeFactory(name="Rock Type"), label="Basalt"
        )
        specimen = SpecimenFactory(rock_type=concept)

        with translation.override("fr"):
            assert specimen.get_rock_type_label() == "Basalt"

    def test_uri_accessor_returns_the_concepts_own_uri_unchanged(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        specimen = SpecimenFactory(rock_type=concept)

        assert specimen.get_rock_type_uri() == concept.uri

    def test_both_accessors_return_none_when_nothing_is_attached(self):
        sample = SampleFactory()

        assert sample.get_mineral_label() is None
        assert sample.get_mineral_uri() is None

    def test_a_models_own_definition_survives_the_contribution_guard(self):
        artifact = ArtifactFactory()

        assert (
            artifact.get_mineral_label() == "this artifact's own label, not the field's"
        )


class TestConceptFieldAccessorsWithoutADatabase:
    def test_both_accessors_return_none_on_a_required_field_with_nothing_attached(self):
        # A required field's forward descriptor raises RelatedObjectDoesNotExist
        # rather than returning None, so the nullable case does not cover this one.
        # Both accessors promise None, never a raise.
        specimen = Specimen(name="not yet classified")

        assert specimen.get_rock_type_label() is None
        assert specimen.get_rock_type_uri() is None


class BoreholeForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``Borehole``."""

    class Meta:
        model = Borehole
        fields = ["name", "dominant_material"]


class SketchForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``Sketch``."""

    class Meta:
        model = Sketch
        fields = ["name", "subject"]


@pytest.mark.django_db
class TestConceptFieldSeveralVocabularies:
    def test_a_concept_from_either_named_vocabulary_validates(self):
        rock_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        mineral_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        Borehole(name="From rock-type", dominant_material=rock_concept).full_clean()
        Borehole(name="From mineral", dominant_material=mineral_concept).full_clean()

    def test_a_concept_from_a_third_vocabulary_is_refused_naming_both_expected(self):
        ConceptSchemeFactory(name="Rock Type")
        ConceptSchemeFactory(name="Mineral")
        outsider = RecordFactory(scheme=ConceptSchemeFactory(name="Geologic Age"))

        with pytest.raises(ValidationError) as excinfo:
            Borehole(name="Wrong vocabulary", dominant_material=outsider).full_clean()

        message = " ".join(excinfo.value.messages)
        assert "rock-type" in message
        assert "mineral" in message

    def test_form_field_offers_only_the_two_named_vocabularies_concepts(self):
        rock_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        mineral_concept = RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        outsider = RecordFactory(scheme=ConceptSchemeFactory(name="Geologic Age"))

        choices = list(BoreholeForm().fields["dominant_material"].queryset)

        assert rock_concept in choices
        assert mineral_concept in choices
        assert outsider not in choices


@pytest.mark.django_db
class TestConceptFieldNoVocabulary:
    def test_a_concept_from_any_vocabulary_validates(self):
        first = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        second = RecordFactory(scheme=ConceptSchemeFactory(name="Geologic Age"))

        Sketch(name="Rock", subject=first).full_clean()
        Sketch(name="Age", subject=second).full_clean()

    def test_form_field_offers_every_concept_in_the_database(self):
        first = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        second = RecordFactory(scheme=ConceptSchemeFactory(name="Geologic Age"))

        choices = list(SketchForm().fields["subject"].queryset)

        assert first in choices
        assert second in choices

    def test_a_missing_concept_is_still_refused_without_naming_an_empty_vocabulary(
        self,
    ):
        # The vocabulary-naming message would raise KeyError here, and one naming ''
        # would be worse than useless.
        sketch = Sketch(name="Dangling", subject_id=987654)

        with pytest.raises(ValidationError) as excinfo:
            sketch.full_clean()

        message = " ".join(excinfo.value.messages)
        assert "987654" in message
        assert "''" not in message

    def test_a_held_concept_cannot_be_deleted(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        SketchFactory(subject=concept)

        with pytest.raises(ProtectedError):
            concept.delete()

    def test_label_and_uri_read_back(self):
        concept = RecordFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        sketch = SketchFactory(subject=concept)

        assert sketch.get_subject_label() == concept.display_label()
        assert sketch.get_subject_uri() == concept.uri


# Read off field.error_messages, where nothing has interpolated the msgid yet.
class TestRestrictionErrorMessagesAreTranslatable:
    def test_the_message_is_a_lazy_proxy_with_a_named_restriction_placeholder(self):
        field = ConceptField(vocabulary="rock-type")
        message = field.error_messages["invalid_restricted"]

        assert isinstance(message, Promise)
        assert "%(restriction)s" in str(message)
        assert "%(value)s" in str(message)


@pytest.mark.django_db
class TestWriteGuardRefusalsAreTranslatable:
    def test_the_collection_axis_refusal_is_a_lazy_proxy_with_named_placeholders(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core Samples", labels=("Granite",))
        outsider = RecordFactory(scheme=scheme, label="Marble")
        drill_core = DrillCoreFactory()

        with pytest.raises(ValidationError) as excinfo:
            drill_core.rock_types.add(outsider)

        assert isinstance(excinfo.value.message, Promise)
        assert "%(restriction)s" in str(excinfo.value.message)
        assert "%(value)s" in str(excinfo.value.message)


# Developer-facing diagnostics raised while a declaration is read, exempt under
# Article XII. Wrapping one in _() would break nothing visible, so only a test stops a
# later pass doing it.
class TestDeclarationRuleTypeErrorsStayUntranslated:
    @pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
    def test_a_collection_naming_no_vocabulary_raises_a_plain_string(self, field_class):
        with pytest.raises(TypeError) as excinfo:
            field_class(collection="core-samples")

        assert not isinstance(excinfo.value.args[0], Promise)
        assert type(excinfo.value.args[0]) is str

    @pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
    def test_a_non_string_collection_raises_a_plain_string(self, field_class):
        with pytest.raises(TypeError) as excinfo:
            field_class(vocabulary="rock-type", collection=42)

        assert not isinstance(excinfo.value.args[0], Promise)
        assert type(excinfo.value.args[0]) is str

    def test_concept_fields_own_delete_setting_raises_a_plain_string(self):
        with pytest.raises(TypeError) as excinfo:
            ConceptField(vocabulary="rock-type", on_delete=PROTECT)

        assert not isinstance(excinfo.value.args[0], Promise)
        assert type(excinfo.value.args[0]) is str

    def test_concepts_fields_own_through_setting_raises_a_plain_string(self):
        with pytest.raises(TypeError) as excinfo:
            ConceptsField(vocabulary="rock-type", through="whatever")

        assert not isinstance(excinfo.value.args[0], Promise)
        assert type(excinfo.value.args[0]) is str


class TestFieldsI18nSweep:
    def test_module_carries_no_bare_user_visible_literal(self):
        source = Path(inspect.getfile(fields_module)).read_text()
        visitor = visit_fields_checks_source(source)

        assert visitor.bare_literals == [], (
            f"{fields_module.__name__} passes a bare, untranslated literal to a user-visible sink: {visitor.bare_literals}"
        )
        assert visitor.positional_placeholders == [], (
            f"{fields_module.__name__} passes a positional placeholder to a translation call: "
            f"{visitor.positional_placeholders}"
        )


class TestFieldsChecksI18nVisitorCatchesAViolation:
    def test_catches_a_bare_help_text_keyword_literal(self):
        visitor = visit_fields_checks_source("ForeignKey(help_text='boom')\n")

        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_verbose_name_keyword_literal(self):
        visitor = visit_fields_checks_source("CharField(verbose_name='boom')\n")

        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_help_text_default_via_kwargs_setdefault(self):
        visitor = visit_fields_checks_source("kwargs.setdefault('help_text', 'boom')\n")

        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_error_messages_dict_value(self):
        visitor = visit_fields_checks_source("error_messages = {'invalid': 'boom'}\n")

        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_raised_as_a_validation_error(self):
        visitor = visit_fields_checks_source("raise ValidationError('boom')\n")

        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_raised_as_improperly_configured(self):
        visitor = visit_fields_checks_source("raise ImproperlyConfigured('boom')\n")

        assert visitor.bare_literals == ["boom"]

    def test_catches_a_positional_placeholder_passed_to_a_translation_call(self):
        visitor = visit_fields_checks_source(
            "from django.utils.translation import gettext_lazy as _\n_('%s changed')\n"
        )

        assert visitor.positional_placeholders == ["%s changed"]

    def test_does_not_flag_a_named_placeholder_passed_to_a_translation_call(self):
        visitor = visit_fields_checks_source(
            "from django.utils.translation import gettext_lazy as _\n_('%(model)s changed')\n"
        )

        assert visitor.positional_placeholders == []

    def test_catches_a_bare_literal_as_a_checks_warning(self):
        visitor = visit_fields_checks_source("checks.Warning('boom')\n")

        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_as_a_checks_error(self):
        visitor = visit_fields_checks_source("checks.Error('boom')\n")

        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_interpolated_message(self):
        visitor = visit_fields_checks_source(
            "checks.Warning('boom %(model)s' % {'model': m})\n"
        )

        assert visitor.bare_literals == ["boom %(model)s"]

    def test_catches_a_bare_f_string_message(self):
        visitor = visit_fields_checks_source("checks.Warning(f'boom {model}')\n")

        assert visitor.bare_literals == ["f'boom {model}'"]

    def test_catches_a_bare_hint_keyword_literal(self):
        visitor = visit_fields_checks_source("checks.Warning(_('fine'), hint='boom')\n")

        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_verbose_name_dict_literal_value(self):
        visitor = visit_fields_checks_source(
            "meta = {'verbose_name': 'boom', 'verbose_name_plural': 'booms', 'db_table': 'x'}\n"
        )

        assert visitor.bare_literals == ["boom", "booms"]

    def test_does_not_flag_a_translated_sink(self):
        visitor = visit_fields_checks_source(
            "from django.utils.translation import gettext_lazy as _\n"
            "kwargs.setdefault('help_text', _('fine'))\n"
            "error_messages = {'invalid': _('fine')}\n"
            "raise ValidationError(_('fine'))\n"
            "raise ImproperlyConfigured(_('fine'))\n"
            "checks.Warning(_('fine %(model)s') % {'model': m}, hint=_('fine'))\n"
            "meta = {'verbose_name': _('fine') % {'x': 1}, 'db_table': 'x'}\n"
        )

        assert visitor.bare_literals == []
        assert visitor.positional_placeholders == []
