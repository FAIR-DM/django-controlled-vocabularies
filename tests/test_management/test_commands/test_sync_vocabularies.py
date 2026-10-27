"""Tests for controlled_vocabularies.management.commands.sync_vocabularies."""

import inspect
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.fields import ConceptField, Vocabulary
from controlled_vocabularies.management.commands import (
    sync_vocabularies as sync_vocabularies_command,
)
from controlled_vocabularies.models import ConceptScheme, Record
from tests.i18n_sweep import visit_management_source
from tests.testapp.models import ERA, MINERAL, ROCK_TYPE, UNUSED

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "skos"
ROCKS_URI = "http://example.org/rocks/"


def sync(*slugs, **options):
    """Run ``sync_vocabularies`` and return what it wrote to stdout and stderr.

    Args:
        *slugs: The declared vocabularies to limit the run to.
        **options: The command's options.

    Returns:
        A ``(stdout, stderr)`` pair.
    """
    out, err = StringIO(), StringIO()
    call_command("sync_vocabularies", *slugs, stdout=out, stderr=err, **options)
    return out.getvalue(), err.getvalue()


def declared(**sources):
    """Declare each keyword's source under its key, with ``_`` read as ``-``.

    Args:
        **sources: The source of each vocabulary, keyed by its slug.

    Returns:
        A settings override declaring them.
    """
    return override_settings(
        CONTROLLED_VOCABULARIES={
            slug.replace("_", "-"): {"source": source}
            for slug, source in sources.items()
        }
    )


@pytest.fixture
def fields_naming(monkeypatch):
    """Replace the site's concept fields with fields naming the given vocabularies.

    Returns:
        A function taking each field's ``vocabulary`` argument.
    """

    def install(*vocabularies):
        fields = [ConceptField(vocabulary=vocabulary) for vocabulary in vocabularies]
        monkeypatch.setattr(sync_vocabularies_command, "concept_fields", lambda: fields)

    return install


@pytest.fixture
def models_naming_no_vocabulary(fields_naming):
    """Run against a site whose models name no vocabulary, so only settings load."""
    fields_naming()


@pytest.mark.django_db
@pytest.mark.usefixtures("models_naming_no_vocabulary")
class TestSyncVocabulariesLoadsDeclaredVocabularies:
    def test_a_declared_file_is_loaded_under_its_declared_slug(self):
        with declared(rock_type=FIXTURES / "rocks.ttl"):
            sync()

        scheme = ConceptScheme.objects.get(uri=ROCKS_URI)
        assert scheme.slug == "rock-type"
        assert scheme.records.count() == 7

    def test_a_second_run_updates_the_same_rows_in_place(self):
        with declared(rock_type=FIXTURES / "rocks.ttl"):
            sync()
            keys_before = dict(Record.objects.values_list("uri", "pk"))
            sync()

        assert ConceptScheme.objects.get().slug == "rock-type"
        assert dict(Record.objects.values_list("uri", "pk")) == keys_before

    def test_every_declared_vocabulary_is_loaded_in_one_run(self):
        with declared(
            rock_type=FIXTURES / "rocks.ttl",
            french=FIXTURES / "french_vocabulary.ttl",
        ):
            sync()

        assert set(ConceptScheme.objects.values_list("slug", flat=True)) == {
            "rock-type",
            "french",
        }

    def test_a_declared_url_is_fetched_and_loaded(self, http_stub):
        http_stub.set_response(
            "/rocks.ttl",
            body=(FIXTURES / "rocks.ttl").read_bytes(),
            content_type="text/turtle",
        )
        with declared(rock_type=http_stub.url + "/rocks.ttl"):
            sync()

        assert ConceptScheme.objects.get(uri=ROCKS_URI).slug == "rock-type"

    def test_a_declared_format_is_used_for_a_source_whose_name_carries_none(
        self, tmp_path
    ):
        source = tmp_path / "rocks.data"
        source.write_bytes((FIXTURES / "rocks.ttl").read_bytes())
        with override_settings(
            CONTROLLED_VOCABULARIES={
                "rock-type": {"source": source, "format": "turtle"}
            }
        ):
            sync()

        assert ConceptScheme.objects.get(uri=ROCKS_URI).slug == "rock-type"

    def test_the_report_counts_what_each_run_did(self):
        with declared(rock_type=FIXTURES / "rocks.ttl"):
            first, _ = sync()
            second, _ = sync()

        assert "8 records created." in first
        assert "8 records updated." in second

    def test_nothing_is_printed_at_verbosity_zero(self):
        with declared(rock_type=FIXTURES / "rocks.ttl"):
            out, _ = sync(verbosity=0)

        assert out == ""

    def test_a_site_declaring_nothing_loads_nothing_and_succeeds(self):
        with override_settings(CONTROLLED_VOCABULARIES={}):
            sync()

        assert not ConceptScheme.objects.exists()


