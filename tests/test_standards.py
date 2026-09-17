"""US-7 — Translatable, self-documenting field metadata + deliberate indexing.

FS-002 extends the vocabulary to four models (``ConceptScheme``, ``Concept``,
``ConceptLabel``, ``ConceptNote``). This suite holds every one of them to the
same standard #15 set for the first two:

- Article XII: every editable field carries a lazily-translatable ``verbose_name``
  and a non-empty, lazily-translatable ``help_text``; user-facing validation
  messages are translatable with *named* placeholders (the
  ``ValidationError(msgid, params=…)`` form — #15 ``decisions.md`` §9).
- Article XIII: indexing is deliberate. ``ConceptLabel`` is indexed on its
  ``(language, kind, text)`` lookup path and enforces one preferred label per
  language; ``ConceptNote.value`` is free prose and stays unindexed (FS-002
  ``decisions.md`` §20).

It walks ``_meta`` rather than a hand-listed field set, so a future field is
held to the same standard automatically.
"""

import ast
import inspect
import re
from pathlib import Path

import pytest
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db.models import Model, UniqueConstraint
from django.utils.functional import Promise
from django.utils.text import Truncator

from controlled_vocabularies import admin as admin_module
from controlled_vocabularies import checks as checks_module
from controlled_vocabularies import fields as fields_module
from controlled_vocabularies import forms as forms_module
from controlled_vocabularies import views as views_module
from controlled_vocabularies.exchange.report import (
    NormalizedEntry,
    NormalizedReason,
    SetAsideEntry,
    SetAsideReason,
)
from controlled_vocabularies.management import rendering as rendering_module
from controlled_vocabularies.management import sources as sources_module
from controlled_vocabularies.management.commands import (
    import_skos as import_skos_command_module,
)
from controlled_vocabularies.models import (
    Collection,
    CollectionMember,
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptRelation,
    ConceptScheme,
    validate_static_uri,
)

ALL_MODELS = [
    ConceptScheme,
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptRelation,
    Collection,
    CollectionMember,
]


def _editable_fields(model: type[Model]):
    """The model's own, user-editable, concrete fields (excludes the auto pk
    and reverse relations) — every one must meet the metadata standard."""
    return [
        field
        for field in model._meta.get_fields()
        if getattr(field, "concrete", False)
        and getattr(field, "editable", False)
        and not field.auto_created
    ]


# --- Article XII: every editable field carries lazy verbose_name + non-empty help_text ---


@pytest.mark.parametrize("model", ALL_MODELS)
def test_every_editable_field_has_metadata(model):
    fields = _editable_fields(model)
    assert fields, f"{model.__name__} exposes no editable fields to check"
    for field in fields:
        # help_text: present, non-empty, and a lazy translation proxy.
        assert field.help_text, f"{model.__name__}.{field.name} has no help_text"
        assert isinstance(field.help_text, Promise), (
            f"{model.__name__}.{field.name}.help_text is not lazily translatable"
        )
        # verbose_name: a lazy translation proxy (Django defaults it to a plain
        # str derived from the attribute name, which is not translatable).
        assert isinstance(field.verbose_name, Promise), (
            f"{model.__name__}.{field.name}.verbose_name is not lazily translatable"
        )


@pytest.mark.parametrize("model", ALL_MODELS)
def test_meta_verbose_names_are_lazy(model):
    assert isinstance(model._meta.verbose_name, Promise), (
        f"{model.__name__} Meta.verbose_name is not lazily translatable"
    )
    assert isinstance(model._meta.verbose_name_plural, Promise), (
        f"{model.__name__} Meta.verbose_name_plural is not lazily translatable"
    )


def test_app_config_verbose_name_is_lazy():
    from django.apps import apps

    verbose_name = apps.get_app_config("controlled_vocabularies").verbose_name
    assert isinstance(verbose_name, Promise), (
        "AppConfig.verbose_name is not lazily translatable"
    )


# --- Article XII: the new FS-002 validation messages are translatable, with named placeholders ---


def _inner_error(exc: ValidationError, field: str) -> ValidationError:
    """The single field-scoped ValidationError carrying the lazy message."""
    return exc.error_dict[field][0]


@pytest.mark.django_db
def test_missing_default_language_label_message_uses_named_placeholder(scheme):
    # FR-002: a concept needs a preferred label in the scheme's effective default
    # language. The refusal names that language through a *named* placeholder, so the
    # translatable msgid stays static and the language is supplied via params.
    with pytest.raises(ValidationError) as excinfo:
        Concept.objects.create(scheme=scheme, label="")
    err = _inner_error(excinfo.value, "label")
    assert isinstance(err.message, Promise), (
        "missing-default-language-label message is not lazily translatable"
    )
    assert "%(language)s" in str(err.message), (
        "message lacks a named %(language)s placeholder"
    )
    assert err.params == {"language": scheme.effective_default_language}
    # ...and it still renders with the real language substituted in.
    assert scheme.effective_default_language in excinfo.value.messages[0]


@pytest.mark.django_db
def test_duplicate_preferred_label_message_uses_named_placeholder(scheme):
    # FR-001: at most one preferred label per language. The second is refused with a
    # translatable, curator-facing message that names the language via a placeholder.
    concept = Concept.objects.create(scheme=scheme, label="Heat flow")
    concept.add_label(
        language="de", kind=ConceptLabel.Kind.PREFERRED, text="Wärmefluss"
    )
    with pytest.raises(ValidationError) as excinfo:
        concept.add_label(
            language="de",
            kind=ConceptLabel.Kind.PREFERRED,
            text="Terrestrischer Wärmefluss",
        )
    err = _inner_error(excinfo.value, "language")
    assert isinstance(err.message, Promise), (
        "duplicate-preferred-label message is not lazily translatable"
    )
    assert "%(language)s" in str(err.message), (
        "message lacks a named %(language)s placeholder"
    )
    assert err.params == {"language": "de"}
    assert "de" in excinfo.value.messages[0]


