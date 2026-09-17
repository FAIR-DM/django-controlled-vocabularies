"""T002 — the ``management`` package skeleton (Article XIV).

No behaviour lands here: this only proves the package the command (T003
onward) and the renderer (T015) build on is importable. The command itself
is out of this story's scope.

T003 onward (below): the ``import_skos`` command itself — one positional
``source``, a ``--format`` option, and ``handle()`` delegating the whole
import to :func:`~controlled_vocabularies.exchange.skos.import_skos` and
rendering the result through :class:`~controlled_vocabularies.management.rendering.ReportRenderer`
(plan.md "Rendering", tasks.md US-1).
"""

import importlib
import os
import socket
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
from django.apps import apps
from django.core.management import CommandError, call_command
from django.utils.functional import Promise

from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.management import sources
from controlled_vocabularies.management.commands import (
    import_skos as import_skos_command,
)
from controlled_vocabularies.management.commands.import_skos import Command
from controlled_vocabularies.models import Concept, ConceptScheme

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
    """T003 — spec Acceptance Scenarios 1-2: an empty database gets the vocabulary and its
    concepts, named by count; a second run against the same file reports updates and creates
    no duplicate concept. Every line comes from ``ReportRenderer`` (plan.md "Rendering")."""

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
    """T003 — Article XII: every help string is wrapped for translation at its source.

    That wrapping is enforced statically by ``TestManagementPackageI18nSweep`` in
    ``tests/test_standards.py``, which reads the AST. What is asserted here is the runtime
    half: the strings reach argparse as real strings, because a lazy proxy that survives
    into the parser makes ``--help`` raise rather than print.
    """

    def test_command_help_is_lazily_translatable_at_its_source(self):
        # The class attribute stays lazy. Only the parser's own copy is forced, in
        # create_parser, with the active language already set.
        assert isinstance(Command.help, Promise)

    def test_help_output_renders(self):
        """The regression test for a `--help` that raised instead of printing.

        argparse lays out both the description and every argument help through ``re.sub``
        (``HelpFormatter._fill_text`` / ``_split_lines``), which rejects a ``gettext_lazy``
        proxy with ``TypeError: expected string or bytes-like object``. Django hands
        ``Command.help`` straight to argparse as ``description`` and never calls ``str()``
        on it, so leaving the proxies in place broke the first thing an operator runs.
        """
        parser = Command().create_parser("manage.py", "import_skos")
        rendered = parser.format_help()
        assert "Import a published SKOS vocabulary" in rendered
        assert "--dry-run" in rendered
        assert "--format" in rendered
        assert "A local filesystem path or an http(s) URL" in rendered

    def test_every_argument_help_reaches_the_parser_as_a_real_string(self):
        # Only this command's own arguments — Django's base arguments (verbosity,
        # settings, pythonpath, ...) carry Django's own plain-str help and are not
        # this story's to translate.
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
    """T004 — spec Acceptance Scenario 4 and Edge Cases: a missing path fails naming the path,
    writes nothing, and exits non-zero via `CommandError`; a path that exists but cannot be
    opened for permission reasons is reported distinctly, not as absent (spec Edge Cases)."""

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
        assert "is not readable" in str(unreadable_exc.value)
        assert "is not readable" not in str(missing_exc.value)
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandFormatOption:
    """T005 — spec Acceptance Scenario 3: `--format` reaches `from_file` as the `serialization`
    keyword, the same one the programmatic entry point already accepts. The command does not
    reimplement format guessing (tasks.md T005) — a fixture built under `tmp_path` rather than
    committed to `tests/fixtures/skos/`, per decisions.md D11's own precedent, so it is never
    swept by `TestEverySkosPredicateIsReadOrReported`'s directory walk."""

    def test_a_file_whose_extension_names_no_format_imports_when_format_is_given(
        self, db, tmp_path
    ):
        mystery = tmp_path / "vocab.mysteryext"
        mystery.write_bytes((FIXTURES / "rocks.ttl").read_bytes())
        call_command("import_skos", str(mystery), format="turtle", stdout=StringIO())
        assert ConceptScheme.objects.filter(static_uri=ROCKS_URI).exists()

    def test_the_same_file_without_format_is_refused_with_the_existing_message(
        self, db, tmp_path
    ):
        mystery = tmp_path / "vocab.mysteryext"
        mystery.write_bytes((FIXTURES / "rocks.ttl").read_bytes())
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", str(mystery), stdout=StringIO())
        assert "not in a serialization this application reads" in str(exc_info.value)
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandURLFailureModes:
    """T010, FR-014, spec Edge Cases — every URL retrieval failure exits non-zero (raises
    `CommandError`), names the URL, and leaves the database untouched. Uses `http_stub` and
    `hanging_socket` (tests/conftest.py, T006) — no real network call anywhere in this class."""

    def test_an_unreachable_host_is_refused_naming_the_url(self, db):
        # A closed local socket: connecting to it fails immediately with "connection refused" —
        # a local failure, not a real network call.
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
        assert "could not be parsed" in str(exc_info.value)
        assert ConceptScheme.objects.count() == 0

    def test_a_connection_that_never_answers_fails_on_a_timeout_rather_than_hanging(
        self, db, hanging_socket, monkeypatch
    ):
        # The shipped timeout is set for real publishers, which is far longer than a test
        # should wait to prove the same behaviour.
        monkeypatch.setattr(sources, "_TIMEOUT_SECONDS", 0.5)
        url = hanging_socket
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", url, stdout=StringIO())
        assert url in str(exc_info.value)
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandURLParity:
    """T011, SC-002, FR-003 — `SourceResolver` wired into `Command`: a URL import of a document
    with absolute identifiers produces the same records and report as the identical bytes from
    disk, and a document with relative identifiers is stored under the address it was served
    from, never under a `file://` path (decisions.md D10)."""

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
    """T012, spec Acceptance Scenario 1, `decisions.md` D4, `research.md` R5 — `--dry-run`
    runs the whole import inside an outer transaction it then abandons. `transactional_db`,
    not `db`: under `db` the test itself already runs inside a transaction rolled back at the
    end, which would make a broken dry run (one that never actually rolls back) pass anyway.
    """

    @staticmethod
    def _snapshot() -> dict[str, list[dict[str, object]]]:
        """Every row of every model this app defines, field values included — proves every
        table is unchanged rather than only that row counts match (tasks.md T012)."""
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
    """T013, spec Acceptance Scenarios 2-3, SC-003 — a dry run and a live run against the
    same starting state produce equal reports, compared by bucket rather than by rendered
    text; a source that would be refused is refused the same way whether dry-run or not."""

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
    """T014, FR-010, `decisions.md` D9 — the dry run line reaches the command's actual
    output: present for a dry run, absent for a live run of the same source."""

    def test_the_dry_run_line_is_present_for_a_dry_run_and_absent_for_a_live_run(
        self, db
    ):
        dry_run_out = StringIO()
        call_command(
            "import_skos", str(FIXTURES / "rocks.ttl"), dry_run=True, stdout=dry_run_out
        )
        assert "nothing was kept" in dry_run_out.getvalue()

        live_out = StringIO()
        call_command("import_skos", str(FIXTURES / "rocks.ttl"), stdout=live_out)
        assert "nothing was kept" not in live_out.getvalue()


