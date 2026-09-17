"""Tests for ``controlled_vocabularies.fields``.

Phase F covers ``ConceptField`` construction and ``deconstruct()``, unbound to
any consuming model — no model declares the field yet, so every test here
builds the field directly rather than through a model instance. The bound
behaviour (declaring it on a model, saving, reading back) is US-1's (T004),
and the ``validate()`` override's behavioural proof — raise, then read
``.messages`` and find the vocabulary named — is US-2's T005, against a real
test-app model. Neither is in scope here: with ``to`` the string
``"controlled_vocabularies.Concept"`` (not the imported class — see
``fields.py``'s module docstring for why), ``remote_field.model`` only
resolves once the field is attached to a model class, so an unbound field
cannot run ``validate()`` at all.

- ``TestConceptFieldConstruction`` — the fixed kwargs, the two construction-time
  rejections, that building the field issues no query (FR-003's mechanism),
  and that ``error_messages["invalid"]`` carries the named placeholder
  ``validate()`` needs (proved bound in T005).
- ``TestConceptFieldMigrations`` — a model carrying the field migrates from
  zero and stays ``makemigrations --check`` clean, which is what the string
  ``to`` and ``deconstruct()`` together exist to make possible.
- ``TestConceptFieldFactories`` and ``TestConceptVocabularyFixtures`` — the
  test-app factories and the two scheme fixtures ``conftest.py`` carries for
  #87, #88 and #89 build the shape their docstrings promise.
- ``TestConceptFieldDeconstruct`` — ``deconstruct()`` strips the three kwargs
  this field fixes and adds ``vocabulary``, so a field built from the emitted
  path/kwargs round-trips (T003, moved into Phase F because
  ``ModelState.from_model()`` clones every field through ``deconstruct()``,
  so T002's test app cannot migrate without it).
- ``TestConceptFieldRoundTrip`` — T004 (US-1): declaring the field on a real
  model, saving, and reading back a concept survives a save/reload; the
  optional field validates and saves with nothing attached; and using the
  field this way stays ``makemigrations --check`` clean, the regression guard
  against ``deconstruct()`` rotting.
- ``TestConceptFieldOrdinaryOptions`` — T004 (US-1): the field's ordinary
  ``ForeignKey`` options — ``related_name``, ``null``/``blank``,
  ``verbose_name``, ``help_text``, the automatic index — behave exactly as
  they would on a plain ``ForeignKey``, asserted directly on the bound field
  rather than only through a save/reload round trip.
- ``TestConceptFieldValidation`` — T005 (US-2): ``full_clean()`` on a record
  holding a concept from another vocabulary raises ``ValidationError``, and
  *reading* ``.messages`` shows the vocabulary named — the behavioural proof
  T001's ``validate()`` override exists for, only reachable against a real,
  bound model. A concept from the correct vocabulary passes; an optional
  field with nothing attached passes.
- ``TestConceptFieldFormChoices`` — T006 (US-2): a ``ModelForm`` generated
  from a consuming model offers only the named vocabulary's concepts as
  choices, and a submission carrying another vocabulary's concept is
  rejected rather than saved — proof that ``ForeignKey.formfield()`` passes
  ``limit_choices_to`` through, since nothing in this package's own source
  states that guarantee.
- ``TestConceptFieldDeleteGuard`` — T007 (US-3): no new code — ``PROTECT``
  was fixed on the field in T001. This class is the proof FR-007 needs: a
  referenced concept survives both a single-instance and a bulk queryset
  delete, the scheme holding it survives too (the cascade from scheme to
  concept meets the protection on the way down), an unreferenced concept
  deletes normally, and deleting the referencing record leaves the concept
  in place.
- ``TestConceptsFieldWritePathVocabularyCheck`` — FS-010 T005 (US-2): the
  ``pre_add`` receiver connected in ``ConceptsField.contribute_to_class``
  refuses a concept from an unnamed vocabulary at the point the relation is
  written (D2), not only at model validation. Driven entirely through
  :class:`~tests.testapp.models.Deposit`'s real relation manager — never
  against the receiver directly, since a direct call would pass even if
  Django's ``bulk_create`` fast path were skipping ``m2m_changed`` entirely
  (R6), which is precisely the failure this task guards against.
- ``TestConceptsFieldFormChoices`` — FS-010 T006 (US-2): no new code —
  ``limit_choices_to`` from T002 already restricts a ``ModelForm``'s
  ``ModelMultipleChoiceField`` queryset and rejects an out-of-vocabulary
  submission, the same way T006 (FS-009) already proved for ``ConceptField``.
- ``TestConceptsFieldDeleteGuard`` — FS-010 T007 (US-3): no new code —
  ``PROTECT`` on the membership model's foreign key to ``Concept`` (T003)
  already refuses any delete path that would strand a reference. This class
  is the proof, the ``ConceptsField`` counterpart of
  ``TestConceptFieldDeleteGuard``: a held concept survives both a
  single-instance and a bulk queryset delete, the scheme holding it survives
  too, an unheld concept deletes normally, and deleting the consuming record
  removes only its membership rows and leaves every concept in place (D5).
- ``TestConceptsFieldLabelAndUriAccessors`` — FS-010 T008 (US-4, FR-008,
  FR-009): ``contribute_to_class()`` gives the consuming model
  ``get_<name>_labels()`` and ``get_<name>_uris()``, plural, named the way
  ``ConceptField``'s own singular accessors are (T011's precedent). Labels
  delegate to ``Concept.display_label()`` per attached concept, in the
  active language with fallback to the vocabulary's default; URIs return
  each concept's own ``uri`` unchanged. Both return an empty result rather
  than raising for a record holding nothing, including an unsaved one —
  the many-to-many manager raises ``ValueError`` the moment it is touched
  before a primary key exists. The ``setattr`` is guarded exactly like
  ``ConceptField``'s.
- ``TestConceptsFieldSeveralVocabulariesWritePath`` and
  ``TestConceptsFieldSeveralVocabulariesFormChoices`` — FS-010 T012 (US-8,
  FR-002, FR-005, FR-006, D9): the several-vocabulary shape against
  :class:`~tests.testapp.models.FieldNote` — a concept from either named
  vocabulary attaches, a concept from a third is refused with both expected
  vocabularies named in the message, and a form built from the model offers
  only the two named vocabularies' concepts.
- ``TestConceptsFieldNoVocabularyWritePath``,
  ``TestConceptsFieldNoVocabularyFormChoices`` and
  ``TestConceptsFieldNoVocabularyDeleteGuard`` — FS-010 T012 (US-8, FR-002,
  FR-005, FR-006, FR-007, D9): the no-vocabulary shape against
  :class:`~tests.testapp.models.Photograph` — concepts from several distinct
  vocabularies all attach in one write with none refused, a form built from
  the model offers every concept in the database, and the delete guard holds
  without a restriction to enforce, proving the unconstrained shape is a real
  member of the family rather than a plain many-to-many wearing the same
  name. The receiver-absence assertion this shape also needs already lives
  on ``TestConceptsFieldWritePathVocabularyCheck`` (T005) and the several-
  vocabulary system-check coverage already lives on
  ``TestCheckConceptsFieldVocabularies`` (T010, ``test_checks.py``) — neither
  is duplicated here.
- ``TestSharedRestrictedHelpText`` — T023 (US-7, FR-013): a restricted field
  with no ``help_text`` of its own describes itself as restricted within its
  vocabulary, one static default per field shared by all three axes, never
  one interpolating the restriction; an unrestricted field and a consumer's
  own ``help_text`` are both unaffected.
- ``TestRestrictionErrorMessagesAreTranslatable``,
  ``TestWriteGuardRefusalsAreTranslatable``,
  ``TestW005MessagesAreStaticWithNamedPlaceholders`` and
  ``TestDeclarationRuleTypeErrorsStayUntranslated`` — T024 (US-7, Article
  XII): every curator-facing string this feature added — the three
  ``invalid_restricted*`` messages, the many-valued write guard's three
  refusals, and W005's three messages and hints — is a static msgid with
  named placeholders, checked as lazy proxies rather than by content alone.
  The last class asserts the opposite direction: T002's and T003's
  declaration-rule ``TypeError``s stay plain, untranslated strings, on
  purpose (research.md R7).
"""

