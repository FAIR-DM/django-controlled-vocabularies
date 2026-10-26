"""The curator's forms for a vocabulary's own record."""

import re
from urllib.parse import urlsplit

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Column, Layout, Row
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory
from django.utils.translation import gettext_lazy as _
from django_tomselect.app_settings import AllowedCSSFrameworks, TomSelectConfig
from django_tomselect.forms import TomSelectChoiceField

from controlled_vocabularies.models import ConceptScheme
from controlled_vocabularies.predicates import (
    PREDICATES,
    PREFIXES,
    Kind,
    Namespaces,
    Predicate,
)
from controlled_vocabularies.ui.filters import language_name

PREDICATE_AUTOCOMPLETE_URL_NAME = "controlled_vocabularies:predicate-autocomplete"

#: What a predicate the package does not list is taken to be.
_UNLISTED = Predicate(Kind.LITERAL)


class PredicateChoiceField(TomSelectChoiceField):
    """A predicate picked from the configured namespaces' terms, or typed in full.

    Any text is a valid choice here; the row's own validation decides whether it names a
    predicate.
    """

    def __init__(self, *args, **kwargs):
        """Search the predicate endpoint, and let a curator create a value of their own."""
        kwargs.setdefault(
            "config",
            TomSelectConfig(
                url=PREDICATE_AUTOCOMPLETE_URL_NAME,
                value_field="value",
                label_field="label",
                create=True,
                # css_framework takes the enum's value: TomSelectConfig.validate() rejects the member itself.
                css_framework=AllowedCSSFrameworks.DEFAULT.value,  # type: ignore[arg-type]
            ),
        )
        super().__init__(*args, **kwargs)

    def clean(self, value):
        """Accept whatever was entered, as the text box this replaces did."""
        return forms.CharField(required=False).clean(value)

    def valid_value(self, value):
        """Count any value as one of the choices, so a stored predicate redisplays selected."""
        return True


class VocabularyForm(forms.ModelForm):
    """The default language of a vocabulary.

    Everything else the vocabulary says about itself is a row of the statements
    formset beside it. The identifier and the address segment are never offered: both
    are made once, when the vocabulary is created.
    """

    class Meta:
        model = ConceptScheme
        fields = ["default_language"]

    def __init__(self, *args, **kwargs):
        """Offer the configured languages, and fix the language once records exist."""
        super().__init__(*args, **kwargs)
        scheme = self.instance
        self.fields["default_language"] = forms.ChoiceField(
            label=_("Default language"),
            choices=[(code, language_name(code)) for code, _name in settings.LANGUAGES],
            help_text=_(
                "The language the name is read in. It cannot be changed once the "
                "vocabulary holds records."
            ),
            initial=scheme.default_language or settings.LANGUAGE_CODE,
        )
        # A disabled control is not submitted, so an absent value is the browser keeping the
        # stored one. Put it back into the data, so it is both what is saved and what is shown
        # when the form comes back with an error.
        key = self.add_prefix("default_language")
        widget = self.fields["default_language"].widget
        if self.is_bound and widget.value_omitted_from_data(self.data, self.files, key):
            self.data = self.data.copy()
            self.data[key] = scheme.default_language
        self.language_fixed = bool(scheme.pk) and scheme.records.exists()
        if self.language_fixed:
            field = self.fields["default_language"]
            # Not Django's disabled field, which would drop a submitted change without a word.
            field.widget.attrs["disabled"] = True
            field.help_text = _(
                "Fixed, because this vocabulary holds records and each one's name is "
                "read in this language."
            )
        self.helper = FormHelper()
        self.helper.form_tag = False

    def clean_default_language(self):
        """Keep the stored language, and refuse another, once the vocabulary holds records."""
        language = self.cleaned_data["default_language"]
        if self.language_fixed and language != self.instance.default_language:
            raise forms.ValidationError(
                _(
                    "The default language cannot be changed while the vocabulary holds records."
                ),
                code="language_fixed",
            )
        return language


class StatementValueWidget(forms.Textarea):
    """A statement's value, drawn as one control for each kind of predicate.

    All of them share the field's name. The row's script shows one and disables the
    rest, so the browser sends exactly one.
    """

    template_name = "controlled_vocabularies/ui/widgets/statement_value.html"

    def get_context(self, name, value, attrs):
        """Add the value as a date, or nothing when it is not one, for the date control."""
        context = super().get_context(name, value, attrs)
        context["widget"]["date_value"] = (
            value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or "") else ""
        )
        return context