class TestStaticUriValidationMessages:
    """Article XII — the FS-005 ``static_uri`` metadata and validation messages.

    ``static_uri`` is added identically to ``ConceptScheme``, ``Concept``, and
    ``Collection``, all three already in ``ALL_MODELS`` above, so
    ``test_every_editable_field_has_metadata`` already holds its
    ``verbose_name`` and ``help_text`` to the standard. What that generic walk
    cannot see is whether each refusal this feature introduces is itself
    translatable and named — asserted explicitly below, one test per refusal,
    following the pattern above.
    """

    def test_static_uri_not_absolute_message_uses_named_placeholder(self):
        # FR-004/FR-010: a bare relative value is refused, naming the offending value.
        with pytest.raises(ValidationError) as excinfo:
            validate_static_uri("not-absolute")
        err = excinfo.value
        assert isinstance(err.message, Promise), (
            "not-absolute message is not lazily translatable"
        )
        assert "%(uri)s" in str(err.message), (
            "message lacks a named %(uri)s placeholder"
        )
        assert err.params == {"uri": "not-absolute"}
        assert "not-absolute" in excinfo.value.messages[0]

    def test_static_uri_unsafe_scheme_message_uses_named_placeholders(self, settings):
        # FR-004/FR-010: a scheme that can carry executable content is refused, naming
        # both the value and the offending scheme. "javascript" is outside the default
        # allowlist (T035) so it would already be refused there; the allowlist is
        # overridden to include it so this exercises the denylist's own message.
        settings.CONTROLLED_VOCABULARIES_ALLOWED_URI_SCHEMES = [
            "http",
            "https",
            "javascript",
        ]
        with pytest.raises(ValidationError) as excinfo:
            validate_static_uri("javascript:alert(1)")
        err = excinfo.value
        assert isinstance(err.message, Promise), (
            "unsafe-scheme message is not lazily translatable"
        )
        assert "%(uri)s" in str(err.message) and "%(scheme)s" in str(err.message)
        assert err.params == {"uri": "javascript:alert(1)", "scheme": "javascript"}
        assert "javascript" in excinfo.value.messages[0]
        assert err.code == "static_uri_unsafe_scheme"

    def test_static_uri_scheme_not_allowed_message_uses_named_placeholders(self):
        # T035: a scheme outside the configured allowlist is refused, naming both the
        # value and the offending scheme.
        with pytest.raises(ValidationError) as excinfo:
            validate_static_uri("file:///etc/passwd")
        err = excinfo.value
        assert isinstance(err.message, Promise), (
            "scheme-not-allowed message is not lazily translatable"
        )
        assert "%(uri)s" in str(err.message) and "%(scheme)s" in str(err.message)
        assert err.params == {"uri": "file:///etc/passwd", "scheme": "file"}
        assert err.code == "static_uri_scheme_not_allowed"

    def test_static_uri_too_long_message_uses_named_placeholders(self):
        # FR-004/FR-010: an over-length identifier is refused, naming the bound and the
        # offending value's actual length. The echoed value itself is bounded to 80 chars
        # (T032) — a hostile value can be arbitrarily long, and echoing it in full would
        # make the message itself another hazard — but the true length is still reported.
        overlong = "http://example.org/" + "x" * 500
        with pytest.raises(ValidationError) as excinfo:
            validate_static_uri(overlong)
        err = excinfo.value
        assert isinstance(err.message, Promise), (
            "too-long message is not lazily translatable"
        )
        assert all(
            placeholder in str(err.message)
            for placeholder in ("%(max_length)s", "%(uri)s", "%(length)s")
        )
        assert err.params == {
            "max_length": 500,
            "uri": str(Truncator(overlong).chars(80)),
            "length": len(overlong),
        }

    def test_static_uri_unparseable_message_uses_named_placeholder(self):
        # T031: urllib.parse.urlsplit raises a bare ValueError for some malformed input
        # (e.g. a netloc invalid under NFKC normalization); caught and re-raised as a
        # translatable ValidationError naming the offending value.
        with pytest.raises(ValidationError) as excinfo:
            validate_static_uri("http://exa℀mple.com/x")
        err = excinfo.value
        assert isinstance(err.message, Promise), (
            "unparseable message is not lazily translatable"
        )
        assert "%(uri)s" in str(err.message), (
            "message lacks a named %(uri)s placeholder"
        )
        assert err.params == {"uri": "http://exa℀mple.com/x"}
        assert err.code == "static_uri_unparseable"


# --- FS-007: the two new closed-vocabulary import report reasons are translatable, named-placeholder messages ---


class TestImportLanguageMessagesUseNamedPlaceholders:
    """Article XII / SC-018 — this feature adds two entries to the importer's
    closed reason vocabularies (``report.py``): ``NormalizedReason.LANGUAGE_SUBSTITUTION``
    and the contest-loser ``SetAsideReason.VARIANT_NOT_KEPT``. Each must be
    lazily translatable and carry only named placeholders, the same standard
    the field-metadata and validation-message tests above hold every other
    curator-facing message to.
    """

    def test_language_substitution_reason_message_uses_named_placeholders(self):
        # FR-006/FR-012: a value stored under a configured language other than its
        # published tag names both the published tag and the language it was stored
        # under, via named placeholders rather than positional ones.
        assert isinstance(NormalizedReason.LANGUAGE_SUBSTITUTION.template, Promise), (
            "LANGUAGE_SUBSTITUTION template is not lazily translatable"
        )
        template = str(NormalizedReason.LANGUAGE_SUBSTITUTION.template)
        assert "%(language)s" in template and "%(kept_as)s" in template, (
            "LANGUAGE_SUBSTITUTION template lacks named %(language)s/%(kept_as)s placeholders"
        )
        entry = NormalizedEntry(
            reason=NormalizedReason.LANGUAGE_SUBSTITUTION,
            subject="https://example.org/vocab/rocks/granite",
            params={"language": "en-gb", "kept_as": "en"},
        )
        rendered = entry.render()
        assert "en-gb" in rendered
        assert "en" in rendered

    def test_the_kept_as_placeholder_actually_interpolates_its_own_value(self):
        # T027 — CORR-004/SEC-005: the sibling test above asserts "en" in
        # rendered, which the "en-gb" it also asserts is a substring of, so it
        # would still pass even if %(kept_as)s stopped interpolating entirely.
        # Non-overlapping values (the shape test_variant_not_kept_reason_message
        # already uses) so this assertion actually depends on the placeholder.
        entry = NormalizedEntry(
            reason=NormalizedReason.LANGUAGE_SUBSTITUTION,
            subject="https://example.org/vocab/rocks/granite",
            params={"language": "en-gb", "kept_as": "zh-hans"},
        )
        rendered = entry.render()
        assert "en-gb" in rendered
        assert "zh-hans" in rendered

    def test_variant_not_kept_reason_message_uses_named_placeholders(self):
        # FR-005/FR-012: a contest loser names the published tag it lost and the
        # configured language it lost to, via named placeholders rather than positional
        # ones.
        assert isinstance(SetAsideReason.VARIANT_NOT_KEPT.template, Promise), (
            "VARIANT_NOT_KEPT template is not lazily translatable"
        )
        template = str(SetAsideReason.VARIANT_NOT_KEPT.template)
        assert "%(language)s" in template and "%(kept_as)s" in template, (
            "VARIANT_NOT_KEPT template lacks named %(language)s/%(kept_as)s placeholders"
        )
        entry = SetAsideEntry(
            reason=SetAsideReason.VARIANT_NOT_KEPT,
            subject="https://example.org/vocab/rocks/granite",
            params={"language": "en-us", "kept_as": "en-gb"},
        )
        rendered = entry.render()
        assert "en-us" in rendered
        assert "en-gb" in rendered


