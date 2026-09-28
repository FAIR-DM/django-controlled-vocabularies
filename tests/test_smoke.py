"""Smoke tests that the package's runtime dependencies import."""

from django.apps import apps


class TestDjangoTomselectDependency:
    # Compatibility is pinned to names, not a version (Article VIII), so a renamed
    # symbol fails here rather than later at form render.
    def test_app_is_installed(self):
        assert apps.is_installed("django_tomselect")

    def test_autocomplete_model_view_is_importable(self):
        from django_tomselect.autocompletes import AutocompleteModelView

        assert AutocompleteModelView is not None

    def test_tomselect_model_choice_field_is_importable(self):
        from django_tomselect.forms import TomSelectModelChoiceField

        assert TomSelectModelChoiceField is not None

    def test_tomselect_model_multiple_choice_field_is_importable(self):
        from django_tomselect.forms import TomSelectModelMultipleChoiceField

        assert TomSelectModelMultipleChoiceField is not None