class TestImportSkosCommandRefusalPrintsEveryFatalFinding:
    """T020, FR-011, spec US-5 Acceptance Scenario 3 — where the importer collects more than
    one fatal finding, the command prints all of them, not only the first; the exit status
    is non-zero; the database is unchanged. ``multiple_fatal_problems.ttl`` already carries
    two distinct fatal findings at the exchange layer (test_exchange/test_skos.py
    ``TestFatalFindingsAndAtomicity``) — surfaced here unchanged, not re-detected."""

    def test_every_fatal_finding_prints_not_just_the_first(self, db):
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "import_skos",
                str(FIXTURES / "multiple_fatal_problems.ttl"),
                stdout=StringIO(),
            )
        message = str(exc_info.value)
        assert "'Nameless' has no identifier that survives re-serialization" in message
        assert (
            "'ftp://mirror.example.org/mixed/refused' is not an identifier the application accepts"
            in message
        )
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0
        assert Concept.objects.count() == 0


class TestImportSkosCommandRefusesAnUndeterminedVocabulary:
    """T021, FR-013, spec US-5 Acceptance Scenario 1, decisions.md D2 — a source declaring no
    concept scheme is refused as not being SKOS, which falls out of the existing
    ``VOCABULARY_UNDETERMINED`` fatal because the command names no target. The same refusal
    covers two further spec Edge Cases that reach it for the same reason: an empty file, and
    a file that parses to a graph carrying no SKOS content at all, both refused rather than
    importing an empty vocabulary. The two new fixtures are built under ``tmp_path``, not
    committed to ``tests/fixtures/skos/``, per decisions.md D11's own precedent."""

    _NOT_SKOS_MESSAGE = (
        "declares no vocabulary of its own, and no target vocabulary was named"
    )

    def test_a_source_declaring_no_concept_scheme_is_refused_as_not_skos(self, db):
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "import_skos",
                str(FIXTURES / "no_scheme_declared.ttl"),
                stdout=StringIO(),
            )
        assert self._NOT_SKOS_MESSAGE in str(exc_info.value)
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0

    def test_an_empty_file_is_refused_rather_than_importing_an_empty_vocabulary(
        self, db, tmp_path
    ):
        empty = tmp_path / "empty.ttl"
        empty.write_text("")
        with pytest.raises(CommandError) as exc_info:
            call_command("import_skos", str(empty), stdout=StringIO())
        assert self._NOT_SKOS_MESSAGE in str(exc_info.value)
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
        assert self._NOT_SKOS_MESSAGE in str(exc_info.value)
        assert exc_info.value.returncode != 0
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandSafetyScanRefusalReachedFromBothSourceForms:
    """T021, spec US-5 Acceptance Scenario 2 — a source the safety scan refuses is refused
    with that reason and nothing parses further, proven from a filesystem path and from a
    URL served over ``http_stub`` (T006), no real network call either way. Reinstates the
    same measured fixtures ``test_exchange/test_skos.py`` already proves are wired to the
    scan (``entity_bomb.rdf``, ``remote_context_string.jsonld``), surfaced through the
    command rather than re-detected."""

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
    """T021, spec Edge Cases — a source declaring more than one concept scheme is already
    refused by the importer (test_exchange/test_skos.py
    ``TestChoosingBetweenDeclaredVocabularies``); the command surfaces that refusal
    unchanged rather than reinterpreting it."""

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
    """T022, FR-012, decisions.md D5, spec US-5 Acceptance Scenario 4 — a run that stores the
    vocabulary exits zero however much it set aside, because that is the bit a deployment
    script reads. ``call_command`` bypasses ``Command.run_from_argv`` entirely (it calls
    ``execute()`` directly), so it never exercises the one call site — Django's own, inside
    ``except CommandError`` — that turns a refusal's ``returncode`` into ``sys.exit``. This
    test goes through ``run_from_argv`` instead, the real command-line entry point, so the
    assertion is on whether that call site fires, not merely on whether an exception was
    raised."""

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
        """The counterpart the assertion above needs to mean anything: were ``run_from_argv``
        to stop reaching ``sys.exit`` at all, ``assert_not_called`` would keep passing and say
        nothing. A refusal must fire it."""
        command = Command(stdout=StringIO(), stderr=StringIO())
        with mock.patch("sys.exit") as mock_exit:
            command.run_from_argv(
                ["manage.py", "import_skos", str(FIXTURES / "no_scheme_declared.ttl")]
            )
        mock_exit.assert_called_once()
        assert mock_exit.call_args.args[0] != 0
        assert ConceptScheme.objects.count() == 0


