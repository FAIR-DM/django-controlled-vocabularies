"""Tests for controlled_vocabularies.ui.checks."""

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
    def test_reports_nothing_when_mvp_is_importable(self):
        assert check_mvp_installed(None) == []

    def test_reports_one_error_naming_the_extra_and_the_app_when_mvp_is_absent(
        self, monkeypatch
    ):
        # mvp is installed here; a None entry in sys.modules makes ``import mvp`` raise
        # ImportError without unloading the module the rest of the suite uses.
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
    def test_reports_nothing_when_the_mount_and_the_base_address_agree(self):
        # No override: tests/urls.py mounts the routes where CONTROLLED_VOCABULARIES_BASE_URI
        # points, so this is the correctly wired case.
        assert check_vocabulary_detail_route(None) == []

    @override_settings(CONTROLLED_VOCABULARIES_BASE_URI="http://localhost:8000/browse")
    def test_reports_a_warning_naming_its_own_id_when_they_disagree(self):
        # tests/urls.py mounts the routes at /vocabularies/; the override points at /browse.
        warnings = check_vocabulary_detail_route(None)

        assert len(warnings) == 1
        warning = warnings[0]
        assert isinstance(warning, django_checks.Warning)
        assert warning.id == CHECK_ID_ROUTE_MISMATCH

    @override_settings(ROOT_URLCONF="tests.urls_core")
    def test_reports_nothing_when_the_routes_are_not_mounted_at_all(self):
        # A project that installed the app but has not wired its URLs gets silence, not a
        # traceback.
        assert check_vocabulary_detail_route(None) == []