import ast
import inspect
import signal
import warnings

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
    """#111 — the two fields agree on what ``vocabulary`` accepts and what it
    means, asserted against both from one place.

    The defect #111 reported was the two fields disagreeing, and the reason
    they could was that each implemented the contract itself. They now inherit
    it from :class:`ConceptFieldMixin`. This class is the guard against a
    future change reintroducing the divergence: every assertion runs against
    both fields, so a shape supported on one and not the other fails here
    rather than reaching a consumer.
    """

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
        """``clone()`` is what ``ModelState.from_model()`` calls on every local
        field, so a contract that does not survive it breaks every
        ``makemigrations`` and every test-database build."""
        field = field_class(vocabulary=["rock-type", "mineral"])
        assert field.clone().vocabulary == ("rock-type", "mineral")


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedRestrictionArguments:
    """T001 (FR-001, FR-003, decisions.md D4) — both fields accept the three
    restriction arguments — ``collection``, ``concepts``, ``branch`` — each
    defaulting to ``None`` and normalised by the same rule
    ``_normalise_vocabulary`` already applies to a vocabulary slug: a
    non-empty string, or a ``TypeError`` naming the class. ``concepts``
    additionally collapses duplicates and refuses an empty list.

    Nothing resolves yet (plan.md A1): a restricted field still behaves
    exactly like an unrestricted one until a later story teaches
    ``get_limit_choices_to()`` to read these attributes. Every field built
    here names exactly one vocabulary so FR-005 (T002) never fires and this
    class tests normalisation alone.
    """

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
        """FR-003, decisions.md D4 — a restriction that offers nothing while
        reading as restricted is not what a consumer writing it meant."""
        with pytest.raises(TypeError, match=field_class.__name__):
            field_class(vocabulary="rock-type", concepts=[])

    def test_concepts_accepts_a_single_slug_without_splitting_it(self, field_class):
        """``collection`` and ``branch`` both take a bare slug, so a consumer
        will write one for ``concepts`` too. It has to become a one-element
        restriction, the shape ``vocabulary`` already accepts — iterating the
        string instead yields a slug per character, which every check here
        would pass."""
        field = field_class(vocabulary="rock-type", concepts="granite")
        assert field.concepts == ("granite",)


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedRestrictedHelpText:
    """T023 (US-7, FR-013) — a restricted field with no ``help_text`` of its
    own describes itself as restricted within its vocabulary, distinct from
    the unrestricted default both fields already carried. One axis at a
    time, since ``TestSharedRestrictionArguments`` already proves the three
    normalise the same way; what's new here is what each does to the
    default ``help_text``.

    Both defaults stay static ``gettext_lazy`` strings, asserted by identity
    against the class attribute rather than by content: ``%`` applied to a
    ``gettext_lazy()`` proxy evaluates it immediately, which would defeat the
    laziness the default exists to keep, exactly as ``ConceptFieldMixin``'s
    own annotation on ``default_help_text`` explains. The
    ``test_help_text_does_not_vary_with_the_restrictions_target`` case is the
    regression guard for that: it fails the moment someone later
    interpolates ``self.collection``/``self.concepts``/``self.branch`` into
    either default, because two different targets on the same axis would
    then stop reading identically.
    """

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
        """A test that fails if someone later interpolates the restriction
        into the default: the default names no target at all, so two
        declarations restricted to different collections must read
        byte-identical ``help_text``."""
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
    """T002 (FR-005) — a restriction needs exactly one named vocabulary,
    checked after ``_normalise_vocabulary`` has run so "several" and "none"
    are one condition rather than two branches (plan.md A1)."""

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
        """FR-014 — a declaration using none of the three restrictions behaves
        exactly as it did before this feature existed, including naming no
        vocabulary at all."""
        field = field_class()
        assert field.vocabulary == ()

    def test_no_restriction_naming_several_vocabularies_is_unaffected(
        self, field_class
    ):
        field = field_class(vocabulary=["rock-type", "mineral"])
        assert field.vocabulary == ("rock-type", "mineral")


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedRestrictionExclusivity:
    """T003 (FR-006, decisions.md D1) — at most one of collection/concepts/
    branch. Two or more has no single defensible reading — an intersection
    and a union are equally plausible — so no reading is chosen."""

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
    """T004 (FR-011, FR-014, plan.md A7) — a restriction survives
    ``deconstruct()`` and rebuilds. Emitted only when set, so a declaration
    using none produces byte-identical output to before this feature
    (already covered by ``TestSharedVocabularyContract``); this class covers
    the restricted case, one axis at a time."""

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
        """Guards the unconditional ``kwargs.pop("limit_choices_to", None)``
        that keeps T005's callable out of migration output — a later change
        to that pop should fail here, not in a generated migration."""
        field = field_class(vocabulary="rock-type", collection="core-samples")
        _name, _path, _args, kwargs = field.deconstruct()
        assert "limit_choices_to" not in kwargs

    def test_clone_rebuilds_a_restricted_field(self, field_class):
        """``clone()`` is what ``ModelState.from_model()`` calls on every
        local field, so a contract that does not survive it breaks every
        ``makemigrations`` and every test-database build."""
        field = field_class(vocabulary="rock-type", branch="igneous")
        cloned = field.clone()
        assert cloned.branch == "igneous"


