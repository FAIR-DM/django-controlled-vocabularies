"""The curator's form for a vocabulary's own record."""

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Fieldset, Layout
from django import forms
from django.conf import settings
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies.models import ConceptScheme
from controlled_vocabularies.ui.filters import language_name


class VocabularyForm(forms.ModelForm):
    """Name, description, default language and publication details of a vocabulary.

    The identifier and the address segment are never offered: the segment follows the name,
    and fixing an identifier is publication.
    """

    class Meta:
        model = ConceptScheme
        fields = [
            "name",
            "description",
            "default_language",
            "publisher",
            "creator",
            "license",
            "version",
            "modified",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "modified": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
        help_texts = {
            "name": _(
                "The vocabulary's address is made from its name, so renaming it moves the address."
            ),
            "description": _("What the vocabulary covers, in a sentence or two."),
            "publisher": _("A name, or the address of one."),
            "creator": _("A name, or the address of one."),
            "license": _("The licence's address, or its name."),
            "version": _("As you number it, for example 1.2."),
            "modified": _("When the vocabulary's content last changed."),
        }

    def __init__(self, *args, **kwargs):
        """Offer the configured languages, and fix the default language once concepts exist."""
        super().__init__(*args, **kwargs)
        self.fields["default_language"] = forms.ChoiceField(
            label=_("Default language"),
            required=False,
            choices=[
                (
                    "",
                    _("The site's default (%(language)s)")
                    % {"language": language_name(settings.LANGUAGE_CODE)},
                ),
                *((code, language_name(code)) for code, _name in settings.LANGUAGES),
            ],
            help_text=_(
                "The language a concept is identified by. It cannot be changed once the "
                "vocabulary holds concepts."
            ),
            initial=self.instance.default_language,
        )
        self.language_fixed = bool(self.instance.pk) and self.instance.concepts.exists()
        if self.language_fixed:
            field = self.fields["default_language"]
            field.disabled = True
            field.help_text = _(
                "Fixed, because this vocabulary holds concepts and each one is identified by "
                "its label in this language."
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

    def clean_name(self):
        """Refuse a name whose address is empty or already another vocabulary's."""
        name = self.cleaned_data["name"].strip()
        if self.instance.slug_is_manual:
            return name
        slug = slugify(name, allow_unicode=True)
        if not slug:
            raise forms.ValidationError(
                _(
                    "Use at least one letter or number, so the vocabulary has an address."
                ),
                code="empty_slug",
            )
        taken = ConceptScheme.objects.filter(slug=slug).exclude(pk=self.instance.pk)
        if taken.exists():
            raise forms.ValidationError(
                _(
                    '"%(name)s" would have the same address as the vocabulary "%(other)s". '
                    "Choose a different name."
                ),
                code="slug_taken",
                params={"name": name, "other": taken.first().name},
            )
        return name