@pytest.mark.django_db
@pytest.mark.usefixtures("models_naming_no_vocabulary")
class TestSyncVocabulariesNeverDeletes:
    def test_records_the_source_no_longer_lists_are_reported_and_kept(self):
        with declared(rock_type=FIXTURES / "rocks.ttl"):
            sync()
        held = set(Record.objects.values_list("uri", flat=True))

        with declared(rock_type=FIXTURES / "rocks_updated.ttl"):
            sync()

        assert held <= set(Record.objects.values_list("uri", flat=True))


@pytest.mark.django_db
@pytest.mark.usefixtures("models_naming_no_vocabulary")
class TestSyncVocabulariesFindsAVocabularyByItsDeclaredSlug:
    def test_a_source_declaring_another_vocabulary_is_refused_and_changes_nothing(
        self,
    ):
        with declared(rock_type=FIXTURES / "rocks.ttl"):
            sync()
        held = dict(Record.objects.values_list("uri", "data"))

        with (
            declared(rock_type=FIXTURES / "french_vocabulary.ttl"),
            pytest.raises(CommandError),
        ):
            sync()

        assert ConceptScheme.objects.get().uri == ROCKS_URI
        assert dict(Record.objects.values_list("uri", "data")) == held

    def test_a_source_declaring_no_vocabulary_loads_into_the_one_already_held(self):
        with declared(rock_type=FIXTURES / "rocks.ttl"):
            sync()

        with declared(rock_type=FIXTURES / "no_scheme_declared.ttl"):
            sync()

        assert Record.objects.filter(
            uri="http://example.org/loose/basalt", scheme__slug="rock-type"
        ).exists()

    def test_a_vocabulary_loaded_under_another_slug_is_reported_not_renamed(self):
        import_skos(FIXTURES / "rocks.ttl")
        slug_before = ConceptScheme.objects.get().slug

        with (
            declared(rock_type=FIXTURES / "rocks.ttl"),
            pytest.raises(CommandError),
        ):
            sync()

        scheme = ConceptScheme.objects.get()
        assert scheme.slug == slug_before
        assert scheme.slug != "rock-type"

    def test_the_report_of_a_vocabulary_loaded_under_another_slug_names_that_slug(
        self,
    ):
        import_skos(FIXTURES / "rocks.ttl")
        slug_before = ConceptScheme.objects.get().slug
        err = StringIO()

        with (
            declared(rock_type=FIXTURES / "rocks.ttl"),
            pytest.raises(CommandError),
        ):
            call_command("sync_vocabularies", stdout=StringIO(), stderr=err)

        assert slug_before in err.getvalue()


@pytest.mark.django_db
@pytest.mark.usefixtures("models_naming_no_vocabulary")
class TestSyncVocabulariesReportsAFailureAndCarriesOn:
    def test_one_failing_vocabulary_does_not_stop_the_others(self):
        err = StringIO()
        with (
            declared(
                missing=FIXTURES / "does-not-exist.ttl",
                rock_type=FIXTURES / "rocks.ttl",
            ),
            pytest.raises(CommandError),
        ):
            call_command("sync_vocabularies", stdout=StringIO(), stderr=err)

        assert ConceptScheme.objects.get().slug == "rock-type"
        assert "missing" in err.getvalue()

    def test_a_refused_source_leaves_nothing_of_its_own_behind(self):
        with (
            declared(loose=FIXTURES / "no_scheme_declared.ttl"),
            pytest.raises(CommandError),
        ):
            sync()

        assert not ConceptScheme.objects.exists()
        assert not Record.objects.exists()

    def test_a_key_that_is_not_a_slug_is_reported_and_the_others_still_load(self):
        with (
            override_settings(
                CONTROLLED_VOCABULARIES={
                    "rock type!": {"source": FIXTURES / "rocks.ttl"},
                    "french": {"source": FIXTURES / "french_vocabulary.ttl"},
                }
            ),
            pytest.raises(CommandError),
        ):
            sync()

        assert list(ConceptScheme.objects.values_list("slug", flat=True)) == ["french"]

    def test_a_declaration_without_a_source_is_reported_as_a_failure(self):
        with (
            override_settings(CONTROLLED_VOCABULARIES={"rock-type": {}}),
            pytest.raises(CommandError),
        ):
            sync()

        assert not ConceptScheme.objects.exists()


@pytest.mark.django_db
@pytest.mark.usefixtures("models_naming_no_vocabulary")
class TestSyncVocabulariesDryRun:
    def test_a_dry_run_reports_what_would_be_created_and_keeps_nothing(self):
        with declared(rock_type=FIXTURES / "rocks.ttl"):
            out, _ = sync(dry_run=True)

        assert "8 records created." in out
        assert not ConceptScheme.objects.exists()
        assert not Record.objects.exists()

    def test_a_dry_run_of_a_failing_source_still_fails(self):
        with (
            declared(loose=FIXTURES / "no_scheme_declared.ttl"),
            pytest.raises(CommandError),
        ):
            sync(dry_run=True)