@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestSharedLimitChoicesToCallable:
    """T005 (FR-007, research.md R2) — ``limit_choices_to`` becomes a
    callable returning today's vocabulary ``Q``, installed as the seam later
    stories resolve a restriction through. This task changes no observable
    behaviour: every existing field test in this module still proves it,
    unmodified."""

    def test_get_limit_choices_to_returns_the_vocabulary_q(self, field_class):
        field = field_class(vocabulary="rock-type")
        assert field.get_limit_choices_to() == Q(scheme__slug__in=("rock-type",))

    def test_limit_choices_to_is_callable_when_a_vocabulary_is_named(self, field_class):
        field = field_class(vocabulary="rock-type")
        assert callable(field.remote_field.limit_choices_to)

    @pytest.mark.django_db
    def test_construction_issues_no_query(self, field_class):
        """FR-007 — the callable is installed, never invoked, while the
        declaration is only being read."""
        with CaptureQueriesContext(connection) as ctx:
            field_class(vocabulary="rock-type")
        assert len(ctx.captured_queries) == 0

    def test_no_vocabulary_named_sets_no_restriction_at_all(self, field_class):
        """Not a callable returning an empty Q that matches everything —
        nothing is set, exactly as before this feature."""
        field = field_class()
        assert field.get_limit_choices_to() == {}
        assert field.remote_field.limit_choices_to == {}

    @pytest.mark.django_db
    def test_a_restriction_present_now_narrows_beyond_the_bare_vocabulary_q(
        self, field_class
    ):
        """T006 (US-1) is the "later story" this method's own name once
        promised would teach the axis — it no longer resolves to only the
        vocabulary ``Q`` once ``collection`` is set. ``Q`` objects wrapping a
        subquery are not ``==``-comparable across two independently built
        instances (the embedded ``QuerySet`` compares by identity, not
        value), so this is checked against real rows rather than by
        structural equality — the same reason ``TestCollectionRestrictionResolves``
        below asserts by membership. See ``decisions.md`` for why this
        pre-existing test's assertion changed rather than being left to fail
        as the feature that already predicted it landed."""
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite",)
        )
        outsider = ConceptFactory(scheme=scheme, label="Marble")

        field = field_class(vocabulary="rock-type", collection=collection.slug)
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert set(resolved) == set(members)
        assert outsider not in resolved


@pytest.mark.django_db
@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestCollectionRestrictionResolves:
    """T006 (US-1, FR-002, plan.md A2) — the callable from T005 additionally
    returns a ``pk__in`` subquery over ``CollectionMember`` when ``collection``
    is set. Both halves of the resolved ``Q`` matter (research.md R3): the
    vocabulary term is never dropped, so a same-named collection in another
    vocabulary cannot widen the field, and the membership term is a
    subquery, never a ``collection_memberships__…`` join, so it cannot
    duplicate rows for a concept that belongs to more than one collection.

    Two independently resolved ``Q``s wrapping a subquery are not
    ``==``-comparable (the embedded ``QuerySet`` compares by identity), so
    every assertion here evaluates the resolved ``Q`` against real rows via
    ``Concept.objects.complex_filter()`` — the same bare call this package's
    own widget and search endpoint make (research.md R3), rather than
    inspecting the ``Q``'s structure."""

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
        """The row-duplication research.md R3 exists to guard against: a
        member of both the restricted collection and a second one must
        still resolve once."""
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite",)
        )
        other_collection = CollectionFactory(scheme=scheme, name="Display Samples")
        other_collection.add(members[0])

        field = field_class(vocabulary="rock-type", collection=collection.slug)
        resolved = Concept.objects.complex_filter(field.get_limit_choices_to())

        assert list(resolved.values_list("pk", flat=True)) == [members[0].pk]


@pytest.mark.django_db
@pytest.mark.parametrize("field_class", [ConceptField, ConceptsField])
class TestCollectionRestrictionResolvesLive:
    """T010 (US-1, FR-002's "resolved live") — no cache to invalidate: T005
    made ``limit_choices_to`` a callable, re-resolved on every read, so a
    membership change reaches the field with nothing to invalidate and
    nothing to restart. This test is what stops a later "optimisation" that
    resolves the restriction once and holds onto it."""

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
    """T013 (US-2, FR-003, plan.md A2) — the callable from T005 gains its
    third and final term: ``Q(slug__in=self.concepts)`` when ``concepts`` is
    set. The one axis needing no subquery — research.md R3's row-duplication
    concern does not arise for a plain column filter, so this is checked
    against real rows the same way the collection axis is, but for
    consistency with the rest of this module rather than out of necessity:
    a bare ``Q`` *is* ``==``-comparable, unlike the collection axis's
    subquery-wrapped one."""

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


class TestBranchClosure:
    """T015 (US-3, plan.md A3, research.md R5) — the branch axis's downward
    closure, unit-tested directly against ``_branch_closure()`` rather than
    through a field: the concept named ``branch`` within ``vocabulary``,
    plus everything narrower than it at any depth. Iterative widening over
    the stored ``broader`` edges, in the direction ``models.py:1161-1174``
    fixes: a ``BROADER`` row's ``source`` is the narrower concept and its
    ``target`` the broader one, so walking downward means matching
    ``target`` and collecting ``source`` — the opposite of what an inverted
    walk would do."""

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
    """T016 (FR-004, SC-006, decisions.md D5) — a two-edge cycle, built with
    two ordinary ``add_broader()`` calls exactly as ``decisions.md`` D5
    describes, still terminates and yields each concept exactly once. The
    relation model refuses a self-relation and a mirror-order *related*
    duplicate, but not a reversed *broader* edge (``models.py:1209-1211``),
    so this is the shortest cycle storable through the public API — nothing
    contrived needed to reach it. Bounded by an alarm so a regression in the
    seen-set logic fails this test rather than hanging the whole suite."""

    @pytest.mark.django_db
    def test_a_two_edge_cycle_terminates_and_yields_each_concept_once(self):
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
    """T018 (US-3, FR-004, plan.md A2) — the callable from T005 gains its
    third and final term: ``Q(pk__in=<the closure from T015>)`` when
    ``branch`` is set. As with the collection axis (research.md R3), the
    closure is a ``pk__in`` subquery, never a join, and the vocabulary term
    is never dropped — a same-slugged concept in another vocabulary cannot
    be reached as a root."""

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
    """T018 — no cache to invalidate, the same guarantee
    ``TestCollectionRestrictionResolvesLive`` proves for the collection axis:
    a concept added below the root at any depth appears on the next read."""

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
    """FR-001, FR-002, FR-007, FR-010 — the kwargs a consumer does not supply."""

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
        """The shape #111 aligns with ``ConceptsField``: naming no vocabulary is
        a supported declaration, not an error, and sets no restriction at all
        rather than one that happens to match everything."""
        field = ConceptField()
        assert field.vocabulary == ()
        assert field.get_limit_choices_to() == {}

    @pytest.mark.django_db
    def test_construction_issues_no_queries(self):
        """FR-003's mechanism: the ``Q`` is constructed, never evaluated."""
        with CaptureQueriesContext(connection) as ctx:
            ConceptField(vocabulary="rock-type")
        assert len(ctx.captured_queries) == 0

    def test_rejects_consumer_supplied_on_delete(self):
        with pytest.raises(TypeError, match="on_delete"):
            ConceptField(vocabulary="rock-type", on_delete=PROTECT)

    def test_rejects_consumer_supplied_limit_choices_to(self):
        # The vocabulary constraint IS limit_choices_to, so accepting a
        # consumer's would silently discard either theirs or the constraint.
        # Refused loudly, the same way on_delete is.
        with pytest.raises(TypeError, match="limit_choices_to"):
            ConceptField(vocabulary="rock-type", limit_choices_to=Q(label="Granite"))

    def test_rejects_non_string_vocabulary_element(self):
        with pytest.raises(TypeError, match="ConceptField"):
            ConceptField(vocabulary=["rock-type", 7])

    def test_rejects_an_empty_slug(self):
        """An empty string is not a slug any scheme can carry, so a field
        declaring one would offer no choices at all while looking restricted.
        Refused for both fields rather than normalised away."""
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
        """A field naming no vocabulary has no vocabulary to name in a refusal,
        so the message that would interpolate one is not the message it uses."""
        field = ConceptField()
        assert "%(vocabulary)s" not in field.error_messages["invalid_unrestricted"]