# --- Article XIII: indexing is deliberate on the two new models ---


def test_concept_label_lookup_path_is_indexed():
    # FR-015: the (language, kind, text) lookup/search path is indexed.
    indexed = [tuple(index.fields) for index in ConceptLabel._meta.indexes]
    assert ("language", "kind", "text") in indexed, (
        f"ConceptLabel is missing a (language, kind, text) index; has {indexed}"
    )


def test_concept_label_has_one_preferred_per_language_constraint():
    constraint = next(
        (
            c
            for c in ConceptLabel._meta.constraints
            if isinstance(c, UniqueConstraint)
            and c.name == "one_preferred_label_per_language"
        ),
        None,
    )
    assert constraint is not None, (
        "missing one_preferred_label_per_language partial unique constraint"
    )
    assert tuple(constraint.fields) == ("concept", "language")
    assert constraint.condition is not None, (
        "the preferred-label uniqueness must be a *partial* constraint"
    )


def test_concept_note_value_is_unindexed():
    # decisions.md §20: value is free documentary prose with no lookup path this
    # slice, so it carries no db_index and appears in no explicit index.
    assert ConceptNote._meta.get_field("value").db_index is False, (
        "ConceptNote.value must stay unindexed"
    )
    for index in ConceptNote._meta.indexes:
        assert "value" not in index.fields, (
            "ConceptNote.value must not be part of any index"
        )


def test_concept_note_and_label_fks_are_indexed():
    # FKs are auto-indexed; assert it holds for the two new child models.
    assert ConceptLabel._meta.get_field("concept").db_index is True
    assert ConceptNote._meta.get_field("concept").db_index is True


# --- FS-003: the relation model meets the same metadata + indexing standard ---


def _authored_nonfield_error(exc: ValidationError) -> ValidationError:
    """The authored non-field ValidationError (params-bearing, else the first).

    The relation invariants raise non-field errors under ``__all__``; ``full_clean`` may
    append the DB constraint's own message alongside ours, so pick the one we authored.
    """
    errors = exc.error_dict[NON_FIELD_ERRORS]
    return next((e for e in errors if getattr(e, "params", None)), errors[0])


@pytest.mark.django_db
def test_self_relation_message_is_translatable():
    # FR-006: a self message names nothing dynamic, so it carries no placeholder — but it
    # must still be a lazily-translatable string, not a bare str.
    scheme = ConceptScheme.objects.create(name="Rock types")
    granite = Concept.objects.create(scheme=scheme, label="Granite")
    with pytest.raises(ValidationError) as excinfo:
        granite.add_broader(granite)
    err = _authored_nonfield_error(excinfo.value)
    assert isinstance(err.message, Promise), (
        "self-relation message is not lazily translatable"
    )


@pytest.mark.django_db
def test_cross_vocabulary_relation_message_uses_named_placeholders():
    # FR-009: the refusal names both vocabularies via *named* placeholders so the msgid stays static.
    rocks = ConceptScheme.objects.create(name="Rock types")
    minerals = ConceptScheme.objects.create(name="Minerals")
    granite = Concept.objects.create(scheme=rocks, label="Granite")
    quartz = Concept.objects.create(scheme=minerals, label="Quartz")
    with pytest.raises(ValidationError) as excinfo:
        granite.add_related(quartz)
    err = _authored_nonfield_error(excinfo.value)
    assert isinstance(err.message, Promise), (
        "cross-vocabulary message is not lazily translatable"
    )
    assert "%(source)s" in str(err.message) and "%(target)s" in str(err.message)
    assert set(err.params) == {"source", "target"}


@pytest.mark.django_db
def test_disjointness_message_uses_named_placeholder():
    # FR-008: the refusal names the conflicting kind via a placeholder.
    scheme = ConceptScheme.objects.create(name="Rock types")
    granite = Concept.objects.create(scheme=scheme, label="Granite")
    igneous = Concept.objects.create(scheme=scheme, label="Igneous rock")
    granite.add_broader(igneous)
    with pytest.raises(ValidationError) as excinfo:
        granite.add_related(igneous)
    err = _authored_nonfield_error(excinfo.value)
    assert isinstance(err.message, Promise), (
        "disjointness message is not lazily translatable"
    )
    assert "%(kind)s" in str(err.message)
    assert set(err.params) == {"kind"}


def test_concept_relation_reverse_read_path_is_indexed():
    # FR-012 / research R6: the (target, kind) reverse-read path is indexed deliberately.
    indexed = [tuple(index.fields) for index in ConceptRelation._meta.indexes]
    assert ("target", "kind") in indexed, (
        f"ConceptRelation missing a (target, kind) index; has {indexed}"
    )


