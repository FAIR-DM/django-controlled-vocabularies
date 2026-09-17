"""Tests for :mod:`controlled_vocabularies.checks` (T008, T009)."""

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
from tests.factories import CollectionFactory, ConceptFactory, ConceptSchemeFactory
from tests.testapp.models import Specimen

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_django_admin(
    *args: str, settings: str = "tests.settings"
) -> subprocess.CompletedProcess:
    """Run ``django-admin`` in a fresh subprocess against a brand-new, never-migrated
    ``:memory:`` sqlite database (``tests/settings.py``'s ``DATABASES``) — the state
    the very first ``migrate`` on a real install runs the checks against (T009).

    ``settings`` defaults to today's module and is overridden by T014 to run against
    ``tests.settings_no_admin`` — proving the no-admin case needs a fresh interpreter
    with a different ``INSTALLED_APPS``, which only a subprocess can give (012
    decisions.md D13, D-T014)."""
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": settings}
    poetry = shutil.which("poetry")
    assert poetry is not None, "poetry must be on PATH to run this test"
    return subprocess.run(  # noqa: S603 — fixed argv, no untrusted input
        [poetry, "run", "django-admin", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.django_db
class TestCheckConceptFieldVocabularies:
    """T008 — the check walks every declared ``ConceptField`` and warns about the
    ones naming a vocabulary absent from the database."""

    def test_warns_about_a_field_whose_vocabulary_is_absent(self):
        warnings = check_concept_field_vocabularies(None)
        by_field = {(w.obj.model._meta.label, w.obj.name): w for w in warnings}
        assert ("testapp.Specimen", "rock_type") in by_field
        message = str(by_field[("testapp.Specimen", "rock_type")].msg)
        assert "testapp.Specimen" in message
        assert "rock_type" in message
        assert "rock-type" in message

    def test_reports_nothing_once_every_named_vocabulary_exists(self):
        ConceptSchemeFactory(name="Rock Type")
        ConceptSchemeFactory(name="Mineral")

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
        """#111 — the single-value field reaches the check the same way the
        many-valued one does, one warning per absent slug it names."""
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
        assert "mineral" in message
        assert "rock-type" not in message

    def test_never_reports_a_concept_field_naming_no_vocabulary(self):
        """#111 — a single-value field naming none names nothing that could be
        missing, so the check has nothing to say about it, before or after any
        vocabulary is imported."""
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
        # The test app declares several ConceptField and ConceptsField
        # instances (T010 widens the check to cover both) across a handful
        # of distinct vocabularies. However many slugs those fields name
        # between them, the distinct set is still resolved in one query.
        with CaptureQueriesContext(connection) as ctx:
            check_concept_field_vocabularies(None)

        assert len(ctx.captured_queries) == 1


@pytest.mark.django_db
class TestCheckConceptsFieldVocabularies:
    """T010 — the check widens to cover ``ConceptsField`` too (US-6, FR-003,
    FR-004, D9): a field naming several vocabularies contributes each slug it
    names, and a field naming none contributes nothing and is never warned
    about."""

    def test_warns_about_a_concepts_field_whose_vocabulary_is_absent(self):
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
        assert "rock-type" in message

    def test_reports_nothing_once_the_concepts_fields_vocabulary_exists(self):
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
        assert "mineral" in message
        assert "rock-type" not in message

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
    """T019 (FS-016 US-5, FR-009) — a new check walking every declared
    ``collection``, ``concepts`` and ``branch`` restriction, warning about the
    ones naming a target absent from the vocabulary the field itself names.
    ``CoreSample``/``DrillCore`` (collection), ``ChipSample``/``ChipTray``
    (concepts) and ``BranchSample``/``BranchTray`` (branch) all restrict to
    the "rock-type" vocabulary, so no vocabulary needs creating here — only
    the target rows this check is deciding are present or absent."""

    def test_warns_about_an_absent_collection_target(self):
        warnings = check_concept_field_restriction_targets(None)

        by_field = {(w.obj.model._meta.label, w.obj.name): w for w in warnings}
        assert ("testapp.CoreSample", "rock_type") in by_field
        message = str(by_field[("testapp.CoreSample", "rock_type")].msg)
        assert "core-samples" in message
        assert "rock-type" in message

    def test_warns_about_an_absent_concepts_target_naming_the_specific_slug(self):
        """A ten-item ``concepts`` list with one typo names the one missing
        slug, not the list — here a two-item list with one present."""
        scheme = ConceptSchemeFactory(name="Rock Type")
        ConceptFactory(scheme=scheme, label="Granite")

        warnings = check_concept_field_restriction_targets(None)

        matches = [
            w
            for w in warnings
            if w.obj.model._meta.label == "testapp.ChipSample"
            and w.obj.name == "rock_type"
        ]
        assert len(matches) == 1
        message = str(matches[0].msg)
        assert "basalt" in message
        assert "granite" not in message

    def test_warns_about_an_absent_branch_target(self):
        warnings = check_concept_field_restriction_targets(None)

        matches = [
            w for w in warnings if w.obj.model._meta.label == "testapp.BranchSample"
        ]
        assert len(matches) == 1
        message = str(matches[0].msg)
        assert "igneous" in message

    def test_reports_nothing_once_every_named_target_exists(self):
        scheme = ConceptSchemeFactory(name="Rock Type")
        CollectionFactory(scheme=scheme, name="Core samples")
        ConceptFactory(scheme=scheme, label="Granite")
        ConceptFactory(scheme=scheme, label="Basalt")
        ConceptFactory(scheme=scheme, label="Igneous")

        warnings = check_concept_field_restriction_targets(None)

        restricted_labels = {
            "testapp.CoreSample",
            "testapp.DrillCore",
            "testapp.ChipSample",
            "testapp.ChipTray",
            "testapp.BranchSample",
            "testapp.BranchTray",
        }
        assert [
            w for w in warnings if w.obj.model._meta.label in restricted_labels
        ] == []

    def test_resolves_on_the_vocabulary_and_target_pair_not_a_flat_set_of_slugs(self):
        """The one thing most likely to be got wrong (plan.md A6, decisions.md
        D7): a collection slug is unique only within its own scheme, so a
        collection named "core-samples" that exists in a *different*
        vocabulary ("mineral") must not be read as satisfying
        ``CoreSample.rock_type``'s restriction, which names "core-samples"
        within "rock-type". A flat set of existing collection slugs would
        wrongly consider this one present."""
        other_scheme = ConceptSchemeFactory(name="Mineral")
        CollectionFactory(scheme=other_scheme, name="Core samples")

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

    def test_costs_three_queries_however_many_fields_are_declared(self):
        # One batched query per target kind (collection, concepts, branch),
        # never one per field — the same batching check_concept_field_vocabularies
        # already uses, extended to the three restriction axes.
        with CaptureQueriesContext(connection) as ctx:
            check_concept_field_restriction_targets(None)

        assert len(ctx.captured_queries) == 3


@pytest.mark.django_db
class TestCheckConceptFieldRestrictionTargetsStaysQuietWhenItShould:
    """T020 (FS-016 US-5, FR-009) — the three silences, plus the one case W005
    must not be quiet for."""

    def test_a_collection_that_exists_and_holds_no_members_is_not_reported(self):
        """Present and empty is not missing (plan.md A6): a curator's
        legitimate, unpopulated collection is not a declaration error."""
        scheme = ConceptSchemeFactory(name="Rock Type")
        CollectionFactory(scheme=scheme, name="Core samples")

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

    def test_still_reports_a_target_whose_slug_exists_in_a_different_vocabulary(self):
        """The case this check exists to catch, on the concepts axis this
        time: a concept slug that only exists in a different vocabulary is
        still reported absent from the one the field names. "basalt" is made
        genuinely present in "rock-type" so the one surviving warning can
        only be about "granite"."""
        rock_type = ConceptSchemeFactory(name="Rock Type")
        ConceptFactory(scheme=rock_type, label="Basalt")
        other_scheme = ConceptSchemeFactory(name="Mineral")
        ConceptFactory(scheme=other_scheme, label="Granite")

        warnings = check_concept_field_restriction_targets(None)

        matches = [
            w
            for w in warnings
            if w.obj.model._meta.label == "testapp.ChipSample"
            and w.obj.name == "rock_type"
        ]
        assert len(matches) == 1
        message = str(matches[0].msg)
        assert "granite" in message


class TestCheckRestrictionTargetsSurvivesUnmigratedDatabase:
    """T020 — the check runs before ``migrate``, so it must survive a database
    with no tables rather than raising. Exercised against a genuinely
    unmigrated connection (a fresh subprocess, never-migrated ``:memory:``
    database), not a mock of ``DatabaseError`` — reproducing
    ``TestCheckSurvivesUnmigratedDatabase``'s own reasoning for this check's
    guard."""

    def test_check_reports_nothing_against_an_unmigrated_connection(self):
        result = _run_django_admin("check")

        assert result.returncode == 0, result.stderr
        assert CHECK_ID_MISSING_RESTRICTION_TARGET not in result.stdout
        assert "System check identified no issues" in result.stdout


_MIGRATE_CHECK_MAKEMIGRATIONS_MIGRATE_WITH_ABSENT_TARGETS = """
from django.core.management import call_command

from controlled_vocabularies.checks import check_concept_field_restriction_targets

call_command("migrate", verbosity=0)

# Non-vacuous: the tables now exist and hold none of the restriction targets
# CoreSample/ChipSample/BranchSample and friends name, so the check must
# actually have something to report at this point.
warnings = check_concept_field_restriction_targets(None)
assert warnings, "expected W005 to report the absent restriction targets once the tables exist"

call_command("check")
call_command("makemigrations", check=True, dry_run=True)
call_command("migrate", verbosity=0)
print("ALL_SUCCEEDED")
"""


class TestNothingAboutAnAbsentRestrictionTargetStopsTheProject:
    """T021 (FS-016 US-5) — FR-007 end to end for this feature: with every
    named restriction target absent, importing the models, ``makemigrations``
    and ``migrate`` all succeed. This is the assertion that would catch
    someone "helpfully" turning W005 into an ``Error`` or resolving a
    restriction target at declaration time."""

    def test_check_makemigrations_and_migrate_all_succeed_with_every_target_absent(
        self,
    ):
        result = _run_django_admin(
            "shell",
            "--no-startup",
            "--no-imports",
            "-c",
            _MIGRATE_CHECK_MAKEMIGRATIONS_MIGRATE_WITH_ABSENT_TARGETS,
        )

        assert result.returncode == 0, result.stderr
        assert "ALL_SUCCEEDED" in result.stdout


class TestCheckSurvivesUnmigratedDatabase:
    """T009 — the check runs before ``migrate``, so it must survive a database with
    no tables rather than raising. Exercised against a genuinely unmigrated
    connection (a fresh subprocess, never-migrated ``:memory:`` database), not a
    mock of ``DatabaseError`` (`plan.md` Risks, `research.md` R3)."""

    def test_check_reports_nothing_against_an_unmigrated_connection(self):
        result = _run_django_admin("check")

        assert result.returncode == 0, result.stderr
        assert CHECK_ID not in result.stdout
        assert "System check identified no issues" in result.stdout

    def test_makemigrations_succeeds_against_an_unmigrated_connection(self):
        result = _run_django_admin("makemigrations", "--check", "--dry-run")

        assert result.returncode == 0, result.stderr

    def test_migrate_succeeds_against_an_unmigrated_connection(self):
        result = _run_django_admin("migrate", "--no-input")

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
    """T008 — warns when the project has not included this package's URL
    configuration (FR-010, decisions.md D14). ``reverse()`` resolves entirely
    against the already-loaded URLconf, so this never touches the database."""

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
    """T008 — warns when ``django_tomselect`` is not among the project's
    installed applications (FR-010, decisions.md D10). ``apps.is_installed()``
    reads the already-loaded app registry, so this never touches the
    database."""

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
    """T008 — FR-010 promises the two wiring steps are *reported*, which a
    function nobody registered never does. Calling the check functions directly
    passes whether or not ``apps.ready()`` registers them, so these assert on
    what a project actually runs: ``manage.py check``."""

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
    """US-6 repair — the third wiring step (decisions.md D15). Without
    ``TomSelectMiddleware`` the widget renders an empty select carrying no
    control, and nothing raises, so this check is the only report of it.
    ``settings.MIDDLEWARE`` is read directly, so it never touches the database."""

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
    """US-6 repair — same reasoning as :class:`TestBothWiringChecksReachManageCheck`:
    a check nobody registered reports nothing, whatever it returns."""

    def test_the_missing_middleware_is_reported_by_manage_check(self):
        # Drop only the middleware under test rather than emptying the list: since
        # 012 T001 the test project installs django.contrib.admin, whose own checks
        # refuse an empty MIDDLEWARE and would abort the command before this
        # assertion (012 decisions.md D17). Isolating the one entry is also the
        # narrower test — it cannot pass for a reason other than the one it names.
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

from tests.testapp.models import Specimen


class SpecimenForm(forms.ModelForm):
    class Meta:
        model = Specimen
        fields = ["name", "rock_type"]


str(SpecimenForm())

assert "django.contrib.admin" not in sys.modules, sorted(sys.modules)
print("ADMIN_NOT_IMPORTED")
"""


class TestProjectWithoutTheAdminIsUnaffected:
    """T014 — FR-006, US-5 scenarios 1 and 2, SC-005: a project that never
    installs ``django.contrib.admin`` sees no change from this feature.

    ``tests/settings_no_admin.py`` mirrors ``tests/settings.py`` minus the
    admin app and its supporting middleware/apps (``decisions.md`` D13's
    reasoning extended to this story). Every assertion here runs against it
    in a fresh subprocess, via ``_run_django_admin``'s new ``settings``
    parameter — a single process' app registry and ``sys.modules`` are built
    once at startup, so nothing in-process can prove either absent.

    The two ``check`` tests mirror :class:`TestCheckSurvivesUnmigratedDatabase`'s
    already-clean baseline under ``tests.settings``: the no-admin
    configuration must report exactly as little, not merely something.

    The ``sys.modules`` assertion is deliberately not "``controlled_vocabularies.admin``
    is unimported" — ``forms.py`` calls its lookup on every render, so that
    module is imported whether or not the admin is installed (``decisions.md``
    D10). What FR-006 actually forbids is ``django.contrib.admin`` itself
    reaching ``sys.modules``, which is what the rendered form here is built to
    prove: the lookup runs, finds the admin not installed, and returns
    without importing it.
    """

    def test_check_is_as_clean_without_the_admin_as_it_is_with_it(self):
        result = _run_django_admin("check", settings="tests.settings_no_admin")

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
        result = _run_django_admin(
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
        """With the admin installed (``tests.settings``, this suite's default),
        ``controlled_vocabularies.admin`` still registers nothing — the module
        exists only to hold the lazy lookup (``decisions.md`` D10), never a
        ``@admin.register``."""
        from django.contrib import admin as django_admin

        assert "django.contrib.admin" in settings.INSTALLED_APPS
        registered_app_labels = {
            model._meta.app_label for model in django_admin.site._registry
        }
        assert "controlled_vocabularies" not in registered_app_labels