class TestConceptFieldDeconstruct:
    """T003 — without this, ``Field.clone()`` (``db/models/fields/__init__.py``,
    ``self.__class__(*args, **kwargs)`` built from ``self.deconstruct()``) cannot
    rebuild the field: ``ForeignKey``/``RelatedField.deconstruct()`` would emit
    ``to``, ``on_delete`` and ``limit_choices_to`` but never ``vocabulary``, and
    ``__init__`` requires the latter and rejects the former. ``ModelState.from_model()``
    calls ``clone()`` on every local field, so every one of ``makemigrations``,
    ``makemigrations --check``, ``migrate`` and pytest-django's own test-database
    build would raise before writing anything — precisely what T002 hit.
    """

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
        """Deconstruct, rebuild from the emitted path and kwargs — exactly what
        ``Field.clone()`` and a replayed migration file both do — and the
        rebuilt field carries the same vocabulary, the same ``limit_choices_to``,
        and ``PROTECT``. Run over all three shapes, since a migration written
        before #111 records ``vocabulary`` as a bare string and has to keep
        replaying."""
        field = ConceptField(vocabulary=vocabulary)
        _name, path, args, kwargs = field.deconstruct()
        field_class = import_string(path)
        rebuilt = field_class(*args, **kwargs)
        assert rebuilt.vocabulary == field.vocabulary
        assert rebuilt.get_limit_choices_to() == field.get_limit_choices_to()
        assert rebuilt.remote_field.on_delete is PROTECT

    def test_clone_rebuilds_without_error(self):
        """``clone()`` is exactly what ``ModelState.from_model()`` calls on every
        local field (``db/migrations/state.py``) — the failure T002 actually hit."""
        field = ConceptField(vocabulary="rock-type")
        cloned = field.clone()
        assert cloned.vocabulary == ("rock-type",)


class TestConceptsFieldConstruction:
    """FS-010 T002 (FR-001, FR-002, FR-003, FR-011) — ``vocabulary`` is optional
    and takes three shapes, normalised once in ``__init__`` to a tuple of
    slugs; the two kwargs a consumer does not supply (``limit_choices_to``,
    ``through``); construction issues no query."""

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
        """FR-003's mechanism, for all three shapes: the ``Q`` is constructed,
        never evaluated, and an omitted vocabulary sets nothing to evaluate."""
        with CaptureQueriesContext(connection) as ctx:
            ConceptsField(vocabulary="rock-type")
            ConceptsField(vocabulary=["gcmd", "agu-index"])
            ConceptsField()
        assert len(ctx.captured_queries) == 0

    def test_rejects_consumer_supplied_limit_choices_to(self):
        with pytest.raises(TypeError, match="limit_choices_to"):
            ConceptsField(vocabulary="rock-type", limit_choices_to=Q(label="Granite"))

    def test_rejects_consumer_supplied_through(self):
        # A consumer-supplied through model would silently drop T003's delete
        # guarantee, the same reasoning that refuses on_delete on ConceptField.
        with pytest.raises(TypeError, match="through"):
            ConceptsField(
                vocabulary="rock-type", through="controlled_vocabularies.Concept"
            )

    def test_rejects_non_string_vocabulary_element(self):
        with pytest.raises(TypeError, match="ConceptsField"):
            ConceptsField(vocabulary=["mineral", 42])

    def test_rejects_an_empty_slug(self):
        """Refused rather than normalised away, for both fields: a declaration
        carrying one would restrict to a slug no scheme can hold and offer no
        choices at all, while reading as a restricted field."""
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
    """FS-010 T002 — ``deconstruct()`` strips ``to`` and ``limit_choices_to``
    and records ``vocabulary`` instead, for the same ``Field.clone()`` reason
    documented on :class:`~controlled_vocabularies.fields.ConceptField`.
    ``through`` is never emitted (T003) so there is nothing to strip."""

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
        """Deconstruct, rebuild from the emitted path and kwargs — exactly what
        ``Field.clone()`` and a replayed migration file both do — for each of
        the three shapes."""
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
    """FS-010 T003 (FR-007, FR-011, US-3, R4, R6) — ``contribute_to_class``
    skips ``ManyToManyField``'s own through generation and substitutes one
    whose foreign key to ``Concept`` is ``PROTECT`` rather than ``CASCADE``,
    following Django's own ``create_many_to_many_intermediary_model`` closely
    otherwise. Against :class:`~tests.testapp.models.Deposit` (one
    ``ConceptsField``) and :class:`~tests.testapp.models.Survey` (two, both
    ``related_name="+"``), never against the generation helper in isolation.
    """

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
        """Unbound, T002 already proves this by never setting ``through`` at
        all. Bound, ``through`` is real and ``Meta.auto_created`` is what
        keeps ``ManyToManyField.deconstruct()`` from emitting it — this is
        the test that would fail if that attribute were ever dropped."""
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
        """Without the hidden ``related_name`` rewrite this task replicates
        before its ``super(ManyToManyField, self).contribute_to_class()``
        call, both fields would keep the literal ``related_name="+"`` — proved
        failing directly below by the reverse-query-name-clash check."""
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
        """ARC-001 (design review) — the MRO skip
        (``super(ManyToManyField, self).contribute_to_class(...)``) must skip
        ``ManyToManyField``'s own through generation, not merely call it and
        then generate again: doing both registers the through model under the
        same name twice and Django warns ``Model ... was already
        registered``, on every consuming declaration."""
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
    """FS-010 T003 — ``Deposit`` and ``Survey`` migrate cleanly with the
    generated membership models, and stay ``makemigrations --check`` clean."""

    @pytest.mark.django_db
    def test_models_are_queryable(self):
        assert Deposit.objects.count() == 0
        assert Survey.objects.count() == 0

    @pytest.mark.django_db
    def test_makemigrations_check_is_clean(self):
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)


class TestConceptsFieldConsumingModels:
    """FS-010 T001 (FR-001, US-1 through US-8) — the remaining four consuming
    models: optional with a ``related_name``, both field types on one model,
    two named vocabularies, and no vocabulary named. ``Deposit`` and
    ``Survey`` (T003) round out the six `tasks.md` T001 lists."""

    @pytest.mark.django_db
    def test_all_six_models_are_queryable(self):
        """Proof the extended migration applied — pytest-django builds the
        test database from every installed app's migrations, from zero, for
        the whole session."""
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
        """The collision case `plan.md`'s Risks section refuses to assume
        away: a ``ConceptField`` and a ``ConceptsField`` against the same
        vocabulary, declared on the same model, read and write independently."""
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
        """Article XII — ``help_text`` is mandatory and translatable; every
        declaration above also supplies an explicit ``verbose_name``."""
        field = model._meta.get_field(field_name)
        assert isinstance(field.help_text, Promise)
        assert str(field.help_text)
        assert field.verbose_name