def test_concept_relation_has_unique_and_self_constraints():
    names = {c.name for c in ConceptRelation._meta.constraints}
    assert "unique_concept_relation" in names, (
        "missing the (source, target, kind) unique constraint (FR-007)"
    )
    assert "concept_relation_not_self" in names, (
        "missing the not-self check constraint (FR-006)"
    )
    unique = next(
        c
        for c in ConceptRelation._meta.constraints
        if c.name == "unique_concept_relation"
    )
    assert tuple(unique.fields) == ("source", "target", "kind")


def test_concept_relation_fks_are_indexed():
    # FKs are auto-indexed; the source-leading composite comes from the unique constraint,
    # the target-leading from the explicit index above.
    assert ConceptRelation._meta.get_field("source").db_index is True
    assert ConceptRelation._meta.get_field("target").db_index is True


# --- FS-004: the collection models meet the same metadata + indexing standard ---
# (Collection and CollectionMember are in ALL_MODELS above, so the field-metadata and
# Meta.verbose_name walks already cover them. Below: the new validation messages and the
# deliberate indexing decision.)


@pytest.mark.django_db
def test_cross_vocabulary_membership_message_uses_named_placeholders():
    # FR-005: adding a concept from another vocabulary names both vocabularies via *named*
    # placeholders so the translatable msgid stays static.
    rocks = ConceptScheme.objects.create(name="Rocks")
    minerals = ConceptScheme.objects.create(name="Minerals")
    igneous = Collection.objects.create(scheme=rocks, name="Igneous")
    mica = Concept.objects.create(scheme=minerals, label="Mica")
    with pytest.raises(ValidationError) as excinfo:
        igneous.add(mica)
    err = _authored_nonfield_error(excinfo.value)
    assert isinstance(err.message, Promise), (
        "cross-vocabulary membership message is not lazily translatable"
    )
    assert "%(concept_scheme)s" in str(err.message) and "%(collection_scheme)s" in str(
        err.message
    )
    assert set(err.params) == {"concept_scheme", "collection_scheme"}


@pytest.mark.django_db
def test_not_ordered_guard_message_uses_named_placeholder():
    # FR-006: ordering an unordered collection is refused with a translatable message that
    # names the collection via a placeholder.
    scheme = ConceptScheme.objects.create(name="Rocks")
    granite = Concept.objects.create(scheme=scheme, label="Granite")
    plain = Collection.objects.create(scheme=scheme, name="A set")
    plain.add(granite)
    with pytest.raises(ValidationError) as excinfo:
        plain.set_member_order([granite])
    # a non-field ValidationError raised directly (no error_dict); read messages/params off it
    assert isinstance(excinfo.value.messages[0], str)
    err = excinfo.value.error_list[0]
    assert isinstance(err.message, Promise), (
        "not-ordered guard message is not lazily translatable"
    )
    assert "%(name)s" in str(err.message)
    assert set(err.params) == {"name"}


def test_collection_member_has_held_once_constraint_and_order_index():
    # FR-004 / Article XIII: held-once is a DB unique constraint; the ordered read is index-backed.
    names = {c.name for c in CollectionMember._meta.constraints}
    assert "unique_collection_member" in names, (
        "missing the (collection, concept) held-once constraint (FR-004)"
    )
    unique = next(
        c
        for c in CollectionMember._meta.constraints
        if c.name == "unique_collection_member"
    )
    assert tuple(unique.fields) == ("collection", "concept")
    indexed = [tuple(index.fields) for index in CollectionMember._meta.indexes]
    assert ("collection", "position") in indexed, (
        f"CollectionMember missing a (collection, position) index; has {indexed}"
    )


def test_collection_has_per_scheme_unique_slug_constraint():
    # FR-009: two collections in one vocabulary are distinguishable by a per-scheme-unique slug.
    constraint = next(
        (
            c
            for c in Collection._meta.constraints
            if isinstance(c, UniqueConstraint)
            and c.name == "unique_collection_slug_per_scheme"
        ),
        None,
    )
    assert constraint is not None, (
        "missing unique_collection_slug_per_scheme constraint"
    )
    assert tuple(constraint.fields) == ("scheme", "slug")


def test_collection_member_fks_are_indexed():
    # FKs are auto-indexed; the reverse read (a concept's collections) rides the concept FK index.
    assert CollectionMember._meta.get_field("collection").db_index is True
    assert CollectionMember._meta.get_field("concept").db_index is True


class TestStaticUriIndexing:
    """FS-005 — ``static_uri``'s indexing decision (data-model.md "Indexing decision").

    ``static_uri`` is indexed by its own partial unique constraint, and
    nothing else in this feature gains an index: ``local_url``, ``uri``, and
    ``has_static_uri`` are properties, not columns, composed from slug fields
    R1 already indexed and constrained.
    """

    @pytest.mark.parametrize("model", [ConceptScheme, Concept, Collection])
    def test_static_uri_is_covered_only_by_its_partial_unique_constraint(self, model):
        field = model._meta.get_field("static_uri")
        assert field.db_index is False, (
            f"{model.__name__}.static_uri must not carry a plain db_index"
        )
        for index in model._meta.indexes:
            assert "static_uri" not in index.fields, (
                f"{model.__name__}.static_uri must not appear in any explicit Meta.indexes entry"
            )
        constraint_name = f"{model.__name__.lower()}_static_uri_unique"
        constraint = next(
            (
                c
                for c in model._meta.constraints
                if isinstance(c, UniqueConstraint) and c.name == constraint_name
            ),
            None,
        )
        assert constraint is not None, (
            f"missing {constraint_name} partial unique constraint"
        )
        assert tuple(constraint.fields) == ("static_uri",)
        assert constraint.condition is not None, (
            "static_uri's uniqueness must be a *partial* constraint"
        )

    def test_local_url_and_has_static_uri_are_properties_not_indexable_columns(self):
        # Neither local_url nor has_static_uri is a model field, so neither can carry an
        # index; they compose from slug fields already indexed/constrained by R1.
        for model in (ConceptScheme, Concept, Collection):
            field_names = {field.name for field in model._meta.get_fields()}
            assert "local_url" not in field_names, (
                f"{model.__name__}.local_url must not be a model field"
            )
            assert "has_static_uri" not in field_names, (
                f"{model.__name__}.has_static_uri must not be a model field"
            )
            assert isinstance(model.local_url, property)
            assert isinstance(model.has_static_uri, property)


