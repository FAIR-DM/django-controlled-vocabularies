"""Tests for :mod:`controlled_vocabularies.ui.checks` (T005)."""

import sys

from django.core import checks as django_checks
from django.test import override_settings

from controlled_vocabularies.ui.checks import (
    CHECK_ID,
    CHECK_ID_ROUTE_MISMATCH,
    check_mvp_installed,
    check_vocabulary_detail_route,
)


class TestCheckMVPInstalled:
    """FR-012's neighbour: a project that forgets the ``ui`` extra learns so at
    ``manage.py check``, naming both the extra to install and the app that requires it, rather
    than from a bare ``ModuleNotFoundError: mvp`` raised from URL loading."""

    def test_reports_nothing_when_mvp_is_importable(self):
        assert check_mvp_installed(None) == []

    def test_reports_one_error_naming_the_extra_and_the_app_when_mvp_is_absent(
        self, monkeypatch
    ):
        # ``mvp`` is genuinely installed in this environment (the ``ui`` extra is a dev
        # dependency of this repo's own test run) — sys.modules["mvp"] = None is the standard
        # way to make a real ``import mvp`` statement raise ImportError regardless, without
        # touching the module the rest of the suite already has loaded.
        monkeypatch.setitem(sys.modules, "mvp", None)

        errors = check_mvp_installed(None)

        assert len(errors) == 1
        error = errors[0]
        assert isinstance(error, django_checks.Error)
        assert error.id == CHECK_ID
        message = str(error.msg)
        assert "django-controlled-vocabularies[ui]" in message
        assert "controlled_vocabularies.ui" in message

    def test_reported_object_is_an_error_not_a_warning(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "mvp", None)

        errors = check_mvp_installed(None)

        assert errors
        for error in errors:
            assert isinstance(error, django_checks.Error)


class TestCheckVocabularyDetailRoute:
    """FR-004's precondition, Article IX (T005): a vocabulary's identifier only leads to its
    page when the browsing routes are mounted where the configured base address says they are.
    """

    def test_reports_nothing_when_the_mount_and_the_base_address_agree(self):
        # No override: the test project's own configuration is the agreeing case
        # (tests/urls.py mounts the browsing routes at the path
        # CONTROLLED_VOCABULARIES_BASE_URI names), so this asserts the check stays silent
        # against a correctly wired project rather than against a contrivance.
        assert check_vocabulary_detail_route(None) == []

    @override_settings(CONTROLLED_VOCABULARIES_BASE_URI="http://localhost:8000/browse")
    def test_reports_a_warning_naming_its_own_id_when_they_disagree(self):
        # The test settings mount the browsing routes at /vocabularies/ (tests/urls.py)
        # while this override points the base address at /browse — the same disagreement
        # the demonstration itself ships with until T006.
        warnings = check_vocabulary_detail_route(None)

        assert len(warnings) == 1
        warning = warnings[0]
        assert isinstance(warning, django_checks.Warning)
        assert warning.id == CHECK_ID_ROUTE_MISMATCH

    @override_settings(ROOT_URLCONF="tests.urls_core")
    def test_reports_nothing_when_the_routes_are_not_mounted_at_all(self):
        # tests.urls_core is the empty URLconf tests/test_ui/test_boot.py already uses to
        # prove the core-only settings module stays free of the ui app's URLs — a project
        # that has installed the app but not yet wired its URLs gets silence here, not a
        # traceback.
        assert check_vocabulary_detail_route(None) == []