class TestConceptsFieldAttachAndReadBack:
    """FS-010 T004 (FR-001, US-1, D1, D4) — attaching, reading back, and the
    reverse accessor, against :class:`~tests.testapp.models.Deposit` and
    :class:`~tests.testapp.models.Outcrop`. With T002 and T003 already in
    place, this is assertion rather than construction: the duplicate-attach
    case is Django's own ``m2m_changed`` ``pre_add`` behaviour (``pk_set``
    already excludes an already-attached concept, research.md R3), asserted
    here rather than built. No test in this class asserts an order — D1 makes
    the attached set unordered, so every multi-concept comparison is a set
    comparison."""

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
    """FS-010 T005 (US-2, FR-005, D2, R1, R3, R6) — the ``pre_add`` receiver
    connected in ``contribute_to_class`` refuses a concept from an unnamed
    vocabulary at the moment the relation is written, not only at
    validation (D2). Every test drives :class:`~tests.testapp.models.Deposit`'s
    real relation manager — never the receiver directly, because a direct
    call would pass even if Django's ``bulk_create`` fast path were skipping
    ``m2m_changed`` entirely, which is exactly the failure this task guards
    against (R6). The several-vocabulary and no-vocabulary write-path shapes
    belong to T012; the one assertion below about a no-vocabulary field is
    about whether a receiver is connected at all, not about its write-path
    behaviour."""

    @pytest.mark.django_db
    def test_add_of_a_concept_from_an_unnamed_vocabulary_is_refused_and_the_set_is_unchanged(
        self,
    ):
        other_scheme = ConceptSchemeFactory(name="Mineral")
        other_concept = ConceptFactory(scheme=other_scheme)
        deposit = DepositFactory()

        # ManyRelatedManager.add() runs inside transaction.atomic(savepoint=False),
        # so a propagating exception poisons pytest-django's own enclosing
        # transaction unless the call is given its own savepoint to roll
        # back to — the documented pattern for asserting a raise from inside
        # an atomic block.
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

        # Asserted after the failed write, not merely that it raised (US-2 acceptance).
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
        # Django gives every relation a live reverse accessor unless the
        # declaration hides it, so this path reaches the same through model
        # as deposit.rock_types.add() and has to be refused on the same
        # terms. Deposit.rock_types names no related_name, so the accessor
        # here is Django's default one.
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
    """T012 (US-1, plan.md A4, research.md R4) — the one enforcement path
    that does not read ``limit_choices_to``: the ``m2m_changed`` receiver is
    re-expressed against the resolved restriction and bound with the field
    itself rather than with ``vocabulary``, so the collection axis reaches
    this guard exactly as it reaches the other three paths. Driven entirely
    through :class:`~tests.testapp.models.DrillCore`'s real relation
    manager, the collection-restricted counterpart of
    ``TestConceptsFieldWritePathVocabularyCheck`` — which this task must
    leave passing unmodified alongside these."""

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

        # Asserted after the failed write, not merely that it raised (D2's whole-write refusal).
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
    """T013 (US-2, plan.md A4) — the many-valued write guard needs no
    further change of its own: it already reads ``field.get_limit_choices_to()``
    (T012), and ``TestConceptsRestrictionResolves`` above proves that method
    now resolves the concepts axis too, so this class is the end-to-end
    proof rather than new enforcement code. Driven entirely through
    :class:`~tests.testapp.models.ChipTray`'s real relation manager, the
    concepts-axis counterpart of ``TestConceptsFieldCollectionRestrictionWritePath``."""

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
        # The concepts-axis counterpart of
        # ``TestConceptsFieldCollectionRestrictionWritePath.test_the_refusal_names_the_collection``:
        # naming the wider vocabulary would say nothing about why a
        # same-vocabulary concept was rejected.
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

        # Asserted after the failed write, not merely that it raised (D2's whole-write refusal).
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
    """T017 (US-3, plan.md A4) — the many-valued write guard needs no
    further change of its own beyond naming the axis in its message: it
    already reads ``field.get_limit_choices_to()`` (T012), and
    ``TestBranchRestrictionResolves`` above proves that method now resolves
    the branch axis too. Driven entirely through
    :class:`~tests.testapp.models.BranchTray`'s real relation manager, the
    branch-axis counterpart of ``TestConceptsFieldConceptsRestrictionWritePath``."""

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

        # Asserted after the failed write, not merely that it raised (D2's whole-write refusal).
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
    """FS-010 T012 (US-8, FR-002, FR-005, D9) — a field naming several
    vocabularies accepts a concept from either, and refuses one from a third,
    naming both expected vocabularies in the refusal. Driven through
    :class:`~tests.testapp.models.FieldNote`'s real relation manager, the
    several-vocabulary counterpart of
    ``TestConceptsFieldWritePathVocabularyCheck``'s single-vocabulary proof
    against ``Deposit``."""

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

        # ManyRelatedManager.add() runs inside transaction.atomic(savepoint=False),
        # so a propagating exception poisons pytest-django's own enclosing
        # transaction unless the call is given its own savepoint to roll
        # back to (D11) — the same pattern
        # ``TestConceptsFieldWritePathVocabularyCheck`` already uses.
        with pytest.raises(ValidationError) as excinfo, transaction.atomic():
            field_note.keywords.add(other_concept)

        message = " ".join(excinfo.value.messages)
        assert "rock-type" in message
        assert "mineral" in message
        assert list(field_note.keywords.all()) == []


class TestConceptsFieldNoVocabularyWritePath:
    """FS-010 T012 (US-8, FR-002, FR-005, D9) — the extension
    ``TestConceptsFieldConsumingModels.test_field_naming_no_vocabulary_still_attaches_a_concept_from_any_scheme``
    (T001) does not make: attaching concepts drawn from *several distinct*
    vocabularies in one write to a field naming none, none refused. The
    receiver-absence assertion this shape also needs already lives on
    ``TestConceptsFieldWritePathVocabularyCheck.test_a_field_naming_no_vocabulary_connects_no_receiver_for_its_through_model``
    and is not repeated here."""

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
    """Test-only — the plain ``ModelForm`` Django would auto-generate from
    ``Deposit``, used by T006 to prove ``limit_choices_to`` reaches a
    ``ConceptsField``'s ``ModelMultipleChoiceField`` choices and submission
    validation, the same way ``SpecimenForm`` already proves it for
    ``ConceptField`` (T006, FS-009)."""

    class Meta:
        model = Deposit
        fields = ["name", "rock_types"]


class TestConceptsFieldFormChoices:
    """FS-010 T006 (US-2, FR-006, R1) — also no new code:
    ``ManyToManyField.formfield()`` passes ``limit_choices_to`` through to
    ``ModelMultipleChoiceField`` exactly as ``ForeignKey.formfield()`` does
    for ``ConceptField``. This class is the proof."""

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
    """Test-only — the plain ``ModelForm`` Django would auto-generate from
    ``FieldNote``, used by ``TestConceptsFieldSeveralVocabulariesFormChoices``
    to prove ``limit_choices_to`` reaches a several-vocabulary
    ``ConceptsField``'s ``ModelMultipleChoiceField`` choices, the way
    ``DepositForm`` already proves it for a single-vocabulary field."""

    class Meta:
        model = FieldNote
        fields = ["name", "keywords"]


class TestConceptsFieldSeveralVocabulariesFormChoices:
    """FS-010 T012 (US-8, FR-006, D9) — a form built from a model carrying a
    field naming several vocabularies offers the concepts of both and no
    others."""

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
    """Test-only — the plain ``ModelForm`` Django would auto-generate from
    ``Photograph``, used by ``TestConceptsFieldNoVocabularyFormChoices`` to
    prove a field naming no vocabulary sets no ``limit_choices_to`` at all,
    so its form field offers every concept in the database rather than an
    empty or partial set."""

    class Meta:
        model = Photograph
        fields = ["name", "keywords"]