class StatementForm(forms.Form):
    """One statement a vocabulary makes about itself: a predicate, a value, a language.

    A row with no value is blank and is dropped when the vocabulary is saved.
    """

    predicate = PredicateChoiceField(
        required=False,
        label=_("Predicate"),
        help_text=_("Pick a known term, or enter a prefixed name or a full address."),
    )
    language = forms.ChoiceField(
        required=False,
        label=_("Language"),
        choices=(),
        widget=forms.Select(attrs={"x-bind:disabled": "kind !== 'literal'"}),
    )
    value = forms.CharField(
        required=False, label=_("Value"), widget=StatementValueWidget(attrs={"rows": 2})
    )

    _CURIE = re.compile(r"(?P<prefix>[^:/\s]+):[\w.-]+")

    def __init__(self, *args, **kwargs):
        """Offer the configured languages, and lay the row out: key and language, then value."""
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Row(
                # django-mvp's stylesheet has no utility for a 3:1 split, so the ratio is inline.
                Column("predicate", style="flex: 3 1 0%"),
                Column(
                    "language",
                    style="flex: 1 1 0%",
                    **{"x-show": "kind === 'literal'"},
                ),
                css_class="sm:flex-row",
            ),
            "value",
        )
        choices = [("", _("None"))] + [
            (code, language_name(code)) for code, _name in settings.LANGUAGES
        ]
        stored = self.initial.get("language", "")
        if stored and stored not in dict(choices):
            choices.append((stored, stored))
        self.fields["language"].choices = choices

    @staticmethod
    def is_http_uri(text: str) -> bool:
        """Return whether ``text`` is an absolute http or https address.

        Args:
            text: The text to test.

        Returns:
            True when it has an http or https scheme and a host, and no whitespace.
        """
        parts = urlsplit(text)
        return (
            parts.scheme in ("http", "https")
            and bool(parts.netloc)
            and not re.search(r"\s", text)
        )

    def clean(self):
        """Check the predicate, and the value and language it asks for."""
        cleaned = super().clean()
        value = cleaned.get("value", "")
        predicate = cleaned.get("predicate", "")
        if not value:
            return cleaned
        if not predicate:
            self.add_error("predicate", _("Name the predicate this value belongs to."))
            return cleaned
        if self.is_http_uri(predicate):
            predicate = Namespaces.compact(predicate)
        elif not (
            (match := self._CURIE.fullmatch(predicate)) and match["prefix"] in PREFIXES
        ):
            self.add_error(
                "predicate",
                _(
                    "Use a name with a known prefix (%(prefixes)s), or a full "
                    "http or https address."
                )
                % {"prefixes": ", ".join(PREFIXES)},
            )
            return cleaned
        cleaned["predicate"] = predicate
        spec = PREDICATES.get(predicate, _UNLISTED)
        if spec.kind is Kind.URI and not self.is_http_uri(value):
            self.add_error("value", _("This predicate takes an http or https address."))
        if (
            spec.translatable
            and "language" not in self.errors
            and not cleaned.get("language")
        ):
            self.add_error(
                "language", _("This predicate needs the language of its value.")
            )
        return cleaned


class StatementFormSet(BaseFormSet):
    """The statements of a vocabulary, which together become its document.

    Args:
        default_language: The vocabulary's default language, in which a
            ``skos:prefLabel`` must be given.
    """

    def __init__(self, *args, default_language: str, **kwargs):
        """Remember the default language, and give the set its prefix."""
        kwargs.setdefault("prefix", "statements")
        super().__init__(*args, **kwargs)
        self.default_language = default_language

    @classmethod
    def initial_for(cls, scheme: ConceptScheme, default_language: str) -> list[dict]:
        """Return a row for each entry the vocabulary stores.

        Args:
            scheme: The vocabulary; a new one has no rows yet.
            default_language: The language of the rows a new vocabulary starts with.

        Returns:
            Rows in the order of the known predicates, then the others as stored.
        """
        if not scheme.pk:
            return [
                {"predicate": curie, "language": default_language}
                for curie in ("skos:prefLabel", "dcterms:description")
            ]
        data = scheme.data
        curies = [curie for curie in PREDICATES if curie in data]
        curies += [curie for curie in data if curie not in PREDICATES]
        return [
            {
                "predicate": curie,
                "value": str(entry.get("@value", entry.get("@id", ""))),
                "language": entry.get("@language", ""),
            }
            for curie in curies
            for entry in data[curie]
        ]

    def statements(self) -> list[dict]:
        """Return the rows to keep: not removed, and with a value.

        Returns:
            The cleaned rows, in the order they were submitted.
        """
        return [
            form.cleaned_data
            for form in self.forms
            if not self._should_delete_form(form) and form.cleaned_data.get("value")
        ]

    def clean(self):
        """Refuse a single-valued predicate given twice, and a missing name."""
        live = [form for form in self.forms if not self._should_delete_form(form)]
        if not all(form.is_valid() for form in live):
            return
        errors = []
        seen = set()
        for row in self.statements():
            spec = PREDICATES.get(row["predicate"], _UNLISTED)
            if spec.many:
                continue
            language = row["language"].lower() if spec.translatable else ""
            if (row["predicate"], language) in seen:
                message = _("%(predicate)s takes a single value, but is given twice.")
                if language:
                    message = _(
                        "%(predicate)s takes a single value in each language, but is "
                        "given twice in %(language)s."
                    )
                errors.append(
                    ValidationError(
                        message,
                        code="single_valued",
                        params={
                            "predicate": row["predicate"],
                            "language": language_name(language) if language else "",
                        },
                    )
                )
            seen.add((row["predicate"], language))
        if ("skos:prefLabel", self.default_language.lower()) not in seen:
            errors.append(
                ValidationError(
                    _("Give the vocabulary a skos:prefLabel in %(language)s."),
                    code="no_name",
                    params={"language": language_name(self.default_language)},
                )
            )
        if errors:
            raise ValidationError(errors)

    def to_data(self) -> dict:
        """Build the vocabulary's document from the rows.

        Returns:
            Entries grouped by predicate, in row order.
        """
        data: dict[str, list[dict]] = {}
        for row in self.statements():
            curie, value, language = row["predicate"], row["value"], row["language"]
            kind = PREDICATES.get(curie, _UNLISTED).kind
            if kind is Kind.URI:
                entry = {"@id": value}
            elif kind is Kind.TYPED:
                entry = {"@value": value}
                if curie == "dcterms:modified":
                    entry["@type"] = "xsd:date"
            else:
                entry = {"@value": value}
                if language:
                    entry["@language"] = language
            data.setdefault(curie, []).append(entry)
        return data


StatementsFormSet = formset_factory(
    StatementForm, formset=StatementFormSet, extra=0, can_delete=True
)
