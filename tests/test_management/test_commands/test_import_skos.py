"""Tests for controlled_vocabularies.management.commands.import_skos."""

import importlib
import inspect
import os
import socket
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
from django.apps import apps
from django.core.management import CommandError, call_command
from django.utils.functional import Promise

from controlled_vocabularies.exchange.report import FatalReason
from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.management import sources
from controlled_vocabularies.management.commands import (
    import_skos as import_skos_command,
)
from controlled_vocabularies.management.commands.import_skos import Command
from controlled_vocabularies.models import Concept, ConceptScheme
from tests.i18n_sweep import visit_management_source

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "skos"
SECURITY_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "security"
ROCKS_URI = "http://example.org/rocks/"


class TestManagementPackageSkeleton:
    def test_management_package_is_importable(self):
        module = importlib.import_module("controlled_vocabularies.management")
        assert module.__file__ is not None

    def test_management_commands_package_is_importable(self):
        module = importlib.import_module("controlled_vocabularies.management.commands")
        assert module.__file__ is not None


class TestImportSkosCommandCreatesAndUpdates:
    def test_importing_into_an_empty_database_creates_the_vocabulary_and_names_the_count(
        self, db
    ):
        out = StringIO()
        call_command("import_skos", str(FIXTURES / "rocks.ttl"), stdout=out)
        scheme = ConceptScheme.objects.get(static_uri=ROCKS_URI)
        assert scheme.name == "Rock types"
        assert Concept.objects.count() == 5
        output = out.getvalue()
        assert "8 records created." in output
        assert "0 records updated." in output

    def test_reimporting_the_same_file_reports_updates_and_creates_no_duplicate_concept(
        self, db
    ):
        call_command("import_skos", str(FIXTURES / "rocks.ttl"), stdout=StringIO())
        out = StringIO()
        call_command("import_skos", str(FIXTURES / "rocks.ttl"), stdout=out)
        assert ConceptScheme.objects.filter(static_uri=ROCKS_URI).count() == 1
        assert Concept.objects.count() == 5
        output = out.getvalue()
        assert "8 records updated." in output
        assert "0 records created." in output


class TestImportSkosCommandHelpIsTranslatable:
    def test_command_help_is_lazily_translatable_at_its_source(self):
        # The class attribute stays lazy. Only the parser's own copy is forced, in
        # create_parser, with the active language already set.
        assert isinstance(Command.help, Promise)

    def test_help_output_renders(self):
        # argparse lays help out through re.sub, which rejects a gettext_lazy proxy, so
        # a proxy left in the parser makes --help raise instead of print.
        parser = Command().create_parser("manage.py", "import_skos")
        rendered = parser.format_help()
        assert "--dry-run" in rendered
        assert "--format" in rendered

    def test_every_argument_help_reaches_the_parser_as_a_real_string(self):
        # Only this command's own arguments: Django's base arguments carry its plain-str
        # help.
        parser = Command().create_parser("manage.py", "import_skos")
        ours = {
            action.dest: action
            for action in parser._actions
            if action.dest in ("source", "format", "dry_run")
        }
        assert set(ours) == {"source", "format", "dry_run"}
        for dest, action in ours.items():
            assert action.help, f"{dest} has no help text"
            assert isinstance(action.help, str), (
                f"{dest} help reaches argparse as a proxy, which breaks --help"
            )
        assert isinstance(parser.description, str)