class TestConceptsFieldNoVocabularyFormChoices:
    """FS-010 T012 (US-8, FR-006, D9) — a form built from a model carrying a
    field naming no vocabulary offers every concept in the database."""

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
    """T007 (US-3, FR-007, D5, R4) — no new code: T003 already generates the
    membership model with ``PROTECT`` on its foreign key to ``Concept`` and
    ``CASCADE`` on the one to the owner. This class is the proof, against a
    real :class:`~tests.testapp.models.Deposit` and real deletes, never a
    mocked collector."""

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
        """The protection lives in the relation rather than in model
        validation, so a bulk ``QuerySet.delete()`` is refused exactly like a
        single-instance delete — the queryset path builds the same collector,
        since ``can_fast_delete`` returns ``False`` whenever a related
        ``on_delete`` is not ``DO_NOTHING``, rather than skipping it."""
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
        """``Concept.scheme`` cascades, so deleting the scheme tries to
        cascade-delete the concept — and meets the same ``PROTECT`` on the
        way down. Nothing in the vocabulary is removed."""
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
        """D5 — deleting a consuming record keeps its concepts. The owning
        foreign key is ``CASCADE``, so only the membership rows go."""
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
    """FS-010 T012 (US-8, FR-007, D9) — a concept held by a field naming no
    vocabulary is still refused a delete: the ``PROTECT`` on the generated
    through model's foreign key to ``Concept`` (T003) does not depend on the
    restriction, only on the field being a ``ConceptsField`` at all. This is
    the assertion that proves the unconstrained shape is a real member of
    the family rather than a plain many-to-many wearing the same name."""

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
    """FS-010 T008 (US-4, FR-008, FR-009) — ``contribute_to_class()`` gives
    the consuming model ``get_<name>_labels()`` and ``get_<name>_uris()``,
    plural, one entry per attached concept, named the way
    ``ConceptField``'s own singular ``get_<name>_label()``/
    ``get_<name>_uri()`` are (``TestConceptFieldLabelAndUriAccessors``'s
    precedent). Labels delegate to ``Concept.display_label()``, which
    already resolves the active language with fallback to the vocabulary's
    default — nothing here reimplements that. URIs are each concept's own
    ``uri``, unchanged. Both return an empty result rather than raising for
    a record holding nothing, and the ``setattr`` is guarded so a model
    that already defines one of these names keeps its own. Exercised
    against :class:`~tests.testapp.models.Photograph`'s ``keywords`` field,
    the one ``ConceptsField`` naming no vocabulary, so the ``multilingual_scheme``
    and ``single_language_scheme`` fixtures' concepts can be attached
    without tripping T005's write-path vocabulary check."""

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
        # Touching a many-to-many manager before the instance has a primary
        # key raises ValueError; both accessors promise an empty result
        # instead (FR-008, FR-009), the ConceptsField counterpart of
        # TestConceptFieldLabelAndUriAccessors's unsaved-required-field case.
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
    """Test-only — the plain ``ModelForm`` Django would auto-generate from
    ``Outcrop``, used by ``TestConceptsFieldRequiredSet`` to prove the
    optional half of FR-010's form behaviour: ``blank=True`` leaves
    ``ModelMultipleChoiceField`` non-required, so an empty selection is a
    valid submission, the counterpart of ``DepositForm``'s required half."""

    class Meta:
        model = Outcrop
        fields = ["name", "minerals"]


class TestConceptsFieldRequiredSet:
    """FS-010 T009 (US-5, FR-010, D3, D8, R2, R5) — ``full_clean()`` refuses a
    required ``ConceptsField`` left holding no concepts. ``clean_fields()``
    never looks at ``_meta.many_to_many`` (R2), so the rule has no hook
    without ``ConceptsField`` installing one onto the consuming class's own
    ``full_clean``, once per class (D8). The installed wrapper resolves
    every required ``ConceptsField`` on the *instance's* class from
    ``_meta.get_fields()`` at call time, never the one field instance that
    triggered the install — :class:`~tests.testapp.models.Survey`'s two
    required fields only trigger one install between them, so a wrapper
    closed over the triggering field would leave the other silently
    unenforced, which the three ``test_two_required_fields_*`` tests below
    exist to catch. An unsaved record is skipped outright, because touching
    a many-to-many manager before the instance has a primary key raises
    ``ValueError`` rather than ``ValidationError`` (R5), and the wrapped
    ``full_clean``'s own errors survive rather than being replaced."""

    @pytest.mark.django_db
    def test_an_optional_field_with_an_empty_set_validates(self):
        outcrop = OutcropFactory()

        outcrop.full_clean()

    @pytest.mark.django_db
    def test_a_required_field_with_an_empty_set_is_refused_naming_the_field(self):
        deposit = DepositFactory()

        with pytest.raises(ValidationError) as excinfo:
            deposit.full_clean()

        assert "rock_types" in excinfo.value.message_dict
        assert any(
            "rock types" in message
            for message in excinfo.value.message_dict["rock_types"]
        )

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
        # Touching Deposit.rock_types before the instance has a primary key
        # raises ValueError, which full_clean() does not catch (R5); the
        # required-set check must not reach it, and a record's memberships
        # cannot exist before the record does (D3).
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
        # #124: ModelForm._post_clean() calls instance.full_clean() before
        # save_m2m() attaches anything, so a saved record's relation is still
        # empty in the database at the moment this package's installed check
        # runs. The check must not read that stale state as a refusal of a
        # submission that would have populated it.
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
        # And the inherited wrapper does cover the subclass's own field.
        assert {
            field.name
            for field in Child._meta.get_fields()
            if isinstance(field, ConceptsField)
        } == {
            "firsts",
            "seconds",
        }


class TestConceptFieldMigrations:
    """T002 — the app migrates from zero, and stays ``makemigrations --check`` clean."""

    @pytest.mark.django_db
    def test_models_are_queryable(self):
        """Tables exist and are queryable — proof the app's own migration
        applied. pytest-django builds the test database from every installed
        app's migrations, run from zero, for the whole session; a query
        against any of these three tables fails outright if it did not."""
        assert Specimen.objects.count() == 0
        assert Sample.objects.count() == 0
        assert Artifact.objects.count() == 0

    @pytest.mark.django_db
    def test_makemigrations_check_is_clean(self):
        """No undeclared model changes: exits normally rather than raising
        ``SystemExit(1)``, which is ``makemigrations --check``'s failure mode
        when it detects an unmade migration."""
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)


class TestConceptFieldCollectionRestrictionMigrations:
    """T011 (US-1, plan.md A7) — a collection-restricted declaration in the
    test app (:class:`~tests.testapp.models.CoreSample`,
    :class:`~tests.testapp.models.DrillCore`) migrates from zero and stays
    ``makemigrations --check`` clean — the same command the story's own
    rituals gate on, run across all apps rather than scoped to one."""

    @pytest.mark.django_db
    def test_models_are_queryable(self):
        """Tables exist and are queryable — proof the restricted
        declarations' migration applied, rebuilding the field from the
        ``collection`` kwarg ``deconstruct()`` emits (T004) rather than
        raising."""
        assert CoreSample.objects.count() == 0
        assert DrillCore.objects.count() == 0

    @pytest.mark.django_db
    def test_makemigrations_check_is_clean_across_all_apps(self):
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)