class TestImportSkosCommandCarriesVerbosityIntoTheRenderer:
    """Convergence (T018, FR-007, `decisions.md` D6/D18) — ``ReportRenderer`` gates per-entry
    set-aside detail on a ``verbosity`` argument, and Django's own ``--verbosity`` is what was
    specified to carry it. T019, deleted at planning as redundant, was the task that wired the
    renderer into ``handle()``; the wiring of this argument went with it, and T018's tests
    construct the renderer directly, so nothing proved the option reached it. These do."""

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
    """CORR-002 (review, correctness) — ``handle()``'s ``finally: resolver.cleanup()`` was
    the only guarantee that a fetched document's temporary file is removed, and nothing at
    the command level checked it.

    Every existing cleanup assertion lives in ``tests/test_management/test_sources.py``,
    where the test body calls ``resolver.cleanup()`` itself — so they prove the resolver
    can clean up, not that the command does. Moving the call out of the ``finally`` and
    into the success path left the whole suite green while every refused URL import leaked
    a file of up to the byte ceiling.

    Both paths are pinned here because they fail differently: the success path leaks on a
    misplaced call, the raise path leaks only when the ``finally`` itself is lost.
    """

    @staticmethod
    def _watch_temp_paths(monkeypatch):
        """Record the temp path of every resolver the command builds, then clean up as
        usual — the path is private to the resolver and gone by the time the command
        returns, so it has to be captured as it happens."""
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
        # The fetch succeeds and the import is what fails, so the file exists at the moment
        # the refusal is raised — the case a cleanup outside the finally would leak.
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
        # The control: cleanup is a no-op for a path source, and the file the operator
        # named is theirs, not a temporary the command may remove.
        seen = self._watch_temp_paths(monkeypatch)
        call_command("import_skos", str(FIXTURES / "rocks.ttl"), stdout=StringIO())
        assert seen == []
        assert (FIXTURES / "rocks.ttl").exists()
