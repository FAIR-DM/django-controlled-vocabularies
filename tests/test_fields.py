"""Tests for controlled_vocabularies.fields."""

import ast
import inspect
import signal
import warnings
from pathlib import Path

import pytest
from django import forms
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection, models, transaction
from django.db.models import CASCADE, PROTECT, ProtectedError, Q
from django.db.models.signals import m2m_changed
from django.test.utils import CaptureQueriesContext, isolate_apps
from django.utils import translation
from django.utils.functional import Promise
from django.utils.module_loading import import_string

from controlled_vocabularies import checks as checks_module
from controlled_vocabularies import fields as fields_module
from controlled_vocabularies.fields import (
    ConceptField,
    ConceptFieldMixin,
    ConceptsField,
    _branch_closure,
)
from controlled_vocabularies.models import Concept, ConceptLabel, ConceptScheme
from tests.factories import (
    ArtifactFactory,
    BoreholeFactory,
    BranchTrayFactory,
    ChipTrayFactory,
    CollectionFactory,
    ConceptFactory,
    ConceptSchemeFactory,
    DepositFactory,
    DrillCoreFactory,
    FieldNoteFactory,
    OutcropFactory,
    PhotographFactory,
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
    BranchSample,
    ChipSample,
    CoreSample,
    Deposit,
    DrillCore,
    FieldNote,
    Outcrop,
    Photograph,
    RockSample,
    Sample,
    Sketch,
    Specimen,
    Survey,
)


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedVocabularyContract:
    def test_inherits_the_shared_contract(self, field_class):
        assert issubclass(field_class, ConceptFieldMixin)

    def test_one_slug_normalises_to_a_one_element_tuple(self, field_class):
        field = field_class(vocabulary="rock-type")
        assert field.vocabulary == ("rock-type",)
        assert field.get_limit_choices_to() == Q(scheme__slug__in=("rock-type",))

    def test_several_slugs_normalise_to_their_union_with_duplicates_collapsed(
        self, field_class
    ):
        field = field_class(vocabulary=["rock-type", "mineral", "rock-type"])
        assert field.vocabulary == ("rock-type", "mineral")
        assert field.get_limit_choices_to() == Q(
            scheme__slug__in=("rock-type", "mineral")
        )

    def test_an_omitted_vocabulary_sets_no_restriction_at_all(self, field_class):
        field = field_class()
        assert field.vocabulary == ()
        assert field.get_limit_choices_to() == {}

    def test_an_empty_slug_is_refused_by_name(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="")

    def test_a_non_string_slug_is_refused_by_name(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary=["mineral", 42])

    def test_a_consumer_supplied_limit_choices_to_is_refused(self, field_class):
        with pytest.raises(TypeError, match="limit_choices_to"):
            field_class(vocabulary="rock-type", limit_choices_to=Q(label="Granite"))

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
        _name, path, args, kwargs = field.deconstruct()

        assert kwargs["vocabulary"] == field.vocabulary
        assert "to" not in kwargs
        assert "limit_choices_to" not in kwargs
        assert "on_delete" not in kwargs
        assert "through" not in kwargs

        rebuilt = import_string(path)(*args, **kwargs)
        assert rebuilt.vocabulary == field.vocabulary
        assert rebuilt.get_limit_choices_to() == field.get_limit_choices_to()

    def test_clone_rebuilds_an_equivalent_field(self, field_class):
        field = field_class(vocabulary=["rock-type", "mineral"])
        assert field.clone().vocabulary == ("rock-type", "mineral")


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedRestrictionArguments:
    def test_collection_defaults_to_none(self, field_class):
        field = field_class(vocabulary="rock-type")
        assert field.collection is None

    def test_concepts_defaults_to_none(self, field_class):
        field = field_class(vocabulary="rock-type")
        assert field.concepts is None

    def test_branch_defaults_to_none(self, field_class):
        field = field_class(vocabulary="rock-type")
        assert field.branch is None

    def test_collection_normalises_and_stores_the_slug(self, field_class):
        field = field_class(vocabulary="rock-type", collection="core-samples")
        assert field.collection == "core-samples"

    def test_branch_normalises_and_stores_the_slug(self, field_class):
        field = field_class(vocabulary="rock-type", branch="igneous")
        assert field.branch == "igneous"

    def test_concepts_normalises_and_collapses_duplicates(self, field_class):
        field = field_class(
            vocabulary="rock-type", concepts=["granite", "basalt", "granite"]
        )
        assert field.concepts == ("granite", "basalt")

    def test_collection_rejects_a_non_string(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", collection=42)

    def test_collection_rejects_an_empty_string(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", collection="")

    def test_branch_rejects_a_non_string(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", branch=42)

    def test_branch_rejects_an_empty_string(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", branch="")

    def test_concepts_rejects_a_non_string_element(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", concepts=["granite", 42])

    def test_concepts_rejects_an_empty_string_element(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", concepts=["granite", ""])

    def test_concepts_rejects_an_empty_list(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", concepts=[])

    def test_concepts_accepts_a_single_slug_without_splitting_it(self, field_class):
        # Iterating the string would yield a slug per character, which every check here
        # would pass.
        field = field_class(vocabulary="rock-type", concepts="granite")
        assert field.concepts == ("granite",)


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

    def test_a_concepts_restricted_field_gets_the_restricted_default(self, field_class):
        field = field_class(vocabulary="rock-type", concepts=["granite", "basalt"])
        assert field.help_text == field_class.default_restricted_help_text
        assert field.help_text != field_class.default_help_text

    def test_a_branch_restricted_field_gets_the_restricted_default(self, field_class):
        field = field_class(vocabulary="rock-type", branch="igneous")
        assert field.help_text == field_class.default_restricted_help_text
        assert field.help_text != field_class.default_help_text

    def test_restricted_help_text_is_a_lazy_translatable_string(self, field_class):
        field = field_class(vocabulary="rock-type", branch="igneous")
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


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedRestrictionRequiresOneVocabulary:
    def test_a_restriction_naming_no_vocabulary_is_refused(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(branch="igneous")

    def test_a_restriction_naming_several_vocabularies_is_refused(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary=["rock-type", "mineral"], collection="core-samples")

    def test_a_restriction_naming_exactly_one_vocabulary_is_accepted(self, field_class):
        field = field_class(vocabulary="rock-type", collection="core-samples")
        assert field.collection == "core-samples"

    def test_no_restriction_naming_no_vocabulary_is_unaffected(self, field_class):
        field = field_class()
        assert field.vocabulary == ()

    def test_no_restriction_naming_several_vocabularies_is_unaffected(
        self, field_class
    ):
        field = field_class(vocabulary=["rock-type", "mineral"])
        assert field.vocabulary == ("rock-type", "mineral")


# An intersection and a union are equally plausible, so no reading is chosen.
@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedRestrictionExclusivity:
    def test_collection_and_concepts_together_are_refused(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(
                vocabulary="rock-type", collection="core-samples", concepts=["granite"]
            )

    def test_collection_and_branch_together_are_refused(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(
                vocabulary="rock-type", collection="core-samples", branch="igneous"
            )

    def test_concepts_and_branch_together_are_refused(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", concepts=["granite"], branch="igneous")

    def test_all_three_together_are_refused(self, field_class):
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(
                vocabulary="rock-type",
                collection="core-samples",
                concepts=["granite"],
                branch="igneous",
            )


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedRestrictionDeconstruct:
    def test_collection_is_emitted_and_survives_the_round_trip(self, field_class):
        field = field_class(vocabulary="rock-type", collection="core-samples")
        _name, path, args, kwargs = field.deconstruct()

        assert kwargs["collection"] == "core-samples"
        assert "concepts" not in kwargs
        assert "branch" not in kwargs

        rebuilt = import_string(path)(*args, **kwargs)
        assert rebuilt.collection == "core-samples"

    def test_concepts_is_emitted_and_survives_the_round_trip(self, field_class):
        field = field_class(vocabulary="rock-type", concepts=["granite", "basalt"])
        _name, path, args, kwargs = field.deconstruct()

        assert kwargs["concepts"] == ("granite", "basalt")
        assert "collection" not in kwargs
        assert "branch" not in kwargs

        rebuilt = import_string(path)(*args, **kwargs)
        assert rebuilt.concepts == ("granite", "basalt")

    def test_branch_is_emitted_and_survives_the_round_trip(self, field_class):
        field = field_class(vocabulary="rock-type", branch="igneous")
        _name, path, args, kwargs = field.deconstruct()

        assert kwargs["branch"] == "igneous"
        assert "collection" not in kwargs
        assert "concepts" not in kwargs

        rebuilt = import_string(path)(*args, **kwargs)
        assert rebuilt.branch == "igneous"

    def test_no_restriction_emits_none_of_the_three(self, field_class):
        field = field_class(vocabulary="rock-type")
        _name, _path, _args, kwargs = field.deconstruct()

        assert "collection" not in kwargs
        assert "concepts" not in kwargs
        assert "branch" not in kwargs

    def test_a_restricted_fields_deconstructed_kwargs_carry_no_limit_choices_to(
        self, field_class
    ):
        field = field_class(vocabulary="rock-type", collection="core-samples")
        _name, _path, _args, kwargs = field.deconstruct()
        assert "limit_choices_to" not in kwargs

    def test_clone_rebuilds_a_restricted_field(self, field_class):
        field = field_class(vocabulary="rock-type", branch="igneous")
        cloned = field.clone()
        assert cloned.branch == "igneous"


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedLimitChoicesToCallable:
    def test_get_limit_choices_to_returns_the_vocabulary_q(self, field_class):
        field = field_class(vocabulary="rock-type")
        assert field.get_limit_choices_to() == Q(scheme__slug__in=("rock-type",))

    def test_limit_choices_to_is_callable_when_a_vocabulary_is_named(self, field_class):
        field = field_class(vocabulary="rock-type")
        assert callable(field.remote_field.limit_choices_to)

    @pytest.mark.django_db
    def test_construction_issues_no_query(self, field_class):
        with CaptureQueriesContext(connection) as ctx:
            field_class(vocabulary="rock-type")
        assert len(ctx.captured_queries) == 0

    def test_no_vocabulary_named_sets_no_restriction_at_all(self, field_class):
        field = field_class()
        assert field.get_limit_choices_to() == {}
        assert field.remote_field.limit_choices_to == {}

    @pytest.mark.django_db
    def test_a_restriction_present_now_narrows_beyond_the_bare_vocabulary_q(
        self, field_class
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite",)
        )
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        field = field_class(vocabulary="rock-type", collection=collection.slug)
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert set(resolved) == set(members)
        assert outsider not in resolved


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
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        field = field_class(vocabulary="rock-type", collection=collection.slug)
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert set(resolved) == set(members)
        assert outsider not in resolved

    def test_a_same_named_collection_in_another_vocabulary_does_not_widen_the_field(
        self, field_class
    ):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        rock_collection, rock_members = collection_with_members(
            scheme=rock_scheme, labels=("Granite",)
        )
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        mineral_collection = CollectionFactory(
            scheme=mineral_scheme, name=rock_collection.name
        )
        assert mineral_collection.slug == rock_collection.slug
        mineral_concept = ConceptFactory(scheme=mineral_scheme, label="Quartz")
        mineral_collection.add(mineral_concept)

        field = field_class(vocabulary="rock-type", collection=rock_collection.slug)
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert set(resolved) == set(rock_members)
        assert mineral_concept not in resolved

    def test_a_concept_in_a_second_collection_too_is_not_duplicated(self, field_class):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite",)
        )
        other_collection = CollectionFactory(scheme=scheme, name="Display Samples")
        other_collection.add(members[0])

        field = field_class(vocabulary="rock-type", collection=collection.slug)
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert list(resolved.values_list("pk", flat=True)) == [members[0].pk]


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
        assert set(Concept.objects.complex_filter(field.get_limit_choices_to())) == set(
            members
        )

        newcomer = ConceptFactory(scheme=scheme, label="Basalt")
        collection.add(newcomer)

        resolved_again = Concept.objects.complex_filter(field.get_limit_choices_to())
        assert set(resolved_again) == {*members, newcomer}


@pytest.mark.django_db
@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestConceptsRestrictionResolves:
    def test_resolves_to_exactly_the_listed_concepts(self, field_class):
        scheme = ConceptSchemeFactory(name="Rock Type")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        field = field_class(vocabulary="rock-type", concepts=["granite", "basalt"])
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert set(resolved) == {granite, basalt}
        assert outsider not in resolved

    def test_a_same_slugged_concept_in_another_vocabulary_does_not_widen_the_field(
        self, field_class
    ):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        granite = ConceptFactory(scheme=rock_scheme, label="Granite")
        ConceptFactory(scheme=rock_scheme, label="Marble")  # unlisted, same vocabulary
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        mineral_granite = ConceptFactory(scheme=mineral_scheme, label="Granite")
        assert mineral_granite.slug == granite.slug

        field = field_class(vocabulary="rock-type", concepts=["granite"])
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert list(resolved) == [granite]
        assert mineral_granite not in resolved

    def test_a_slug_listed_twice_offers_the_concept_once(self, field_class):
        scheme = ConceptSchemeFactory(name="Rock Type")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        ConceptFactory(scheme=scheme, label="Marble")  # unlisted, same vocabulary

        field = field_class(vocabulary="rock-type", concepts=["granite", "granite"])
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert list(resolved) == [granite]


# A BROADER row's source is the narrower concept and its target the broader one, so
# walking down matches target and collects source.
class TestBranchClosure:
    @pytest.mark.django_db
    def test_a_three_level_tree_returns_root_plus_children_plus_grandchildren(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        child = ConceptFactory(scheme=scheme, label="Granite")
        grandchild = ConceptFactory(scheme=scheme, label="Porphyritic Granite")
        child.add_broader(root)
        grandchild.add_broader(child)

        closure = _branch_closure("rock-type", root.slug)

        assert closure == {root.pk, child.pk, grandchild.pk}

    @pytest.mark.django_db
    def test_a_root_with_no_children_returns_just_the_root(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Obsidian")

        closure = _branch_closure("rock-type", root.slug)

        assert closure == {root.pk}

    @pytest.mark.django_db
    def test_a_wide_level_returns_every_sibling(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        gabbro = ConceptFactory(scheme=scheme, label="Gabbro")
        granite.add_broader(root)
        basalt.add_broader(root)
        gabbro.add_broader(root)

        closure = _branch_closure("rock-type", root.slug)

        assert closure == {root.pk, granite.pk, basalt.pk, gabbro.pk}

    @pytest.mark.django_db
    def test_a_root_belonging_to_another_vocabulary_resolves_to_nothing(self):
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        mineral_root = ConceptFactory(scheme=mineral_scheme, label="Igneous")

        closure = _branch_closure("rock-type", mineral_root.slug)

        assert closure == set()


class TestBranchClosureCycles:
    @pytest.mark.django_db
    def test_a_two_edge_cycle_terminates_and_yields_each_concept_once(self):
        # A reversed broader edge is storable (only self-relations are refused), so
        # this is the shortest cycle. The alarm turns a hang in the seen-set logic
        # into a failure.
        scheme = ConceptSchemeFactory(name="Rock Type")
        alpha = ConceptFactory(scheme=scheme, label="Alpha")
        beta = ConceptFactory(scheme=scheme, label="Beta")
        alpha.add_broader(beta)
        beta.add_broader(alpha)

        def _raise_timeout(signum, frame):
            raise TimeoutError("branch closure did not terminate on a two-edge cycle")

        previous_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(5)
        try:
            closure = _branch_closure("rock-type", alpha.slug)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)

        assert closure == {alpha.pk, beta.pk}


@pytest.mark.django_db
@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestBranchRestrictionResolves:
    def test_resolves_to_exactly_the_closure(self, field_class):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        child = ConceptFactory(scheme=scheme, label="Granite")
        child.add_broader(root)
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        field = field_class(vocabulary="rock-type", branch=root.slug)
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert set(resolved) == {root, child}
        assert outsider not in resolved

    def test_a_same_slugged_root_in_another_vocabulary_does_not_widen_the_field(
        self, field_class
    ):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        rock_root = ConceptFactory(scheme=rock_scheme, label="Igneous")
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        mineral_root = ConceptFactory(scheme=mineral_scheme, label="Igneous")
        assert mineral_root.slug == rock_root.slug

        field = field_class(vocabulary="rock-type", branch=rock_root.slug)
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert list(resolved) == [rock_root]
        assert mineral_root not in resolved


@pytest.mark.django_db
@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestBranchRestrictionResolvesLive:
    def test_a_concept_added_below_the_root_after_construction_appears_on_the_next_read(
        self, field_class
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        field = field_class(vocabulary="rock-type", branch=root.slug)
        assert set(Concept.objects.complex_filter(field.get_limit_choices_to())) == {
            root
        }

        newcomer = ConceptFactory(scheme=scheme, label="Granite")
        newcomer.add_broader(root)

        resolved_again = Concept.objects.complex_filter(field.get_limit_choices_to())
        assert set(resolved_again) == {root, newcomer}


class TestConceptFieldConstruction:
    def test_fixes_to_concept(self):
        field = ConceptField(vocabulary="rock-type")
        assert field.remote_field.model == "controlled_vocabularies.Concept"

    def test_fixes_on_delete_to_protect(self):
        field = ConceptField(vocabulary="rock-type")
        assert field.remote_field.on_delete is PROTECT

    def test_single_slug_normalises_to_a_one_element_tuple(self):
        field = ConceptField(vocabulary="rock-type")
        assert field.vocabulary == ("rock-type",)
        assert field.get_limit_choices_to() == Q(scheme__slug__in=("rock-type",))

    def test_list_normalises_with_duplicates_collapsed_and_order_not_significant(self):
        field = ConceptField(vocabulary=["rock-type", "mineral", "rock-type"])
        assert field.vocabulary == ("rock-type", "mineral")
        assert field.get_limit_choices_to() == Q(
            scheme__slug__in=("rock-type", "mineral")
        )

    def test_omitted_vocabulary_normalises_to_empty_and_sets_no_restriction(self):
        field = ConceptField()
        assert field.vocabulary == ()
        assert field.get_limit_choices_to() == {}

    @pytest.mark.django_db
    def test_construction_issues_no_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            ConceptField(vocabulary="rock-type")
        assert len(ctx.captured_queries) == 0

    def test_rejects_consumer_supplied_on_delete(self):
        with pytest.raises(TypeError, match="on_delete"):
            ConceptField(vocabulary="rock-type", on_delete=PROTECT)

    def test_rejects_consumer_supplied_limit_choices_to(self):
        # The vocabulary constraint IS limit_choices_to, so accepting a consumer's
        # would silently discard either theirs or the constraint.
        with pytest.raises(TypeError, match="limit_choices_to"):
            ConceptField(vocabulary="rock-type", limit_choices_to=Q(label="Granite"))

    def test_rejects_non_string_vocabulary_element(self):
        with pytest.raises(TypeError, match="ConceptField"):
            ConceptField(vocabulary=["rock-type", 7])

    def test_rejects_an_empty_slug(self):
        with pytest.raises(TypeError, match="ConceptField"):
            ConceptField(vocabulary="")

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
    def test_deconstruct_omits_the_three_fixed_kwargs(self):
        field = ConceptField(vocabulary="rock-type")
        _name, _path, _args, kwargs = field.deconstruct()
        assert "to" not in kwargs
        assert "on_delete" not in kwargs
        assert "limit_choices_to" not in kwargs

    def test_deconstruct_adds_vocabulary(self):
        field = ConceptField(vocabulary="rock-type")
        _name, _path, _args, kwargs = field.deconstruct()
        assert kwargs["vocabulary"] == ("rock-type",)

    @pytest.mark.parametrize(
        "vocabulary", [None, "rock-type", ["rock-type", "mineral"]]
    )
    def test_round_trip_rebuilds_an_equivalent_field(self, vocabulary):
        # A migration written before #111 records vocabulary as a bare string and has to
        # keep replaying.
        field = ConceptField(vocabulary=vocabulary)
        _name, path, args, kwargs = field.deconstruct()
        field_class = import_string(path)
        rebuilt = field_class(*args, **kwargs)
        assert rebuilt.vocabulary == field.vocabulary
        assert rebuilt.get_limit_choices_to() == field.get_limit_choices_to()
        assert rebuilt.remote_field.on_delete is PROTECT

    def test_clone_rebuilds_without_error(self):
        field = ConceptField(vocabulary="rock-type")
        cloned = field.clone()
        assert cloned.vocabulary == ("rock-type",)


class TestConceptsFieldConstruction:
    def test_single_slug_normalises_to_a_one_element_tuple(self):
        field = ConceptsField(vocabulary="rock-type")
        assert field.vocabulary == ("rock-type",)
        assert field.get_limit_choices_to() == Q(scheme__slug__in=("rock-type",))

    def test_list_normalises_with_duplicates_collapsed_and_order_not_significant(self):
        field = ConceptsField(vocabulary=["gcmd", "agu-index", "gcmd"])
        assert set(field.vocabulary) == {"gcmd", "agu-index"}
        assert len(field.vocabulary) == 2
        assert field.get_limit_choices_to() == Q(scheme__slug__in=field.vocabulary)

    def test_omitted_vocabulary_normalises_to_empty_and_sets_no_restriction(self):
        field = ConceptsField()
        assert field.vocabulary == ()
        assert field.get_limit_choices_to() == {}

    def test_fixes_to_concept(self):
        field = ConceptsField(vocabulary="rock-type")
        assert field.remote_field.model == "controlled_vocabularies.Concept"

    @pytest.mark.django_db
    def test_construction_issues_no_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            ConceptsField(vocabulary="rock-type")
            ConceptsField(vocabulary=["gcmd", "agu-index"])
            ConceptsField()
        assert len(ctx.captured_queries) == 0

    def test_rejects_consumer_supplied_limit_choices_to(self):
        with pytest.raises(TypeError, match="limit_choices_to"):
            ConceptsField(vocabulary="rock-type", limit_choices_to=Q(label="Granite"))

    def test_rejects_consumer_supplied_through(self):
        # A consumer-supplied through model would silently drop the PROTECT guard.
        with pytest.raises(TypeError, match="through"):
            ConceptsField(
                vocabulary="rock-type", through="controlled_vocabularies.Concept"
            )

    def test_rejects_non_string_vocabulary_element(self):
        with pytest.raises(TypeError, match="ConceptsField"):
            ConceptsField(vocabulary=["mineral", 42])

    def test_rejects_an_empty_slug(self):
        with pytest.raises(TypeError, match="ConceptsField"):
            ConceptsField(vocabulary=["mineral", ""])

    def test_help_text_has_a_translatable_default(self):
        field = ConceptsField(vocabulary="rock-type")
        assert isinstance(field.help_text, Promise)
        assert str(field.help_text)

    def test_help_text_default_is_overridable(self):
        field = ConceptsField(vocabulary="rock-type", help_text="Pick some rock types.")
        assert field.help_text == "Pick some rock types."


class TestConceptsFieldDeconstruct:
    def test_deconstruct_omits_to_and_limit_choices_to(self):
        field = ConceptsField(vocabulary="rock-type")
        _name, _path, _args, kwargs = field.deconstruct()
        assert "to" not in kwargs
        assert "limit_choices_to" not in kwargs
        assert "through" not in kwargs

    def test_deconstruct_adds_vocabulary(self):
        field = ConceptsField(vocabulary=["gcmd", "agu-index"])
        _name, _path, _args, kwargs = field.deconstruct()
        assert set(kwargs["vocabulary"]) == {"gcmd", "agu-index"}

    @pytest.mark.parametrize("vocabulary", ["rock-type", ["gcmd", "agu-index"], None])
    def test_round_trip_rebuilds_an_equivalent_field(self, vocabulary):
        field = ConceptsField(vocabulary=vocabulary)
        _name, path, args, kwargs = field.deconstruct()
        field_class = import_string(path)
        rebuilt = field_class(*args, **kwargs)
        assert rebuilt.vocabulary == field.vocabulary
        assert rebuilt.get_limit_choices_to() == field.get_limit_choices_to()

    def test_clone_rebuilds_without_error(self):
        field = ConceptsField(vocabulary="rock-type")
        cloned = field.clone()
        assert cloned.vocabulary == ("rock-type",)


class TestConceptsFieldMembershipModel:
    def test_membership_model_is_named_owner_fieldname(self):
        field = Deposit._meta.get_field("rock_types")
        assert field.remote_field.through._meta.object_name == "Deposit_rock_types"

    def test_membership_models_concept_fk_is_protect(self):
        field = Deposit._meta.get_field("rock_types")
        concept_fk = field.remote_field.through._meta.get_field("concept")
        assert concept_fk.remote_field.on_delete is PROTECT

    def test_membership_models_owner_fk_is_cascade(self):
        field = Deposit._meta.get_field("rock_types")
        owner_fk = field.remote_field.through._meta.get_field("deposit")
        assert owner_fk.remote_field.on_delete is CASCADE

    def test_deconstruct_still_emits_no_through_once_bound(self):
        # Meta.auto_created keeps ManyToManyField.deconstruct() from emitting it.
        field = Deposit._meta.get_field("rock_types")
        _name, _path, _args, kwargs = field.deconstruct()
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


class TestConceptsFieldMigrations:
    @pytest.mark.django_db
    def test_models_are_queryable(self):
        assert Deposit.objects.count() == 0
        assert Survey.objects.count() == 0

    @pytest.mark.django_db
    def test_makemigrations_check_is_clean(self):
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)


class TestConceptsFieldConsumingModels:
    @pytest.mark.django_db
    def test_all_six_models_are_queryable(self):
        assert Deposit.objects.count() == 0
        assert Survey.objects.count() == 0
        assert Outcrop.objects.count() == 0
        assert RockSample.objects.count() == 0
        assert FieldNote.objects.count() == 0
        assert Photograph.objects.count() == 0

    @pytest.mark.django_db
    def test_makemigrations_check_is_clean(self):
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)

    @pytest.mark.django_db
    def test_all_six_factories_build_valid_saved_records(self):
        assert DepositFactory().pk is not None
        assert SurveyFactory().pk is not None
        assert OutcropFactory().pk is not None
        assert RockSampleFactory().pk is not None
        assert FieldNoteFactory().pk is not None
        assert PhotographFactory().pk is not None

    @pytest.mark.django_db
    def test_optional_field_with_related_name_reads_back_from_both_sides(self):
        outcrop = OutcropFactory()
        scheme = ConceptSchemeFactory(name="Mineral")
        concept = ConceptFactory(scheme=scheme)

        outcrop.minerals.add(concept)

        assert concept in outcrop.minerals.all()
        assert outcrop in concept.outcrops.all()

    @pytest.mark.django_db
    def test_both_field_types_on_one_model_coexist_without_clashing(self):
        scheme = ConceptSchemeFactory(name="Mineral")
        primary = ConceptFactory(scheme=scheme)
        associated = ConceptFactory(scheme=scheme)
        sample = RockSampleFactory(primary_mineral=primary)

        sample.associated_minerals.add(associated)

        reloaded = RockSample.objects.get(pk=sample.pk)
        assert reloaded.primary_mineral == primary
        assert associated in reloaded.associated_minerals.all()

    def test_field_naming_two_vocabularies_restricts_to_their_union(self):
        field = FieldNote._meta.get_field("keywords")
        assert field.vocabulary == ("rock-type", "mineral")
        assert field.get_limit_choices_to() == Q(
            scheme__slug__in=("rock-type", "mineral")
        )

    def test_field_naming_no_vocabulary_sets_no_restriction(self):
        field = Photograph._meta.get_field("keywords")
        assert field.vocabulary == ()
        assert field.get_limit_choices_to() == {}

    @pytest.mark.django_db
    def test_field_naming_no_vocabulary_still_attaches_a_concept_from_any_scheme(self):
        photograph = PhotographFactory()
        scheme = ConceptSchemeFactory(name="Anything")
        concept = ConceptFactory(scheme=scheme)

        photograph.keywords.add(concept)

        assert concept in photograph.keywords.all()

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


class TestConceptsFieldAttachAndReadBack:
    @pytest.mark.django_db
    def test_two_attached_concepts_are_returned_and_no_third(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        first = ConceptFactory(scheme=scheme)
        second = ConceptFactory(scheme=scheme)
        third = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()

        deposit.rock_types.add(first, second)

        reloaded = Deposit.objects.get(pk=deposit.pk)
        assert set(reloaded.rock_types.all()) == {first, second}
        assert third not in reloaded.rock_types.all()

    @pytest.mark.django_db
    def test_attaching_an_already_held_concept_holds_it_exactly_once(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(concept)

        deposit.rock_types.add(concept)

        assert list(deposit.rock_types.all()) == [concept]

    @pytest.mark.django_db
    def test_removing_one_of_two_leaves_the_other_attached_and_the_concept_intact(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        kept = ConceptFactory(scheme=scheme)
        removed = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(kept, removed)

        deposit.rock_types.remove(removed)

        assert set(deposit.rock_types.all()) == {kept}
        assert Concept.objects.filter(pk=removed.pk).exists()

    @pytest.mark.django_db
    def test_reverse_accessor_from_the_concept_side_returns_the_record(self):
        outcrop = OutcropFactory()
        scheme = ConceptSchemeFactory(name="Mineral")
        concept = ConceptFactory(scheme=scheme)
        other_concept = ConceptFactory(scheme=scheme)

        outcrop.minerals.add(concept)

        assert outcrop in concept.outcrops.all()
        assert outcrop not in other_concept.outcrops.all()


class TestConceptsFieldWritePathVocabularyCheck:
    @pytest.mark.django_db
    def test_add_of_a_concept_from_an_unnamed_vocabulary_is_refused_and_the_set_is_unchanged(
        self,
    ):
        other_scheme = ConceptSchemeFactory(name="Mineral")
        other_concept = ConceptFactory(scheme=other_scheme)
        deposit = DepositFactory()

        # ManyRelatedManager.add() runs in transaction.atomic(savepoint=False), so a
        # raise poisons the test's own transaction unless the call has a savepoint
        # of its own to roll back to.
        with pytest.raises(ValidationError), transaction.atomic():
            deposit.rock_types.add(other_concept)

        assert list(deposit.rock_types.all()) == []

    @pytest.mark.django_db
    def test_refusal_message_names_the_expected_vocabulary(self):
        other_scheme = ConceptSchemeFactory(name="Mineral")
        other_concept = ConceptFactory(scheme=other_scheme)
        deposit = DepositFactory()

        with pytest.raises(ValidationError) as excinfo:
            deposit.rock_types.add(other_concept)

        assert any("rock-type" in message for message in excinfo.value.messages)

    @pytest.mark.django_db
    def test_set_carrying_a_mix_is_refused_whole_and_the_set_is_unchanged_afterwards(
        self,
    ):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        kept = ConceptFactory(scheme=rock_scheme)
        other_scheme = ConceptSchemeFactory(name="Mineral")
        other_concept = ConceptFactory(scheme=other_scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(kept)

        with pytest.raises(ValidationError), transaction.atomic():
            deposit.rock_types.set([kept, other_concept])

        assert set(deposit.rock_types.all()) == {kept}

    @pytest.mark.django_db
    def test_several_concepts_all_from_the_named_vocabulary_are_attached(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        first = ConceptFactory(scheme=scheme)
        second = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()

        deposit.rock_types.add(first, second)

        assert set(deposit.rock_types.all()) == {first, second}

    @pytest.mark.django_db
    def test_the_default_reverse_accessor_refuses_a_concept_from_an_unnamed_vocabulary(
        self,
    ):
        # Django gives every relation a live reverse accessor unless the declaration
        # hides it, so this path reaches the same through model and must be refused
        # on the same terms. Deposit.rock_types names no related_name.
        other_scheme = ConceptSchemeFactory(name="Mineral")
        other_concept = ConceptFactory(scheme=other_scheme)
        deposit = DepositFactory()

        with pytest.raises(ValidationError), transaction.atomic():
            other_concept.deposit_set.add(deposit)

        assert list(deposit.rock_types.all()) == []

    @pytest.mark.django_db
    def test_a_named_reverse_accessor_refuses_a_concept_from_an_unnamed_vocabulary(
        self,
    ):
        outcrop = OutcropFactory()
        other_concept = ConceptFactory(scheme=ConceptSchemeFactory(name="Rock Type"))

        with pytest.raises(ValidationError), transaction.atomic():
            other_concept.outcrops.add(outcrop)

        assert list(outcrop.minerals.all()) == []

    @pytest.mark.django_db
    def test_the_reverse_accessor_attaches_a_concept_from_the_named_vocabulary(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()

        concept.deposit_set.add(deposit)

        assert list(deposit.rock_types.all()) == [concept]

    def test_a_field_naming_no_vocabulary_connects_no_receiver_for_its_through_model(
        self,
    ):
        through = Photograph._meta.get_field("keywords").remote_field.through
        assert not m2m_changed.has_listeners(sender=through)


class TestConceptsFieldCollectionRestrictionWritePath:
    @pytest.mark.django_db
    def test_forward_add_of_a_non_member_is_refused_and_the_set_is_unchanged(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        _collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite",)
        )
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        drill_core = DrillCoreFactory()
        drill_core.rock_types.add(members[0])

        with pytest.raises(ValidationError), transaction.atomic():
            drill_core.rock_types.add(outsider)

        assert list(drill_core.rock_types.all()) == [members[0]]

    @pytest.mark.django_db
    def test_the_refusal_names_the_collection(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core Samples", labels=("Granite",))
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        drill_core = DrillCoreFactory()

        with pytest.raises(ValidationError) as excinfo:
            drill_core.rock_types.add(outsider)

        assert any("core-samples" in message for message in excinfo.value.messages)

    @pytest.mark.django_db
    def test_the_reverse_accessor_refuses_a_non_member(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core Samples", labels=("Granite",))
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        drill_core = DrillCoreFactory()

        with pytest.raises(ValidationError), transaction.atomic():
            outsider.drill_cores.add(drill_core)

        assert list(drill_core.rock_types.all()) == []

    @pytest.mark.django_db
    def test_the_reverse_accessor_attaches_a_member(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        _collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite",)
        )
        drill_core = DrillCoreFactory()

        members[0].drill_cores.add(drill_core)

        assert list(drill_core.rock_types.all()) == [members[0]]

    @pytest.mark.django_db
    def test_a_set_carrying_a_mix_is_refused_whole_and_the_set_is_unchanged_afterwards(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        _collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite", "Basalt")
        )
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        drill_core = DrillCoreFactory()
        drill_core.rock_types.add(members[0])

        with pytest.raises(ValidationError), transaction.atomic():
            drill_core.rock_types.set([members[1], outsider])

        assert set(drill_core.rock_types.all()) == {members[0]}

    @pytest.mark.django_db
    def test_several_members_all_attach(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        _collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite", "Basalt")
        )
        drill_core = DrillCoreFactory()

        drill_core.rock_types.add(*members)

        assert set(drill_core.rock_types.all()) == set(members)


class TestConceptsFieldConceptsRestrictionWritePath:
    @pytest.mark.django_db
    def test_forward_add_of_an_unlisted_concept_is_refused_and_the_set_is_unchanged(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        chip_tray = ChipTrayFactory()
        chip_tray.rock_types.add(granite)

        with pytest.raises(ValidationError), transaction.atomic():
            chip_tray.rock_types.add(outsider)

        assert list(chip_tray.rock_types.all()) == [granite]

    @pytest.mark.django_db
    def test_the_refusal_names_the_permitted_concepts(self):
        # Naming the wider vocabulary would say nothing about why a same-vocabulary
        # concept was rejected.
        scheme = ConceptSchemeFactory(name="Rock Type")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        chip_tray = ChipTrayFactory()

        with pytest.raises(ValidationError) as excinfo:
            chip_tray.rock_types.add(outsider)

        assert any("granite, basalt" in message for message in excinfo.value.messages)
        assert not any("rock-type" in message for message in excinfo.value.messages)

    @pytest.mark.django_db
    def test_the_reverse_accessor_refuses_an_unlisted_concept(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        chip_tray = ChipTrayFactory()

        with pytest.raises(ValidationError), transaction.atomic():
            outsider.chip_trays.add(chip_tray)

        assert list(chip_tray.rock_types.all()) == []

    @pytest.mark.django_db
    def test_the_reverse_accessor_attaches_a_listed_concept(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        chip_tray = ChipTrayFactory()

        granite.chip_trays.add(chip_tray)

        assert list(chip_tray.rock_types.all()) == [granite]

    @pytest.mark.django_db
    def test_a_set_carrying_a_mix_is_refused_whole_and_the_set_is_unchanged_afterwards(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        chip_tray = ChipTrayFactory()
        chip_tray.rock_types.add(granite)

        with pytest.raises(ValidationError), transaction.atomic():
            chip_tray.rock_types.set([basalt, outsider])

        assert set(chip_tray.rock_types.all()) == {granite}

    @pytest.mark.django_db
    def test_both_listed_concepts_attach(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        chip_tray = ChipTrayFactory()

        chip_tray.rock_types.add(granite, basalt)

        assert set(chip_tray.rock_types.all()) == {granite, basalt}


class TestConceptsFieldBranchRestrictionWritePath:
    @pytest.mark.django_db
    def test_forward_add_of_a_sibling_branch_concept_is_refused_and_the_set_is_unchanged(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        child = ConceptFactory(scheme=scheme, label="Granite")
        child.add_broader(root)
        sibling_root = ConceptFactory(scheme=scheme, label="Sedimentary")
        sibling_child = ConceptFactory(scheme=scheme, label="Sandstone")
        sibling_child.add_broader(sibling_root)
        branch_tray = BranchTrayFactory()
        branch_tray.rock_types.add(child)

        with pytest.raises(ValidationError), transaction.atomic():
            branch_tray.rock_types.add(sibling_child)

        assert list(branch_tray.rock_types.all()) == [child]

    @pytest.mark.django_db
    def test_the_refusal_names_the_branch_root(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        ConceptFactory(scheme=scheme, label="Igneous")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        branch_tray = BranchTrayFactory()

        with pytest.raises(ValidationError) as excinfo:
            branch_tray.rock_types.add(outsider)

        assert any("igneous" in message for message in excinfo.value.messages)

    @pytest.mark.django_db
    def test_the_reverse_accessor_refuses_a_non_descendant(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        ConceptFactory(scheme=scheme, label="Igneous")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        branch_tray = BranchTrayFactory()

        with pytest.raises(ValidationError), transaction.atomic():
            outsider.branch_trays.add(branch_tray)

        assert list(branch_tray.rock_types.all()) == []

    @pytest.mark.django_db
    def test_the_reverse_accessor_attaches_a_descendant(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        child = ConceptFactory(scheme=scheme, label="Granite")
        child.add_broader(root)
        branch_tray = BranchTrayFactory()

        child.branch_trays.add(branch_tray)

        assert list(branch_tray.rock_types.all()) == [child]

    @pytest.mark.django_db
    def test_a_set_carrying_a_mix_is_refused_whole_and_the_set_is_unchanged_afterwards(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        child = ConceptFactory(scheme=scheme, label="Granite")
        second_child = ConceptFactory(scheme=scheme, label="Basalt")
        child.add_broader(root)
        second_child.add_broader(root)
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        branch_tray = BranchTrayFactory()
        branch_tray.rock_types.add(child)

        with pytest.raises(ValidationError), transaction.atomic():
            branch_tray.rock_types.set([second_child, outsider])

        assert set(branch_tray.rock_types.all()) == {child}

    @pytest.mark.django_db
    def test_several_descendants_all_attach(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        child = ConceptFactory(scheme=scheme, label="Granite")
        second_child = ConceptFactory(scheme=scheme, label="Basalt")
        child.add_broader(root)
        second_child.add_broader(root)
        branch_tray = BranchTrayFactory()

        branch_tray.rock_types.add(child, second_child)

        assert set(branch_tray.rock_types.all()) == {child, second_child}


class TestConceptsFieldSeveralVocabulariesWritePath:
    @pytest.mark.django_db
    def test_a_concept_from_either_named_vocabulary_attaches(self):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        rock_concept = ConceptFactory(scheme=rock_scheme)
        mineral_concept = ConceptFactory(scheme=mineral_scheme)
        field_note = FieldNoteFactory()

        field_note.keywords.add(rock_concept, mineral_concept)

        assert set(field_note.keywords.all()) == {rock_concept, mineral_concept}

    @pytest.mark.django_db
    def test_a_concept_from_an_unnamed_third_vocabulary_is_refused_naming_both_expected_vocabularies(
        self,
    ):
        other_scheme = ConceptSchemeFactory(name="Fossil")
        other_concept = ConceptFactory(scheme=other_scheme)
        field_note = FieldNoteFactory()

        with pytest.raises(ValidationError) as excinfo, transaction.atomic():
            field_note.keywords.add(other_concept)

        message = " ".join(excinfo.value.messages)
        assert "rock-type" in message
        assert "mineral" in message
        assert list(field_note.keywords.all()) == []


class TestConceptsFieldNoVocabularyWritePath:
    @pytest.mark.django_db
    def test_concepts_from_several_distinct_vocabularies_all_attach_and_none_is_refused(
        self,
    ):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        fossil_scheme = ConceptSchemeFactory(name="Fossil")
        rock_concept = ConceptFactory(scheme=rock_scheme)
        mineral_concept = ConceptFactory(scheme=mineral_scheme)
        fossil_concept = ConceptFactory(scheme=fossil_scheme)
        photograph = PhotographFactory()

        photograph.keywords.add(rock_concept, mineral_concept, fossil_concept)

        assert set(photograph.keywords.all()) == {
            rock_concept,
            mineral_concept,
            fossil_concept,
        }


class DepositForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``Deposit``."""

    class Meta:
        model = Deposit
        fields = ["name", "rock_types"]


class TestConceptsFieldFormChoices:
    @pytest.mark.django_db
    def test_form_field_offers_only_the_named_vocabularys_concepts(self):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        matching_concept = ConceptFactory(scheme=rock_scheme)
        other_scheme = ConceptSchemeFactory(name="Mineral")
        other_concept = ConceptFactory(scheme=other_scheme)

        form = DepositForm()
        choices = list(form.fields["rock_types"].queryset)

        assert matching_concept in choices
        assert other_concept not in choices

    @pytest.mark.django_db
    def test_submission_carrying_a_concept_from_an_unnamed_vocabulary_is_rejected(self):
        other_scheme = ConceptSchemeFactory(name="Mineral")
        other_concept = ConceptFactory(scheme=other_scheme)

        form = DepositForm(
            data={"name": "Wrong vocabulary", "rock_types": [other_concept.pk]}
        )

        assert not form.is_valid()
        assert "rock_types" in form.errors
        assert Deposit.objects.count() == 0

    @pytest.mark.django_db
    def test_valid_submission_saves_and_the_memberships_appear(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)

        form = DepositForm(data={"name": "Granite deposit", "rock_types": [concept.pk]})

        assert form.is_valid(), form.errors
        deposit = form.save()

        assert concept in deposit.rock_types.all()


class FieldNoteForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``FieldNote``."""

    class Meta:
        model = FieldNote
        fields = ["name", "keywords"]


class TestConceptsFieldSeveralVocabulariesFormChoices:
    @pytest.mark.django_db
    def test_form_field_offers_the_concepts_of_both_named_vocabularies_and_no_others(
        self,
    ):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        other_scheme = ConceptSchemeFactory(name="Fossil")
        rock_concept = ConceptFactory(scheme=rock_scheme)
        mineral_concept = ConceptFactory(scheme=mineral_scheme)
        other_concept = ConceptFactory(scheme=other_scheme)

        form = FieldNoteForm()
        choices = list(form.fields["keywords"].queryset)

        assert rock_concept in choices
        assert mineral_concept in choices
        assert other_concept not in choices


class PhotographForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``Photograph``."""

    class Meta:
        model = Photograph
        fields = ["name", "keywords"]


class TestConceptsFieldNoVocabularyFormChoices:
    @pytest.mark.django_db
    def test_form_field_offers_every_concept_in_the_database(self):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        mineral_scheme = ConceptSchemeFactory(name="Mineral")
        rock_concept = ConceptFactory(scheme=rock_scheme)
        mineral_concept = ConceptFactory(scheme=mineral_scheme)

        form = PhotographForm()
        choices = list(form.fields["keywords"].queryset)

        assert set(choices) == {rock_concept, mineral_concept}


class TestConceptsFieldDeleteGuard:
    @pytest.mark.django_db
    def test_deleting_a_held_concept_is_refused(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(concept)

        with pytest.raises(ProtectedError):
            concept.delete()

        assert Concept.objects.filter(pk=concept.pk).exists()
        assert Deposit.objects.filter(pk=deposit.pk).exists()
        assert concept in deposit.rock_types.all()

    @pytest.mark.django_db
    def test_bulk_queryset_delete_of_a_held_concept_is_refused(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(concept)

        with pytest.raises(ProtectedError):
            Concept.objects.filter(pk=concept.pk).delete()

        assert Concept.objects.filter(pk=concept.pk).exists()
        assert concept in deposit.rock_types.all()

    @pytest.mark.django_db
    def test_deleting_the_scheme_holding_a_held_concept_is_refused(self):
        # Concept.scheme cascades, so deleting the scheme tries to cascade-delete the
        # concept and meets the same PROTECT on the way down.
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(concept)

        with pytest.raises(ProtectedError):
            scheme.delete()

        assert ConceptScheme.objects.filter(pk=scheme.pk).exists()
        assert Concept.objects.filter(pk=concept.pk).exists()
        assert concept in deposit.rock_types.all()

    @pytest.mark.django_db
    def test_a_concept_no_record_holds_deletes_cleanly(self):
        concept = ConceptFactory()

        concept.delete()

        assert not Concept.objects.filter(pk=concept.pk).exists()

    @pytest.mark.django_db
    def test_deleting_the_consuming_record_removes_only_its_memberships_and_every_concept_survives(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        first = ConceptFactory(scheme=scheme)
        second = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(first, second)
        through = Deposit._meta.get_field("rock_types").remote_field.through

        deposit.delete()

        assert not Deposit.objects.filter(pk=deposit.pk).exists()
        assert not through.objects.filter(concept__in=[first, second]).exists()
        assert Concept.objects.filter(pk=first.pk).exists()
        assert Concept.objects.filter(pk=second.pk).exists()

    @pytest.mark.django_db
    def test_a_concept_detached_from_every_record_that_held_it_then_deletes_cleanly(
        self,
    ):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()
        deposit.rock_types.add(concept)

        deposit.rock_types.remove(concept)
        concept.delete()

        assert not Concept.objects.filter(pk=concept.pk).exists()


class TestConceptsFieldNoVocabularyDeleteGuard:
    @pytest.mark.django_db
    def test_deleting_a_concept_held_by_a_field_naming_no_vocabulary_is_refused(self):
        scheme = ConceptSchemeFactory(name="Anything")
        concept = ConceptFactory(scheme=scheme)
        photograph = PhotographFactory()
        photograph.keywords.add(concept)

        with pytest.raises(ProtectedError):
            concept.delete()

        assert Concept.objects.filter(pk=concept.pk).exists()
        assert Photograph.objects.filter(pk=photograph.pk).exists()
        assert concept in photograph.keywords.all()


class TestConceptsFieldLabelAndUriAccessors:
    @pytest.mark.django_db
    def test_labels_accessor_returns_the_active_languages_label_for_each_attached_concept(
        self, multilingual_scheme
    ):
        concepts = list(multilingual_scheme.concepts.all())
        multilingual_concept = next(
            c for c in concepts if c.labels.filter(language="de").exists()
        )
        other_concept = next(c for c in concepts if c.pk != multilingual_concept.pk)
        photograph = PhotographFactory()
        photograph.keywords.add(multilingual_concept, other_concept)

        with translation.override("de"):
            expected = {
                multilingual_concept.display_label(),
                other_concept.display_label(),
            }
            assert set(photograph.get_keywords_labels()) == expected

    @pytest.mark.django_db
    def test_labels_accessor_falls_back_to_the_vocabulary_default(
        self, single_language_scheme
    ):
        concept = single_language_scheme.concepts.first()
        photograph = PhotographFactory()
        photograph.keywords.add(concept)

        with translation.override("fr"):
            assert photograph.get_keywords_labels() == [concept.display_label()]

    @pytest.mark.django_db
    def test_uris_accessor_returns_each_attached_concepts_own_uri_unchanged(
        self, multilingual_scheme
    ):
        concepts = list(multilingual_scheme.concepts.all())
        photograph = PhotographFactory()
        photograph.keywords.add(*concepts)

        assert set(photograph.get_keywords_uris()) == {
            concept.uri for concept in concepts
        }

    @pytest.mark.django_db
    def test_both_accessors_return_an_empty_list_when_nothing_is_attached(self):
        photograph = PhotographFactory()

        assert photograph.get_keywords_labels() == []
        assert photograph.get_keywords_uris() == []

    def test_both_accessors_return_an_empty_list_on_an_unsaved_record_rather_than_raising(
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


# Survey's two required fields trigger one install of the full_clean wrapper between
# them, so a wrapper closed over the triggering field would leave the other unenforced.
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
        concept = ConceptFactory(scheme=scheme)
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
        concept = ConceptFactory(scheme=scheme)
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

    @pytest.mark.django_db
    def test_a_required_fields_form_half_rejects_an_empty_selection(self):
        form = DepositForm(data={"name": "Granite deposit", "rock_types": []})

        assert not form.is_valid()
        assert "rock_types" in form.errors

    @pytest.mark.django_db
    def test_an_optional_fields_form_half_accepts_an_empty_selection(self):
        form = OutcropForm(data={"name": "Bare outcrop", "minerals": []})

        assert form.is_valid(), form.errors

    @pytest.mark.django_db
    def test_a_saved_records_valid_submission_is_accepted_though_its_relation_is_still_empty(
        self,
    ):
        # #124: ModelForm calls instance.full_clean() before save_m2m(), so a saved
        # record's relation is still empty when the installed check runs. It must not
        # read that as a refusal of a submission that would have populated it.
        scheme = ConceptSchemeFactory(name="Rock Type", slug="rock-type")
        concept = ConceptFactory(scheme=scheme)
        deposit = DepositFactory()
        assert not deposit.rock_types.exists()

        form = DepositForm(
            data={"name": deposit.name, "rock_types": [concept.pk]}, instance=deposit
        )

        assert form.is_valid(), form.errors

    @pytest.mark.django_db
    def test_a_saved_records_empty_submission_is_still_refused(self):
        # The form field's own `required` still has to do this job once the
        # model-level check defers to it during a ModelForm's own clean.
        deposit = DepositFactory()

        form = DepositForm(
            data={"name": deposit.name, "rock_types": []}, instance=deposit
        )

        assert not form.is_valid()
        assert "rock_types" in form.errors

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

        assert Parent.__dict__["full_clean"]._concepts_field_required_set_check
        assert "full_clean" not in Child.__dict__
        assert {
            field.name
            for field in Child._meta.get_fields()
            if isinstance(field, ConceptsField)
        } == {
            "firsts",
            "seconds",
        }


class TestConceptFieldMigrations:
    @pytest.mark.django_db
    def test_models_are_queryable(self):
        assert Specimen.objects.count() == 0
        assert Sample.objects.count() == 0
        assert Artifact.objects.count() == 0

    @pytest.mark.django_db
    def test_makemigrations_check_is_clean(self):
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)


class TestConceptFieldCollectionRestrictionMigrations:
    @pytest.mark.django_db
    def test_models_are_queryable(self):
        assert CoreSample.objects.count() == 0
        assert DrillCore.objects.count() == 0

    @pytest.mark.django_db
    def test_makemigrations_check_is_clean_across_all_apps(self):
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)


class TestConceptFieldFactories:
    @pytest.mark.django_db
    def test_borehole_factory_leaves_the_optional_field_unset_by_default(self):
        borehole = BoreholeFactory()
        assert borehole.pk is not None
        assert borehole.dominant_material is None

    @pytest.mark.django_db
    def test_sketch_factory_leaves_the_optional_field_unset_by_default(self):
        sketch = SketchFactory()
        assert sketch.pk is not None
        assert sketch.subject is None

    @pytest.mark.django_db
    def test_specimen_factory_builds_a_required_concept(self):
        specimen = SpecimenFactory()
        assert specimen.pk is not None
        assert specimen.rock_type is not None

    @pytest.mark.django_db
    def test_sample_factory_leaves_the_optional_field_unset_by_default(self):
        sample = SampleFactory()
        assert sample.pk is not None
        assert sample.mineral is None

    @pytest.mark.django_db
    def test_artifact_factory_leaves_the_optional_field_unset_by_default(self):
        artifact = ArtifactFactory()
        assert artifact.pk is not None
        assert artifact.mineral is None

    @pytest.mark.django_db
    def test_artifact_keeps_its_own_get_mineral_label(self):
        artifact = ArtifactFactory()
        assert (
            artifact.get_mineral_label() == "this artifact's own label, not the field's"
        )


class TestConceptVocabularyFixtures:
    @pytest.mark.django_db
    def test_multilingual_scheme_has_one_concept_with_a_second_language_label(
        self, multilingual_scheme
    ):
        assert multilingual_scheme.concepts.count() == 2
        labelled = [c for c in multilingual_scheme.concepts.all() if c.labels.exists()]
        assert len(labelled) == 1
        assert labelled[0].labels.filter(language="de").exists()

    @pytest.mark.django_db
    def test_single_language_scheme_has_no_extra_labels(self, single_language_scheme):
        assert single_language_scheme.concepts.count() == 2
        assert not any(c.labels.exists() for c in single_language_scheme.concepts.all())

    @pytest.mark.django_db
    def test_the_two_schemes_are_distinct(
        self, multilingual_scheme, single_language_scheme
    ):
        assert multilingual_scheme.pk != single_language_scheme.pk


class TestConceptFieldRoundTrip:
    @pytest.mark.django_db
    def test_saving_and_reloading_returns_the_same_concept(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        specimen = SpecimenFactory(rock_type=concept)

        reloaded = Specimen.objects.get(pk=specimen.pk)

        assert reloaded.rock_type == concept

    @pytest.mark.django_db
    def test_optional_field_with_nothing_attached_validates_and_saves(self):
        sample = Sample(name="Unclassified sample")

        sample.full_clean()
        sample.save()

        assert sample.pk is not None
        assert sample.mineral is None

    @pytest.mark.django_db
    def test_makemigrations_check_stays_clean_after_declaring_and_saving(self):
        ConceptFactory()
        SpecimenFactory()

        call_command("makemigrations", "--check", "--dry-run", verbosity=0)


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


class TestConceptFieldValidation:
    @pytest.mark.django_db
    def test_full_clean_rejects_a_concept_from_another_vocabulary(self):
        other_scheme = ConceptSchemeFactory(name="Mineral")
        other_concept = ConceptFactory(scheme=other_scheme)
        specimen = Specimen(name="Wrong vocabulary", rock_type=other_concept)

        with pytest.raises(ValidationError) as excinfo:
            specimen.full_clean()

        assert any("rock-type" in message for message in excinfo.value.messages)

    @pytest.mark.django_db
    def test_full_clean_accepts_a_concept_from_the_correct_vocabulary(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        specimen = Specimen(name="Correct vocabulary", rock_type=concept)

        specimen.full_clean()

    @pytest.mark.django_db
    def test_full_clean_accepts_an_optional_field_with_nothing_attached(self):
        sample = Sample(name="Unclassified sample")

        sample.full_clean()

    @pytest.mark.django_db
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
            other_concept = ConceptFactory(scheme=ConceptSchemeFactory(name="Mineral"))
            specimen = Specimen(name="Wrong vocabulary", rock_type=other_concept)

            with pytest.raises(ValidationError) as excinfo:
                specimen.full_clean()

            assert any("rock-type" in message for message in excinfo.value.messages)
        finally:
            field.error_messages["invalid"] = original


class TestConceptFieldCollectionRestrictionValidation:
    @pytest.mark.django_db
    def test_a_collection_member_validates(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        _collection, members = collection_with_members(
            scheme=scheme, name="Core Samples", labels=("Granite",)
        )
        core_sample = CoreSample(name="Sample A", rock_type=members[0])

        core_sample.full_clean()

    @pytest.mark.django_db
    def test_a_non_member_of_the_same_vocabulary_is_refused(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core Samples", labels=("Granite",))
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        core_sample = CoreSample(name="Sample B", rock_type=outsider)

        with pytest.raises(ValidationError):
            core_sample.full_clean()


class TestConceptFieldCollectionRestrictionRefusalMessage:
    @pytest.mark.django_db
    def test_the_refusal_names_the_collection(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core Samples", labels=("Granite",))
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        core_sample = CoreSample(name="Sample B", rock_type=outsider)

        with pytest.raises(ValidationError) as excinfo:
            core_sample.full_clean()

        assert any("core-samples" in message for message in excinfo.value.messages)

    @pytest.mark.django_db
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
            outsider = ConceptFactory(scheme=scheme, label="Marble")
            core_sample = CoreSample(name="Sample C", rock_type=outsider)

            with pytest.raises(ValidationError) as excinfo:
                core_sample.full_clean()

            assert any("core-samples" in message for message in excinfo.value.messages)
        finally:
            field.error_messages["invalid_restricted"] = original


class TestConceptFieldConceptsRestrictionValidation:
    @pytest.mark.django_db
    def test_a_listed_concept_validates(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        chip_sample = ChipSample(name="Sample A", rock_type=granite)

        chip_sample.full_clean()

    @pytest.mark.django_db
    def test_an_unlisted_concept_of_the_same_vocabulary_is_refused(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        chip_sample = ChipSample(name="Sample B", rock_type=outsider)

        with pytest.raises(ValidationError):
            chip_sample.full_clean()


class TestConceptFieldConceptsRestrictionRefusalMessage:
    @pytest.mark.django_db
    def test_the_refusal_names_the_permitted_concepts(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        chip_sample = ChipSample(name="Sample B", rock_type=outsider)

        with pytest.raises(ValidationError) as excinfo:
            chip_sample.full_clean()

        assert any(
            "granite" in message and "basalt" in message
            for message in excinfo.value.messages
        )

    @pytest.mark.django_db
    def test_a_consumers_own_error_messages_override_still_works(self):
        field = ChipSample._meta.get_field("rock_type")
        original = field.error_messages["invalid_restricted_concepts"]
        field.error_messages["invalid_restricted_concepts"] = (
            "%(model)s pk=%(pk)s field=%(field)s in %(restriction)s"
        )
        try:
            scheme = ConceptSchemeFactory(name="Rock Type")
            outsider = ConceptFactory(scheme=scheme, label="Marble")
            chip_sample = ChipSample(name="Sample C", rock_type=outsider)

            with pytest.raises(ValidationError) as excinfo:
                chip_sample.full_clean()

            assert any("granite" in message for message in excinfo.value.messages)
        finally:
            field.error_messages["invalid_restricted_concepts"] = original


class TestConceptFieldBranchRestrictionValidation:
    @pytest.mark.django_db
    def test_the_root_itself_validates(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        sample = BranchSample(name="Sample A", rock_type=root)

        sample.full_clean()

    @pytest.mark.django_db
    def test_a_grandchild_validates(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        child = ConceptFactory(scheme=scheme, label="Granite")
        grandchild = ConceptFactory(scheme=scheme, label="Porphyritic Granite")
        child.add_broader(root)
        grandchild.add_broader(child)
        sample = BranchSample(name="Sample B", rock_type=grandchild)

        sample.full_clean()

    @pytest.mark.django_db
    def test_a_sibling_branch_is_refused(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        ConceptFactory(scheme=scheme, label="Igneous")
        sibling_root = ConceptFactory(scheme=scheme, label="Sedimentary")
        sibling_child = ConceptFactory(scheme=scheme, label="Sandstone")
        sibling_child.add_broader(sibling_root)
        sample = BranchSample(name="Sample C", rock_type=sibling_child)

        with pytest.raises(ValidationError):
            sample.full_clean()

    @pytest.mark.django_db
    def test_the_concept_the_root_sits_below_is_refused(self):
        # A closure walked in the wrong direction would admit the ancestor.
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        ancestor = ConceptFactory(scheme=scheme, label="Rock")
        root.add_broader(ancestor)
        sample = BranchSample(name="Sample D", rock_type=ancestor)

        with pytest.raises(ValidationError):
            sample.full_clean()


class TestConceptFieldBranchRestrictionRefusalMessage:
    @pytest.mark.django_db
    def test_the_refusal_names_the_branch_root(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        ConceptFactory(scheme=scheme, label="Igneous")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        sample = BranchSample(name="Sample E", rock_type=outsider)

        with pytest.raises(ValidationError) as excinfo:
            sample.full_clean()

        assert any("igneous" in message for message in excinfo.value.messages)

    @pytest.mark.django_db
    def test_a_consumers_own_error_messages_override_still_works(self):
        field = BranchSample._meta.get_field("rock_type")
        original = field.error_messages["invalid_restricted_branch"]
        field.error_messages["invalid_restricted_branch"] = (
            "%(model)s pk=%(pk)s field=%(field)s in %(restriction)s"
        )
        try:
            scheme = ConceptSchemeFactory(name="Rock Type")
            ConceptFactory(scheme=scheme, label="Igneous")
            outsider = ConceptFactory(scheme=scheme, label="Marble")
            sample = BranchSample(name="Sample F", rock_type=outsider)

            with pytest.raises(ValidationError) as excinfo:
                sample.full_clean()

            assert any("igneous" in message for message in excinfo.value.messages)
        finally:
            field.error_messages["invalid_restricted_branch"] = original


class SpecimenForm(forms.ModelForm):
    """Plain ``ModelForm`` over ``Specimen``."""

    class Meta:
        model = Specimen
        fields = ["name", "rock_type"]


class TestConceptFieldFormChoices:
    @pytest.mark.django_db
    def test_form_field_offers_only_the_named_vocabularys_concepts(self):
        rock_scheme = ConceptSchemeFactory(name="Rock Type")
        matching_concept = ConceptFactory(scheme=rock_scheme)
        other_scheme = ConceptSchemeFactory(name="Mineral")
        other_concept = ConceptFactory(scheme=other_scheme)

        form = SpecimenForm()
        choices = list(form.fields["rock_type"].queryset)

        assert matching_concept in choices
        assert other_concept not in choices

    @pytest.mark.django_db
    def test_form_submission_with_another_vocabularys_concept_is_rejected(self):
        other_scheme = ConceptSchemeFactory(name="Mineral")
        other_concept = ConceptFactory(scheme=other_scheme)

        form = SpecimenForm(
            data={"name": "Wrong vocabulary", "rock_type": other_concept.pk}
        )

        assert not form.is_valid()
        assert "rock_type" in form.errors
        assert Specimen.objects.count() == 0


class TestConceptFieldDeleteGuard:
    @pytest.mark.django_db
    def test_deleting_a_referenced_concept_is_refused(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        specimen = SpecimenFactory(rock_type=concept)

        with pytest.raises(ProtectedError):
            concept.delete()

        assert Concept.objects.filter(pk=concept.pk).exists()
        assert Specimen.objects.filter(pk=specimen.pk).exists()

    @pytest.mark.django_db
    def test_bulk_queryset_delete_of_a_referenced_concept_is_refused(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        specimen = SpecimenFactory(rock_type=concept)

        with pytest.raises(ProtectedError):
            Concept.objects.filter(pk=concept.pk).delete()

        assert Concept.objects.filter(pk=concept.pk).exists()
        assert Specimen.objects.filter(pk=specimen.pk).exists()

    @pytest.mark.django_db
    def test_deleting_the_scheme_holding_a_referenced_concept_is_refused(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        specimen = SpecimenFactory(rock_type=concept)

        with pytest.raises(ProtectedError):
            scheme.delete()

        assert ConceptScheme.objects.filter(pk=scheme.pk).exists()
        assert Concept.objects.filter(pk=concept.pk).exists()
        assert Specimen.objects.filter(pk=specimen.pk).exists()

    @pytest.mark.django_db
    def test_an_unreferenced_concept_deletes_normally(self):
        concept = ConceptFactory()

        concept.delete()

        assert not Concept.objects.filter(pk=concept.pk).exists()

    @pytest.mark.django_db
    def test_deleting_the_consuming_record_leaves_the_concept_in_place(self):
        concept = ConceptFactory()
        specimen = SpecimenFactory(rock_type=concept)

        specimen.delete()

        assert not Specimen.objects.filter(pk=specimen.pk).exists()
        assert Concept.objects.filter(pk=concept.pk).exists()


class TestConceptFieldLabelAndUriAccessors:
    @pytest.mark.django_db
    def test_label_accessor_returns_the_active_languages_preferred_label(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme, label="Basalt")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Basalt (de)"
        )
        specimen = SpecimenFactory(rock_type=concept)

        with translation.override("de"):
            assert specimen.get_rock_type_label() == "Basalt (de)"

    @pytest.mark.django_db
    def test_label_accessor_falls_back_to_the_vocabulary_default(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme, label="Basalt")
        specimen = SpecimenFactory(rock_type=concept)

        with translation.override("fr"):
            assert specimen.get_rock_type_label() == "Basalt"

    @pytest.mark.django_db
    def test_uri_accessor_returns_the_concepts_own_uri_unchanged(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        specimen = SpecimenFactory(rock_type=concept)

        assert specimen.get_rock_type_uri() == concept.uri

    @pytest.mark.django_db
    def test_both_accessors_return_none_when_nothing_is_attached(self):
        sample = SampleFactory()

        assert sample.get_mineral_label() is None
        assert sample.get_mineral_uri() is None

    def test_both_accessors_return_none_on_a_required_field_with_nothing_attached(self):
        # A required field's forward descriptor raises RelatedObjectDoesNotExist
        # rather than returning None, so the nullable case above does not cover
        # this one. Both accessors promise None, never a raise.
        specimen = Specimen(name="not yet classified")

        assert specimen.get_rock_type_label() is None
        assert specimen.get_rock_type_uri() is None

    @pytest.mark.django_db
    def test_a_models_own_definition_survives_the_contribution_guard(self):
        artifact = ArtifactFactory()

        assert (
            artifact.get_mineral_label() == "this artifact's own label, not the field's"
        )


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


class TestConceptFieldSeveralVocabularies:
    @pytest.mark.django_db
    def test_a_concept_from_either_named_vocabulary_validates(self):
        rock_concept = ConceptFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        mineral_concept = ConceptFactory(scheme=ConceptSchemeFactory(name="Mineral"))

        Borehole(name="From rock-type", dominant_material=rock_concept).full_clean()
        Borehole(name="From mineral", dominant_material=mineral_concept).full_clean()

    @pytest.mark.django_db
    def test_a_concept_from_a_third_vocabulary_is_refused_naming_both_expected(self):
        ConceptSchemeFactory(name="Rock Type")
        ConceptSchemeFactory(name="Mineral")
        outsider = ConceptFactory(scheme=ConceptSchemeFactory(name="Geologic Age"))

        with pytest.raises(ValidationError) as excinfo:
            Borehole(name="Wrong vocabulary", dominant_material=outsider).full_clean()

        message = " ".join(excinfo.value.messages)
        assert "rock-type" in message
        assert "mineral" in message

    @pytest.mark.django_db
    def test_form_field_offers_only_the_two_named_vocabularies_concepts(self):
        rock_concept = ConceptFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        mineral_concept = ConceptFactory(scheme=ConceptSchemeFactory(name="Mineral"))
        outsider = ConceptFactory(scheme=ConceptSchemeFactory(name="Geologic Age"))

        choices = list(BoreholeForm().fields["dominant_material"].queryset)

        assert rock_concept in choices
        assert mineral_concept in choices
        assert outsider not in choices


class TestConceptFieldNoVocabulary:
    @pytest.mark.django_db
    def test_a_concept_from_any_vocabulary_validates(self):
        first = ConceptFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        second = ConceptFactory(scheme=ConceptSchemeFactory(name="Geologic Age"))

        Sketch(name="Rock", subject=first).full_clean()
        Sketch(name="Age", subject=second).full_clean()

    @pytest.mark.django_db
    def test_form_field_offers_every_concept_in_the_database(self):
        first = ConceptFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        second = ConceptFactory(scheme=ConceptSchemeFactory(name="Geologic Age"))

        choices = list(SketchForm().fields["subject"].queryset)

        assert first in choices
        assert second in choices

    @pytest.mark.django_db
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

    @pytest.mark.django_db
    def test_a_held_concept_cannot_be_deleted(self):
        concept = ConceptFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        SketchFactory(subject=concept)

        with pytest.raises(ProtectedError):
            concept.delete()

    @pytest.mark.django_db
    def test_label_and_uri_read_back(self):
        concept = ConceptFactory(scheme=ConceptSchemeFactory(name="Rock Type"))
        sketch = SketchFactory(subject=concept)

        assert sketch.get_subject_label() == concept.display_label()
        assert sketch.get_subject_uri() == concept.uri


# Read off field.error_messages, where nothing has interpolated the msgid yet.
class TestRestrictionErrorMessagesAreTranslatable:
    @pytest.mark.parametrize(
        "message_id",
        [
            "invalid_restricted",
            "invalid_restricted_concepts",
            "invalid_restricted_branch",
        ],
    )
    def test_the_message_is_a_lazy_proxy_with_a_named_restriction_placeholder(
        self, message_id
    ):
        field = ConceptField(vocabulary="rock-type")
        message = field.error_messages[message_id]
        assert isinstance(message, Promise)
        assert "%(restriction)s" in str(message)
        assert "%(value)s" in str(message)


class TestWriteGuardRefusalsAreTranslatable:
    @pytest.mark.django_db
    def test_the_collection_axis_refusal_is_a_lazy_proxy_with_named_placeholders(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core Samples", labels=("Granite",))
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        drill_core = DrillCoreFactory()

        with pytest.raises(ValidationError) as excinfo:
            drill_core.rock_types.add(outsider)

        assert isinstance(excinfo.value.message, Promise)
        assert "%(restriction)s" in str(excinfo.value.message)
        assert "%(value)s" in str(excinfo.value.message)

    @pytest.mark.django_db
    def test_the_concepts_axis_refusal_is_a_lazy_proxy_with_named_placeholders(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        chip_tray = ChipTrayFactory()

        with pytest.raises(ValidationError) as excinfo:
            chip_tray.rock_types.add(outsider)

        assert isinstance(excinfo.value.message, Promise)
        assert "%(restriction)s" in str(excinfo.value.message)
        assert "%(value)s" in str(excinfo.value.message)

    @pytest.mark.django_db
    def test_the_branch_axis_refusal_is_a_lazy_proxy_with_named_placeholders(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        ConceptFactory(scheme=scheme, label="Igneous")
        outsider = ConceptFactory(scheme=scheme, label="Marble")
        branch_tray = BranchTrayFactory()

        with pytest.raises(ValidationError) as excinfo:
            branch_tray.rock_types.add(outsider)

        assert isinstance(excinfo.value.message, Promise)
        assert "%(restriction)s" in str(excinfo.value.message)
        assert "%(value)s" in str(excinfo.value.message)


def _translation_call_string_literals(func) -> list[str]:
    """Return every string ``func`` passes straight to ``_()`` or ``gettext_lazy()``.

    Reads the function's source rather than calling it: ``checks.py`` interpolates
    the lazy proxy with ``%`` immediately, so a rendered warning carries no trace
    of having been translatable.

    Args:
        func: The function whose source is inspected.

    Returns:
        The string literals, in source order.
    """
    tree = ast.parse(inspect.getsource(func))
    literals = []

    class _Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name) and node.func.id in {
                "_",
                "gettext_lazy",
            }:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        literals.append(arg.value)
            self.generic_visit(node)

    _Visitor().visit(tree)
    return literals


class TestW005MessagesAreStaticWithNamedPlaceholders:
    def test_none_of_them_carries_a_positional_placeholder(self):
        literals = _translation_call_string_literals(
            checks_module.check_concept_field_restriction_targets
        )
        assert literals, "expected the W005 messages dict to be found at all"
        for literal in literals:
            assert "%s" not in literal
            assert "%d" not in literal

    def test_each_message_carries_the_four_named_placeholders(self):
        literals = _translation_call_string_literals(
            checks_module.check_concept_field_restriction_targets
        )
        messages = [literal for literal in literals if "%(target)s" in literal]
        assert len(messages) == 3
        for message in messages:
            assert "%(model)s" in message
            assert "%(field)s" in message
            assert "%(vocabulary)s" in message


# Developer-facing diagnostics raised while a declaration is read, exempt under
# Article XII. Wrapping one in _() would break nothing visible, so only a test stops a
# later pass doing it.
class TestDeclarationRuleTypeErrorsStayUntranslated:
    @pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
    def test_a_restriction_naming_no_vocabulary_raises_a_plain_string(
        self, field_class
    ):
        with pytest.raises(TypeError) as excinfo:
            field_class(branch="igneous")
        assert not isinstance(excinfo.value.args[0], Promise)
        assert type(excinfo.value.args[0]) is str

    @pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
    def test_two_restrictions_together_raises_a_plain_string(self, field_class):
        with pytest.raises(TypeError) as excinfo:
            field_class(
                vocabulary="rock-type", collection="core-samples", branch="igneous"
            )
        assert not isinstance(excinfo.value.args[0], Promise)
        assert type(excinfo.value.args[0]) is str

    @pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
    def test_a_non_string_collection_raises_a_plain_string(self, field_class):
        with pytest.raises(TypeError) as excinfo:
            field_class(vocabulary="rock-type", collection=42)
        assert not isinstance(excinfo.value.args[0], Promise)
        assert type(excinfo.value.args[0]) is str

    @pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
    def test_an_empty_concepts_list_raises_a_plain_string(self, field_class):
        with pytest.raises(TypeError) as excinfo:
            field_class(vocabulary="rock-type", concepts=[])
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