class TestConceptFieldFactories:
    """The three model factories T002 adds, and the two #111 adds for the
    several- and no-vocabulary shapes, build valid, saved records."""

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
        """The pre-existing definition T011's collision guard must leave alone."""
        artifact = ArtifactFactory()
        assert (
            artifact.get_mineral_label() == "this artifact's own label, not the field's"
        )


class TestConceptVocabularyFixtures:
    """The scheme/concept fixtures ``conftest.py`` now carries for #87, #88, #89."""

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
    """T004 (US-1) — end-to-end usage of the field the way a consuming project
    would use it: a concept from the named vocabulary survives a save/reload,
    an optional field with nothing attached validates and saves, and using the
    field this way stays ``makemigrations --check`` clean."""

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
        """Regression guard for ``deconstruct()`` (T003): using the field
        end-to-end must not surface an undeclared model change beyond what
        Phase F already committed."""
        ConceptFactory()
        SpecimenFactory()

        call_command("makemigrations", "--check", "--dry-run", verbosity=0)


class TestConceptFieldOrdinaryOptions:
    """T004 (US-1) — the field's ordinary ``ForeignKey`` options behave
    exactly as they would on a plain ``ForeignKey``, asserted directly on the
    bound field rather than only through a save/reload round trip."""

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

    def test_verbose_name_and_help_text_are_what_was_declared(self):
        field = Specimen._meta.get_field("rock_type")
        assert field.verbose_name == "rock type"
        assert str(field.help_text) == "The rock type this specimen is classified as."

    def test_the_fks_index_is_present(self):
        field = Specimen._meta.get_field("rock_type")
        assert field.db_index is True


class TestConceptFieldValidation:
    """T005 (US-2) — no new constraint code: ``ForeignKey.validate()`` already
    applies ``limit_choices_to`` before checking existence. What this class
    proves is the behavioural chain T001's ``validate()`` override exists
    for — raise, then *read* ``.messages`` and find the vocabulary named —
    which an unbound field (T001's own tests) cannot reach."""

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
        # error_messages is an ordinary field kwarg, and a consumer's message
        # may use any placeholder a plain ForeignKey supplies. The override
        # adds `vocabulary` to those params; it must not replace them, or
        # reading .messages raises KeyError at form-render time.
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
    """T007 (US-1, FR-008 for the single-value field) — no new constraint
    code: ``ForeignKey.validate()`` already applies ``limit_choices_to``
    (research.md R1), and T006 taught the resolved ``Q`` the collection
    axis. What this class proves is the behavioural chain end to end,
    through :class:`~tests.testapp.models.CoreSample`'s real ``rock_type``
    field: a member of the declared collection validates, and a concept
    from the same vocabulary but outside the collection is refused. The
    message naming the collection is T008's, not this task's — asserted
    there, not here."""

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
    """T008 — extends the existing re-raise (``fields.py:230-270``, now
    choosing between three message ids rather than two): a field restricted
    to a collection names the collection, as one static msgid with a single
    named placeholder (Article XII), not one that varies with the
    restriction's contents. A consumer's own ``error_messages`` override
    still works and the ``ForeignKey``'s own ``params`` are still carried
    through, the same guarantee ``TestConceptFieldValidation.
    test_the_re_raise_keeps_the_foreign_keys_own_params`` already proves for
    the vocabulary-only case."""

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
    """T013 (US-2, FR-008 for the single-value field) — the concepts axis's
    counterpart to T007: no new constraint code, since ``ForeignKey.validate()``
    already applies ``limit_choices_to`` and this task taught the resolved
    ``Q`` the concepts axis. Proves the behavioural chain end to end through
    :class:`~tests.testapp.models.ChipSample`'s real ``rock_type`` field,
    restricted to "granite" and "basalt": a listed concept validates, and a
    concept from the same vocabulary but not on the list is refused. The
    message naming the permitted concepts is the next class's, not this
    task's — asserted there, not here."""

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
    """T013 — extends the same re-raise with a fourth message id: a field
    restricted to an explicit concept list names the permitted concepts, as
    one static msgid with a single named placeholder (Article XII), not one
    that varies with the restriction's contents — the same shape T008
    established for the collection axis. A consumer's own ``error_messages``
    override still works and the ``ForeignKey``'s own ``params`` are still
    carried through."""

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
    """T017 (US-3, FR-008 for the single-value field) — no new constraint
    code: ``ForeignKey.validate()`` already applies ``limit_choices_to``
    (research.md R1), and T018 taught the resolved ``Q`` the branch axis.
    Proves the behavioural chain end to end through
    :class:`~tests.testapp.models.BranchSample`'s real ``rock_type`` field,
    restricted to the "igneous" branch: the root itself validates, a
    grandchild validates, a sibling branch is refused, and the concept the
    root sits *below* is refused. The last two are the ones an inverted
    walk (T015) passes anyway, so neither is optional."""

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
        # An inverted walk (T015) would pass this refusal too, which is
        # exactly why tasks.md marks it non-optional.
        scheme = ConceptSchemeFactory(name="Rock Type")
        root = ConceptFactory(scheme=scheme, label="Igneous")
        ancestor = ConceptFactory(scheme=scheme, label="Rock")
        root.add_broader(ancestor)
        sample = BranchSample(name="Sample D", rock_type=ancestor)

        with pytest.raises(ValidationError):
            sample.full_clean()


class TestConceptFieldBranchRestrictionRefusalMessage:
    """T017 — extends the same re-raise with a fifth message id
    (``decisions.md`` D11's naming pattern, ``invalid_restricted_<axis>``):
    a field restricted to a branch names the branch root, as one static
    msgid with a single named placeholder (Article XII), the same shape
    T008 and T013 established. A consumer's own ``error_messages`` override
    still works and the ``ForeignKey``'s own ``params`` are still carried
    through."""

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
    """Test-only — the plain ``ModelForm`` Django would auto-generate from
    ``Specimen``, used by T006 to prove ``limit_choices_to`` reaches a form's
    field choices and submission validation without this package adding any
    form-layer code of its own."""

    class Meta:
        model = Specimen
        fields = ["name", "rock_type"]


