"""Registers the vocabulary model with the demo's admin site."""

from django.contrib import admin

from controlled_vocabularies.models import ConceptScheme


# Registered here rather than in the package, which registers nothing so each project decides
# for itself. Concept is left out: a hand-added vocabulary should show a count of zero.
@admin.register(ConceptScheme)
class ConceptSchemeAdmin(admin.ModelAdmin):
    """Admin for vocabularies, showing only the fields the list page reads."""

    # slug and slug_is_manual are left off the form: the slug is derived from the name on save, and a
    # required slug field would demand a value the model is about to compute.
    fields = ("name", "description", "default_language", "static_uri")
    list_display = ("name", "slug", "static_uri")
    search_fields = ("name", "description")
