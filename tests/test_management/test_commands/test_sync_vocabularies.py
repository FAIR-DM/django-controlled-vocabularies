"""Tests for controlled_vocabularies.management.commands.sync_vocabularies."""

import inspect
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.management.commands import (
    sync_vocabularies as sync_vocabularies_command,
)
from controlled_vocabularies.models import ConceptScheme, Record
from tests.i18n_sweep import visit_management_source

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


@pytest.mark.django_db
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
class TestSyncVocabulariesNeverDeletes:
    def test_records_the_source_no_longer_lists_are_reported_and_kept(self):
        with declared(rock_type=FIXTURES / "rocks.ttl"):
            sync()
        held = set(Record.objects.values_list("uri", flat=True))

        with declared(rock_type=FIXTURES / "rocks_updated.ttl"):
            sync()

        assert held <= set(Record.objects.values_list("uri", flat=True))


@pytest.mark.django_db
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

        assert list(ConceptScheme.objects.values_list("slug", flat=True)) == [
            "french"
        ]

    def test_a_declaration_without_a_source_is_reported_as_a_failure(self):
        with (
            override_settings(CONTROLLED_VOCABULARIES={"rock-type": {}}),
            pytest.raises(CommandError),
        ):
            sync()

        assert not ConceptScheme.objects.exists()


@pytest.mark.django_db
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
class TestSyncVocabulariesLimitedToNamedSlugs:
    def test_only_the_named_vocabularies_are_loaded(self):
        with declared(
            rock_type=FIXTURES / "rocks.ttl",
            french=FIXTURES / "french_vocabulary.ttl",
        ):
            sync("french")

        assert list(ConceptScheme.objects.values_list("slug", flat=True)) == [
            "french"
        ]

    def test_an_undeclared_slug_is_refused_before_anything_is_loaded(self):
        with (
            declared(rock_type=FIXTURES / "rocks.ttl"),
            pytest.raises(CommandError),
        ):
            sync("rock-type", "mineral")

        assert not ConceptScheme.objects.exists()


class TestSyncVocabulariesCommandI18nSweep:
    def test_every_output_string_is_translatable_with_named_placeholders(self):
        source = Path(inspect.getfile(sync_vocabularies_command)).read_text()
        visitor = visit_management_source(source)
        assert visitor.positional_placeholders == []
        assert visitor.bare_literals == []