class TestConceptFieldFormChoices:
    """T006 (US-2) — also no new code: ``ForeignKey.formfield()`` passes
    ``limit_choices_to`` through. This class is the proof FR-006 needs."""

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
    """T007 (US-3) — no new code: ``on_delete=PROTECT`` (T001) already refuses
    any delete path that would strand a reference. This class is the proof
    FR-007 needs."""

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
        """The protection lives in the relation rather than in model
        validation, so a bulk ``QuerySet.delete()`` is refused exactly like a
        single-instance delete."""
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = ConceptFactory(scheme=scheme)
        specimen = SpecimenFactory(rock_type=concept)

        with pytest.raises(ProtectedError):
            Concept.objects.filter(pk=concept.pk).delete()

        assert Concept.objects.filter(pk=concept.pk).exists()
        assert Specimen.objects.filter(pk=specimen.pk).exists()

    @pytest.mark.django_db
    def test_deleting_the_scheme_holding_a_referenced_concept_is_refused(self):
        """``Concept.scheme`` cascades, so deleting the scheme tries to
        cascade-delete the concept — and meets the same ``PROTECT`` on the
        way down. Nothing in the scheme is removed."""
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
    """T011 (US-5) — FR-008/FR-009: ``contribute_to_class()`` gives the
    consuming model ``get_<field>_label()`` and ``get_<field>_uri()``, named
    the way Django's own ``get_FOO_display()`` is. The label accessor
    delegates to T010's ``Concept.display_label()``; the URI accessor returns
    the concept's own ``uri`` unchanged. Both return ``None`` rather than
    raising when nothing is attached, and the ``setattr`` is guarded so a
    model that already defines one of these names keeps its own."""

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
    """Test-only — the plain ``ModelForm`` Django would auto-generate from
    :class:`~tests.testapp.models.Borehole`, for the several-vocabulary shape
    #111 added to ``ConceptField``."""

    class Meta:
        model = Borehole
        fields = ["name", "dominant_material"]


class SketchForm(forms.ModelForm):
    """Test-only — the plain ``ModelForm`` Django would auto-generate from
    :class:`~tests.testapp.models.Sketch`, for the no-vocabulary shape #111
    added to ``ConceptField``."""

    class Meta:
        model = Sketch
        fields = ["name", "subject"]


class TestConceptFieldSeveralVocabularies:
    """#111 — a ``ConceptField`` naming two vocabularies accepts a concept from
    either and refuses one from a third, naming both expected vocabularies in
    the refusal. The ``ConceptsField`` counterpart is
    ``TestConceptsFieldSeveralVocabulariesWritePath``.
    """

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
    """#111 — a ``ConceptField`` naming no vocabulary restricts nothing, and
    keeps everything else the field is worth declaring for: the reference
    cannot be deleted out from under the record, and the label and identifier
    still read back. The ``ConceptsField`` counterpart is
    ``TestConceptsFieldNoVocabularyWritePath``.
    """

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
        """``ForeignKey.validate()`` still refuses a primary key no concept
        carries. Reading ``.messages`` is the assertion that matters: the
        vocabulary-naming message would raise ``KeyError`` here, and a message
        naming ``''`` would be worse than useless."""
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


# --- T024 (US-7, Article XII) — every curator-facing string this feature added is translatable ---
#
# Four classes below split the two directions T024 asserts. The first three cover the strings a
# curator actually reads: the three ``invalid_restricted*`` error messages (``TestConceptField*
# RefusalMessage`` above already prove their *content*; these prove they are lazy proxies with
# named placeholders, not incidentally-correct plain strings), the many-valued write guard's three
# refusals, and W005's three messages and hints. The fourth proves the opposite: T002's and T003's
# declaration-rule ``TypeError``s stay plain, untranslated strings, on purpose (research.md R7) —
# they are developer-facing diagnostics raised while a declaration is only being read, matching
# every existing refusal ``ConceptFieldMixin`` already raises the same way, and nothing renders
# them for an end user. That last point is exactly why the direction needs its own test: wrapping
# one in ``_()`` would not visibly break anything, so a later "consistency" pass could do it by
# accident and nothing here would tell it not to without this class.


class TestRestrictionErrorMessagesAreTranslatable:
    """T024 — the three restriction-axis entries in ``ConceptField``'s
    ``default_error_messages`` (T008, T013, T017) are ``gettext_lazy``
    proxies carrying a single named placeholder, the same shape ``invalid``
    already uses. Read directly off ``field.error_messages`` rather than off
    a raised exception: a ``ValidationError``'s own ``__iter__`` does
    ``message %= params`` on a *local* variable and never touches
    ``error.message`` itself (``django/core/exceptions.py``), so the dict
    entry is the one place this is checked before anything has interpolated
    it. ``ConceptsField`` carries no ``error_messages`` dict of its own —
    its refusals are the write guard's, covered by the next class.
    """

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
    """T024 — the many-valued write guard's three refusals
    (``_refuse_concepts_the_restriction_does_not_admit``) are each a
    ``gettext_lazy`` call, not an f-string built per raise. Unlike the class
    above, these are never stored on the field, only raised, so each is
    triggered for real through :class:`~tests.testapp.models.DrillCore`,
    :class:`~tests.testapp.models.ChipTray` and
    :class:`~tests.testapp.models.BranchTray`'s own write paths (the same
    fixtures ``TestConceptsField*RestrictionWritePath`` already drive), and
    the caught ``ValidationError``'s own ``.message`` — untouched by
    ``.messages``, for the reason given above — is asserted directly.
    """

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
    """Every string this ``func`` passes straight to ``_()``/``gettext_lazy()``.

    Reads the function's own source rather than calling it: ``checks.py``'s
    ``message % {...}`` interpolates a ``gettext_lazy()`` proxy immediately
    (the same ``%`` behaviour ``fields.py:97-114``'s annotation warns
    ``default_help_text`` against), so by the time a warning is produced the
    lazy proxy is already gone, replaced by an ordinary ``str`` that carries
    no trace of having started translatable. Reading the source is the one
    place that distinction still exists (``TestFieldsChecksI18nSweep`` in
    ``test_standards.py`` takes the same approach for the whole module, for
    the same reason).
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
    """T024 — W005's three messages (one per restriction axis) and their
    hints are each a single ``_()`` call with only named placeholders, never
    one assembled per call. Checked against the function's own source
    (:func:`_translation_call_string_literals`) rather than a rendered
    warning, for the reason given there.
    """

    def test_every_message_and_hint_is_a_translation_call(self):
        literals = _translation_call_string_literals(
            checks_module.check_concept_field_restriction_targets
        )

        expected_messages = {
            "%(model)s.%(field)s names collection '%(target)s', which does not exist in the "
            "'%(vocabulary)s' vocabulary.",
            "%(model)s.%(field)s names concept '%(target)s', which does not exist in the '%(vocabulary)s' vocabulary.",
            "%(model)s.%(field)s names branch root '%(target)s', which does not exist in the "
            "'%(vocabulary)s' vocabulary.",
        }
        expected_hints = {
            "Create this collection, or correct the name.",
            "Create this concept, or correct the name.",
        }

        assert expected_messages <= set(literals)
        assert expected_hints <= set(literals)

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


class TestDeclarationRuleTypeErrorsStayUntranslated:
    """T024's other direction (research.md R7) — the declaration-rule
    ``TypeError``s from T002 (FR-005, FR-006) and T003
    (``_normalise_vocabulary``/``_normalise_restriction_slug``/
    ``_normalise_concepts``) stay plain, untranslated ``str`` objects. They
    are developer-facing diagnostics raised while a declaration is read, the
    same class of message every pre-existing refusal in ``fields.py``
    (``on_delete``, ``through``, ``limit_choices_to``) already raises
    untranslated, and Article XII's translation requirement is explicit that
    a developer-facing diagnostic is exempt. Asserted here, deliberately, so
    a later pass making "every message translatable" its whole brief does
    not wrap these too: nothing renders a ``TypeError`` for a curator or a
    form-filler to read, so doing so would not visibly break anything and
    would go unnoticed without a test naming the exact reverse expectation.
    """

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