class TestStaticUriFieldAttributesAgree:
    """Review round 4. ``ConceptScheme``, ``Concept``, and ``Collection`` each
    redeclared the entire ``static_uri`` field — ``max_length``, ``null``,
    ``blank``, ``verbose_name``, and ``validators`` byte-identical, only
    ``help_text`` legitimately differing per model. Nothing asserted they
    agreed, so one model's ``max_length`` (say) could drift silently and
    every one of the existing tests would still pass. This walks the three
    concrete models' own field and fails the moment one of the shared
    attributes stops matching the others.
    """

    def test_the_three_concrete_models_static_uri_fields_agree_on_every_shared_attribute(
        self,
    ):
        fields = {
            model: model._meta.get_field("static_uri")
            for model in (ConceptScheme, Concept, Collection)
        }
        max_lengths = {
            model.__name__: field.max_length for model, field in fields.items()
        }
        nulls = {model.__name__: field.null for model, field in fields.items()}
        blanks = {model.__name__: field.blank for model, field in fields.items()}
        verbose_names = {
            model.__name__: str(field.verbose_name) for model, field in fields.items()
        }

        # Validators are compared by (type, limit_value) rather than identity or raw repr:
        # Django gives every field its own MaxLengthValidator *instance* (derived from
        # max_length), so instances that are equivalent are still distinct objects with
        # distinct default reprs — comparing raw repr would report a false disagreement.
        def _validator_signature(v):
            return (
                type(v).__name__,
                getattr(v, "limit_value", None),
                getattr(v, "__qualname__", None),
            )

        validator_reprs = {
            model.__name__: [_validator_signature(v) for v in field.validators]
            for model, field in fields.items()
        }
        assert len(set(max_lengths.values())) == 1, (
            f"static_uri.max_length disagrees across models: {max_lengths}"
        )
        assert len(set(nulls.values())) == 1, (
            f"static_uri.null disagrees across models: {nulls}"
        )
        assert len(set(blanks.values())) == 1, (
            f"static_uri.blank disagrees across models: {blanks}"
        )
        assert len(set(verbose_names.values())) == 1, (
            f"static_uri.verbose_name disagrees across models: {verbose_names}"
        )
        assert len({tuple(v) for v in validator_reprs.values()}) == 1, (
            f"static_uri.validators disagrees across models: {validator_reprs}"
        )


# --- FS-008 US-6: the management command package's i18n sweep (Article XII, FR-015, T023) ---
#
# By the time a rendered line reaches a terminal, `ReportRenderer` has already %-formatted a
# translated template into a plain string — the placeholder shape is gone. So this is a static
# check over the three source files themselves rather than a runtime introspection of rendered
# output: no string reaching a known output sink (`CommandError`, `self.stdout`/`self.stderr.write`,
# `parser.add_argument(help=...)`, or a command's own `help = ...`) is a bare literal, and no string
# passed to a translation call (`_`/`gettext_lazy`/`ngettext_lazy`) carries a positional `%`
# placeholder rather than a named one.

_MANAGEMENT_I18N_MODULES = [
    import_skos_command_module,
    rendering_module,
    sources_module,
]
_TRANSLATION_CALL_NAMES = {"_", "gettext_lazy", "ngettext_lazy"}
# A `%` not immediately followed by `(` (a named placeholder's opening paren) or another `%`
# (an escaped literal percent) is positional: %s, %d, %-10.2f, and so on.
_POSITIONAL_PLACEHOLDER = re.compile(r"%(?!%|\()[-+ 0#]*\d*(?:\.\d+)?[a-zA-Z]")


class ManagementI18nVisitor(ast.NodeVisitor):
    """Walks one module's AST, recording every positional placeholder passed to a translation
    call and every bare string literal reaching a known output sink un-translated."""

    def __init__(self) -> None:
        self.positional_placeholders: list[str] = []
        self.bare_literals: list[str] = []

    @staticmethod
    def _call_name(node: ast.Call) -> str | None:
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    @staticmethod
    def _str_constant(node: ast.expr) -> str | None:
        return (
            node.value
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            else None
        )

    def visit_Call(self, node: ast.Call) -> None:
        name = self._call_name(node)
        if name in _TRANSLATION_CALL_NAMES:
            for arg in node.args:
                literal = self._str_constant(arg)
                if literal is not None and _POSITIONAL_PLACEHOLDER.search(literal):
                    self.positional_placeholders.append(literal)
        elif name == "CommandError":
            for arg in node.args:
                literal = self._str_constant(arg)
                if literal is not None:
                    self.bare_literals.append(literal)
        elif name == "write" and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Attribute) and owner.attr in {"stdout", "stderr"}:
                for arg in node.args:
                    literal = self._str_constant(arg)
                    if literal is not None:
                        self.bare_literals.append(literal)
        elif name == "add_argument":
            for kw in node.keywords:
                if kw.arg == "help":
                    literal = self._str_constant(kw.value)
                    if literal is not None:
                        self.bare_literals.append(literal)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # A command's own `help = "..."` class attribute (Django reads it as the command's
        # top-level help text, alongside every argument's own `help=`).
        if any(
            isinstance(target, ast.Name) and target.id == "help"
            for target in node.targets
        ):
            literal = self._str_constant(node.value)
            if literal is not None:
                self.bare_literals.append(literal)
        self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield) -> None:
        literal = self._str_constant(node.value) if node.value is not None else None
        if literal is not None:
            self.bare_literals.append(literal)
        self.generic_visit(node)


def _visit_source(source: str) -> ManagementI18nVisitor:
    visitor = ManagementI18nVisitor()
    visitor.visit(ast.parse(source))
    return visitor