class TestImportSkosCommandRefusesABadPath:
    def test_a_missing_path_is_refused_naming_the_path_and_writes_nothing(self, db):
        missing = str(FIXTURES / "does-not-exist.ttl")
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", missing, stdout=StringIO())
        assert missing in str(exc_info.value)
        assert ConceptScheme.objects.count() == 0

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root ignores file permissions",
    )
    def test_an_unreadable_path_is_reported_distinctly_from_a_missing_one(
        self, db, tmp_path
    ):
        unreadable = tmp_path / "vocab.ttl"
        unreadable.write_bytes((FIXTURES / "rocks.ttl").read_bytes())
        unreadable.chmod(0o000)
        try:
            with pytest.raises(CommandError) as missing_exc:
                call_command(
                    "import_skos",
                    str(FIXTURES / "does-not-exist.ttl"),
                    stdout=StringIO(),
                )
            with pytest.raises(CommandError) as unreadable_exc:
                call_command("import_skos", str(unreadable), stdout=StringIO())
        finally:
            unreadable.chmod(0o644)
        assert str(missing_exc.value) != str(unreadable_exc.value)
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandFormatOption:
    def test_a_file_whose_extension_names_no_format_imports_when_format_is_given(
        self, db, tmp_path
    ):
        # Built under tmp_path so the fixtures directory walk never sweeps it.
        mystery = tmp_path / "vocab.mysteryext"
        mystery.write_bytes((FIXTURES / "rocks.ttl").read_bytes())
        call_command("import_skos", str(mystery), format="turtle", stdout=StringIO())
        assert ConceptScheme.objects.filter(static_uri=ROCKS_URI).exists()

    def test_the_same_file_without_format_is_refused(self, db, tmp_path):
        mystery = tmp_path / "vocab.mysteryext"
        mystery.write_bytes((FIXTURES / "rocks.ttl").read_bytes())
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", str(mystery), stdout=StringIO())
        assert str(mystery) in str(exc_info.value)
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandURLFailureModes:
    def test_an_unreachable_host_is_refused_naming_the_url(self, db):
        # A closed local socket: connecting to it fails immediately with "connection
        # refused" — a local failure, not a real network call.
        closed = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        url = f"http://127.0.0.1:{port}/vocab.ttl"
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", url, stdout=StringIO())
        assert url in str(exc_info.value)
        assert ConceptScheme.objects.count() == 0

    def test_a_non_2xx_status_is_refused_naming_the_url(self, db, http_stub):
        http_stub.set_response("/vocab.ttl", status=500, body=b"boom")
        url = http_stub.url + "/vocab.ttl"
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", url, stdout=StringIO())
        assert url in str(exc_info.value)
        assert ConceptScheme.objects.count() == 0

    def test_an_html_body_fails_as_unreadable_content_not_an_empty_vocabulary(
        self, db, http_stub
    ):
        http_stub.set_response(
            "/vocab.ttl",
            status=200,
            body=b"<html><body>Not a vocabulary</body></html>",
            content_type="text/html",
        )
        url = http_stub.url + "/vocab.ttl"
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", url, stdout=StringIO())
        assert url in str(exc_info.value)
        assert ConceptScheme.objects.count() == 0

    def test_a_connection_that_never_answers_fails_on_a_timeout_rather_than_hanging(
        self, db, hanging_socket, monkeypatch
    ):
        # The shipped timeout is set for real publishers, which is far longer than a
        # test should wait to prove the same behaviour.
        monkeypatch.setattr(sources, "_TIMEOUT_SECONDS", 0.5)
        url = hanging_socket
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", url, stdout=StringIO())
        assert url in str(exc_info.value)
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandURLParity:
    _RELATIVE_URIS_TURTLE = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

<>
    a skos:ConceptScheme ;
    skos:prefLabel "Relative vocabulary"@en ;
    skos:hasTopConcept <concept-a> .

<concept-a>
    a skos:Concept ;
    skos:inScheme <> ;
    skos:topConceptOf <> ;
    skos:prefLabel "Concept A"@en .
