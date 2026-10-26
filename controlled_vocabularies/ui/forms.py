"""The curator's form for a vocabulary's own record."""

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Fieldset, Layout
from django import forms
from django.conf import settings
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies.models import ConceptScheme
from controlled_vocabularies.ui.filters import language_name


class VocabularyForm(forms.ModelForm):
    """Name, description, default language and publication details of a vocabulary.

    The name is the default-language ``skos:prefLabel`` and the description the
    ``dcterms:description``; the publication details are their own predicates. All are
    written into the vocabulary's document. The identifier and the address segment are
    never offered: both are made once, when the vocabulary is created.
    """

    name = forms.CharField(
        max_length=255,
        label=_("Name"),
        help_text=_("What the vocabulary is called, in its default language."),
    )
    description = forms.CharField(
        required=False,
        label=_("Description"),
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("What the vocabulary covers, in a sentence or two."),
    )
    publisher = forms.CharField(
        required=False,
        label=_("Publisher"),
        help_text=_("A name, or the address of one."),
    )
    creator = forms.CharField(
        required=False,
        label=_("Creator"),
        help_text=_("A name, or the address of one."),
    )
    license = forms.CharField(
        required=False,
        label=_("Licence"),
        help_text=_("The licence's address, or its name."),
    )
    version = forms.CharField(
        required=False,
        label=_("Version"),
        help_text=_("As you number it, for example 1.2."),
    )
    modified = forms.DateField(
        required=False,
        label=_("Last modified"),
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text=_("When the vocabulary's content last changed."),
    )

    #: Each publication field and the predicate it is stored under.
    PUBLICATION_CURIES = {
        "publisher": "dcterms:publisher",
        "creator": "dcterms:creator",
        "license": "dcterms:license",
        "version": "owl:versionInfo",
    }

    class Meta:
        model = ConceptScheme
        fields = ["default_language"]

    def __init__(self, *args, **kwargs):
        """Offer the configured languages, fix the default language once records exist, and fill the fields."""
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
        if scheme.pk:
            language = scheme.default_language
            self.initial.update(
                name=scheme.label(language) or scheme.pref_label,
                description=self._stored_description(),
                modified=parse_date(scheme.first_value("dcterms:modified") or ""),
                **{
                    field: scheme.first_value(curie)
                    for field, curie in self.PUBLICATION_CURIES.items()
                },
            )
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            "name",
            "description",
            "default_language",
            Fieldset(
                _("Publication details"),
                "publisher",
                "creator",
                "license",
                "version",
                "modified",
            ),
        )

    def _stored_description(self) -> str:
        """Return the description in the vocabulary's default language."""
        scheme = self.instance
        for entry in scheme.values("dcterms:description"):
            if entry.get("@language", "").lower() == scheme.default_language.lower():
                return str(entry["@value"])
        return ""

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

    def save(self, commit=True):
        """Write the submitted values into the vocabulary's document.

        A value left as it was keeps its stored entries, so a vocabulary with several
        creators does not lose all but one by being saved.

        Args:
            commit: Whether to save the vocabulary.

        Returns:
            The vocabulary.
        """
        scheme = super().save(commit=False)
        data = dict(scheme.data)
        language = scheme.default_language
        cleaned = self.cleaned_data
        self._replace(data, "skos:prefLabel", cleaned["name"], language)
        self._replace(data, "dcterms:description", cleaned["description"], language)
        for field, curie in self.PUBLICATION_CURIES.items():
            self._replace(data, curie, cleaned[field])
        modified = cleaned["modified"]
        self._replace(
            data,
            "dcterms:modified",
            modified.isoformat() if modified else "",
            datatype="xsd:date",
        )
        scheme.data = data
        if commit:
            scheme.save()
        return scheme

    def _replace(
        self,
        data: dict,
        curie: str,
        text: str,
        language: str | None = None,
        datatype: str | None = None,
    ) -> None:
        """Set a predicate to one value, unless the stored first value already is ``text``.

        Args:
            data: The document, updated in place.
            curie: The predicate.
            text: The submitted value; empty removes it.
            language: The language of a translatable value; entries in other languages stay.
            datatype: The datatype of a typed literal.
        """
        text = text.strip()
        entries = data.get(curie, [])
        ours = [
            e for e in entries if language is None or e.get("@language") == language
        ]
        if (ours and str(ours[0].get("@value", ours[0].get("@id", ""))) == text) or (
            not ours and not text
        ):
            return
        kept = [entry for entry in entries if entry not in ours]
        if text:
            if language is not None:
                new = {"@value": text, "@language": language}
            elif datatype is not None:
                new = {"@value": text, "@type": datatype}
            elif text.startswith(("http://", "https://")):
                new = {"@id": text}
            else:
                new = {"@value": text}
            kept.append(new)
        if kept:
            data[curie] = kept
        else:
            data.pop(curie, None)
