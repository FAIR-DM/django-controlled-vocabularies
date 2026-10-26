"""A page that shows the statement predicate picker on its own, outside a formset."""

from django import forms
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from mvp.views import MVPFormView
from mvp_forms.widgets import TomSelect

from controlled_vocabularies.predicates import Namespaces
from controlled_vocabularies.ui.forms import PredicateChoiceField


class TermPickerForm(forms.Form):
    """The same choice made with each of the two Tom Select widgets the stack offers."""

    remote = PredicateChoiceField(
        label=_("Predicate, searched on the server"),
        help_text=_(
            "django-tomselect: options come from the predicate endpoint as you type, "
            "and a term not in the list can be typed in."
        ),
        required=False,
    )
    listed = forms.ChoiceField(
        label=_("Predicate, from a list on the page"),
        help_text=_(
            "django-mvp-forms: every term is drawn into the select, and only a listed "
            "term can be chosen."
        ),
        required=False,
        widget=TomSelect(placeholder=_("Pick a predicate")),
    )

    def __init__(self, *args, **kwargs):
        """List the configured namespaces' terms in the second select."""
        super().__init__(*args, **kwargs)
        self.fields["listed"].choices = [
            ("", ""),
            *((curie, curie) for curie in Namespaces.terms()),
        ]


class TermPickerView(MVPFormView):
    """Show what each widget submits, without saving anything."""

    form_class = TermPickerForm
    template_name = "form_view.html"
    page_title = _("Predicate picker")

    def form_valid(self, form):
        """Draw the form again with a message naming what was submitted."""
        messages.info(
            self.request,
            _("Submitted: %(remote)s, and %(listed)s.")
            % {
                "remote": form.cleaned_data["remote"] or "—",
                "listed": form.cleaned_data["listed"] or "—",
            },
        )
        return self.render_to_response(self.get_context_data(form=form))
