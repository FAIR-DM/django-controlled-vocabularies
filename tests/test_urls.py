"""Tests for controlled_vocabularies.urls, as mounted by the test project."""

import json

import pytest
from django.test import Client
from django.urls import reverse


class TestConceptAutocompleteUrl:
    # The test project mounts the package under `widget/`, never the root, so a
    # hard-coded path in the widget's `url` argument would fail here (FS-011).
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