class TestManagementI18nSweepVisitorCatchesAViolation:
    """Proves the checker below is a real gate, not a vacuous one: each of these feeds it a
    deliberately bad snippet it must flag, before the sweep test trusts it to report a clean
    management package."""

    def test_catches_a_positional_placeholder_in_a_translation_call(self):
        visitor = _visit_source(
            'from django.utils.translation import gettext_lazy as _\n_("%s changed")\n'
        )
        assert visitor.positional_placeholders == ["%s changed"]

    def test_catches_a_bare_literal_raised_as_a_command_error(self):
        visitor = _visit_source(
            "from django.core.management.base import CommandError\nraise CommandError('boom')\n"
        )
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_written_to_stdout(self):
        visitor = _visit_source("self.stdout.write('boom')\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_as_an_argument_help(self):
        visitor = _visit_source("parser.add_argument('--x', help='boom')\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_as_the_command_help_attribute(self):
        visitor = _visit_source("class Command(BaseCommand):\n    help = 'boom'\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_yielded_as_a_rendered_line(self):
        visitor = _visit_source("def render():\n    yield 'boom'\n")
        assert visitor.bare_literals == ["boom"]

    def test_does_not_flag_a_named_placeholder_or_a_translated_sink(self):
        visitor = _visit_source(
            "from django.utils.translation import gettext_lazy as _\n"
            "from django.core.management.base import CommandError\n"
            "raise CommandError(str(_(\"'%(file)s' is fine.\")) % {'file': 'x'})\n"
        )
        assert visitor.positional_placeholders == []
        assert visitor.bare_literals == []


class TestManagementPackageI18nSweep:
    """T023 — the sweep itself. Every printed and help string in the management command
    package (``commands/import_skos.py``, ``rendering.py``, ``sources.py``) is translatable
    with only named placeholders. Earlier tasks wrapped as they wrote; this asserts the whole
    package holds, so a later addition that misses one is caught here rather than by review."""

    @pytest.mark.parametrize(
        "module", _MANAGEMENT_I18N_MODULES, ids=lambda m: m.__name__
    )
    def test_every_output_string_is_translatable_with_named_placeholders(self, module):
        source = Path(inspect.getfile(module)).read_text()
        visitor = _visit_source(source)
        assert visitor.positional_placeholders == [], (
            f"{module.__name__} passes a positional placeholder to a translation call: "
            f"{visitor.positional_placeholders}"
        )
        assert visitor.bare_literals == [], (
            f"{module.__name__} passes a bare, untranslated literal to an output sink: {visitor.bare_literals}"
        )


# --- FS-009 US-6 (T012), extended FS-011 US-7 (T011), extended 012 US-6 (T018): fields.py,
# --- checks.py, views.py, forms.py and admin.py carry no bare user-visible literal, and no
# --- translated one carries a positional placeholder ---
#
# The management-package sweep above (`ManagementI18nVisitor`) is built for CommandError,
# stdout/stderr.write, add_argument(help=...) and a class-level help = "...". None of those
# shapes appears in a field, a system check, a view or a form, so pointing it at these modules
# unmodified would report a clean sweep regardless of what they actually contain — the exact
# false-green tasks.md warns against. This visitor recognises the sinks these four modules
# actually carry: a Field/ForeignKey-style call's `help_text=`/`verbose_name=` keyword literal
# (including `kwargs.setdefault("help_text", ...)`, the form `ConceptField` and `ConceptsField`
# both use so a consumer can still override the default), an `error_messages`/
# `default_error_messages` dict's literal values, a bare string passed to `ValidationError(...)`
# or `ImproperlyConfigured(...)` — the exception `forms.py`'s widgets raise when a project
# ignores the route-inclusion check (T008, decisions.md D14) — `checks.Warning(...)` or
# `checks.Error(...)`, and a `help_text`/`verbose_name`/`verbose_name_plural` key in *any* dict
# literal — the shape `ConceptsField`'s generated through-model `Meta` uses
# (`type("Meta", (), {...})`), which a keyword-argument check cannot see at all. It also flags a
# positional placeholder (`%s`, `%d`, ...) passed directly to a translation call (`_`,
# `gettext_lazy`, `ngettext_lazy`), the same standard the management sweep above already holds
# `import_skos.py`/`rendering.py`/`sources.py` to, extended here to these four modules so a
# system check's interpolated message (`checks.py`'s vocabulary warning) is held to it too.
# `on_delete`/`vocabulary`/`limit_choices_to`/`through` are rejected via bare `TypeError`s in
# `fields.py`, deliberately outside every one of these sinks — they are developer-facing,
# import-time diagnostics, not something an end user ever reads (decisions.md D8).
#
# `admin.py` (012) joined the set below rather than gaining a parallel sweep of its own
# (`decisions.md` D25): it is the one production module 012 added that this list did not yet
# cover, and it carries the same kind of sinks this visitor already recognises — none of them
# populated, since the module is one lazy lookup function that returns a class or `None`.

_FIELDS_CHECKS_MODULES = [
    fields_module,
    checks_module,
    forms_module,
    views_module,
    admin_module,
]
_FIELD_METADATA_KEYWORDS = {"help_text", "verbose_name", "verbose_name_plural"}
_DIAGNOSTIC_MESSAGE_KEYWORDS = {"msg", "message", "hint"}


class FieldsChecksI18nVisitor(ast.NodeVisitor):
    """Walks one module's AST, recording every bare string literal reaching a field's, a
    check's, a view's or a form's user-visible sinks, and every positional placeholder passed
    directly to a translation call."""

    def __init__(self) -> None:
        self.bare_literals: list[str] = []
        self.positional_placeholders: list[str] = []

    @staticmethod
    def _str_constant(node: ast.expr) -> str | None:
        # A message is routinely interpolated at its sink (`"%(model)s …" % {...}`), which puts
        # an ast.BinOp where the literal would otherwise sit. Unwrap it, or every interpolated
        # message — the shape checks.py actually uses — passes unseen.
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            node = node.left
        # An f-string is the construction a developer reaches for when a message
        # needs interpolating, and it is exactly as untranslated as a plain
        # literal. ast.JoinedStr carries no .value, so report its source text.
        if isinstance(node, ast.JoinedStr):
            return ast.unparse(node)
        return (
            node.value
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            else None
        )

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_validation_error = isinstance(func, ast.Name) and func.id in {
            "ValidationError",
            "ImproperlyConfigured",
        }
        is_checks_diagnostic = (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "checks"
            and func.attr in {"Warning", "Error"}
        )
        is_translation_call = (
            isinstance(func, ast.Name) and func.id in _TRANSLATION_CALL_NAMES
        )
        if is_translation_call:
            for arg in node.args:
                literal = self._str_constant(arg)
                if literal is not None and _POSITIONAL_PLACEHOLDER.search(literal):
                    self.positional_placeholders.append(literal)
        if is_validation_error or is_checks_diagnostic:
            for arg in node.args:
                literal = self._str_constant(arg)
                if literal is not None:
                    self.bare_literals.append(literal)
            # `hint=` and `msg=` are read by the same person as the positional message.
            for kw in node.keywords:
                if kw.arg in _DIAGNOSTIC_MESSAGE_KEYWORDS:
                    literal = self._str_constant(kw.value)
                    if literal is not None:
                        self.bare_literals.append(literal)
        elif isinstance(func, ast.Attribute) and func.attr == "setdefault":
            # kwargs.setdefault("help_text", <value>) — how ConceptField ships a default
            # while still letting a consumer override it.
            if (
                len(node.args) == 2
                and self._str_constant(node.args[0]) in _FIELD_METADATA_KEYWORDS
            ):
                literal = self._str_constant(node.args[1])
                if literal is not None:
                    self.bare_literals.append(literal)
        else:
            # A Field/ForeignKey-style call carrying help_text=/verbose_name= directly.
            for kw in node.keywords:
                if kw.arg in _FIELD_METADATA_KEYWORDS:
                    literal = self._str_constant(kw.value)
                    if literal is not None:
                        self.bare_literals.append(literal)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # error_messages = {...} / default_error_messages = {...} — every dict value is a
        # message a consumer eventually reads off a raised ValidationError.
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        if names & {"error_messages", "default_error_messages"} and isinstance(
            node.value, ast.Dict
        ):
            for value in node.value.values:
                literal = self._str_constant(value)
                if literal is not None:
                    self.bare_literals.append(literal)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        # A `help_text`/`verbose_name`/`verbose_name_plural` key in *any* dict literal, not only
        # one assigned to an `error_messages`-named variable. ConceptsField's generated
        # through-model Meta is built exactly this way — `type("Meta", (), {...})` — so a keyword
        # check on the enclosing `type(...)` call would never see it: the dict is a positional
        # argument, not a keyword.
        for key, value in zip(node.keys, node.values, strict=True):
            name = self._str_constant(key) if key is not None else None
            if name in _FIELD_METADATA_KEYWORDS:
                literal = self._str_constant(value)
                if literal is not None:
                    self.bare_literals.append(literal)
        self.generic_visit(node)


def _visit_fields_checks_source(source: str) -> FieldsChecksI18nVisitor:
    visitor = FieldsChecksI18nVisitor()
    visitor.visit(ast.parse(source))
    return visitor


class TestFieldsChecksI18nVisitorCatchesAViolation:
    """Proves the sweep below is a real gate, not a vacuous one: each of these feeds it a
    deliberately bad snippet, mirroring a shape fields.py/checks.py actually contains, that it
    must flag before the sweep test trusts it to report the two modules clean."""

    def test_catches_a_bare_help_text_keyword_literal(self):
        visitor = _visit_fields_checks_source("ForeignKey(help_text='boom')\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_verbose_name_keyword_literal(self):
        visitor = _visit_fields_checks_source("CharField(verbose_name='boom')\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_help_text_default_via_kwargs_setdefault(self):
        visitor = _visit_fields_checks_source(
            "kwargs.setdefault('help_text', 'boom')\n"
        )
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_error_messages_dict_value(self):
        visitor = _visit_fields_checks_source("error_messages = {'invalid': 'boom'}\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_raised_as_a_validation_error(self):
        visitor = _visit_fields_checks_source("raise ValidationError('boom')\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_raised_as_improperly_configured(self):
        # forms.py's route mixin raises this when a project ignores the missing-route check.
        visitor = _visit_fields_checks_source("raise ImproperlyConfigured('boom')\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_positional_placeholder_passed_to_a_translation_call(self):
        visitor = _visit_fields_checks_source(
            "from django.utils.translation import gettext_lazy as _\n_('%s changed')\n"
        )
        assert visitor.positional_placeholders == ["%s changed"]

    def test_does_not_flag_a_named_placeholder_passed_to_a_translation_call(self):
        visitor = _visit_fields_checks_source(
            "from django.utils.translation import gettext_lazy as _\n_('%(model)s changed')\n"
        )
        assert visitor.positional_placeholders == []

    def test_catches_a_bare_literal_as_a_checks_warning(self):
        visitor = _visit_fields_checks_source("checks.Warning('boom')\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_as_a_checks_error(self):
        visitor = _visit_fields_checks_source("checks.Error('boom')\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_interpolated_message(self):
        # checks.py's own message shape: the literal sits under a `%` BinOp, not directly
        # under the call.
        visitor = _visit_fields_checks_source(
            "checks.Warning('boom %(model)s' % {'model': m})\n"
        )
        assert visitor.bare_literals == ["boom %(model)s"]

    def test_catches_a_bare_f_string_message(self):
        visitor = _visit_fields_checks_source("checks.Warning(f'boom {model}')\n")
        assert visitor.bare_literals == ["f'boom {model}'"]

    def test_catches_a_bare_hint_keyword_literal(self):
        visitor = _visit_fields_checks_source(
            "checks.Warning(_('fine'), hint='boom')\n"
        )
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_verbose_name_dict_literal_value(self):
        # ConceptsField's generated through model builds its Meta as a plain dict passed to
        # type(), not as ForeignKey(verbose_name=...) or a Meta class body — a shape the
        # keyword-argument checks above cannot see at all.
        visitor = _visit_fields_checks_source(
            "meta = {'verbose_name': 'boom', 'verbose_name_plural': 'booms', 'db_table': 'x'}\n"
        )
        assert visitor.bare_literals == ["boom", "booms"]

    def test_does_not_flag_a_translated_sink(self):
        visitor = _visit_fields_checks_source(
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


class TestFieldsChecksI18nSweep:
    """T012, extended T011, extended 012 T018 — the sweep itself, run against the real files:
    ``fields.py``, ``checks.py`` (including the T011 middleware check,
    ``controlled_vocabularies.W004``), ``views.py``, ``forms.py`` and ``admin.py``. Every
    user-visible string these five modules put in front of a person is translatable with only
    named placeholders; the developer-facing ``on_delete``/``vocabulary`` ``TypeError``s are
    outside every sink this visitor recognises, so they are exempt by construction
    (decisions.md D8)."""

    @pytest.mark.parametrize("module", _FIELDS_CHECKS_MODULES, ids=lambda m: m.__name__)
    def test_module_carries_no_bare_user_visible_literal(self, module):
        source = Path(inspect.getfile(module)).read_text()
        visitor = _visit_fields_checks_source(source)
        assert visitor.bare_literals == [], (
            f"{module.__name__} passes a bare, untranslated literal to a user-visible sink: {visitor.bare_literals}"
        )
        assert visitor.positional_placeholders == [], (
            f"{module.__name__} passes a positional placeholder to a translation call: "
            f"{visitor.positional_placeholders}"
        )


class TestFormsMissingRouteMessageIsTranslatable:
    """T011 — ``forms.py``'s ``_MISSING_ROUTE_MESSAGE`` (decisions.md D14) is built once, at
    import time, and referenced by name where it is raised (``ConceptWidgetRouteMixin``), so
    the AST sweep above — which only inspects an exception call's own arguments — cannot see
    whether the referenced name is itself translatable. Checked directly here instead, the same
    way the model-level validation messages earlier in this file are."""

    def test_missing_route_message_is_a_lazy_translation(self):
        assert isinstance(forms_module._MISSING_ROUTE_MESSAGE, Promise), (
            "_MISSING_ROUTE_MESSAGE is not lazily translatable"
        )


# --- FS-011 US-7 (T011): the documentation covers the concept search control's wiring ---
#
# decisions.md D10 amended the "one route" promise to two steps, and D15 amended it again,
# during implementation, to three — the third is the supporting package's middleware, and it is
# the one that fails silently rather than raising (spec.md FR-002, FR-010, FR-014). This asserts
# the shipped page documents all three, by name and in the order a developer does them, rather
# than trusting a docs-writing pass to remember an amendment made after the plan was written.

_SEARCH_DOC_TEXT = (
    Path(__file__).resolve().parents[1] / "docs" / "search.md"
).read_text()


class TestDocumentationCoversTheConceptSearchControlsWiring:
    """T011 — the three wiring steps (decisions.md D10, D15), in the order a developer does
    them, plus what the endpoint exposes, its default permission stance, and the browser
    requirement (FR-013, FR-014)."""

    def test_documents_the_route_include_step(self):
        assert 'include("controlled_vocabularies.urls")' in _SEARCH_DOC_TEXT

    def test_documents_the_installed_apps_step(self):
        assert (
            '"django_tomselect"' in _SEARCH_DOC_TEXT
            and "INSTALLED_APPS" in _SEARCH_DOC_TEXT
        )

    def test_documents_the_middleware_step(self):
        assert (
            "django_tomselect.middleware.TomSelectMiddleware" in _SEARCH_DOC_TEXT
            and "MIDDLEWARE" in _SEARCH_DOC_TEXT
        )

    def test_documents_the_three_steps_in_wiring_order(self):
        # A project does these in the order the render-time failure modes surface them: no route
        # means every request 404s, a missing INSTALLED_APPS entry means no template/static asset
        # to render with, and a missing middleware — the one that raises nothing at all — is the
        # one a developer notices last, so it is documented last (decisions.md D15).
        route_at = _SEARCH_DOC_TEXT.index('include("controlled_vocabularies.urls")')
        installed_apps_at = _SEARCH_DOC_TEXT.index('"django_tomselect"')
        middleware_at = _SEARCH_DOC_TEXT.index(
            "django_tomselect.middleware.TomSelectMiddleware"
        )
        assert route_at < installed_apps_at < middleware_at

    def test_documents_what_the_endpoint_exposes(self):
        assert (
            "preferred label" in _SEARCH_DOC_TEXT
            and "identifier" in _SEARCH_DOC_TEXT
            and "vocabulary" in _SEARCH_DOC_TEXT
        )

    def test_documents_no_default_permission_rule_and_the_include_as_the_restriction_lever(
        self,
    ):
        assert "no permission rule" in _SEARCH_DOC_TEXT
        assert "restrict" in _SEARCH_DOC_TEXT

    def test_documents_the_javascript_requirement(self):
        assert "JavaScript" in _SEARCH_DOC_TEXT


# --- 012 US-6 (T017): the documentation covers the concept fields' admin representation ---
#
# spec.md US-6 Acceptance Scenario 1: registering a consuming model in the admin is
# sufficient, the wiring is the same three entries already documented above and nothing
# more, concepts are chosen on these pages and never created or edited there, and the
# ways a project can ask for a different control are documented. Same technique as
# TestDocumentationCoversTheConceptSearchControlsWiring above, for the admin section.


class TestDocumentationCoversTheAdminSection:
    """T017 — spec.md US-6 scenario 1, FR-012."""

    def test_documents_that_registering_is_the_whole_requirement(self):
        assert "nothing further to configure" in _SEARCH_DOC_TEXT

    def test_documents_concepts_are_chosen_not_created_or_edited(self):
        assert "never created or edited" in _SEARCH_DOC_TEXT

    def test_documents_no_related_object_affordance(self):
        assert "add, change, delete or view" in _SEARCH_DOC_TEXT

    def test_documents_read_only_presentation(self):
        assert "read-only" in _SEARCH_DOC_TEXT and "preferred label" in _SEARCH_DOC_TEXT

    def test_documents_the_override_mechanisms(self):
        for override in (
            "autocomplete_fields",
            "raw_id_fields",
            "readonly_fields",
            "Meta.widgets",
        ):
            assert override in _SEARCH_DOC_TEXT, (
                f"docs/search.md does not document {override}"
            )
