"""Tests for the test project's URL wiring of ``controlled_vocabularies.urls`` (T002, FR-002).

The package's own ``urls.py`` is included under a non-empty prefix chosen by this
test project (``widget/``), never at the root, because a root inclusion would
never catch a hard-coded path in the widget's ``url`` argument. The prefix is
deliberately unrelated to the app's own name, so nothing can match by accident.
"""

import json

import pytest
from django.test import Client
from django.urls import reverse


class TestConceptAutocompleteUrl:
    """The endpoint reverses under its project-chosen prefix and answers anonymously."""

    def test_reverses_under_the_project_chosen_prefix(self):
        assert (
            reverse("controlled_vocabularies:concept-autocomplete")
            == "/widget/concepts/"
        )

    @pytest.mark.django_db
    def test_anonymous_get_returns_200_with_the_expected_json_shape(self):
        response = Client().get(reverse("controlled_vocabularies:concept-autocomplete"))

        assert response.status_code == 200
        body = json.loads(response.content)
        assert "results" in body
        assert "page" in body
        assert "has_more" in body
