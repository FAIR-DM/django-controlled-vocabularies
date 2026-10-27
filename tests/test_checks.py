"""Tests for controlled_vocabularies.checks."""

import ast
import inspect
import io
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from django import forms
from django.conf import settings
from django.core import checks as django_checks
from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from controlled_vocabularies import checks as checks_module
from controlled_vocabularies.checks import (
    CHECK_ID,
    CHECK_ID_MISSING_INSTALLED_APP,
    CHECK_ID_MISSING_MIDDLEWARE,
    CHECK_ID_MISSING_RESTRICTION_TARGET,
    CHECK_ID_MISSING_ROUTE,
    TOMSELECT_MIDDLEWARE,
    check_concept_autocomplete_route_included,
    check_concept_field_restriction_targets,
    check_concept_field_vocabularies,
    check_django_tomselect_installed,
    check_tomselect_middleware_installed,
)
from controlled_vocabularies.models import Record
from tests.factories import ConceptSchemeFactory, RecordFactory, collection_with_members
from tests.i18n_sweep import visit_fields_checks_source
from tests.testapp.models import CORE_SAMPLES, IGNEOUS, MINERAL, ROCK_TYPE, Specimen

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_django_admin(
    *args: str, settings: str = "tests.settings"
) -> subprocess.CompletedProcess:
    """Run ``django-admin`` in a fresh subprocess against a never-migrated database.

    The database is a brand-new in-memory sqlite one, the state the first ``migrate`` on a
    real install runs the checks against. A subprocess is the only way to run under a
    different ``INSTALLED_APPS`` (docs/adr/0013-the-django-admin-stays-an-optional-dependency.md).

    Args:
        *args: The arguments to ``django-admin``.
        settings: The settings module to run under.

    Returns:
        The completed process, with its output captured.
    """
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": settings}
    uv = shutil.which("uv")
    assert uv is not None, "uv must be on PATH to run this test"
    return subprocess.run(  # noqa: S603 — fixed argv, no untrusted input
        [uv, "run", "django-admin", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.django_db
class TestCheckConceptFieldVocabularies:
    def test_warns_about_a_field_whose_vocabulary_is_absent(self):
        warnings = check_concept_field_vocabularies(None)
        by_field = {(w.obj.model._meta.label, w.obj.name): w for w in warnings}
        assert ("testapp.Specimen", "rock_type") in by_field
        message = str(by_field[("testapp.Specimen", "rock_type")].msg)
        assert "testapp.Specimen" in message
        assert "rock_type" in message
        assert ROCK_TYPE.uri in message

    def test_reports_nothing_once_every_named_vocabulary_exists(self):
        ConceptSchemeFactory(name="Rock Type")
        ConceptSchemeFactory(name="Mineral")
        ConceptSchemeFactory(name="Era")

        warnings = check_concept_field_vocabularies(None)

        assert warnings == []

    def test_reported_objects_are_warnings_not_errors(self):
        warnings = check_concept_field_vocabularies(None)

        assert warnings
        for warning in warnings:
            assert isinstance(warning, django_checks.Warning)
            assert warning.id == CHECK_ID

    def test_reports_only_the_absent_vocabulary_when_a_concept_field_names_several(
        self,
    ):
        ConceptSchemeFactory(name="Rock Type")

        warnings = check_concept_field_vocabularies(None)

        matches = [
            w
            for w in warnings
            if w.obj.model._meta.label == "testapp.Borehole"
            and w.obj.name == "dominant_material"
        ]
        assert len(matches) == 1
        message = str(matches[0].msg)
        assert MINERAL.uri in message
        assert ROCK_TYPE.uri not in message

    def test_never_reports_a_concept_field_naming_no_vocabulary(self):
        assert [
            w
            for w in check_concept_field_vocabularies(None)
            if w.obj.model._meta.label == "testapp.Sketch"
        ] == []

        ConceptSchemeFactory(name="Rock Type")
        ConceptSchemeFactory(name="Mineral")

        assert [
            w
            for w in check_concept_field_vocabularies(None)
            if w.obj.model._meta.label == "testapp.Sketch"
        ] == []

    def test_costs_one_query_however_many_fields_are_declared(self):
        with CaptureQueriesContext(connection) as ctx:
            check_concept_field_vocabularies(None)

        assert len(ctx.captured_queries) == 1


@pytest.mark.django_db
class TestCheckMultiConceptFieldVocabularies:
    def test_warns_about_a_multi_concept_field_whose_vocabulary_is_absent(self):
        warnings = check_concept_field_vocabularies(None)

        matches = [
            w
            for w in warnings
            if w.obj.model._meta.label == "testapp.Deposit"
            and w.obj.name == "rock_types"
        ]
        assert len(matches) == 1
        message = str(matches[0].msg)
        assert "testapp.Deposit" in message
        assert "rock_types" in message
        assert ROCK_TYPE.uri in message

    def test_reports_nothing_once_the_multi_concept_fields_vocabulary_exists(self):
        ConceptSchemeFactory(name="Rock Type")

        warnings = check_concept_field_vocabularies(None)

        matches = [
            w
            for w in warnings
            if w.obj.model._meta.label == "testapp.Deposit"
            and w.obj.name == "rock_types"
        ]
        assert matches == []

    def test_reports_both_field_types_when_one_model_declares_both_against_one_absent_vocabulary(
        self,
    ):
        warnings = check_concept_field_vocabularies(None)

        matches = {
            w.obj.name
            for w in warnings
            if w.obj.model._meta.label == "testapp.RockSample"
        }
        assert matches == {"primary_mineral", "associated_minerals"}

    def test_reports_only_the_absent_vocabulary_when_a_field_names_several(self):
        ConceptSchemeFactory(name="Rock Type")

        warnings = check_concept_field_vocabularies(None)

        matches = [
            w
            for w in warnings
            if w.obj.model._meta.label == "testapp.FieldNote"
            and w.obj.name == "keywords"
        ]
        assert len(matches) == 1
        message = str(matches[0].msg)
        assert MINERAL.uri in message
        assert ROCK_TYPE.uri not in message

    def test_never_reports_a_field_naming_no_vocabulary(self):
        warnings = check_concept_field_vocabularies(None)

        matches = [
            w for w in warnings if w.obj.model._meta.label == "testapp.Photograph"
        ]
        assert matches == []

    def test_never_reports_a_field_naming_no_vocabulary_even_once_others_exist(self):
        ConceptSchemeFactory(name="Rock Type")
        ConceptSchemeFactory(name="Mineral")

        warnings = check_concept_field_vocabularies(None)

        matches = [
            w for w in warnings if w.obj.model._meta.label == "testapp.Photograph"
        ]
        assert matches == []

    def test_costs_one_query_when_a_field_names_several_vocabularies(self):
        with CaptureQueriesContext(connection) as ctx:
            check_concept_field_vocabularies(None)

        assert len(ctx.captured_queries) == 1


@pytest.mark.django_db
class TestCheckConceptFieldRestrictionTargets:
    def test_warns_about_an_absent_collection_target(self):
        warnings = check_concept_field_restriction_targets(None)

        by_field = {(w.obj.model._meta.label, w.obj.name): w for w in warnings}
        assert ("testapp.CoreSample", "rock_type") in by_field
        message = str(by_field[("testapp.CoreSample", "rock_type")].msg)
        assert CORE_SAMPLES in message
        assert ROCK_TYPE.uri in message

    def test_reports_nothing_once_every_named_target_exists(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core samples", labels=())

        warnings = check_concept_field_restriction_targets(None)

        assert [
            w
            for w in warnings
            if w.obj.model._meta.label in {"testapp.CoreSample", "testapp.DrillCore"}
        ] == []

    def test_an_ordered_collection_satisfies_the_target(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(
            scheme=scheme, name="Core samples", labels=(), ordered=True
        )

        warnings = check_concept_field_restriction_targets(None)

        assert [
            w for w in warnings if w.obj.model._meta.label == "testapp.CoreSample"
        ] == []

    def test_a_concept_sharing_the_slug_does_not_satisfy_the_target(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        concept = RecordFactory(scheme=scheme, label="Core samples")
        assert concept.slug == "core-samples"
        assert concept.type == Record.Type.CONCEPT

        warnings = check_concept_field_restriction_targets(None)

        matches = [
            w for w in warnings if w.obj.model._meta.label == "testapp.CoreSample"
        ]
        assert len(matches) == 1

    def test_resolves_on_the_vocabulary_and_target_pair_not_a_flat_set_of_slugs(self):
        other_scheme = ConceptSchemeFactory(name="Mineral")
        collection_with_members(scheme=other_scheme, name="Core samples", labels=())

        warnings = check_concept_field_restriction_targets(None)

        matches = [
            w
            for w in warnings
            if w.obj.model._meta.label == "testapp.CoreSample"
            and w.obj.name == "rock_type"
        ]
        assert len(matches) == 1

    def test_reported_objects_are_warnings_not_errors(self):
        warnings = check_concept_field_restriction_targets(None)

        assert warnings
        for warning in warnings:
            assert isinstance(warning, django_checks.Warning)
            assert warning.id == CHECK_ID_MISSING_RESTRICTION_TARGET

    def test_costs_one_query_however_many_fields_are_declared(self):
        with CaptureQueriesContext(connection) as ctx:
            check_concept_field_restriction_targets(None)

        assert len(ctx.captured_queries) == 1


@pytest.mark.django_db
class TestCheckConceptFieldRestrictionTargetsStaysQuietWhenItShould:
    def test_a_collection_that_exists_and_holds_no_members_is_not_reported(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        collection_with_members(scheme=scheme, name="Core samples", labels=())

        warnings = check_concept_field_restriction_targets(None)

        matches = [
            w
            for w in warnings
            if w.obj.model._meta.label == "testapp.CoreSample"
            and w.obj.name == "rock_type"
        ]
        assert matches == []

    def test_silencing_the_check_id_suppresses_it(self):
        stderr = io.StringIO()
        call_command("check", stderr=stderr)
        assert CHECK_ID_MISSING_RESTRICTION_TARGET in stderr.getvalue()

        stderr = io.StringIO()
        with override_settings(
            SILENCED_SYSTEM_CHECKS=[CHECK_ID_MISSING_RESTRICTION_TARGET]
        ):
            call_command("check", stderr=stderr)
        assert CHECK_ID_MISSING_RESTRICTION_TARGET not in stderr.getvalue()


@pytest.mark.django_db
class TestCheckConceptFieldBranchRoots:
    def branch_warnings(self):
        return [
            w
            for w in check_concept_field_restriction_targets(None)
            if w.obj.model._meta.label
            in {"testapp.IgneousSample", "testapp.IgneousLog"}
        ]

    def test_warns_about_a_branch_root_that_is_missing(self):
        warnings = self.branch_warnings()

        by_field = {(w.obj.model._meta.label, w.obj.name): w for w in warnings}
        assert set(by_field) == {
            ("testapp.IgneousSample", "rock_type"),
            ("testapp.IgneousLog", "rock_types"),
        }
        message = str(by_field[("testapp.IgneousSample", "rock_type")].msg)
        assert "testapp.IgneousSample" in message
        assert "rock_type" in message
        assert IGNEOUS in message
        assert ROCK_TYPE.uri in message

    def test_reports_nothing_once_the_root_exists_with_nothing_below_it(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        RecordFactory(scheme=scheme, label="Igneous")

        assert self.branch_warnings() == []

    def test_a_collection_with_the_roots_address_does_not_satisfy_it(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        RecordFactory(scheme=scheme, uri=IGNEOUS, type=Record.Type.COLLECTION)

        assert len(self.branch_warnings()) == 2

    def test_a_root_held_by_another_vocabulary_does_not_satisfy_it(self):
        ConceptSchemeFactory(name="Rock Type")
        RecordFactory(scheme=ConceptSchemeFactory(name="Mineral"), uri=IGNEOUS)

        assert len(self.branch_warnings()) == 2

    def test_reported_objects_are_warnings_under_the_restriction_target_id(self):
        warnings = self.branch_warnings()

        assert warnings
        for warning in warnings:
            assert isinstance(warning, django_checks.Warning)
            assert warning.id == CHECK_ID_MISSING_RESTRICTION_TARGET

    def test_costs_one_query_however_many_fields_are_declared(self):
        with CaptureQueriesContext(connection) as ctx:
            check_concept_field_restriction_targets(None)

        assert len(ctx.captured_queries) == 1


class TestCheckRestrictionTargetsSurvivesUnmigratedDatabase:
    def test_check_reports_nothing_against_an_unmigrated_connection(self):
        result = run_django_admin("check")

        assert result.returncode == 0, result.stderr
        assert CHECK_ID_MISSING_RESTRICTION_TARGET not in result.stdout
        assert "System check identified no issues" in result.stdout


_MIGRATE_CHECK_MAKEMIGRATIONS_MIGRATE_WITH_ABSENT_TARGETS = """
from django.core.management import call_command

from controlled_vocabularies.checks import check_concept_field_restriction_targets

call_command("migrate", verbosity=0)

# Non-vacuous: the tables exist and hold none of the restriction targets, so the check
# must have something to report.
warnings = check_concept_field_restriction_targets(None)
assert warnings, "expected W005 to report the absent restriction targets once the tables exist"

call_command("check")
call_command("makemigrations", check=True, dry_run=True)
call_command("migrate", verbosity=0)
print("ALL_SUCCEEDED")
"""


class TestNothingAboutAnAbsentRestrictionTargetStopsTheProject:
    def test_check_makemigrations_and_migrate_all_succeed_with_every_target_absent(
        self,
    ):
        result = run_django_admin(
            "shell",
            "--no-startup",
            "--no-imports",
            "-c",
            _MIGRATE_CHECK_MAKEMIGRATIONS_MIGRATE_WITH_ABSENT_TARGETS,
        )

        assert result.returncode == 0, result.stderr
        assert "ALL_SUCCEEDED" in result.stdout


class TestCheckSurvivesUnmigratedDatabase:
    def test_check_reports_nothing_against_an_unmigrated_connection(self):
        result = run_django_admin("check")

        assert result.returncode == 0, result.stderr
        assert CHECK_ID not in result.stdout
        assert "System check identified no issues" in result.stdout

    def test_makemigrations_succeeds_against_an_unmigrated_connection(self):
        result = run_django_admin("makemigrations", "--check", "--dry-run")

        assert result.returncode == 0, result.stderr

    def test_migrate_succeeds_against_an_unmigrated_connection(self):
        result = run_django_admin("migrate", "--no-input")

        assert result.returncode == 0, result.stderr

    @pytest.mark.django_db
    def test_silencing_the_check_id_suppresses_it(self):
        stderr = io.StringIO()
        call_command("check", stderr=stderr)
        assert CHECK_ID in stderr.getvalue()

        stderr = io.StringIO()
        with override_settings(SILENCED_SYSTEM_CHECKS=[CHECK_ID]):
            call_command("check", stderr=stderr)
        assert CHECK_ID not in stderr.getvalue()

    @pytest.mark.django_db
    def test_form_offers_no_choices_and_does_not_raise_when_vocabulary_absent(self):
        class SpecimenForm(forms.ModelForm):
            class Meta:
                model = Specimen
                fields = ["name", "rock_type"]

        form = SpecimenForm()

        assert list(form.fields["rock_type"].queryset) == []


class TestCheckConceptAutocompleteRouteIncluded:
    def test_warns_when_the_route_is_not_included(self):
        with override_settings(ROOT_URLCONF=()):
            warnings = check_concept_autocomplete_route_included(None)

        assert len(warnings) == 1
        warning = warnings[0]
        assert warning.id == CHECK_ID_MISSING_ROUTE
        message = f"{warning.msg} {warning.hint}"
        assert "controlled_vocabularies.urls" in message

    def test_absent_when_the_route_is_included(self):
        warnings = check_concept_autocomplete_route_included(None)

        assert warnings == []

    def test_reported_objects_are_warnings_not_errors(self):
        with override_settings(ROOT_URLCONF=()):
            warnings = check_concept_autocomplete_route_included(None)

        assert warnings
        for warning in warnings:
            assert isinstance(warning, django_checks.Warning)

    @pytest.mark.django_db
    def test_runs_without_touching_the_database(self, django_assert_num_queries):
        with override_settings(ROOT_URLCONF=()), django_assert_num_queries(0):
            check_concept_autocomplete_route_included(None)


class TestCheckDjangoTomselectInstalled:
    def test_warns_when_django_tomselect_is_not_installed(self):
        installed = [
            app for app in settings.INSTALLED_APPS if app != "django_tomselect"
        ]
        with override_settings(INSTALLED_APPS=installed):
            warnings = check_django_tomselect_installed(None)

        assert len(warnings) == 1
        warning = warnings[0]
        assert warning.id == CHECK_ID_MISSING_INSTALLED_APP
        message = f"{warning.msg} {warning.hint}"
        assert "django_tomselect" in message

    def test_absent_when_django_tomselect_is_installed(self):
        warnings = check_django_tomselect_installed(None)

        assert warnings == []

    def test_reported_objects_are_warnings_not_errors(self):
        installed = [
            app for app in settings.INSTALLED_APPS if app != "django_tomselect"
        ]
        with override_settings(INSTALLED_APPS=installed):
            warnings = check_django_tomselect_installed(None)

        assert warnings
        for warning in warnings:
            assert isinstance(warning, django_checks.Warning)

    @pytest.mark.django_db
    def test_runs_without_touching_the_database(self, django_assert_num_queries):
        with django_assert_num_queries(0):
            check_django_tomselect_installed(None)


@pytest.mark.django_db
class TestBothWiringChecksReachManageCheck:
    def test_the_missing_route_is_reported_by_manage_check(self):
        stderr = io.StringIO()
        with override_settings(ROOT_URLCONF=()):
            call_command("check", stderr=stderr)

        assert CHECK_ID_MISSING_ROUTE in stderr.getvalue()

    def test_the_missing_route_is_absent_from_manage_check_once_included(self):
        stderr = io.StringIO()
        call_command("check", stderr=stderr)

        assert CHECK_ID_MISSING_ROUTE not in stderr.getvalue()

    def test_the_missing_installed_app_is_reported_by_manage_check(self):
        installed = [
            app for app in settings.INSTALLED_APPS if app != "django_tomselect"
        ]
        stderr = io.StringIO()
        with override_settings(INSTALLED_APPS=installed):
            call_command("check", stderr=stderr)

        assert CHECK_ID_MISSING_INSTALLED_APP in stderr.getvalue()

    def test_the_missing_installed_app_is_absent_from_manage_check_once_installed(self):
        stderr = io.StringIO()
        call_command("check", stderr=stderr)

        assert CHECK_ID_MISSING_INSTALLED_APP not in stderr.getvalue()


class TestCheckTomselectMiddlewareInstalled:
    def test_warns_when_the_middleware_is_not_installed(self):
        with override_settings(MIDDLEWARE=[]):
            warnings = check_tomselect_middleware_installed(None)

        assert len(warnings) == 1
        warning = warnings[0]
        assert warning.id == CHECK_ID_MISSING_MIDDLEWARE
        message = f"{warning.msg} {warning.hint}"
        assert "django_tomselect.middleware.TomSelectMiddleware" in message

    def test_absent_when_the_middleware_is_installed(self):
        warnings = check_tomselect_middleware_installed(None)

        assert warnings == []

    def test_reported_objects_are_warnings_not_errors(self):
        with override_settings(MIDDLEWARE=[]):
            warnings = check_tomselect_middleware_installed(None)

        assert warnings
        for warning in warnings:
            assert isinstance(warning, django_checks.Warning)

    @pytest.mark.django_db
    def test_runs_without_touching_the_database(self, django_assert_num_queries):
        with override_settings(MIDDLEWARE=[]), django_assert_num_queries(0):
            check_tomselect_middleware_installed(None)


@pytest.mark.django_db
class TestTheMiddlewareCheckReachesManageCheck:
    def test_the_missing_middleware_is_reported_by_manage_check(self):
        # Drop only this entry, not the whole list: the admin's own checks refuse an
        # empty MIDDLEWARE and would abort the command before the assertion.
        remaining = [m for m in settings.MIDDLEWARE if m != TOMSELECT_MIDDLEWARE]
        stderr = io.StringIO()
        with override_settings(MIDDLEWARE=remaining):
            call_command("check", stderr=stderr)

        assert CHECK_ID_MISSING_MIDDLEWARE in stderr.getvalue()

    def test_the_missing_middleware_is_absent_from_manage_check_once_installed(self):
        stderr = io.StringIO()
        call_command("check", stderr=stderr)

        assert CHECK_ID_MISSING_MIDDLEWARE not in stderr.getvalue()


_RENDER_FORM_AND_CHECK_ADMIN_UNIMPORTED = """
import sys

from django import forms

from tests.testapp.models import CORE_SAMPLES, MINERAL, ROCK_TYPE, Specimen


class SpecimenForm(forms.ModelForm):
    class Meta:
        model = Specimen
        fields = ["name", "rock_type"]


str(SpecimenForm())

assert "django.contrib.admin" not in sys.modules, sorted(sys.modules)
print("ADMIN_NOT_IMPORTED")
"""


class TestProjectWithoutTheAdminIsUnaffected:
    def test_check_is_as_clean_without_the_admin_as_it_is_with_it(self):
        result = run_django_admin("check", settings="tests.settings_no_admin")

        assert result.returncode == 0, result.stderr
        assert "System check identified no issues" in result.stdout
        for check_id in (
            CHECK_ID,
            CHECK_ID_MISSING_ROUTE,
            CHECK_ID_MISSING_INSTALLED_APP,
            CHECK_ID_MISSING_MIDDLEWARE,
        ):
            assert check_id not in result.stdout

    def test_django_contrib_admin_never_reaches_sys_modules_after_a_form_renders(self):
        result = run_django_admin(
            "shell",
            "--no-startup",
            "--no-imports",
            "-c",
            _RENDER_FORM_AND_CHECK_ADMIN_UNIMPORTED,
            settings="tests.settings_no_admin",
        )

        assert result.returncode == 0, result.stderr
        assert "ADMIN_NOT_IMPORTED" in result.stdout

    def test_controlled_vocabularies_admin_registers_nothing_with_the_default_site(
        self, settings
    ):
        from django.contrib import admin as django_admin

        assert "django.contrib.admin" in settings.INSTALLED_APPS
        registered_app_labels = {
            model._meta.app_label for model in django_admin.site._registry
        }
        assert "controlled_vocabularies" not in registered_app_labels


def translation_call_string_literals(func) -> list[str]:
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

    class LiteralCollector(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name) and node.func.id in {
                "_",
                "gettext_lazy",
            }:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        literals.append(arg.value)
            self.generic_visit(node)

    LiteralCollector().visit(tree)
    return literals


class TestW005MessagesAreStaticWithNamedPlaceholders:
    def test_none_of_them_carries_a_positional_placeholder(self):
        literals = translation_call_string_literals(
            checks_module.check_concept_field_restriction_targets
        )

        assert literals, "expected the W005 messages to be found at all"
        for literal in literals:
            assert "%s" not in literal
            assert "%d" not in literal

    def test_the_message_carries_the_four_named_placeholders(self):
        literals = translation_call_string_literals(
            checks_module.check_concept_field_restriction_targets
        )

        messages = [literal for literal in literals if "%(target)s" in literal]
        assert len(messages) == 1
        assert "%(model)s" in messages[0]
        assert "%(field)s" in messages[0]
        assert "%(vocabulary)s" in messages[0]

    def test_the_branch_message_carries_the_four_named_placeholders(self):
        literals = translation_call_string_literals(
            checks_module.check_concept_field_restriction_targets
        )

        messages = [literal for literal in literals if "%(root)s" in literal]
        assert len(messages) == 1
        assert "%(model)s" in messages[0]
        assert "%(field)s" in messages[0]
        assert "%(vocabulary)s" in messages[0]


class TestChecksI18nSweep:
    def test_module_carries_no_bare_user_visible_literal(self):
        source = Path(inspect.getfile(checks_module)).read_text()
        visitor = visit_fields_checks_source(source)
        assert visitor.bare_literals == [], (
            f"{checks_module.__name__} passes a bare, untranslated literal to a user-visible sink: {visitor.bare_literals}"
        )
        assert visitor.positional_placeholders == [], (
            f"{checks_module.__name__} passes a positional placeholder to a translation call: "
            f"{visitor.positional_placeholders}"
        )