@pytest.mark.django_db
@pytest.mark.usefixtures("models_naming_no_vocabulary")
class TestSyncVocabulariesLimitedToNamedSlugs:
    def test_only_the_named_vocabularies_are_loaded(self):
        with declared(
            rock_type=FIXTURES / "rocks.ttl",
            french=FIXTURES / "french_vocabulary.ttl",
        ):
            sync("french")

        assert list(ConceptScheme.objects.values_list("slug", flat=True)) == ["french"]

    def test_an_undeclared_slug_is_refused_before_anything_is_loaded(self):
        with (
            declared(rock_type=FIXTURES / "rocks.ttl"),
            pytest.raises(CommandError),
        ):
            sync("rock-type", "mineral")

        assert not ConceptScheme.objects.exists()


@pytest.mark.django_db
class TestSyncVocabulariesLoadsWhatFieldsName:
    def test_every_vocabulary_the_models_name_is_loaded_without_settings(self):
        with override_settings(CONTROLLED_VOCABULARIES={}):
            sync()

        assert set(ConceptScheme.objects.values_list("uri", flat=True)) == {
            ROCK_TYPE.uri,
            MINERAL.uri,
            ERA.uri,
        }

    def test_a_field_inherited_from_an_abstract_model_is_counted(self):
        assert ERA.uri in sync_vocabularies_command.field_vocabularies()

    def test_an_abstract_model_nothing_inherits_names_nothing(self):
        assert UNUSED not in sync_vocabularies_command.field_vocabularies()

    def test_a_second_run_updates_the_same_rows_in_place(self):
        with override_settings(CONTROLLED_VOCABULARIES={}):
            sync()
            keys_before = dict(Record.objects.values_list("uri", "pk"))
            sync()

        assert dict(Record.objects.values_list("uri", "pk")) == keys_before

    def test_a_vocabulary_declared_in_settings_is_never_read_from_the_field(
        self, fields_naming
    ):
        fields_naming(Vocabulary(ROCK_TYPE.uri, source=FIXTURES / "does-not-exist.ttl"))
        with declared(rock_type=FIXTURES / "rock-type.ttl"):
            sync()

        assert ConceptScheme.objects.get(uri=ROCK_TYPE.uri).slug == "rock-type"

    def test_a_declared_vocabulary_named_by_its_uri_is_read_from_the_declaration(
        self, fields_naming
    ):
        with declared(rock_type=FIXTURES / "rock-type.ttl"):
            sync()
            fields_naming(
                Vocabulary(ROCK_TYPE.uri, source=FIXTURES / "does-not-exist.ttl")
            )
            out, _ = sync(ROCK_TYPE.uri)

        assert out.startswith("rock-type")

    def test_a_vocabulary_named_by_several_fields_is_read_once_from_the_first_source(
        self, fields_naming
    ):
        unread = FIXTURES / "does-not-exist.ttl"
        fields_naming(
            ROCK_TYPE.uri,
            ROCK_TYPE,
            Vocabulary(ROCK_TYPE.uri, source=unread),
        )

        with override_settings(CONTROLLED_VOCABULARIES={}):
            out, _ = sync()

        assert ConceptScheme.objects.get().uri == ROCK_TYPE.uri
        assert str(unread) in out

    def test_a_vocabulary_with_no_source_is_read_from_its_uri(
        self, fields_naming, http_stub
    ):
        http_stub.set_response(
            "/vocabulary",
            body=(
                b"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
                b'<> a skos:ConceptScheme ; skos:prefLabel "Stubbed"@en .\n'
                b"<#a> a skos:Concept ; skos:inScheme <> ; "
                b'skos:prefLabel "A"@en .\n'
            ),
            content_type="text/turtle",
        )
        fields_naming(http_stub.url + "/vocabulary")

        with override_settings(CONTROLLED_VOCABULARIES={}):
            sync()

        assert ConceptScheme.objects.get().uri == http_stub.url + "/vocabulary"
        assert Record.objects.get().uri == http_stub.url + "/vocabulary#a"

    def test_a_source_publishing_another_vocabulary_is_refused_and_the_others_load(
        self, fields_naming
    ):
        fields_naming(
            Vocabulary(
                "https://example.org/vocabularies/other", source=FIXTURES / "rocks.ttl"
            ),
            MINERAL,
        )
        err = StringIO()

        with (
            override_settings(CONTROLLED_VOCABULARIES={}),
            pytest.raises(CommandError),
        ):
            call_command("sync_vocabularies", stdout=StringIO(), stderr=err)

        assert ConceptScheme.objects.get().uri == MINERAL.uri
        assert "https://example.org/vocabularies/other" in err.getvalue()

    def test_a_field_vocabulary_can_be_named_on_the_command_line_by_its_uri(self):
        with override_settings(CONTROLLED_VOCABULARIES={}):
            sync(MINERAL.uri)

        assert ConceptScheme.objects.get().uri == MINERAL.uri

    def test_a_dry_run_keeps_nothing_the_fields_name(self):
        with override_settings(CONTROLLED_VOCABULARIES={}):
            sync(dry_run=True)

        assert not ConceptScheme.objects.exists()


class TestSyncVocabulariesCommandI18nSweep:
    def test_every_output_string_is_translatable_with_named_placeholders(self):
        source = Path(inspect.getfile(sync_vocabularies_command)).read_text()
        visitor = visit_management_source(source)
        assert visitor.positional_placeholders == []
        assert visitor.bare_literals == []
