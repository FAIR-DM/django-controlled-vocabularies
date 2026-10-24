"""Tests for controlled_vocabularies.ui.forms."""

import inspect
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from django.test import override_settings

from controlled_vocabularies.models import ConceptScheme
from controlled_vocabularies.ui import forms as forms_module
from controlled_vocabularies.ui.forms import VocabularyForm
from tests.factories import ConceptFactory, ConceptSchemeFactory
from tests.i18n_sweep import visit_fields_checks_source

DETAILS = {
    "description": "Rocks, sorted.",
    "default_language": "de",
    "publisher": "Geological Survey",
    "creator": "A. Curator",
    "license": "https://creativecommons.org/licenses/by/4.0/",
    "version": "1.2",
    "modified": "2026-03-01",
}


def error_codes(form, field):
    """Return the codes of a field's validation errors.

    Args:
        form: The validated form.
        field: The field name.

    Returns:
        The error codes, in order.
    """
    return [error.code for error in form.errors.as_data().get(field, [])]


@pytest.mark.django_db
class TestVocabularyFormCreate:
    def test_a_name_alone_is_valid_and_saves_without_an_identifier(self):
        form = VocabularyForm(data={"name": "Rock Types"})

        assert form.is_valid(), form.errors
        vocabulary = form.save()
        assert vocabulary.pk
        assert vocabulary.static_uri is None
        assert vocabulary.slug == "rock-types"

    def test_every_detail_given_is_saved(self):
        form = VocabularyForm(data={"name": "Rock Types", **DETAILS})

        assert form.is_valid(), form.errors
        vocabulary = ConceptScheme.objects.get(pk=form.save().pk)
        assert vocabulary.description == DETAILS["description"]
        assert vocabulary.default_language == "de"
        assert vocabulary.publisher == DETAILS["publisher"]
        assert vocabulary.creator == DETAILS["creator"]
        assert vocabulary.license == DETAILS["license"]
        assert vocabulary.version == DETAILS["version"]
        assert str(vocabulary.modified) == DETAILS["modified"]

    def test_a_missing_name_is_refused(self):
        form = VocabularyForm(data={"name": ""})

        assert not form.is_valid()
        assert error_codes(form, "name") == ["required"]

    def test_a_name_with_no_letter_or_number_is_refused(self):
        form = VocabularyForm(data={"name": " !?- "})

        assert not form.is_valid()
        assert error_codes(form, "name") == ["empty_slug"]

    def test_a_name_whose_address_another_vocabulary_holds_is_refused(self):
        ConceptSchemeFactory(name="Rock Types")
        form = VocabularyForm(data={"name": "rock  types", **DETAILS})

        assert not form.is_valid()
        assert error_codes(form, "name") == ["slug_taken"]
        assert form["description"].value() == DETAILS["description"]
        assert form["publisher"].value() == DETAILS["publisher"]

    def test_saving_a_vocabulary_under_its_own_name_is_not_refused(self):
        vocabulary = ConceptSchemeFactory(name="Rock Types")
        form = VocabularyForm(data={"name": "Rock Types"}, instance=vocabulary)

        assert form.is_valid(), form.errors

    def test_the_form_offers_no_address_or_identifier_field(self):
        assert {"slug", "slug_is_manual", "static_uri"}.isdisjoint(
            VocabularyForm().fields
        )

    def test_a_manual_address_is_left_alone_when_the_name_has_no_letter(self):
        vocabulary = ConceptSchemeFactory(name="Rocks")
        ConceptScheme.objects.filter(pk=vocabulary.pk).update(slug_is_manual=True)
        vocabulary.refresh_from_db()
        form = VocabularyForm(data={"name": "???"}, instance=vocabulary)

        assert form.is_valid(), form.errors


@pytest.mark.django_db
class TestVocabularyFormDefaultLanguage:
    def test_it_offers_the_site_default_and_each_configured_language(self):
        choices = VocabularyForm().fields["default_language"].choices

        assert [code for code, _label in choices] == ["", "en", "de", "fr"]

    def test_a_language_that_is_not_configured_is_refused(self):
        form = VocabularyForm(data={"name": "Rock Types", "default_language": "ja"})

        assert not form.is_valid()
        assert error_codes(form, "default_language") == ["invalid_choice"]

    @override_settings(LANGUAGES=[("en", "English"), ("xx", "Made up")])
    def test_a_configured_language_django_does_not_know_does_not_break_the_form(self):
        form = VocabularyForm(data={"name": "Rock Types", "default_language": "xx"})

        assert form.is_valid(), form.errors
        assert dict(form.fields["default_language"].choices)["xx"] == "xx"

    @override_settings(LANGUAGE_CODE="en-xx")
    def test_a_regional_site_language_does_not_break_the_form(self):
        form = VocabularyForm(data={"name": "Rock Types"})

        assert form.is_valid(), form.errors