"""

    def test_a_url_import_and_a_disk_import_of_absolute_identifiers_produce_the_same_records_and_report(
        self, db, http_stub
    ):
        rocks_bytes = (FIXTURES / "rocks.ttl").read_bytes()
        http_stub.set_response(
            "/rocks.ttl", status=200, body=rocks_bytes, content_type="text/turtle"
        )

        url_out = StringIO()
        call_command("import_skos", http_stub.url + "/rocks.ttl", stdout=url_out)
        url_records = set(Concept.objects.values_list("static_uri", flat=True))
        url_scheme_name = ConceptScheme.objects.get(static_uri=ROCKS_URI).name
        url_report = url_out.getvalue()

        Concept.objects.all().delete()
        ConceptScheme.objects.all().delete()

        disk_out = StringIO()
        call_command("import_skos", str(FIXTURES / "rocks.ttl"), stdout=disk_out)
        disk_records = set(Concept.objects.values_list("static_uri", flat=True))
        disk_scheme_name = ConceptScheme.objects.get(static_uri=ROCKS_URI).name

        assert url_records == disk_records
        assert url_scheme_name == disk_scheme_name
        assert url_report == disk_out.getvalue()

    def test_relative_identifiers_are_stored_under_the_stubs_address_not_a_file_path(
        self, db, http_stub
    ):
        http_stub.set_response(
            "/relative.ttl",
            status=200,
            body=self._RELATIVE_URIS_TURTLE.encode(),
            content_type="text/turtle",
        )
        scheme_uri = http_stub.url + "/relative.ttl"
        concept_uri = http_stub.url + "/concept-a"
        call_command("import_skos", scheme_uri, stdout=StringIO())
        assert ConceptScheme.objects.filter(static_uri=scheme_uri).exists()
        assert Concept.objects.filter(static_uri=concept_uri).exists()
        assert not ConceptScheme.objects.filter(
            static_uri__startswith="file://"
        ).exists()
        assert not Concept.objects.filter(static_uri__startswith="file://").exists()


class TestImportSkosCommandDryRun:
    # transactional_db, not db: under db the test's own transaction is rolled back at
    # the end, so a dry run that never rolled back would pass anyway
    # (docs/adr/0005-a-preview-is-the-real-operation-rolled-back.md).

    @staticmethod
    def _snapshot() -> dict[str, list[dict[str, object]]]:
        """Return every row of every model this app defines, field values included.

        Returns:
            The rows of each model, keyed by the model's label.
        """
        return {
            model._meta.label: list(model.objects.order_by("pk").values())  # type: ignore[attr-defined]
            for model in apps.get_app_config("controlled_vocabularies").get_models()
        }

    def test_a_dry_run_against_a_populated_database_leaves_every_table_unchanged(
        self, transactional_db
    ):
        import_skos(FIXTURES / "rocks.ttl")
        before = self._snapshot()

        call_command(
            "import_skos",
            str(FIXTURES / "rocks_updated.ttl"),
            dry_run=True,
            stdout=StringIO(),
        )

        assert self._snapshot() == before

    def test_a_dry_run_of_a_new_vocabulary_against_an_empty_database_creates_nothing(
        self, transactional_db
    ):
        before = self._snapshot()

        call_command(
            "import_skos", str(FIXTURES / "rocks.ttl"), dry_run=True, stdout=StringIO()
        )

        assert self._snapshot() == before
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandDryRunFidelity:
    def test_a_dry_run_and_a_live_run_against_the_same_state_produce_equal_reports(
        self, transactional_db, monkeypatch
    ):
        import_skos(FIXTURES / "rocks.ttl")

        captured = []
        real_import_skos = import_skos_command.import_skos

        def spy(*args, **kwargs):
            report = real_import_skos(*args, **kwargs)
            captured.append(report)
            return report

        monkeypatch.setattr(import_skos_command, "import_skos", spy)

        call_command(
            "import_skos",
            str(FIXTURES / "rocks_updated.ttl"),
            dry_run=True,
            stdout=StringIO(),
        )
        dry_run_report = captured.pop()

        call_command(
            "import_skos", str(FIXTURES / "rocks_updated.ttl"), stdout=StringIO()
        )
        live_report = captured.pop()

        assert dry_run_report.created == live_report.created
        assert dry_run_report.updated == live_report.updated
        assert dry_run_report.set_aside == live_report.set_aside
        assert dry_run_report.normalized == live_report.normalized
        assert dry_run_report.absent_from_source == live_report.absent_from_source
        assert dry_run_report.fatal == live_report.fatal == []

    def test_a_refused_source_is_reported_as_refused_when_dry_run_and_still_exits_non_zero(
        self, transactional_db
    ):
        with pytest.raises(CommandError):
            call_command(
                "import_skos",
                str(FIXTURES / "no_scheme_declared.ttl"),
                dry_run=True,
                stdout=StringIO(),
            )
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandDryRunLine:
    def test_a_dry_run_prints_one_line_more_than_a_live_run_of_the_same_source(
        self, db
    ):
        dry_run_out = StringIO()
        call_command(
            "import_skos", str(FIXTURES / "rocks.ttl"), dry_run=True, stdout=dry_run_out
        )

        live_out = StringIO()
        call_command("import_skos", str(FIXTURES / "rocks.ttl"), stdout=live_out)

        dry_run_lines = dry_run_out.getvalue().splitlines()
        assert len(dry_run_lines) == len(live_out.getvalue().splitlines()) + 1


class TestImportSkosCommandRefusalPrintsEveryFatalFinding:
    def test_every_fatal_finding_prints_not_just_the_first(self, db):
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "import_skos",
                str(FIXTURES / "multiple_fatal_problems.ttl"),
                stdout=StringIO(),
            )
        message = str(exc_info.value)
        findings = exc_info.value.__cause__.report.fatal
        assert len(findings) == 2
        for finding in findings:
            assert finding.render() in message
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0
        assert Concept.objects.count() == 0


class TestImportSkosCommandRefusesAnUndeterminedVocabulary:
    def test_a_source_declaring_no_concept_scheme_is_refused_as_not_skos(self, db):
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "import_skos",
                str(FIXTURES / "no_scheme_declared.ttl"),
                stdout=StringIO(),
            )
        findings = exc_info.value.__cause__.report.fatal
        assert [finding.reason for finding in findings] == [
            FatalReason.VOCABULARY_UNDETERMINED
        ]
        assert findings[0].render() in str(exc_info.value)
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0

    def test_an_empty_file_is_refused_rather_than_importing_an_empty_vocabulary(
        self, db, tmp_path
    ):
        empty = tmp_path / "empty.ttl"
        empty.write_text("")
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", str(empty), stdout=StringIO())
        findings = exc_info.value.__cause__.report.fatal
        assert [finding.reason for finding in findings] == [
            FatalReason.VOCABULARY_UNDETERMINED
        ]
        assert findings[0].render() in str(exc_info.value)
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0

    def test_a_graph_with_no_skos_content_is_refused_rather_than_importing_an_empty_vocabulary(
        self, db, tmp_path
    ):
        no_skos = tmp_path / "no_skos.ttl"
        no_skos.write_text(
            '@prefix dc: <http://purl.org/dc/elements/1.1/> .\n<http://example.org/thing> dc:title "Just a thing" .\n'
        )
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", str(no_skos), stdout=StringIO())
        findings = exc_info.value.__cause__.report.fatal
        assert [finding.reason for finding in findings] == [
            FatalReason.VOCABULARY_UNDETERMINED
        ]
        assert findings[0].render() in str(exc_info.value)
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandSafetyScanRefusalReachedFromBothSourceForms:
    def test_an_unsafe_rdf_xml_document_is_refused_from_a_path(self, db):
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "import_skos",
                str(SECURITY_FIXTURES / "entity_bomb.rdf"),
                stdout=StringIO(),
            )
        assert "e0" in str(exc_info.value)
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0

    def test_an_unsafe_rdf_xml_document_is_refused_from_a_url(self, db, http_stub):
        body = (SECURITY_FIXTURES / "entity_bomb.rdf").read_bytes()
        http_stub.set_response(
            "/entity_bomb.rdf",
            status=200,
            body=body,
            content_type="application/rdf+xml",
        )
        url = http_stub.url + "/entity_bomb.rdf"
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", url, stdout=StringIO())
        assert "e0" in str(exc_info.value)
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0

    def test_an_unsafe_json_ld_document_is_refused_from_a_path(self, db):
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "import_skos",
                str(SECURITY_FIXTURES / "remote_context_string.jsonld"),
                stdout=StringIO(),
            )
        assert "http://127.0.0.1:1/x.json" in str(exc_info.value)
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0

    def test_an_unsafe_json_ld_document_is_refused_from_a_url(self, db, http_stub):
        body = (SECURITY_FIXTURES / "remote_context_string.jsonld").read_bytes()
        http_stub.set_response(
            "/remote_context_string.jsonld",
            status=200,
            body=body,
            content_type="application/ld+json",
        )
        url = http_stub.url + "/remote_context_string.jsonld"
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", url, stdout=StringIO())
        assert "http://127.0.0.1:1/x.json" in str(exc_info.value)
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandSurfacesAnAmbiguousVocabularyRefusalUnchanged:
    def test_a_source_declaring_more_than_one_concept_scheme_is_refused_unchanged(
        self, db
    ):
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "import_skos", str(FIXTURES / "two_vocabularies.ttl"), stdout=StringIO()
            )
        message = str(exc_info.value)
        assert "http://example.org/alpha/" in message
        assert "http://example.org/beta/" in message
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandExitsZeroOnACompletedRun:
    # call_command bypasses run_from_argv, the one call site that turns a refusal's
    # returncode into sys.exit, so these go through run_from_argv, the real command-line
    # entry point.

    def test_a_run_that_sets_values_aside_still_exits_zero(self, db):
        command = Command(stdout=StringIO())
        with mock.patch("sys.exit") as mock_exit:
            command.run_from_argv(
                [
                    "manage.py",
                    "import_skos",
                    str(FIXTURES / "unconfigured_language_values.ttl"),
                ]
            )
        mock_exit.assert_not_called()
        scheme = ConceptScheme.objects.get(static_uri="http://example.org/quarry3/")
        assert Concept.objects.filter(
            scheme=scheme, static_uri__endswith="/schist"
        ).exists()

    def test_a_refused_run_exits_non_zero_through_the_same_call_site(self, db):
        # The counterpart that gives assert_not_called above its meaning.
        command = Command(stdout=StringIO(), stderr=StringIO())
        with mock.patch("sys.exit") as mock_exit:
            command.run_from_argv(
                ["manage.py", "import_skos", str(FIXTURES / "no_scheme_declared.ttl")]
            )
        mock_exit.assert_called_once()
        assert mock_exit.call_args.args[0] != 0
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandCarriesVerbosityIntoTheRenderer:
    def test_the_default_verbosity_prints_counts_without_a_line_per_set_aside_value(
        self, db
    ):
        out = StringIO()
        call_command(
            "import_skos",
            str(FIXTURES / "unconfigured_language_values.ttl"),
            stdout=out,
        )
        lines = out.getvalue().splitlines()
        assert any("set aside" in line for line in lines)
        assert not any(
            line.startswith("'http://example.org/quarry3/") for line in lines
        )

    def test_raised_verbosity_prints_one_line_per_set_aside_entry(self, db):
        out = StringIO()
        call_command(
            "import_skos",
            str(FIXTURES / "unconfigured_language_values.ttl"),
            stdout=out,
            verbosity=2,
        )
        report = import_skos(FIXTURES / "unconfigured_language_values.ttl")
        rendered = out.getvalue()
        assert report.set_aside
        for entry in report.set_aside:
            assert str(entry.render()) in rendered


class TestImportSkosCommandRemovesTheFetchedTemporaryFile:
    # The resolver's own cleanup tests call cleanup() themselves, so only these prove
    # the command's finally block does. The success path leaks on a misplaced call, the
    # raise path only when the finally is lost.

    @staticmethod
    def _watch_temp_paths(monkeypatch):
        """Record the temp path of every resolver the command builds, then clean up as usual.

        Args:
            monkeypatch: The pytest fixture used to wrap ``SourceResolver.cleanup``.

        Returns:
            The list the recorded paths are appended to.
        """
        seen = []
        original = sources.SourceResolver.cleanup

        def recording_cleanup(self):
            if self._temp_path is not None:
                seen.append(self._temp_path)
            return original(self)

        monkeypatch.setattr(sources.SourceResolver, "cleanup", recording_cleanup)
        return seen

    def test_a_completed_url_import_leaves_no_temporary_file(
        self, db, http_stub, monkeypatch
    ):
        seen = self._watch_temp_paths(monkeypatch)
        http_stub.set_response(
            "/rocks.ttl",
            status=200,
            body=(FIXTURES / "rocks.ttl").read_bytes(),
            content_type="text/turtle",
        )
        call_command("import_skos", http_stub.url + "/rocks.ttl", stdout=StringIO())
        assert len(seen) == 1, (
            "the command built no resolver, so this test proves nothing"
        )
        assert not seen[0].exists()

    def test_a_refused_url_import_leaves_no_temporary_file(
        self, db, http_stub, monkeypatch
    ):
        # The fetch succeeds and the import is what fails, so the file exists at the
        # moment the refusal is raised — the case a cleanup outside the finally would
        # leak.
        seen = self._watch_temp_paths(monkeypatch)
        http_stub.set_response(
            "/vocab.ttl",
            status=200,
            body=b"<html><body>Not found</body></html>",
            content_type="text/turtle",
        )
        with pytest.raises(CommandError):
            call_command("import_skos", http_stub.url + "/vocab.ttl", stdout=StringIO())
        assert len(seen) == 1, (
            "the command built no resolver, so this test proves nothing"
        )
        assert not seen[0].exists()

    def test_a_local_path_import_deletes_nothing(self, db, monkeypatch):
        # The file the operator named is theirs, not a temporary the command may remove.
        seen = self._watch_temp_paths(monkeypatch)
        call_command("import_skos", str(FIXTURES / "rocks.ttl"), stdout=StringIO())
        assert seen == []
        assert (FIXTURES / "rocks.ttl").exists()


class TestImportSkosCommandI18nSweep:
    def test_every_output_string_is_translatable_with_named_placeholders(self):
        source = Path(inspect.getfile(import_skos_command)).read_text()
        visitor = visit_management_source(source)
        assert visitor.positional_placeholders == [], (
            f"{import_skos_command.__name__} passes a positional placeholder to a translation call: "
            f"{visitor.positional_placeholders}"
        )
        assert visitor.bare_literals == [], (
            f"{import_skos_command.__name__} passes a bare, untranslated literal to an output sink: {visitor.bare_literals}"
        )


class TestManagementI18nVisitorCatchesAViolation:
    def test_catches_a_positional_placeholder_in_a_translation_call(self):
        visitor = visit_management_source(
            'from django.utils.translation import gettext_lazy as _\n_("%s changed")\n'
        )
        assert visitor.positional_placeholders == ["%s changed"]

    def test_catches_a_bare_literal_raised_as_a_command_error(self):
        visitor = visit_management_source(
            "from django.core.management.base import CommandError\nraise CommandError('boom')\n"
        )
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_written_to_stdout(self):
        visitor = visit_management_source("self.stdout.write('boom')\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_as_an_argument_help(self):
        visitor = visit_management_source("parser.add_argument('--x', help='boom')\n")
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_as_the_command_help_attribute(self):
        visitor = visit_management_source(
            "class Command(BaseCommand):\n    help = 'boom'\n"
        )
        assert visitor.bare_literals == ["boom"]

    def test_catches_a_bare_literal_yielded_as_a_rendered_line(self):
        visitor = visit_management_source("def render():\n    yield 'boom'\n")
        assert visitor.bare_literals == ["boom"]

    def test_does_not_flag_a_named_placeholder_or_a_translated_sink(self):
        visitor = visit_management_source(
            "from django.utils.translation import gettext_lazy as _\n"
            "from django.core.management.base import CommandError\n"
            "raise CommandError(str(_(\"'%(file)s' is fine.\")) % {'file': 'x'})\n"
        )
        assert visitor.positional_placeholders == []
        assert visitor.bare_literals == []
