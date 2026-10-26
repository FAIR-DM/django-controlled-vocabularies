"""Registers the vocabulary models with the demo's admin site."""

from django.contrib import admin

from controlled_vocabularies.models import ConceptScheme, Record


# Registered here rather than in the package, which registers nothing so each project decides
# for itself.
@admin.register(ConceptScheme)
class ConceptSchemeAdmin(admin.ModelAdmin):
    """Admin for vocabularies; the name lives in the document, so it is searched there."""

    list_display = ("pref_label", "slug", "uri", "managed")
    list_filter = ("managed",)
    search_fields = ("pref_label", "uri")
    readonly_fields = ("pref_label",)


@admin.register(Record)
class RecordAdmin(admin.ModelAdmin):
    """Admin for concepts and collections, filtered by vocabulary and type."""

    list_display = ("pref_label", "type", "scheme", "uri")
    list_filter = ("scheme", "type")
    list_select_related = ("scheme",)
    search_fields = ("pref_label", "search_text", "uri")
    readonly_fields = ("pref_label", "search_text")
