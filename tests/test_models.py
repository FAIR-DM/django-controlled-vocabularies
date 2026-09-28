"""Tests for controlled_vocabularies.models."""

import pytest
from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Model, UniqueConstraint
from django.utils import translation
from django.utils.functional import Promise
from django.utils.text import Truncator

from controlled_vocabularies import conf
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
from tests.factories import (
    CollectionFactory,
    ConceptFactory,
    ConceptSchemeFactory,
)


class TestConceptScheme:
    @pytest.mark.django_db
    def test_create_derives_slug_from_name(self):
        scheme = ConceptScheme.objects.create(name="Geothermics")
        assert scheme.slug == "geothermics"

    @pytest.mark.django_db
    def test_create_accepts_optional_description(self):
        scheme = ConceptScheme.objects.create(
            name="Geothermics", description="Study of Earth's heat."
        )
        fetched = ConceptScheme.objects.get(pk=scheme.pk)
        assert fetched.description == "Study of Earth's heat."

    @pytest.mark.django_db
    def test_rename_updates_slug(self):
        scheme = ConceptScheme.objects.create(name="Geothermics")
        scheme.name = "Geothermal Science"
        scheme.save()
        assert scheme.slug == "geothermal-science"

    @pytest.mark.django_db
    def test_empty_name_is_rejected(self):
        with pytest.raises(ValidationError):
            ConceptScheme.objects.create(name="")

    @pytest.mark.django_db
    def test_whitespace_only_name_is_rejected(self):
        with pytest.raises(ValidationError):
            ConceptScheme.objects.create(name="   ")

    @pytest.mark.django_db
    def test_non_latin_name_yields_nonempty_unicode_slug(self):
        scheme = ConceptScheme.objects.create(name="Wärmefluss")
        assert scheme.slug
        assert scheme.slug == "wärmefluss"

    @pytest.mark.django_db
    def test_colliding_slug_is_refused_not_suffixed(self):
        ConceptScheme.objects.create(name="Geothermics")
        with pytest.raises(ValidationError):
            # A different name that slugifies to the same value must be refused,
            # never silently auto-suffixed to "geothermics-2".
            ConceptScheme.objects.create(name="GEOTHERMICS")
        assert ConceptScheme.objects.filter(slug="geothermics").count() == 1
        assert not ConceptScheme.objects.filter(slug="geothermics-2").exists()

    @pytest.mark.django_db
    def test_uri_composes_from_base_and_slug(self):
        scheme = ConceptScheme.objects.create(name="Geothermics")
        assert scheme.uri == "https://example.org/vocabularies/geothermics"

    @pytest.mark.django_db
    def test_uri_reflects_rename(self):
        scheme = ConceptScheme.objects.create(name="Geothermics")
        scheme.name = "Geothermal Science"
        scheme.save()
        assert scheme.uri == "https://example.org/vocabularies/geothermal-science"

    @pytest.mark.django_db
    def test_str_is_the_name(self):
        scheme = ConceptScheme.objects.create(name="Geothermics")
        assert str(scheme) == "Geothermics"

    @pytest.mark.django_db
    def test_delete_removes_scheme(self):
        scheme = ConceptScheme.objects.create(name="Geothermics")
        pk = scheme.pk
        scheme.delete()
        assert not ConceptScheme.objects.filter(pk=pk).exists()