@pytest.mark.django_db
class TestVocabularyFormLanguageFixedOnceConceptsExist:
    @pytest.fixture
    def held(self):
        vocabulary = ConceptSchemeFactory(name="Rock Types", default_language="de")
        ConceptFactory(scheme=vocabulary)
        return vocabulary

    def test_the_widget_is_disabled(self, held):
        select = BeautifulSoup(
            str(VocabularyForm(instance=held)["default_language"]), "html.parser"
        ).select_one("select")

        assert select.has_attr("disabled")

    def test_a_post_leaving_the_field_out_keeps_the_stored_language(self, held):
        form = VocabularyForm(data={"name": "Rock Types"}, instance=held)

        assert form.is_valid(), form.errors
        form.save()
        held.refresh_from_db()
        assert held.default_language == "de"

    def test_a_form_shown_again_with_an_error_still_shows_the_stored_language(
        self, held
    ):
        form = VocabularyForm(
            data={"name": "Rock Types", "modified": "x"}, instance=held
        )

        assert not form.is_valid()
        selected = BeautifulSoup(
            str(form["default_language"]), "html.parser"
        ).select_one("option[selected]")
        assert selected is not None
        assert selected["value"] == "de"

    def test_a_post_naming_the_stored_language_is_accepted(self, held):
        form = VocabularyForm(
            data={"name": "Rock Types", "default_language": "de"}, instance=held
        )

        assert form.is_valid(), form.errors

    @pytest.mark.parametrize("submitted", ["fr", ""])
    def test_a_post_naming_a_different_language_is_refused_and_saves_nothing(
        self, held, submitted
    ):
        form = VocabularyForm(
            data={"name": "Rock Types", "default_language": submitted}, instance=held
        )

        assert not form.is_valid()
        assert error_codes(form, "default_language") == ["language_fixed"]
        held.refresh_from_db()
        assert held.default_language == "de"


@pytest.mark.django_db
class TestVocabularyFormLanguageFreeWhileEmpty:
    def test_the_widget_is_not_disabled(self):
        vocabulary = ConceptSchemeFactory(default_language="de")

        select = BeautifulSoup(
            str(VocabularyForm(instance=vocabulary)["default_language"]), "html.parser"
        ).select_one("select")

        assert not select.has_attr("disabled")

    def test_a_changed_language_is_saved(self):
        vocabulary = ConceptSchemeFactory(name="Rock Types", default_language="de")
        form = VocabularyForm(
            data={"name": "Rock Types", "default_language": "fr"}, instance=vocabulary
        )

        assert form.is_valid(), form.errors
        form.save()
        vocabulary.refresh_from_db()
        assert vocabulary.default_language == "fr"

    def test_a_post_leaving_the_field_out_keeps_the_stored_language(self):
        vocabulary = ConceptSchemeFactory(name="Rock Types", default_language="de")
        form = VocabularyForm(data={"name": "Rock Types"}, instance=vocabulary)

        assert form.is_valid(), form.errors
        form.save()
        vocabulary.refresh_from_db()
        assert vocabulary.default_language == "de"

    def test_choosing_the_site_default_saves_a_blank_language(self):
        vocabulary = ConceptSchemeFactory(name="Rock Types", default_language="de")
        form = VocabularyForm(
            data={"name": "Rock Types", "default_language": ""}, instance=vocabulary
        )

        assert form.is_valid(), form.errors
        form.save()
        vocabulary.refresh_from_db()
        assert vocabulary.default_language == ""


class TestFormsI18nSweep:
    def test_module_carries_no_bare_user_visible_literal(self):
        source = Path(inspect.getfile(forms_module)).read_text()
        visitor = visit_fields_checks_source(source)

        assert visitor.bare_literals == []
        assert visitor.positional_placeholders == []
