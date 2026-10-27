# Add the browsing pages to your site

The `ui` extra adds an opt-in, reader-facing front end: a list of every vocabulary the site holds,
and a page of its own for each vocabulary, concept and collection. Every page is read-only.

```bash
pip install django-controlled-vocabularies[ui]
```

## Wiring it up

This section adds to the package's base configuration rather than replacing it: `django_tomselect`
and its middleware are still required, as [choosing a concept by typing](choosing-a-concept.md#choosing-a-concept-by-typing)
describes, and `manage.py check` says so on startup if they are missing.

Add the ui app and django-mvp's own stack to `INSTALLED_APPS` — quoted from this package's own
test project, so the list below is one that demonstrably works:

```python
INSTALLED_APPS = [
    ...
    "controlled_vocabularies",
    "django_cotton",
    "easy_icons",
    "flex_menu",
    # "daisy_cotton" below "mvp": both ship an icon component, and the first app to declare a
    # template path wins.
    "mvp",
    "daisy_cotton",
    "crispy_forms",
    "mvp_forms",
    "django_filters",
    "controlled_vocabularies.ui",
]

# crispy-forms 2.7's get_template_pack() has no default, and the {% crispy %} tag validates
# the pack against CRISPY_ALLOWED_TEMPLATE_PACKS at template-compile time — django-mvp's own
# templates carry the tag, so both settings are required even though this page renders no
# form of its own. "daisyui" is the pack django-mvp-forms provides; django-mvp installs it.
CRISPY_TEMPLATE_PACK = "daisyui"
CRISPY_ALLOWED_TEMPLATE_PACKS = ["daisyui"]

TEMPLATES[0]["OPTIONS"]["context_processors"] += ["mvp.context_processors.mvp_config"]

# django-mvp's base template renders icons through django-easy-icons and its own sidebar and
# mobile-dock chrome through django-flex-menus; both raise at render time without these.
EASY_ICONS = {
    "default": {
        "renderer": "easy_icons.renderers.ProviderRenderer",
        "config": {"tag": "i"},
        "packs": ["mvp.utils.BS5_ICONS"],
    },
}
FLEX_MENUS = {
    "renderers": {
        "sidebar": "mvp.renderers.SidebarRenderer",
        "dock": "mvp.renderers.MobileFooterNavRenderer",
    },
}
```

Mount the routes at an address of your choosing:

```python
from django.urls import include, path

urlpatterns = [
    ...
    path("browse/", include("controlled_vocabularies.ui.urls")),
]
```

Reverse the page by name, under its own namespace — `controlled_vocabularies_ui`, distinct from
the core package's own `controlled_vocabularies` namespace, so both can be mounted in one
project without either shadowing the other's reverses:

```python
reverse("controlled_vocabularies_ui:vocabulary-list")
```

`manage.py check` reports `controlled_vocabularies.ui.E001`, naming the extra to install, if
`django-mvp` is not importable.

Each entry's name is a link to that vocabulary's own page, described below. The link is reversed
from the route's name rather than composed from the identifier base address, so it stays an
in-site address whatever that setting says.

The search, the sort and the facets are a django-filter filterset, `VocabularyFilter` in
`controlled_vocabularies.ui.filters`: `q` is django-mvp's `SearchFilter`, `o` its `SortFilter`,
and `publisher`, `license` and `language` are multiple-choice filters drawn as `CountedCheckboxes`,
a checkbox widget that adds each option's count when it is drawn. `VocabularyFilter.count_facets()`
sets those counts. `licence_name()` gives a licence its short name from `LICENCE_NAMES`, and
`language_name()` names a language code in the reader's language. Each vocabulary's facet values
are read once into a `Profile`, in the same module. Only the first hundred words of a search are
used, far more than any real search, because the query grows with every word.

An earlier django-mvp release could not submit the search box on this page at all, because its
input was tied to a form only the filter control created. This package waited for the upstream fix
rather than shipping a patched copy of django-mvp's page, and the version floor moved once the fix
was released. An override in a package like this one outlives the release that makes it
unnecessary, and nothing ever reports that it has
([ADR 0015](../adr/0015-upstream-defects-are-waited-on-not-worked-around.md)).

The page is served by `VocabularyListView`, in `controlled_vocabularies.ui.views`. A project that
wants a different presentation subclasses it and routes its own path at the same view — the
queryset, its ordering, its counts and its facets come with the class, so an override that only changes
`list_item_template` keeps every guarantee above:

```python
from controlled_vocabularies.ui.views import VocabularyListView


class BrandedVocabularyListView(VocabularyListView):
    list_item_template = "myproject/vocabulary_card.html"
```