class TestConcept:
    @pytest.mark.django_db
    def test_add_derives_slug_from_label(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        assert concept.slug == "heat-flow"

    @pytest.mark.django_db
    def test_get_concept_by_scheme_and_slug(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        assert Concept.objects.get(scheme=scheme, slug="heat-flow") == concept

    @pytest.mark.django_db
    def test_list_concepts_of_a_scheme(self, scheme):
        Concept.objects.create(scheme=scheme, label="Heat Flow")
        Concept.objects.create(scheme=scheme, label="Gradient")
        assert scheme.concepts.count() == 2

    @pytest.mark.django_db
    def test_relabel_updates_slug(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        concept.label = "Surface Heat Flow"
        concept.save()
        assert concept.slug == "surface-heat-flow"

    @pytest.mark.django_db
    def test_empty_label_is_rejected(self, scheme):
        with pytest.raises(ValidationError):
            Concept.objects.create(scheme=scheme, label="")

    @pytest.mark.django_db
    def test_whitespace_only_label_is_rejected(self, scheme):
        with pytest.raises(ValidationError):
            Concept.objects.create(scheme=scheme, label="   ")

    @pytest.mark.django_db
    def test_non_latin_label_yields_nonempty_unicode_slug(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Wärmefluss")
        assert concept.slug
        assert concept.slug == "wärmefluss"

    @pytest.mark.django_db
    def test_colliding_slug_within_scheme_is_refused_not_suffixed(self, scheme):
        Concept.objects.create(scheme=scheme, label="Heat Flow")
        with pytest.raises(ValidationError):
            # A different label that slugifies to the same value within the same
            # scheme must be refused, never silently auto-suffixed to "heat-flow-2".
            Concept.objects.create(scheme=scheme, label="HEAT FLOW")
        assert scheme.concepts.filter(slug="heat-flow").count() == 1
        assert not scheme.concepts.filter(slug="heat-flow-2").exists()

    @pytest.mark.django_db
    def test_same_slug_allowed_across_different_schemes(self):
        scheme_a = ConceptSchemeFactory()
        scheme_b = ConceptSchemeFactory()
        concept_a = Concept.objects.create(scheme=scheme_a, label="Heat Flow")
        concept_b = Concept.objects.create(scheme=scheme_b, label="Heat Flow")
        assert concept_a.slug == concept_b.slug == "heat-flow"
        assert Concept.objects.filter(slug="heat-flow").count() == 2

    @pytest.mark.django_db
    def test_uri_composes_from_scheme_uri_and_slug(self):
        scheme = ConceptScheme.objects.create(name="Geothermics")
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        assert concept.uri == f"{scheme.uri}/heat-flow"
        assert concept.uri == "https://example.org/vocabularies/geothermics/heat-flow"

    @pytest.mark.django_db
    def test_uri_reflects_relabel(self):
        scheme = ConceptScheme.objects.create(name="Geothermics")
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        concept.label = "Surface Heat Flow"
        concept.save()
        assert (
            concept.uri
            == "https://example.org/vocabularies/geothermics/surface-heat-flow"
        )

    @pytest.mark.django_db
    def test_str_is_the_label(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        assert str(concept) == "Heat Flow"

    @pytest.mark.django_db
    def test_delete_removes_concept(self, concept):
        pk = concept.pk
        concept.delete()
        assert not Concept.objects.filter(pk=pk).exists()

    @pytest.mark.django_db
    def test_deleting_scheme_cascades_to_its_concepts(self, scheme):
        Concept.objects.create(scheme=scheme, label="Heat Flow")
        Concept.objects.create(scheme=scheme, label="Gradient")
        scheme.delete()
        assert Concept.objects.count() == 0


class TestConceptSlugFollowsTheLabelWithNoPublisherIdentifier:
    @pytest.mark.django_db
    def test_a_locally_authored_concept_derives_its_slug_from_its_label(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        assert concept.static_uri is None
        assert concept.slug_is_manual is False
        assert concept.slug == "heat-flow"

    @pytest.mark.django_db
    def test_a_locally_authored_concept_s_slug_still_follows_a_relabel(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        concept.label = "Surface Heat Flow"
        concept.save()
        assert concept.static_uri is None
        assert concept.slug == "surface-heat-flow"


class TestConceptIdentity:
    @pytest.mark.django_db
    def test_full_uri_is_base_plus_scheme_slug_plus_concept_slug(self):
        scheme = ConceptSchemeFactory(name="Geothermics")
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        assert concept.uri == f"{conf.get_base_uri()}/{scheme.slug}/{concept.slug}"
        assert concept.uri == "https://example.org/vocabularies/geothermics/heat-flow"

    @pytest.mark.django_db
    def test_get_by_uri_returns_exactly_that_concept(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        resolved = Concept.objects.get_by_uri(concept.uri)
        assert resolved == concept
        assert resolved.pk == concept.pk

    @pytest.mark.django_db
    def test_no_two_concepts_across_schemes_share_a_uri(self):
        scheme_a = ConceptSchemeFactory(name="Geothermics")
        scheme_b = ConceptSchemeFactory(name="Hydrology")
        concept_a = ConceptFactory(scheme=scheme_a, label="Heat Flow")
        concept_b = ConceptFactory(scheme=scheme_b, label="Heat Flow")
        assert concept_a.slug == concept_b.slug
        assert concept_a.uri != concept_b.uri
        assert Concept.objects.get_by_uri(concept_a.uri) == concept_a
        assert Concept.objects.get_by_uri(concept_b.uri) == concept_b

    @pytest.mark.django_db
    def test_non_latin_label_yields_resolvable_uri(self):
        scheme = ConceptSchemeFactory(name="Geothermik")
        concept = ConceptFactory(scheme=scheme, label="Wärmefluss")
        assert concept.uri == f"{conf.get_base_uri()}/geothermik/wärmefluss"
        assert Concept.objects.get_by_uri(concept.uri) == concept

    @pytest.mark.django_db
    def test_renaming_scheme_recomposes_uri_and_still_resolves(self):
        scheme = ConceptSchemeFactory(name="Geothermics")
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        scheme.name = "Geothermal Science"
        scheme.save()
        concept.refresh_from_db()
        assert (
            concept.uri
            == "https://example.org/vocabularies/geothermal-science/heat-flow"
        )
        assert Concept.objects.get_by_uri(concept.uri) == concept

    @pytest.mark.django_db
    def test_renaming_label_recomposes_uri_and_still_resolves(self):
        scheme = ConceptSchemeFactory(name="Geothermics")
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        concept.label = "Surface Heat Flow"
        concept.save()
        assert (
            concept.uri
            == "https://example.org/vocabularies/geothermics/surface-heat-flow"
        )
        assert Concept.objects.get_by_uri(concept.uri) == concept

    @pytest.mark.django_db
    def test_get_by_uri_unknown_uri_raises_does_not_exist(self, scheme):
        Concept.objects.create(scheme=scheme, label="Heat Flow")
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri(
                f"{conf.get_base_uri()}/geothermics/no-such-concept"
            )

    @pytest.mark.django_db
    def test_get_by_uri_requires_the_configured_base(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        # A bare relative path (no base) must not resolve: get_by_uri means "by URI",
        # so a string outside the configured base is not an identity.
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri(f"{scheme.slug}/{concept.slug}")


class TestStaticUri:
    @pytest.mark.django_db
    def test_static_uri_reads_back_verbatim_from_uri(self, scheme):
        concept = Concept.objects.create(
            scheme=scheme,
            label="Granite",
            static_uri="http://vocabs.example.org/rock/granite",
        )
        assert concept.uri == "http://vocabs.example.org/rock/granite"
        assert concept.has_static_uri is True

    @pytest.mark.django_db
    def test_static_uri_survives_a_rename(self, scheme):
        concept = Concept.objects.create(
            scheme=scheme,
            label="Granite",
            static_uri="http://vocabs.example.org/rock/granite",
        )
        concept.label = "Granite (coarse-grained)"
        concept.save()
        assert concept.uri == "http://vocabs.example.org/rock/granite"

    @pytest.mark.django_db
    def test_static_uri_survives_a_base_address_change(self, scheme, settings):
        concept = Concept.objects.create(
            scheme=scheme,
            label="Granite",
            static_uri="http://vocabs.example.org/rock/granite",
        )
        settings.CONTROLLED_VOCABULARIES_BASE_URI = (
            "https://elsewhere.example.org/vocab"
        )
        assert concept.uri == "http://vocabs.example.org/rock/granite"

    @pytest.mark.parametrize("model", [ConceptScheme, Concept, Collection])
    @pytest.mark.django_db
    def test_static_uri_case_round_trips_byte_identical_through_save_and_reload(
        self, model, scheme
    ):
        mixed_case = "http://Vocabs.Example.ORG/Rock/GRANITE"
        record = create_with_static_uri(model, scheme, mixed_case)
        assert record.static_uri == mixed_case
        record.refresh_from_db()
        assert record.static_uri == mixed_case
        assert record.uri == mixed_case

    @pytest.mark.django_db
    def test_scheme_and_collection_keep_their_own_static_uri(self):
        scheme = ConceptScheme.objects.create(
            name="Rocks", static_uri="http://vocabs.example.org/rocks"
        )
        collection = Collection.objects.create(
            scheme=scheme,
            name="Igneous",
            static_uri="http://vocabs.example.org/rocks/igneous",
        )
        assert scheme.uri == "http://vocabs.example.org/rocks"
        assert scheme.has_static_uri is True
        assert collection.uri == "http://vocabs.example.org/rocks/igneous"
        assert collection.has_static_uri is True

    @pytest.mark.django_db
    def test_concepts_static_uri_is_not_derived_from_its_schemes(self):
        scheme = ConceptScheme.objects.create(
            name="Rocks", static_uri="http://vocabs.example.org/rocks"
        )
        concept = Concept.objects.create(
            scheme=scheme,
            label="Granite",
            static_uri="http://vocabs.example.org/rock/granite",
        )
        assert concept.uri == "http://vocabs.example.org/rock/granite"
        assert concept.uri != scheme.uri

    @pytest.mark.django_db
    def test_has_static_uri_false_while_provisional(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Basalt")
        assert concept.static_uri is None
        assert concept.has_static_uri is False
        assert concept.uri == f"{conf.get_base_uri()}/{scheme.slug}/{concept.slug}"

    @pytest.mark.parametrize(
        "value",
        [
            "not-absolute",
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "data:text/html,x",
            "vbscript:msgbox(1)",
        ],
    )
    def test_refuses_non_absolute_and_script_bearing_schemes(self, value):
        with pytest.raises(ValidationError):
            validate_static_uri(value)

    def test_refuses_overlong_identifier(self):
        with pytest.raises(ValidationError):
            validate_static_uri("http://example.org/" + "x" * 500)

    def test_overlong_identifier_message_does_not_echo_the_full_raw_value(self):
        hostile = "http://example.org/" + "x" * 2008
        with pytest.raises(ValidationError) as excinfo:
            validate_static_uri(hostile)
        message = excinfo.value.messages[0]
        assert len(message) < 200, (
            f"error message is {len(message)} chars — echoes the raw value untruncated"
        )
        assert str(len(hostile)) in message, "the true length must still be reported"

    def test_length_is_checked_before_parsing_so_a_malformed_overlong_value_reports_length(
        self,
    ):
        hostile = "not-absolute-" + "x" * 3000
        with pytest.raises(ValidationError) as excinfo:
            validate_static_uri(hostile)
        assert excinfo.value.code == "static_uri_too_long"

    def test_accepts_urn_identifier(self):
        validate_static_uri("urn:uuid:9f6c1e2a-1234-4a12-9abc-1234567890ab")

    def test_a_value_urlsplit_cannot_parse_raises_validation_error_not_value_error(
        self,
    ):
        with pytest.raises(ValidationError):
            validate_static_uri("http://exa℀mple.com/x")

    def test_a_malformed_ipv6_netloc_raises_validation_error_not_value_error(self):
        with pytest.raises(ValidationError):
            validate_static_uri("http://[fe80::1")

    @pytest.mark.django_db
    def test_concept_save_with_an_unparseable_static_uri_raises_validation_error(
        self, scheme
    ):
        with pytest.raises(ValidationError):
            Concept(
                scheme=scheme, label="Red", static_uri="http://exa℀mple.com/x"
            ).save()

    @pytest.mark.django_db
    def test_concept_full_clean_with_an_unparseable_static_uri_raises_validation_error(
        self, scheme
    ):
        with pytest.raises(ValidationError):
            Concept(
                scheme=scheme, label="Red", static_uri="http://[fe80::1"
            ).full_clean()

    @pytest.mark.django_db
    def test_bare_create_with_bad_static_uri_raises_and_does_not_store(self, scheme):
        with pytest.raises(ValidationError):
            Concept.objects.create(
                scheme=scheme, label="Granite", static_uri="not-absolute"
            )
        assert not Concept.objects.filter(label="Granite").exists()

    @pytest.mark.django_db
    def test_case_folding_for_cross_model_uniqueness_does_not_fold_the_path(
        self, scheme
    ):
        Concept.objects.create(
            scheme=scheme,
            label="Granite",
            static_uri="http://vocabs.example.org/Shared",
        )
        Collection.objects.create(
            scheme=scheme, name="Igneous", static_uri="http://vocabs.example.org/shared"
        )


class TestStaticUriSchemeAllowlist:
    @pytest.mark.parametrize(
        "scheme", ["http", "https", "urn", "doi", "info", "ark", "tag", "hdl", "oai"]
    )
    def test_the_default_schemes_are_accepted(self, scheme):
        validate_static_uri(f"{scheme}:something-or-other/x")

    @pytest.mark.parametrize(
        "value",
        [
            "file:///etc/passwd",
            "about:blank",
            "blob:https://example.org/9f6c1e2a-uuid",
            "jar:http://example.org/x.jar!/",
        ],
    )
    def test_schemes_outside_the_default_allowlist_are_refused(self, value):
        with pytest.raises(ValidationError):
            validate_static_uri(value)

    def test_the_setting_override_is_honoured(self, settings):
        settings.CONTROLLED_VOCABULARIES_ALLOWED_URI_SCHEMES = [
            "http",
            "https",
            "myscheme",
        ]
        validate_static_uri("myscheme:something")
        with pytest.raises(ValidationError):
            validate_static_uri("urn:uuid:9f6c1e2a-1234-4a12-9abc-1234567890ab")

    def test_the_denylist_still_refuses_a_scheme_within_an_overridden_allowlist(
        self, settings
    ):
        settings.CONTROLLED_VOCABULARIES_ALLOWED_URI_SCHEMES = [
            "http",
            "https",
            "javascript",
        ]
        with pytest.raises(ValidationError):
            validate_static_uri("javascript:alert(1)")


def create_with_static_uri(model: type[Model], scheme: ConceptScheme, uri: str):
    """Create a saved record of ``model`` carrying ``uri`` as its ``static_uri``."""
    if model is ConceptScheme:
        return ConceptScheme.objects.create(
            name=f"External scheme {uri}", static_uri=uri
        )
    if model is Concept:
        return Concept.objects.create(
            scheme=scheme, label=f"External concept {uri}", static_uri=uri
        )
    return Collection.objects.create(
        scheme=scheme, name=f"External collection {uri}", static_uri=uri
    )


def create_without_static_uri(model: type[Model], scheme: ConceptScheme):
    """Create a saved, provisional (no ``static_uri``) record of ``model``."""
    if model is ConceptScheme:
        return ConceptScheme.objects.create(name="Provisional scheme")
    if model is Concept:
        return Concept.objects.create(scheme=scheme, label="Provisional concept")
    return Collection.objects.create(scheme=scheme, name="Provisional collection")


# A save with update_fields that leaves out static_uri must not validate a value that never
# reaches the database.


class TestStaticUriUpdateFieldsExclusion:
    @pytest.mark.django_db
    def test_an_invalid_value_in_an_excluded_column_does_not_block_the_save(
        self, scheme
    ):
        concept = Concept.objects.create(scheme=scheme, label="Local")
        concept.static_uri = "not-absolute"
        concept.save(update_fields=["label"])
        concept.refresh_from_db()
        assert concept.static_uri is None

    @pytest.mark.django_db
    def test_a_would_be_rewrite_conflict_in_an_excluded_column_does_not_block_the_save(
        self, scheme
    ):
        concept = Concept.objects.create(
            scheme=scheme, label="Local", static_uri="http://ex.org/fixed"
        )
        reloaded = Concept.objects.get(pk=concept.pk)
        reloaded.static_uri = "http://ex.org/rewritten"
        reloaded.save(update_fields=["label"])
        reloaded.refresh_from_db()
        assert reloaded.static_uri == "http://ex.org/fixed"

    @pytest.mark.django_db
    def test_assigning_and_saving_excluding_the_column_leaves_the_record_provisional_and_still_storable(
        self, scheme
    ):
        concept = Concept.objects.create(scheme=scheme, label="Local")
        concept.static_uri = "http://ex.org/never-written"
        concept.save(update_fields=["label"])
        concept.refresh_from_db()
        assert concept.static_uri is None
        concept.static_uri = "http://ex.org/right"
        concept.save()
        concept.refresh_from_db()
        assert concept.static_uri == "http://ex.org/right"


class TestGetByUri:
    @pytest.mark.django_db
    def test_concept_resolves_by_external_static_uri(self, scheme):
        concept = ConceptFactory(
            scheme=scheme,
            label="Granite",
            static_uri="http://vocabs.example.org/rock/granite",
        )
        assert (
            Concept.objects.get_by_uri("http://vocabs.example.org/rock/granite")
            == concept
        )

    @pytest.mark.django_db
    def test_concept_resolves_by_its_own_local_identifier(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        assert Concept.objects.get_by_uri(concept.uri) == concept

    @pytest.mark.django_db
    def test_concept_unheld_identifier_raises_does_not_exist(self, scheme):
        Concept.objects.create(scheme=scheme, label="Heat Flow")
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri("http://vocabs.example.org/nothing")
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri(
                f"{conf.get_base_uri()}/{scheme.slug}/no-such-concept"
            )

    @pytest.mark.django_db
    def test_imported_and_local_concept_do_not_answer_to_each_others_identifier(
        self, scheme
    ):
        imported = ConceptFactory(
            scheme=scheme,
            label="Granite",
            static_uri="http://vocabs.example.org/rock/granite",
        )
        local = ConceptFactory(scheme=scheme, label="Basalt")
        assert Concept.objects.get_by_uri(imported.uri) == imported
        assert Concept.objects.get_by_uri(local.uri) == local
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri("http://vocabs.example.org/rock/nothing-here")

    @pytest.mark.django_db
    def test_scheme_resolves_by_external_static_uri(self):
        scheme = ConceptSchemeFactory(
            name="Rocks", static_uri="http://vocabs.example.org/rocks"
        )
        assert (
            ConceptScheme.objects.get_by_uri("http://vocabs.example.org/rocks")
            == scheme
        )

    @pytest.mark.django_db
    def test_scheme_resolves_by_its_own_local_identifier(self):
        scheme = ConceptSchemeFactory(name="Geothermics")
        assert ConceptScheme.objects.get_by_uri(scheme.uri) == scheme

    @pytest.mark.django_db
    def test_scheme_unheld_identifier_raises_does_not_exist(self):
        ConceptScheme.objects.create(name="Geothermics")
        with pytest.raises(ConceptScheme.DoesNotExist):
            ConceptScheme.objects.get_by_uri("http://vocabs.example.org/nothing")
        with pytest.raises(ConceptScheme.DoesNotExist):
            ConceptScheme.objects.get_by_uri(f"{conf.get_base_uri()}/no-such-scheme")

    @pytest.mark.django_db
    def test_scheme_does_not_resolve_a_concepts_identifier(self, scheme):
        # A concept's local identifier has two path segments below the base; a
        # scheme's has one — the scheme parse must not mistake one for the other.
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        with pytest.raises(ConceptScheme.DoesNotExist):
            ConceptScheme.objects.get_by_uri(concept.uri)

    @pytest.mark.django_db
    def test_concept_does_not_resolve_a_schemes_identifier(self, scheme):
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri(scheme.uri)

    @pytest.mark.django_db
    def test_collection_resolves_by_external_static_uri(self, scheme):
        collection = CollectionFactory(
            scheme=scheme,
            name="Igneous",
            static_uri="http://vocabs.example.org/rocks/igneous",
        )
        assert (
            Collection.objects.get_by_uri("http://vocabs.example.org/rocks/igneous")
            == collection
        )

    @pytest.mark.django_db
    def test_collection_resolves_by_its_own_local_identifier(self, scheme):
        collection = CollectionFactory(scheme=scheme, name="Igneous")
        assert Collection.objects.get_by_uri(collection.uri) == collection

    @pytest.mark.django_db
    def test_collection_unheld_identifier_raises_does_not_exist(self, scheme):
        Collection.objects.create(scheme=scheme, name="Igneous")
        with pytest.raises(Collection.DoesNotExist):
            Collection.objects.get_by_uri("http://vocabs.example.org/nothing")

    @pytest.mark.django_db
    def test_collection_does_not_resolve_a_concepts_identifier(self, scheme):
        # A collection's local identifier carries a literal "collection" segment
        # that a concept's never does — the collection parse must require it.
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        with pytest.raises(Collection.DoesNotExist):
            Collection.objects.get_by_uri(concept.uri)

    @pytest.mark.django_db
    def test_concept_does_not_resolve_a_collections_identifier(self, scheme):
        collection = CollectionFactory(scheme=scheme, name="Igneous")
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri(collection.uri)


# get(static_uri=None) compiles to `IS NULL` and would match every provisional record, and
# an importer reading a missing identifier yields None.


class TestGetByUriRejectsAbsentIdentifiers:
    @pytest.mark.django_db
    def test_concept_get_by_uri_none_does_not_return_an_unrelated_provisional_record(
        self, scheme
    ):
        Concept.objects.create(scheme=scheme, label="Heat Flow")
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri(None)

    @pytest.mark.django_db
    def test_concept_get_by_uri_none_does_not_raise_multiple_objects_returned(
        self, scheme
    ):
        Concept.objects.create(scheme=scheme, label="Heat Flow")
        Concept.objects.create(scheme=scheme, label="Basalt")
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri(None)

    @pytest.mark.django_db
    def test_concept_get_by_uri_empty_string_does_not_return_an_unrelated_provisional_record(
        self, scheme
    ):
        Concept.objects.create(scheme=scheme, label="Heat Flow")
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri("")

    @pytest.mark.django_db
    def test_scheme_get_by_uri_none_does_not_return_an_unrelated_provisional_record(
        self,
    ):
        ConceptScheme.objects.create(name="Geothermics")
        with pytest.raises(ConceptScheme.DoesNotExist):
            ConceptScheme.objects.get_by_uri(None)

    @pytest.mark.django_db
    def test_scheme_get_by_uri_empty_string_does_not_return_an_unrelated_provisional_record(
        self,
    ):
        ConceptScheme.objects.create(name="Geothermics")
        with pytest.raises(ConceptScheme.DoesNotExist):
            ConceptScheme.objects.get_by_uri("")

    @pytest.mark.django_db
    def test_collection_get_by_uri_none_does_not_return_an_unrelated_provisional_record(
        self, scheme
    ):
        Collection.objects.create(scheme=scheme, name="Igneous")
        with pytest.raises(Collection.DoesNotExist):
            Collection.objects.get_by_uri(None)

    @pytest.mark.django_db
    def test_collection_get_by_uri_empty_string_does_not_return_an_unrelated_provisional_record(
        self, scheme
    ):
        Collection.objects.create(scheme=scheme, name="Igneous")
        with pytest.raises(Collection.DoesNotExist):
            Collection.objects.get_by_uri("")


class TestProvisionalUri:
    @pytest.mark.django_db
    def test_scheme_with_no_static_uri_reports_the_composed_value(self):
        scheme = ConceptSchemeFactory(name="Geothermics")
        assert scheme.static_uri is None
        assert scheme.has_static_uri is False
        assert scheme.uri == f"{conf.get_base_uri()}/{scheme.slug}"

    @pytest.mark.django_db
    def test_scheme_provisional_uri_follows_a_rename(self):
        scheme = ConceptSchemeFactory(name="Geothermics")
        scheme.name = "Geothermal Science"
        scheme.save()
        assert scheme.uri == f"{conf.get_base_uri()}/geothermal-science"

    @pytest.mark.django_db
    def test_scheme_provisional_uri_follows_a_base_address_change(self, settings):
        scheme = ConceptSchemeFactory(name="Geothermics")
        settings.CONTROLLED_VOCABULARIES_BASE_URI = (
            "https://elsewhere.example.org/vocab"
        )
        assert scheme.uri == "https://elsewhere.example.org/vocab/geothermics"

    @pytest.mark.django_db
    def test_concept_with_no_static_uri_reports_the_composed_value(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        assert concept.static_uri is None
        assert concept.has_static_uri is False
        assert concept.uri == f"{conf.get_base_uri()}/{scheme.slug}/{concept.slug}"

    @pytest.mark.django_db
    def test_concept_provisional_uri_follows_a_rename(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        concept.label = "Surface Heat Flow"
        concept.save()
        assert concept.uri == f"{conf.get_base_uri()}/{scheme.slug}/surface-heat-flow"

    @pytest.mark.django_db
    def test_concept_provisional_uri_follows_a_base_address_change(
        self, scheme, settings
    ):
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        settings.CONTROLLED_VOCABULARIES_BASE_URI = (
            "https://elsewhere.example.org/vocab"
        )
        assert (
            concept.uri
            == f"https://elsewhere.example.org/vocab/{scheme.slug}/{concept.slug}"
        )

    @pytest.mark.django_db
    def test_collection_with_no_static_uri_reports_the_composed_value(self, scheme):
        collection = CollectionFactory(scheme=scheme, name="Igneous")
        assert collection.static_uri is None
        assert collection.has_static_uri is False
        assert (
            collection.uri
            == f"{conf.get_base_uri()}/{scheme.slug}/collection/{collection.slug}"
        )

    @pytest.mark.django_db
    def test_collection_provisional_uri_follows_a_rename(self, scheme):
        collection = CollectionFactory(scheme=scheme, name="Igneous")
        collection.name = "Igneous Rocks"
        collection.save()
        assert (
            collection.uri
            == f"{conf.get_base_uri()}/{scheme.slug}/collection/igneous-rocks"
        )

    @pytest.mark.django_db
    def test_collection_provisional_uri_follows_a_base_address_change(
        self, scheme, settings
    ):
        collection = CollectionFactory(scheme=scheme, name="Igneous")
        settings.CONTROLLED_VOCABULARIES_BASE_URI = (
            "https://elsewhere.example.org/vocab"
        )
        assert (
            collection.uri
            == f"https://elsewhere.example.org/vocab/{scheme.slug}/collection/{collection.slug}"
        )


class TestPreExistingRecordsUpgrade:
    @pytest.mark.django_db
    def test_pre_existing_scheme_reports_its_previous_identifier_and_resolves(self):
        scheme = ConceptScheme.objects.create(name="Geothermics")
        assert scheme.static_uri is None
        assert scheme.uri == "https://example.org/vocabularies/geothermics"
        assert ConceptScheme.objects.get_by_uri(scheme.uri) == scheme

    @pytest.mark.django_db
    def test_pre_existing_concept_reports_its_previous_identifier_and_resolves(
        self, scheme
    ):
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        assert concept.static_uri is None
        assert (
            concept.uri == f"https://example.org/vocabularies/{scheme.slug}/heat-flow"
        )
        assert Concept.objects.get_by_uri(concept.uri) == concept

    @pytest.mark.django_db
    def test_pre_existing_collection_reports_its_previous_identifier_and_resolves(
        self, scheme
    ):
        collection = Collection.objects.create(scheme=scheme, name="Igneous")
        assert collection.static_uri is None
        assert (
            collection.uri
            == f"https://example.org/vocabularies/{scheme.slug}/collection/igneous"
        )
        assert Collection.objects.get_by_uri(collection.uri) == collection


class TestStaticUriDatabaseUniqueness:
    @pytest.mark.django_db
    def test_two_schemes_with_the_same_static_uri_hit_the_database_constraint(self):
        ConceptScheme.objects.create(
            name="Rocks", static_uri="http://vocabs.example.org/dup"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ConceptScheme.objects.bulk_create(
                [
                    ConceptScheme(
                        name="Other rocks",
                        slug="other-rocks",
                        static_uri="http://vocabs.example.org/dup",
                    )
                ]
            )

    @pytest.mark.django_db
    def test_two_concepts_with_the_same_static_uri_hit_the_database_constraint(
        self, scheme
    ):
        Concept.objects.create(
            scheme=scheme, label="Granite", static_uri="http://vocabs.example.org/dup"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Concept.objects.bulk_create(
                [
                    Concept(
                        scheme=scheme,
                        label="Basalt",
                        slug="basalt",
                        static_uri="http://vocabs.example.org/dup",
                    )
                ]
            )

    @pytest.mark.django_db
    def test_two_collections_with_the_same_static_uri_hit_the_database_constraint(
        self, scheme
    ):
        Collection.objects.create(
            scheme=scheme, name="Igneous", static_uri="http://vocabs.example.org/dup"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Collection.objects.bulk_create(
                [
                    Collection(
                        scheme=scheme,
                        name="Metamorphic",
                        slug="metamorphic",
                        static_uri="http://vocabs.example.org/dup",
                    )
                ]
            )

    @pytest.mark.django_db
    def test_many_records_holding_no_static_uri_coexist_freely(self, scheme):
        Concept.objects.create(scheme=scheme, label="A")
        Concept.objects.create(scheme=scheme, label="B")
        Concept.objects.create(scheme=scheme, label="C")
        assert Concept.objects.filter(static_uri__isnull=True).count() == 3


class TestLocalUrl:
    @pytest.mark.django_db
    def test_local_unpublished_schemes_local_url_equals_its_uri(self):
        scheme = ConceptSchemeFactory(name="Geothermics")
        assert scheme.local_url == scheme.uri
        assert scheme.local_url == f"{conf.get_base_uri()}/{scheme.slug}"

    @pytest.mark.django_db
    def test_local_unpublished_concepts_local_url_equals_its_uri(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        assert concept.local_url == concept.uri
        assert (
            concept.local_url == f"{conf.get_base_uri()}/{scheme.slug}/{concept.slug}"
        )

    @pytest.mark.django_db
    def test_local_unpublished_collections_local_url_equals_its_uri(self, scheme):
        collection = CollectionFactory(scheme=scheme, name="Igneous")
        assert collection.local_url == collection.uri
        assert (
            collection.local_url
            == f"{conf.get_base_uri()}/{scheme.slug}/collection/{collection.slug}"
        )

    @pytest.mark.django_db
    def test_imported_concepts_local_url_differs_from_its_static_uri(self, scheme):
        concept = ConceptFactory(
            scheme=scheme,
            label="Granite",
            static_uri="http://vocabs.example.org/rock/granite",
        )
        assert concept.uri == "http://vocabs.example.org/rock/granite"
        assert (
            concept.local_url == f"{conf.get_base_uri()}/{scheme.slug}/{concept.slug}"
        )
        assert concept.local_url != concept.uri
        assert concept.local_url.startswith(conf.get_base_uri())

    @pytest.mark.django_db
    def test_imported_schemes_local_url_differs_from_its_static_uri(self):
        scheme = ConceptSchemeFactory(
            name="Rocks", static_uri="http://vocabs.example.org/rocks"
        )
        assert scheme.uri == "http://vocabs.example.org/rocks"
        assert scheme.local_url == f"{conf.get_base_uri()}/{scheme.slug}"
        assert scheme.local_url != scheme.uri
        assert scheme.local_url.startswith(conf.get_base_uri())

    @pytest.mark.django_db
    def test_imported_collections_local_url_differs_from_its_static_uri(self, scheme):
        collection = CollectionFactory(
            scheme=scheme,
            name="Igneous",
            static_uri="http://vocabs.example.org/rocks/igneous",
        )
        assert collection.uri == "http://vocabs.example.org/rocks/igneous"
        assert (
            collection.local_url
            == f"{conf.get_base_uri()}/{scheme.slug}/collection/{collection.slug}"
        )
        assert collection.local_url != collection.uri
        assert collection.local_url.startswith(conf.get_base_uri())

    @pytest.mark.django_db
    def test_a_collections_local_url_can_never_equal_a_concepts(self, scheme):
        # Same slugifiable name, so only the '/collection/' segment tells them apart.
        concept = ConceptFactory(scheme=scheme, label="Igneous")
        collection = CollectionFactory(scheme=scheme, name="Igneous")
        assert concept.slug == collection.slug
        assert concept.local_url != collection.local_url

    @pytest.mark.django_db
    def test_local_url_follows_a_rename(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat Flow")
        concept.label = "Surface Heat Flow"
        concept.save()
        assert (
            concept.local_url
            == f"{conf.get_base_uri()}/{scheme.slug}/surface-heat-flow"
        )

    @pytest.mark.django_db
    def test_local_concept_of_an_externally_fixed_scheme_composes_under_this_sites_address(
        self,
    ):
        scheme = ConceptSchemeFactory(
            name="Rocks", static_uri="http://vocabs.example.org/rocks"
        )
        concept = ConceptFactory(scheme=scheme, label="Granite")
        assert concept.static_uri is None
        assert (
            concept.local_url == f"{conf.get_base_uri()}/{scheme.slug}/{concept.slug}"
        )
        assert concept.uri == concept.local_url
        assert not concept.uri.startswith("http://vocabs.example.org")

    @pytest.mark.django_db
    def test_local_collection_of_an_externally_fixed_scheme_composes_under_this_sites_address(
        self,
    ):
        scheme = ConceptSchemeFactory(
            name="Rocks", static_uri="http://vocabs.example.org/rocks"
        )
        collection = CollectionFactory(scheme=scheme, name="Igneous")
        assert collection.static_uri is None
        assert (
            collection.local_url
            == f"{conf.get_base_uri()}/{scheme.slug}/collection/{collection.slug}"
        )
        assert collection.uri == collection.local_url
        assert not collection.uri.startswith("http://vocabs.example.org")


ALL_MODELS = [
    ConceptScheme,
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptRelation,
    Collection,
    CollectionMember,
]


def editable_fields(model: type[Model]):
    """Return the model's own, user-editable, concrete fields.

    Args:
        model: The model to inspect.

    Returns:
        Every concrete editable field, excluding the auto primary key and reverse relations.
    """
    return [
        field
        for field in model._meta.get_fields()
        if getattr(field, "concrete", False)
        and getattr(field, "editable", False)
        and not field.auto_created
    ]


class TestFieldMetadata:
    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_every_editable_field_has_metadata(self, model):
        fields = editable_fields(model)
        assert fields, f"{model.__name__} exposes no editable fields to check"
        for field in fields:
            assert field.help_text, f"{model.__name__}.{field.name} has no help_text"
            assert isinstance(field.help_text, Promise), (
                f"{model.__name__}.{field.name}.help_text is not lazily translatable"
            )
            # Django defaults verbose_name to a plain str, which is not translatable.
            assert isinstance(field.verbose_name, Promise), (
                f"{model.__name__}.{field.name}.verbose_name is not lazily translatable"
            )

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_meta_verbose_names_are_lazy(self, model):
        assert isinstance(model._meta.verbose_name, Promise), (
            f"{model.__name__} Meta.verbose_name is not lazily translatable"
        )
        assert isinstance(model._meta.verbose_name_plural, Promise), (
            f"{model.__name__} Meta.verbose_name_plural is not lazily translatable"
        )


def inner_error(exc: ValidationError, field: str) -> ValidationError:
    """Return the field-scoped ValidationError carrying the lazy message.

    Args:
        exc: The raised error.
        field: The field name the error is keyed under.

    Returns:
        The first error recorded for the field.
    """
    return exc.error_dict[field][0]


def authored_nonfield_error(exc: ValidationError) -> ValidationError:
    """Return the non-field error the model authored, not the constraint's own.

    Args:
        exc: The raised error.

    Returns:
        The first non-field error carrying params, else the first non-field error.
    """
    errors = exc.error_dict[NON_FIELD_ERRORS]
    return next((e for e in errors if getattr(e, "params", None)), errors[0])


class TestValidationMessages:
    @pytest.mark.django_db
    def test_empty_name_message_is_translatable(self):
        with pytest.raises(ValidationError) as excinfo:
            ConceptScheme.objects.create(name="   ")
        err = inner_error(excinfo.value, "name")
        assert isinstance(err.message, Promise), (
            "empty-name message is not lazily translatable"
        )

    @pytest.mark.django_db
    def test_empty_label_message_is_translatable(self, scheme):
        with pytest.raises(ValidationError) as excinfo:
            Concept.objects.create(scheme=scheme, label="   ")
        err = inner_error(excinfo.value, "label")
        assert isinstance(err.message, Promise), (
            "empty-label message is not lazily translatable"
        )

    @pytest.mark.django_db
    def test_scheme_slug_collision_message_uses_named_placeholder(self):
        ConceptScheme.objects.create(name="Geothermics")
        with pytest.raises(ValidationError) as excinfo:
            ConceptScheme.objects.create(name="GEOTHERMICS")
        err = inner_error(excinfo.value, "slug")
        assert isinstance(err.message, Promise), (
            "collision message is not lazily translatable"
        )
        assert "%(slug)s" in str(err.message), (
            "collision msgid lacks a named %(slug)s placeholder"
        )
        assert err.params == {"slug": "geothermics"}
        assert "geothermics" in excinfo.value.messages[0]

    @pytest.mark.django_db
    def test_concept_slug_collision_message_uses_named_placeholder(self, scheme):
        Concept.objects.create(scheme=scheme, label="Heat Flow")
        with pytest.raises(ValidationError) as excinfo:
            Concept.objects.create(scheme=scheme, label="HEAT FLOW")
        err = inner_error(excinfo.value, "slug")
        assert isinstance(err.message, Promise), (
            "collision message is not lazily translatable"
        )
        assert "%(slug)s" in str(err.message), (
            "collision msgid lacks a named %(slug)s placeholder"
        )
        assert err.params == {"slug": "heat-flow"}
        assert "heat-flow" in excinfo.value.messages[0]

    @pytest.mark.django_db
    def test_missing_default_language_label_message_uses_named_placeholder(
        self, scheme
    ):
        with pytest.raises(ValidationError) as excinfo:
            Concept.objects.create(scheme=scheme, label="")
        err = inner_error(excinfo.value, "label")
        assert isinstance(err.message, Promise), (
            "missing-default-language-label message is not lazily translatable"
        )
        assert "%(language)s" in str(err.message), (
            "message lacks a named %(language)s placeholder"
        )
        assert err.params == {"language": scheme.effective_default_language}
        assert scheme.effective_default_language in excinfo.value.messages[0]

    @pytest.mark.django_db
    def test_duplicate_preferred_label_message_uses_named_placeholder(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Wärmefluss"
        )
        with pytest.raises(ValidationError) as excinfo:
            concept.add_label(
                language="de",
                kind=ConceptLabel.Kind.PREFERRED,
                text="Terrestrischer Wärmefluss",
            )
        err = inner_error(excinfo.value, "language")
        assert isinstance(err.message, Promise), (
            "duplicate-preferred-label message is not lazily translatable"
        )
        assert "%(language)s" in str(err.message), (
            "message lacks a named %(language)s placeholder"
        )
        assert err.params == {"language": "de"}
        assert "de" in excinfo.value.messages[0]

    @pytest.mark.django_db
    def test_self_relation_message_is_translatable(self):
        granite = ConceptFactory(label="Granite")
        with pytest.raises(ValidationError) as excinfo:
            granite.add_broader(granite)
        err = authored_nonfield_error(excinfo.value)
        assert isinstance(err.message, Promise), (
            "self-relation message is not lazily translatable"
        )

    @pytest.mark.django_db
    def test_cross_vocabulary_relation_message_uses_named_placeholders(self):
        granite = ConceptFactory(label="Granite")
        quartz = ConceptFactory(label="Quartz")
        with pytest.raises(ValidationError) as excinfo:
            granite.add_related(quartz)
        err = authored_nonfield_error(excinfo.value)
        assert isinstance(err.message, Promise), (
            "cross-vocabulary message is not lazily translatable"
        )
        assert "%(source)s" in str(err.message) and "%(target)s" in str(err.message)
        assert set(err.params) == {"source", "target"}

    @pytest.mark.django_db
    def test_disjointness_message_uses_named_placeholder(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        igneous = ConceptFactory(scheme=scheme, label="Igneous rock")
        granite.add_broader(igneous)
        with pytest.raises(ValidationError) as excinfo:
            granite.add_related(igneous)
        err = authored_nonfield_error(excinfo.value)
        assert isinstance(err.message, Promise), (
            "disjointness message is not lazily translatable"
        )
        assert "%(kind)s" in str(err.message)
        assert set(err.params) == {"kind"}

    @pytest.mark.django_db
    def test_cross_vocabulary_membership_message_uses_named_placeholders(self):
        igneous = CollectionFactory(name="Igneous")
        mica = ConceptFactory(label="Mica")
        with pytest.raises(ValidationError) as excinfo:
            igneous.add(mica)
        err = authored_nonfield_error(excinfo.value)
        assert isinstance(err.message, Promise), (
            "cross-vocabulary membership message is not lazily translatable"
        )
        assert "%(concept_scheme)s" in str(
            err.message
        ) and "%(collection_scheme)s" in str(err.message)
        assert set(err.params) == {"concept_scheme", "collection_scheme"}

    @pytest.mark.django_db
    def test_not_ordered_guard_message_uses_named_placeholder(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        plain = CollectionFactory(scheme=scheme, name="A set")
        plain.add(granite)
        with pytest.raises(ValidationError) as excinfo:
            plain.set_member_order([granite])
        # Raised directly as a non-field error, so there is no error_dict to read.
        assert isinstance(excinfo.value.messages[0], str)
        err = excinfo.value.error_list[0]
        assert isinstance(err.message, Promise), (
            "not-ordered guard message is not lazily translatable"
        )
        assert "%(name)s" in str(err.message)
        assert set(err.params) == {"name"}


class TestIndexing:
    def test_scheme_slug_is_uniquely_indexed(self):
        assert ConceptScheme._meta.get_field("slug").unique is True

    def test_concept_scheme_fk_is_indexed(self):
        assert Concept._meta.get_field("scheme").db_index is True

    def test_concept_has_composite_unique_constraint(self):
        constraint = next(
            (
                c
                for c in Concept._meta.constraints
                if isinstance(c, UniqueConstraint)
                and c.name == "unique_concept_slug_per_scheme"
            ),
            None,
        )
        assert constraint is not None, "missing (scheme, slug) UniqueConstraint"
        assert tuple(constraint.fields) == ("scheme", "slug")

    def test_concept_label_lookup_path_is_indexed(self):
        indexed = [tuple(index.fields) for index in ConceptLabel._meta.indexes]
        assert ("language", "kind", "text") in indexed, (
            f"ConceptLabel is missing a (language, kind, text) index; has {indexed}"
        )

    def test_concept_label_has_one_preferred_per_language_constraint(self):
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

    def test_concept_note_value_is_unindexed(self):
        # Free prose with no lookup path, so it stays out of every index.
        assert ConceptNote._meta.get_field("value").db_index is False, (
            "ConceptNote.value must stay unindexed"
        )
        for index in ConceptNote._meta.indexes:
            assert "value" not in index.fields, (
                "ConceptNote.value must not be part of any index"
            )

    def test_concept_note_and_label_fks_are_indexed(self):
        assert ConceptLabel._meta.get_field("concept").db_index is True
        assert ConceptNote._meta.get_field("concept").db_index is True

    def test_concept_relation_reverse_read_path_is_indexed(self):
        indexed = [tuple(index.fields) for index in ConceptRelation._meta.indexes]
        assert ("target", "kind") in indexed, (
            f"ConceptRelation missing a (target, kind) index; has {indexed}"
        )

    def test_concept_relation_has_unique_and_self_constraints(self):
        names = {c.name for c in ConceptRelation._meta.constraints}
        assert "unique_concept_relation" in names, (
            "missing the (source, target, kind) unique constraint"
        )
        assert "concept_relation_not_self" in names, (
            "missing the not-self check constraint"
        )
        unique = next(
            c
            for c in ConceptRelation._meta.constraints
            if c.name == "unique_concept_relation"
        )
        assert tuple(unique.fields) == ("source", "target", "kind")

    def test_concept_relation_fks_are_indexed(self):
        assert ConceptRelation._meta.get_field("source").db_index is True
        assert ConceptRelation._meta.get_field("target").db_index is True

    def test_collection_member_has_held_once_constraint_and_order_index(self):
        names = {c.name for c in CollectionMember._meta.constraints}
        assert "unique_collection_member" in names, (
            "missing the (collection, concept) held-once constraint"
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

    def test_collection_has_per_scheme_unique_slug_constraint(self):
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

    def test_collection_member_fks_are_indexed(self):
        assert CollectionMember._meta.get_field("collection").db_index is True
        assert CollectionMember._meta.get_field("concept").db_index is True


class TestStaticUriValidationMessages:
    def test_static_uri_not_absolute_message_uses_named_placeholder(self):
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
        # "javascript" is outside the default allowlist, so the allowlist is widened to
        # reach the denylist's own message.
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
        # The echoed value is cut to 80 characters because a hostile value can be
        # arbitrarily long, but the true length is still reported.
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
        # urlsplit raises a bare ValueError for some malformed input, such as a netloc
        # that is invalid under NFKC normalisation.
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


class TestStaticUriIndexing:
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

        # Django gives every field its own MaxLengthValidator instance, so comparing raw
        # reprs would report a false disagreement; compare a signature instead.
        def validator_signature(v):
            return (
                type(v).__name__,
                getattr(v, "limit_value", None),
                getattr(v, "__qualname__", None),
            )

        validator_reprs = {
            model.__name__: [validator_signature(v) for v in field.validators]
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


class TestConceptSchemeDefaultLanguage:
    def test_effective_default_language_is_the_app_default(self):
        assert ConceptScheme().effective_default_language == settings.LANGUAGE_CODE


class TestConceptPreferredLabels:
    @pytest.mark.django_db
    def test_preferred_labels_readable_in_each_language(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Wärmefluss"
        )
        assert concept.preferred_label("en") == "Heat flow"
        assert concept.preferred_label("de") == "Wärmefluss"
        assert concept.preferred_label() == "Heat flow"

    @pytest.mark.django_db
    def test_preferred_label_absent_language_returns_none(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        assert concept.preferred_label("fr") is None

    @pytest.mark.django_db
    def test_slug_derives_from_default_language_label(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Wärmefluss"
        )
        assert concept.slug == "heat-flow"

    @pytest.mark.django_db
    def test_second_preferred_label_in_a_language_is_refused(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Wärmefluss"
        )
        with pytest.raises(ValidationError):
            concept.add_label(
                language="de",
                kind=ConceptLabel.Kind.PREFERRED,
                text="Terrestrischer Wärmefluss",
            )

    @pytest.mark.django_db
    def test_concept_without_default_language_label_is_refused(self, scheme):
        with pytest.raises(ValidationError):
            Concept.objects.create(scheme=scheme, label="")

    @pytest.mark.django_db
    def test_preferred_label_row_in_default_language_is_refused(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        with pytest.raises(ValidationError):
            concept.add_label(
                language="en", kind=ConceptLabel.Kind.PREFERRED, text="Heat flow"
            )

    @pytest.mark.django_db
    def test_uri_and_slug_unchanged_by_non_default_label_lifecycle(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        original_slug = concept.slug
        original_uri = concept.uri

        german = concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Wärmefluss"
        )
        concept.refresh_from_db()
        assert concept.slug == original_slug
        assert concept.uri == original_uri

        german.text = "Terrestrischer Wärmefluss"
        german.save()
        concept.refresh_from_db()
        assert concept.slug == original_slug
        assert concept.uri == original_uri
        assert concept.preferred_label("de") == "Terrestrischer Wärmefluss"

        german.delete()
        concept.refresh_from_db()
        assert concept.slug == original_slug
        assert concept.uri == original_uri
        assert concept.preferred_label("de") is None


class TestConceptDisplayLabel:
    @pytest.mark.django_db
    def test_returns_the_active_languages_preferred_label(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Wärmefluss"
        )

        with translation.override("de"):
            assert concept.display_label() == "Wärmefluss"

    @pytest.mark.django_db
    def test_falls_back_to_the_default_language_when_the_active_one_has_no_label(
        self, scheme
    ):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")

        with translation.override("fr"):
            assert concept.display_label() == "Heat flow"

    @pytest.mark.django_db
    def test_never_empty_for_a_concept_that_exists(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")

        for language in ("en", "de", "fr"):
            with translation.override(language):
                assert concept.display_label()


class TestConceptAlternativeAndHiddenLabels:
    @pytest.mark.django_db
    def test_alt_labels_filtered_by_language(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        concept.add_label(
            language="en",
            kind=ConceptLabel.Kind.ALTERNATIVE,
            text="Terrestrial heat flow",
        )
        concept.add_label(
            language="en",
            kind=ConceptLabel.Kind.ALTERNATIVE,
            text="Geothermal heat flow",
        )
        concept.add_label(
            language="de",
            kind=ConceptLabel.Kind.ALTERNATIVE,
            text="Terrestrischer Wärmefluss",
        )
        assert sorted(concept.alt_labels("en")) == [
            "Geothermal heat flow",
            "Terrestrial heat flow",
        ]
        assert concept.alt_labels("de") == ["Terrestrischer Wärmefluss"]

    @pytest.mark.django_db
    def test_alt_labels_absent_language_returns_empty_list(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        assert concept.alt_labels("fr") == []

    @pytest.mark.django_db
    def test_hidden_labels_stored_and_read_per_language(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        concept.add_label(language="en", kind=ConceptLabel.Kind.HIDDEN, text="heatflow")
        concept.add_label(
            language="en", kind=ConceptLabel.Kind.HIDDEN, text="heet flow"
        )
        concept.add_label(
            language="en",
            kind=ConceptLabel.Kind.ALTERNATIVE,
            text="Terrestrial heat flow",
        )
        assert sorted(concept.hidden_labels("en")) == ["heatflow", "heet flow"]
        assert concept.hidden_labels("de") == []
        assert concept.alt_labels("en") == ["Terrestrial heat flow"]

    @pytest.mark.django_db
    def test_uri_and_slug_unchanged_by_alt_and_hidden_label_lifecycle(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        original_slug = concept.slug
        original_uri = concept.uri

        alt = concept.add_label(
            language="en",
            kind=ConceptLabel.Kind.ALTERNATIVE,
            text="Terrestrial heat flow",
        )
        hidden = concept.add_label(
            language="de", kind=ConceptLabel.Kind.HIDDEN, text="waermefluss"
        )
        concept.refresh_from_db()
        assert concept.slug == original_slug
        assert concept.uri == original_uri

        alt.text = "Geothermal heat flow"
        alt.save()
        hidden.text = "wärmefluss"
        hidden.save()
        concept.refresh_from_db()
        assert concept.slug == original_slug
        assert concept.uri == original_uri
        assert concept.alt_labels("en") == ["Geothermal heat flow"]
        assert concept.hidden_labels("de") == ["wärmefluss"]

        alt.delete()
        hidden.delete()
        concept.refresh_from_db()
        assert concept.slug == original_slug
        assert concept.uri == original_uri
        assert concept.alt_labels("en") == []
        assert concept.hidden_labels("de") == []


class TestConceptDefinitionsAndNotes:
    @pytest.mark.django_db
    def test_definitions_readable_in_each_language(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        concept.add_note(
            language="en", kind="definition", value="Heat energy moving through rock."
        )
        concept.add_note(
            language="de", kind="definition", value="Wärme, die durch Gestein strömt."
        )
        assert concept.definition("en") == "Heat energy moving through rock."
        assert concept.definition("de") == "Wärme, die durch Gestein strömt."

    @pytest.mark.django_db
    def test_definition_absent_language_returns_none(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        assert concept.definition("fr") is None

    @pytest.mark.django_db
    def test_each_documentary_note_kind_stored_and_read_by_kind(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        by_kind = {
            "scope": "Use for terrestrial heat only.",
            "example": "Continental crust ~65 mW/m².",
            "editorial": "Check the unit convention before publishing.",
            "history": "Coined in mid-20th-century geophysics.",
            "change": "Broadened from 'surface heat flow' in 2020.",
            "note": "See also thermal gradient.",
        }
        for kind, value in by_kind.items():
            concept.add_note(language="en", kind=kind, value=value)
        for kind, value in by_kind.items():
            assert concept.notes("en", kind=kind) == [value]
            assert concept.notes("de", kind=kind) == []

    @pytest.mark.django_db
    def test_notes_without_kind_returns_all_values_for_language(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        concept.add_note(language="en", kind="definition", value="A definition.")
        concept.add_note(language="en", kind="scope", value="A scope note.")
        concept.add_note(language="de", kind="note", value="Eine Notiz.")
        assert sorted(concept.notes("en")) == ["A definition.", "A scope note."]
        assert concept.notes("de") == ["Eine Notiz."]

    @pytest.mark.django_db
    def test_repeated_notes_of_a_kind_allowed(self, scheme):
        # SKOS permits repeated notes of a kind per language; no uniqueness refuses them.
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        concept.add_note(
            language="en", kind="example", value="Continental crust ~65 mW/m²."
        )
        concept.add_note(
            language="en", kind="example", value="Oceanic crust ~100 mW/m²."
        )
        assert sorted(concept.notes("en", kind="example")) == [
            "Continental crust ~65 mW/m².",
            "Oceanic crust ~100 mW/m².",
        ]

    @pytest.mark.django_db
    def test_uri_and_slug_unchanged_by_note_lifecycle(self, scheme):
        concept = ConceptFactory(scheme=scheme, label="Heat flow")
        original_slug = concept.slug
        original_uri = concept.uri

        note = concept.add_note(
            language="en", kind="definition", value="Heat energy moving through rock."
        )
        concept.refresh_from_db()
        assert concept.slug == original_slug
        assert concept.uri == original_uri

        note.value = "Heat energy conducted through rock."
        note.save()
        concept.refresh_from_db()
        assert concept.slug == original_slug
        assert concept.uri == original_uri
        assert concept.definition("en") == "Heat energy conducted through rock."

        note.delete()
        concept.refresh_from_db()
        assert concept.slug == original_slug
        assert concept.uri == original_uri
        assert concept.definition("en") is None


class TestConceptSchemePerVocabularyDefaultLanguage:
    @pytest.mark.django_db
    def test_no_override_anchors_identity_in_app_default(self, scheme):
        assert scheme.default_language == ""
        assert scheme.effective_default_language == settings.LANGUAGE_CODE

        concept = Concept.objects.create(scheme=scheme, label="Heat flow")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Wärmefluss"
        )
        assert concept.slug == "heat-flow"
        assert concept.preferred_label("en") == "Heat flow"
        assert concept.preferred_label("de") == "Wärmefluss"

    @pytest.mark.django_db
    def test_override_to_de_derives_slug_from_de_label(self, db):
        scheme = ConceptScheme.objects.create(name="Geothermik", default_language="de")
        assert scheme.effective_default_language == "de"

        concept = Concept.objects.create(scheme=scheme, label="Wärmefluss")
        concept.add_label(
            language="en", kind=ConceptLabel.Kind.PREFERRED, text="Heat flow"
        )
        assert concept.slug == "wärmefluss"
        assert concept.uri == f"{scheme.uri}/wärmefluss"
        assert concept.preferred_label("de") == "Wärmefluss"
        assert concept.preferred_label("en") == "Heat flow"

    @pytest.mark.django_db
    def test_effective_default_language_returns_override_or_app_default(self, db):
        overridden = ConceptScheme.objects.create(
            name="Geothermik", default_language="de"
        )
        assert overridden.default_language == "de"
        assert overridden.effective_default_language == "de"

        plain = ConceptScheme.objects.create(name="Geothermics")
        assert plain.default_language == ""
        assert plain.effective_default_language == settings.LANGUAGE_CODE

    @pytest.mark.django_db
    def test_default_language_is_freely_changeable_before_concepts_exist(self):
        scheme = ConceptScheme.objects.create(name="Geothermik", default_language="de")
        scheme.default_language = "fr"
        scheme.save()
        scheme.refresh_from_db()
        assert scheme.default_language == "fr"
        assert scheme.effective_default_language == "fr"

    @pytest.mark.django_db
    def test_default_language_is_frozen_once_concepts_exist(self):
        # Once a concept exists, its identity anchor (Concept.label) is the preferred
        # label in the vocabulary's effective default language. Changing the default
        # language afterwards would silently reinterpret every anchor, so it is refused.
        scheme = ConceptScheme.objects.create(name="Geothermics")
        Concept.objects.create(scheme=scheme, label="Heat flow")
        scheme.default_language = "de"
        with pytest.raises(ValidationError):
            scheme.save()
        scheme.refresh_from_db()
        assert scheme.default_language == ""
        assert scheme.effective_default_language == settings.LANGUAGE_CODE

    @pytest.mark.django_db
    def test_setting_default_language_to_the_same_value_is_allowed_with_concepts(self):
        scheme = ConceptScheme.objects.create(name="Geothermik", default_language="de")
        Concept.objects.create(scheme=scheme, label="Wärmefluss")
        scheme.name = "Geothermik (rev.)"
        scheme.save()
        scheme.refresh_from_db()
        assert scheme.default_language == "de"


class TestConceptOverridableSlug:
    @pytest.mark.django_db
    def test_explicit_slug_is_exactly_the_value_set_not_derived(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        concept.set_slug("custom-identifier")
        assert concept.slug == "custom-identifier"
        assert concept.slug_is_manual is True
        concept.refresh_from_db()
        assert concept.slug == "custom-identifier"
        assert concept.slug != "heat-flow"

    @pytest.mark.django_db
    def test_explicit_slug_survives_a_default_language_relabel(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        concept.set_slug("hf")
        concept.label = "Surface Heat Flow"
        concept.save()
        assert concept.slug == "hf"
        concept.refresh_from_db()
        assert concept.slug == "hf"

    @pytest.mark.django_db
    def test_slug_without_override_still_derives_from_label(self, scheme):
        concept = Concept.objects.create(scheme=scheme, label="Heat Flow")
        assert concept.slug == "heat-flow"
        assert concept.slug_is_manual is False
        concept.label = "Surface Heat Flow"
        concept.save()
        assert concept.slug == "surface-heat-flow"

    @pytest.mark.django_db
    def test_explicit_slug_colliding_within_scheme_is_refused(self, scheme):
        Concept.objects.create(scheme=scheme, label="Heat Flow")
        other = Concept.objects.create(scheme=scheme, label="Gradient")
        with pytest.raises(ValidationError):
            other.set_slug("heat-flow")
        assert scheme.concepts.filter(slug="heat-flow").count() == 1


class TestReviewHardening:
    @pytest.mark.django_db
    def test_explicit_slug_with_invalid_characters_is_refused(self, scheme):
        # A manual slug is stored verbatim but must still be a well-formed single-segment
        # slug: a '/' or whitespace would corrupt the composed URI and break get_by_uri.
        concept = Concept.objects.create(scheme=scheme, label="Heat flow")
        with pytest.raises(ValidationError):
            concept.set_slug("foo/bar")
        with pytest.raises(ValidationError):
            concept.set_slug("has spaces")
        concept.set_slug("hf-1")
        assert concept.slug == "hf-1"

    @pytest.mark.django_db
    def test_default_language_preferred_row_is_refused_even_via_create(self, scheme):
        # The default-language-preferred rule is backstopped at save(), so even
        # .objects.create() (which bypasses full_clean) cannot plant a second identity
        # anchor alongside Concept.label.
        concept = Concept.objects.create(scheme=scheme, label="Heat flow")
        with pytest.raises(ValidationError):
            ConceptLabel.objects.create(
                concept=concept,
                language="en",
                kind=ConceptLabel.Kind.PREFERRED,
                text="Heat flow (dup)",
            )

    @pytest.mark.django_db
    def test_language_outside_the_configured_set_is_refused(self, scheme):
        # choices=settings.LANGUAGES was dropped (so the migration does not freeze the
        # maintainer's LANGUAGES); an unconfigured language is still refused at runtime.
        concept = Concept.objects.create(scheme=scheme, label="Heat flow")
        with pytest.raises(ValidationError):
            concept.add_label(
                language="xx", kind=ConceptLabel.Kind.ALTERNATIVE, text="nope"
            )
        with pytest.raises(ValidationError):
            concept.add_note(language="xx", kind=ConceptNote.Kind.NOTE, value="nope")

    @pytest.mark.django_db
    def test_scheme_default_language_rejects_an_unconfigured_language(self):
        with pytest.raises(ValidationError):
            ConceptScheme.objects.create(name="Bad", default_language="xx")

    @pytest.mark.django_db
    def test_read_helpers_stay_cheap_under_prefetch_related(
        self, django_assert_num_queries, scheme
    ):
        # The helpers iterate the cached related set, so prefetch_related makes reading by
        # language cost no extra queries (a .filter() would bypass the cache).
        concept = Concept.objects.create(scheme=scheme, label="Heat flow")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Wärmefluss"
        )
        concept.add_label(
            language="en",
            kind=ConceptLabel.Kind.ALTERNATIVE,
            text="terrestrial heat flow",
        )
        concept.add_note(
            language="de", kind=ConceptNote.Kind.DEFINITION, value="Wärmestromdichte."
        )

        prefetched = (
            Concept.objects.select_related("scheme")
            .prefetch_related("labels", "concept_notes")
            .get(pk=concept.pk)
        )
        with django_assert_num_queries(0):
            assert prefetched.preferred_label("de") == "Wärmefluss"
            assert prefetched.alt_labels("en") == ["terrestrial heat flow"]
            assert prefetched.hidden_labels("en") == []
            assert prefetched.definition("de") == "Wärmestromdichte."
            assert prefetched.notes("de") == ["Wärmestromdichte."]

    @pytest.mark.django_db
    def test_get_by_uri_rejects_a_sibling_prefix_path(self, scheme):
        # A URI that merely shares the base as a raw prefix ('<base>X/...') must not be
        # treated as in-base — the match is on a '/'-terminated base.
        concept = Concept.objects.create(scheme=scheme, label="Heat flow")
        base = conf.get_base_uri()
        sibling = f"{base}X/{scheme.slug}/{concept.slug}"
        with pytest.raises(Concept.DoesNotExist):
            Concept.objects.get_by_uri(sibling)
        assert Concept.objects.get_by_uri(concept.uri) == concept


class TestBroaderNarrower:
    @pytest.mark.django_db
    def test_broader_readable_and_narrower_derived(self, scheme):
        igneous = ConceptFactory(scheme=scheme, label="Igneous rock")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        granite.add_broader(igneous)
        assert igneous in granite.broader()
        assert granite in igneous.narrower()
        assert list(granite.narrower()) == []
        assert list(igneous.broader()) == []

    @pytest.mark.django_db
    def test_polyhierarchy_several_broader(self, scheme):
        igneous = ConceptFactory(scheme=scheme, label="Igneous rock")
        plutonic = ConceptFactory(scheme=scheme, label="Plutonic rock")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        granite.add_broader(igneous)
        granite.add_broader(plutonic)
        assert set(granite.broader()) == {igneous, plutonic}

    @pytest.mark.django_db
    def test_remove_broader_clears_both_directions(self, scheme):
        igneous = ConceptFactory(scheme=scheme, label="Igneous rock")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        granite.add_broader(igneous)
        granite.remove_broader(igneous)
        assert list(granite.broader()) == []
        assert list(igneous.narrower()) == []
        granite.remove_broader(igneous)

    @pytest.mark.django_db
    def test_self_broader_is_refused(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        with pytest.raises(ValidationError):
            granite.add_broader(granite)

    @pytest.mark.django_db
    def test_duplicate_broader_is_refused(self, scheme):
        igneous = ConceptFactory(scheme=scheme, label="Igneous rock")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        granite.add_broader(igneous)
        with pytest.raises(ValidationError):
            granite.add_broader(igneous)
        assert list(granite.broader()) == [igneous]

    @pytest.mark.django_db
    def test_reverse_broader_is_a_distinct_edge(self, scheme):
        # A two-cycle is permitted: no hierarchy traversal happens and the ordered
        # unique key differs.
        a = ConceptFactory(scheme=scheme, label="A")
        b = ConceptFactory(scheme=scheme, label="B")
        a.add_broader(b)
        b.add_broader(a)
        assert b in a.broader()
        assert a in b.broader()

    @pytest.mark.django_db
    def test_cross_scheme_broader_is_refused(self, scheme):
        other = ConceptSchemeFactory()
        here = ConceptFactory(scheme=scheme, label="Granite")
        there = ConceptFactory(scheme=other, label="Quartz")
        with pytest.raises(ValidationError):
            here.add_broader(there)

    @pytest.mark.django_db
    def test_adding_and_removing_broader_leaves_identity_unchanged(self, scheme):
        igneous = ConceptFactory(scheme=scheme, label="Igneous rock")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        uri_before, slug_before = granite.uri, granite.slug
        granite.add_broader(igneous)
        granite.refresh_from_db()
        assert (granite.uri, granite.slug) == (uri_before, slug_before)
        granite.remove_broader(igneous)
        granite.refresh_from_db()
        assert (granite.uri, granite.slug) == (uri_before, slug_before)


class TestRelated:
    @pytest.mark.django_db
    def test_related_is_symmetric(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        quartz = ConceptFactory(scheme=scheme, label="Quartz")
        granite.add_related(quartz)
        assert quartz in granite.related()
        assert granite in quartz.related()

    @pytest.mark.django_db
    def test_related_stored_once_mirror_refused(self, scheme):
        from controlled_vocabularies.models import ConceptRelation

        granite = ConceptFactory(scheme=scheme, label="Granite")
        quartz = ConceptFactory(scheme=scheme, label="Quartz")
        granite.add_related(quartz)
        with pytest.raises(ValidationError):
            quartz.add_related(granite)
        assert (
            ConceptRelation.objects.filter(kind=ConceptRelation.Kind.RELATED).count()
            == 1
        )
        assert list(granite.related()) == [quartz]

    @pytest.mark.django_db
    def test_same_order_related_duplicate_is_refused(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        quartz = ConceptFactory(scheme=scheme, label="Quartz")
        granite.add_related(quartz)
        with pytest.raises(ValidationError):
            granite.add_related(quartz)

    @pytest.mark.django_db
    def test_self_related_is_refused(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        with pytest.raises(ValidationError):
            granite.add_related(granite)

    @pytest.mark.django_db
    def test_remove_related_clears_both_sides(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        quartz = ConceptFactory(scheme=scheme, label="Quartz")
        granite.add_related(quartz)
        quartz.remove_related(granite)
        assert list(granite.related()) == []
        assert list(quartz.related()) == []
        quartz.remove_related(granite)

    @pytest.mark.django_db
    def test_cross_scheme_related_is_refused(self, scheme):
        other = ConceptSchemeFactory()
        here = ConceptFactory(scheme=scheme, label="Granite")
        there = ConceptFactory(scheme=other, label="Quartz")
        with pytest.raises(ValidationError):
            here.add_related(there)

    @pytest.mark.django_db
    def test_adding_related_leaves_identity_unchanged(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        quartz = ConceptFactory(scheme=scheme, label="Quartz")
        uri_before, slug_before = granite.uri, granite.slug
        granite.add_related(quartz)
        granite.refresh_from_db()
        assert (granite.uri, granite.slug) == (uri_before, slug_before)


class TestGraphIntegrity:
    @pytest.mark.django_db
    def test_hierarchical_pair_cannot_also_be_related(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        igneous = ConceptFactory(scheme=scheme, label="Igneous rock")
        granite.add_broader(igneous)
        with pytest.raises(ValidationError):
            granite.add_related(igneous)
        with pytest.raises(ValidationError):
            igneous.add_related(granite)

    @pytest.mark.django_db
    def test_related_pair_cannot_be_given_a_broader_link(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        quartz = ConceptFactory(scheme=scheme, label="Quartz")
        granite.add_related(quartz)
        with pytest.raises(ValidationError):
            granite.add_broader(quartz)
        with pytest.raises(ValidationError):
            quartz.add_broader(granite)

    @pytest.mark.django_db
    def test_disjointness_constrains_a_pair_not_the_vocabulary(self, scheme):
        a = ConceptFactory(scheme=scheme, label="A")
        b = ConceptFactory(scheme=scheme, label="B")
        c = ConceptFactory(scheme=scheme, label="C")
        d = ConceptFactory(scheme=scheme, label="D")
        a.add_broader(b)
        c.add_related(d)
        assert b in a.broader()
        assert d in c.related()

    @pytest.mark.django_db
    def test_transitively_hierarchical_pair_can_be_related(self, scheme):
        # a -> b -> c (broader). a and c are only *transitively* hierarchical, so relating
        # them is accepted — disjointness is checked at direct adjacency only.
        a = ConceptFactory(scheme=scheme, label="A")
        b = ConceptFactory(scheme=scheme, label="B")
        c = ConceptFactory(scheme=scheme, label="C")
        a.add_broader(b)
        b.add_broader(c)
        a.add_related(c)
        assert c in a.related()

    @pytest.mark.django_db
    def test_cyclic_broader_chain_is_accepted(self, scheme):
        # a -> b -> c -> a: cycles are not prevented, and inserting one performs no
        # hierarchy traversal.
        a = ConceptFactory(scheme=scheme, label="A")
        b = ConceptFactory(scheme=scheme, label="B")
        c = ConceptFactory(scheme=scheme, label="C")
        a.add_broader(b)
        b.add_broader(c)
        c.add_broader(a)
        assert a in c.broader()


class TestCollectionMembership:
    @pytest.mark.django_db
    def test_add_and_read_members(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        quartz = ConceptFactory(scheme=scheme, label="Quartz")
        igneous = CollectionFactory(scheme=scheme, name="Common igneous rocks")
        igneous.add(granite)
        igneous.add(basalt)
        assert set(igneous.members()) == {granite, basalt}
        assert quartz not in igneous.members()

    @pytest.mark.django_db
    def test_new_collection_has_no_members(self, scheme):
        empty = CollectionFactory(scheme=scheme, name="Empty")
        assert list(empty.members()) == []

    @pytest.mark.django_db
    def test_adding_same_concept_twice_holds_it_once(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        igneous = CollectionFactory(scheme=scheme, name="Igneous")
        igneous.add(granite)
        igneous.add(granite)
        assert list(igneous.members()).count(granite) == 1
        assert igneous.memberships.count() == 1

    @pytest.mark.django_db
    def test_a_concept_can_belong_to_several_collections(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        igneous = CollectionFactory(scheme=scheme, name="Igneous")
        field_guide = CollectionFactory(scheme=scheme, name="Field-guide rocks")
        igneous.add(granite)
        field_guide.add(granite)
        assert granite in igneous.members()
        assert granite in field_guide.members()
        igneous.remove(granite)
        assert granite not in igneous.members()
        assert granite in field_guide.members()

    @pytest.mark.django_db
    def test_remove_member_leaves_others_untouched(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        igneous = CollectionFactory(scheme=scheme, name="Igneous")
        igneous.add(granite)
        igneous.add(basalt)
        igneous.remove(granite)
        assert granite not in igneous.members()
        assert basalt in igneous.members()

    @pytest.mark.django_db
    def test_remove_a_non_member_is_a_no_op(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        igneous = CollectionFactory(scheme=scheme, name="Igneous")
        igneous.remove(granite)
        assert list(igneous.members()) == []

    @pytest.mark.django_db
    def test_concept_reports_its_collections(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        igneous = CollectionFactory(scheme=scheme, name="Igneous")
        field_guide = CollectionFactory(scheme=scheme, name="Field-guide rocks")
        igneous.add(granite)
        field_guide.add(granite)
        assert set(granite.collections()) == {igneous, field_guide}

    @pytest.mark.django_db
    def test_colliding_collection_slug_in_one_scheme_is_refused(self, scheme):
        Collection.objects.create(scheme=scheme, name="Igneous rocks")
        with pytest.raises(ValidationError):
            Collection.objects.create(scheme=scheme, name="Igneous rocks")

    @pytest.mark.django_db
    def test_same_collection_name_allowed_across_schemes(self):
        a = ConceptSchemeFactory(name="Rocks")
        b = ConceptSchemeFactory(name="Minerals")
        first = CollectionFactory(scheme=a, name="Common")
        second = CollectionFactory(scheme=b, name="Common")
        assert first.slug == second.slug
        assert first.scheme_id != second.scheme_id

    @pytest.mark.django_db
    def test_name_that_slugifies_to_empty_is_refused(self, scheme):
        # A name with no slug-able characters would mint an empty identifier; refuse it
        # rather than store an unidentifiable collection (the scheme/concept rule).
        with pytest.raises(ValidationError):
            Collection.objects.create(scheme=scheme, name="***")

    @pytest.mark.django_db
    def test_membership_str_names_the_concept_and_collection(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        igneous = CollectionFactory(scheme=scheme, name="Igneous")
        member = igneous.add(granite)
        assert str(member) == "Granite in Igneous"

    @pytest.mark.django_db
    def test_membership_leaves_concept_identity_unchanged(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        uri_before, slug_before = granite.uri, granite.slug
        igneous = CollectionFactory(scheme=scheme, name="Igneous")
        igneous.add(granite)
        igneous.remove(granite)
        granite.refresh_from_db()
        assert granite.uri == uri_before
        assert granite.slug == slug_before

    @pytest.mark.django_db
    def test_uri_composes_under_a_collection_segment(self):
        vocab = ConceptSchemeFactory(name="Rocks")
        coll = CollectionFactory(scheme=vocab, name="Common igneous rocks")
        assert coll.uri == f"{vocab.uri}/collection/{coll.slug}"

    @pytest.mark.django_db
    def test_str_is_the_name(self, scheme):
        coll = CollectionFactory(scheme=scheme, name="Common igneous rocks")
        assert str(coll) == "Common igneous rocks"


class TestCollectionOverridableSlug:
    @pytest.mark.django_db
    def test_explicit_slug_is_exactly_the_value_set_not_derived(self, scheme):
        collection = Collection.objects.create(scheme=scheme, name="Igneous Rocks")
        collection.set_slug("custom-identifier")
        assert collection.slug == "custom-identifier"
        assert collection.slug_is_manual is True
        collection.refresh_from_db()
        assert collection.slug == "custom-identifier"
        assert collection.slug != "igneous-rocks"

    @pytest.mark.django_db
    def test_explicit_slug_survives_a_rename(self, scheme):
        collection = Collection.objects.create(scheme=scheme, name="Igneous Rocks")
        collection.set_slug("ig")
        collection.name = "Igneous and Volcanic Rocks"
        collection.save()
        assert collection.slug == "ig"
        collection.refresh_from_db()
        assert collection.slug == "ig"

    @pytest.mark.django_db
    def test_slug_without_override_still_derives_from_name(self, scheme):
        collection = Collection.objects.create(scheme=scheme, name="Igneous Rocks")
        assert collection.slug == "igneous-rocks"
        assert collection.slug_is_manual is False
        collection.name = "Volcanic Rocks"
        collection.save()
        assert collection.slug == "volcanic-rocks"

    @pytest.mark.django_db
    def test_explicit_slug_colliding_within_scheme_is_refused(self, scheme):
        Collection.objects.create(scheme=scheme, name="Igneous Rocks")
        other = Collection.objects.create(scheme=scheme, name="Sedimentary Rocks")
        with pytest.raises(ValidationError):
            other.set_slug("igneous-rocks")
        assert scheme.collections.filter(slug="igneous-rocks").count() == 1

    @pytest.mark.django_db
    def test_explicit_slug_that_is_empty_or_malformed_is_refused(self, scheme):
        collection = CollectionFactory(scheme=scheme, name="Igneous Rocks")
        with pytest.raises(ValidationError) as empty_exc:
            collection.set_slug("")
        assert "slug" in empty_exc.value.message_dict
        with pytest.raises(ValidationError) as slash_exc:
            collection.set_slug("foo/bar")
        assert "slug" in slash_exc.value.message_dict
        with pytest.raises(ValidationError) as spaces_exc:
            collection.set_slug("has spaces")
        assert "slug" in spaces_exc.value.message_dict
        collection.set_slug("ig-1")
        assert collection.slug == "ig-1"


class TestOrderedCollection:
    @pytest.mark.django_db
    def test_ordered_members_read_in_add_sequence(self, scheme):
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        gabbro = ConceptFactory(scheme=scheme, label="Gabbro")
        reading = CollectionFactory(scheme=scheme, name="Reading order", ordered=True)
        reading.add(basalt)
        reading.add(granite)
        reading.add(gabbro)
        assert list(reading.members()) == [basalt, granite, gabbro]

    @pytest.mark.django_db
    def test_set_member_order_rearranges(self, scheme):
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        gabbro = ConceptFactory(scheme=scheme, label="Gabbro")
        reading = CollectionFactory(scheme=scheme, name="Reading order", ordered=True)
        for c in (basalt, granite, gabbro):
            reading.add(c)
        reading.set_member_order([gabbro, basalt, granite])
        assert list(reading.members()) == [gabbro, basalt, granite]

    @pytest.mark.django_db
    def test_removing_a_member_keeps_relative_order(self, scheme):
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        granite = ConceptFactory(scheme=scheme, label="Granite")
        gabbro = ConceptFactory(scheme=scheme, label="Gabbro")
        reading = CollectionFactory(scheme=scheme, name="Reading order", ordered=True)
        for c in (basalt, granite, gabbro):
            reading.add(c)
        reading.remove(granite)
        assert list(reading.members()) == [basalt, gabbro]

    @pytest.mark.django_db
    def test_set_member_order_on_unordered_collection_is_refused(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        plain = CollectionFactory(scheme=scheme, name="A set")
        plain.add(granite)
        plain.add(basalt)
        with pytest.raises(ValidationError):
            plain.set_member_order([basalt, granite])

    @pytest.mark.django_db
    def test_set_member_order_with_a_different_set_is_refused(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        quartz = ConceptFactory(scheme=scheme, label="Quartz")
        reading = CollectionFactory(scheme=scheme, name="Reading order", ordered=True)
        reading.add(granite)
        reading.add(basalt)
        with pytest.raises(ValidationError):
            reading.set_member_order([granite, basalt, quartz])

    @pytest.mark.django_db
    def test_unordered_collection_returns_its_members_as_a_set(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        plain = CollectionFactory(scheme=scheme, name="A set")
        plain.add(granite)
        plain.add(basalt)
        assert set(plain.members()) == {granite, basalt}


class TestMembershipIntegrity:
    @pytest.mark.django_db
    def test_cross_vocabulary_member_is_refused(self):
        rocks = ConceptSchemeFactory(name="Rocks")
        minerals = ConceptSchemeFactory(name="Minerals")
        igneous = CollectionFactory(scheme=rocks, name="Igneous")
        mica = ConceptFactory(scheme=minerals, label="Mica")
        with pytest.raises(ValidationError):
            igneous.add(mica)
        assert list(igneous.members()) == []

    @pytest.mark.django_db
    def test_membership_asserts_no_relation(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        basalt = ConceptFactory(scheme=scheme, label="Basalt")
        igneous = CollectionFactory(scheme=scheme, name="Igneous")
        igneous.add(granite)
        igneous.add(basalt)
        assert basalt not in granite.related()
        assert basalt not in granite.broader()
        assert basalt not in granite.narrower()

    @pytest.mark.django_db
    def test_existing_relation_is_unchanged_by_shared_membership(self, scheme):
        granite = ConceptFactory(scheme=scheme, label="Granite")
        igneous_rock = ConceptFactory(scheme=scheme, label="Igneous rock")
        granite.add_broader(igneous_rock)
        coll = CollectionFactory(scheme=scheme, name="Igneous")
        coll.add(granite)
        coll.add(igneous_rock)
        assert igneous_rock in granite.broader()
        assert granite in igneous_rock.narrower()


# An empty string falls inside the partial unique constraint while uri and has_static_uri
# read it as absent, so the models normalise it to None.


class TestBlankStaticUriIsAbsent:
    @pytest.mark.django_db
    def test_two_schemes_assigned_a_blank_static_uri_coexist(self):
        first = ConceptScheme.objects.create(name="First", static_uri="")
        second = ConceptScheme.objects.create(name="Second", static_uri="")
        assert first.static_uri is None
        assert second.static_uri is None
        assert first.uri == first.local_url
        assert second.uri == second.local_url

    @pytest.mark.django_db
    def test_two_concepts_assigned_a_blank_static_uri_coexist(self, scheme):
        first = Concept.objects.create(scheme=scheme, label="First", static_uri="")
        second = Concept.objects.create(scheme=scheme, label="Second", static_uri="")
        assert first.static_uri is None
        assert second.static_uri is None

    @pytest.mark.django_db
    def test_two_collections_assigned_a_blank_static_uri_coexist(self, scheme):
        first = Collection.objects.create(scheme=scheme, name="First", static_uri="")
        second = Collection.objects.create(scheme=scheme, name="Second", static_uri="")
        assert first.static_uri is None
        assert second.static_uri is None

    @pytest.mark.django_db
    def test_a_blank_static_uri_is_stored_as_null_not_an_empty_string(self, scheme):
        concept = Concept.objects.create(
            scheme=scheme, label="Heat Flow", static_uri=""
        )
        concept.refresh_from_db()
        assert concept.static_uri is None
        assert concept.has_static_uri is False
        assert Concept.objects.filter(static_uri__isnull=True).count() == 1

    @pytest.mark.django_db
    def test_full_clean_also_normalises_a_blank_static_uri(self, scheme):
        concept = Concept(scheme=scheme, label="Heat Flow", static_uri="")
        concept.full_clean(exclude=["slug"])
        assert concept.static_uri is None
