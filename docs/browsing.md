# Browsing vocabularies

The `ui` extra adds an opt-in, reader-facing front end: a list of every vocabulary the site holds,
and a page of its own for each vocabulary, concept and collection. Every page is read-only.

```bash
pip install django-controlled-vocabularies[ui]
```

## Finding a vocabulary

The `ui` extra adds one reader-facing page: every vocabulary the site holds, in alphabetical
order. Each entry is laid out as a concept is on [a vocabulary's own page](#a-vocabularys-own-page)
and carries:

- its publisher, above its name, when it names one
- its name, linking to the vocabulary's own page
- its description, cut to 30 words
- how many concepts it holds, how many collections when it has any, and when it was last updated
  when it gives a date
- its identifier (`ConceptScheme.uri`), as a link when it is a web address

A site holding no vocabularies says so rather than showing an empty list.

A search box narrows that list by a vocabulary's name and description, not by the concepts it
holds. Finding a concept without already knowing which vocabulary holds it is not something this
page does. The term travels in the page's address (`?q=`), so a narrowed list can be linked to or
bookmarked and returned to. A second word **widens** the results rather than narrowing them:
matching is OR across every word and both fields, not AND, which is the opposite of what a search
box usually implies. A search matching nothing says so, repeats what was searched for, and offers
**Clear all** as the way back to the full list.

A sort control offers the list by name, A-Z or Z-A, by most concepts, or by most recently
updated, with vocabularies giving no date last. That choice travels in the address as `?o=`,
next to any search term, so a searched and sorted list is still one link you can share. Only the
orderings the view declares are honoured. Anything else in `?o=` is ignored rather than passed to
the database, and the page comes back in its default order. Two vocabularies with the same name
keep the same order across pages. Names sort by the vocabulary's name in its own default language,
which is the copy stored in `pref_label`.

Searching, sorting and moving between pages update the list in place, and the address bar follows,
so the back button and a copied link behave as they would after a full page load.

### Narrowing by publisher, licence and language

Beside the list, a filter panel narrows it by a vocabulary's publication details (see "The
vocabulary's own details" in [importing](importing.md#the-vocabularys-own-details)):

- **Publisher**, from the vocabulary's `dcterms:publisher`
- **Licence**, from its `dcterms:license`. A Creative Commons licence given by its address is
  named by its short name, such as *CC BY 4.0*. Any other licence is shown as given.
- **Language**, the vocabulary's default language.

Ticking several options of one facet keeps the vocabularies carrying any of them. Facets combine
with each other and with the search. Each option says how many vocabularies it would leave, counted
among those the search and the other facets leave, so the counts of a facet do not change when one
of its own options is ticked. A facet is offered only when at least two of the site's vocabularies
differ on it, so a site holding vocabularies from one publisher shows no publisher facet.

The choices travel in the address beside the search and the sort (`?publisher=…&license=…`), and
each applied one is shown above the list with a way to remove it. The panel is django-mvp's filter
panel, placed as the side panel on a vocabulary's own page is.

Case is ignored, with one limit that belongs to the database rather than to this package. SQLite
folds case for ASCII letters only, so a vocabulary named *Ökologie* is found by *ÖKOLOGIE* and not
by *ökologie*. PostgreSQL folds the whole of Unicode and matches either way. Django
[documents this](https://docs.djangoproject.com/en/stable/ref/databases/#substring-matching-and-case-sensitivity)
and does not work around it, and neither does this package, because nothing above the database can.
It matters for any site whose vocabularies are named in German, French, Greek or Russian.

The page carries **no permission rule of its own**. Every vocabulary in the database is listed to
anyone who reaches the URL, exactly as the concept search endpoint serves anyone who reaches
it, and for the same reason: a package cannot guess a project's access policy. A site that needs the
page restricted wraps the include where it mounts these routes.

## Wiring it up

This section adds to the package's base configuration rather than replacing it: `django_tomselect`
and its middleware are still required, as [choosing a concept by typing](how-to/choosing-a-concept.md#choosing-a-concept-by-typing)
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
([ADR 0015](adr/0015-upstream-defects-are-waited-on-not-worked-around.md)).

The page is served by `VocabularyListView`, in `controlled_vocabularies.ui.views`. A project that
wants a different presentation subclasses it and routes its own path at the same view — the
queryset, its ordering, its counts and its facets come with the class, so an override that only changes
`list_item_template` keeps every guarantee above:

```python
from controlled_vocabularies.ui.views import VocabularyListView


class BrandedVocabularyListView(VocabularyListView):
    list_item_template = "myproject/vocabulary_card.html"
```

## A vocabulary's own page

Every vocabulary the site holds has its own address, `{mount}/{slug}/`, under wherever the routes
are mounted. The page's title is the vocabulary's name, and its lead text is the vocabulary's
description, truncated the same way and for the same reason as the list entry above. A vocabulary
with no description has no lead text.

The main column is every concept the vocabulary holds, and only that vocabulary's, in one flat,
alphabetical list: nothing several levels down a broader/narrower chain is nested under one above
it. Alphabetical order follows each concept's `pref_label`, its preferred label in the
vocabulary's default language. A concept carrying a label in the reader's own language shows that
one, and a concept with none in that language shows its default-language label, but the order is
the same whichever language is read.

Each row in the list carries:

- the concept's broader concept, above its label, when it has one (the first, when it has several)
- its label, linking to [the concept's own page](#a-concepts-own-page)
- its definition, in the reader's language or the vocabulary's default language, cut to 30 words
- its identifier (`Record.uri`), as a link to that identifier itself rather than to the page here
  when it is a web address
- the collections that hold it, each linking to [the collection's own page](#a-collections-own-page)

Anything a concept does not have is left out of its row. Alternative and hidden labels are never
shown. A vocabulary holding no concepts says so, in wording distinct from the page's other empty
state, and the rest of the page still renders.

Beside the list, a side panel describes the vocabulary itself:

- its identifier, as a link when it is a web address
- its default language
- its publication details: its publisher, its creator, its licence, its version and when it last
  changed (see "The vocabulary's own details" in [importing](importing.md#the-vocabularys-own-details)).
  A detail held as a web address is a link to it, and a detail the vocabulary does not have is shown
  as a dash.
- how many concepts it holds
- its top concepts, the ones with no broader concept, each linking to its page. A concept has a
  broader concept when it states one with `skos:broader` or another concept names it with
  `skos:narrower`. A vocabulary with
  no broader/narrower relations at all lists none, since every concept would be listed twice
- its collections (`skos:Collection` / `skos:OrderedCollection`), each linking to its page, with
  how many members it has and whether those members carry a deliberate order. A vocabulary
  holding no collections shows a dash.

The panel behaves as django-mvp's filter panel does on a list page: a column at the end of the
page from the `xl` breakpoint up, starting level with the list rather than the title and staying
in view as the page scrolls, and a drawer opened from an **About** button in the toolbar below that
width. Its root element carries the id `vocabulary-about`.

A search box narrows the list of concepts by every name a term goes by: a concept's preferred
label in any language it carries, its alternative labels, and its hidden labels — never its
definition or any other note. A hidden label is matched and never shown: searching for one finds
the concept it names without ever displaying the label itself, which is the whole point of
keeping it hidden. As with the list of vocabularies above, the term travels in the page's own
address (`?q=`), so a narrowed list can be linked to, bookmarked and returned to, and it reaches
every concept in the vocabulary before paging divides the results — not only the page being
viewed. A search matching nothing says so, repeats what was searched for, and offers **Clear all**
as the way back to the whole vocabulary.

Case is ignored, with the same database-dependent limit disclosed above: SQLite folds ASCII
letters only, so a concept labelled *Ökologie* is found by *ÖKOLOGIE* and not by *ökologie*;
PostgreSQL folds the whole of Unicode and matches either way
([ADR 0014](adr/0014-database-collation-differences-are-disclosed-not-repaired.md)).

Searching by address works the same as searching in the box: the demo project's own DCMI Type
Vocabulary carries a concept named *Dataset* with a hidden label of `Datset`, a plausible
misspelling — `?q=Datset` narrows the page to *Dataset* without the misspelling itself ever
appearing among the results, and the narrowed address can be shared and bookmarked the same as any
other. The term you typed is still repeated above the results, as on any search.

A sort control offers the concepts by label, A-Z or Z-A. The choice travels in the address as
`?o=`, next to any search term, exactly as it does on the list of vocabularies. It sorts by the
preferred label in the vocabulary's default language, the copy kept in `pref_label`. The search and
the sort are `ConceptFilter`, in `controlled_vocabularies.ui.filters`, and only the first ten words
of a search are used.

Reverse the page by name, passing the vocabulary's slug:

```python
reverse("controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": vocabulary.slug})
```

**The browsing routes must be mounted at the same path `CONTROLLED_VOCABULARIES_BASE_URI`
composes against**, or the identifier of a vocabulary created here does not lead back to its own
page. Mounting the routes at `browse/` means the setting's path has to be `/browse`, not the
package's own default:

```python
CONTROLLED_VOCABULARIES_BASE_URI = "https://example.org/browse"
```

`manage.py check` reports `controlled_vocabularies.ui.W001` — a warning, not an error, since a
project may serve identifiers through a reverse proxy this package cannot see — when the two
disagree, naming the mismatched paths. It is silent once they agree, and silent too if the
browsing routes are not mounted at all.

The page is served by `VocabularyDetailView`, in `controlled_vocabularies.ui.views`, and is
subclassed the same way as the list above. The publication details are read by
`PublicationDetails.of(vocabulary)`, in `controlled_vocabularies.ui.rows`.

## A concept's own page

Every concept has its own address, `{mount}/{vocabulary-slug}/{concept-slug}/`. The page is a
definition list of everything the concept's document states, other than its hidden labels, each row
labelled by the predicate it was stored under: its type (`rdf:type`), and then each predicate the
document holds. The ones the package knows come first, in a fixed order: labels, notation,
definition and notes, broader, narrower and related concepts, mappings to other vocabularies,
membership, and the publication details. Any other predicate follows, in alphabetical order, so a
statement in a namespace other than SKOS is shown too. Every record-valued row links to that
record's own page here. A predicate the concept carries no value for contributes no row at all —
never an empty one — so a concept carrying nothing beyond its label shows only its label, its type,
its identifier and its vocabulary.

The concept's own canonical identifier leads the page, directly beneath its title, so a reader
citing the record does not have to scroll past everything it says about itself to find it. The
breadcrumb trail above names the site's home, the vocabulary holding the concept, and the concept
itself.

Each row's own term — `skos:definition`, `skos:broader`, and the rest — is the predicate as the
document stores it: a CURIE for a known namespace, and the full URI for any other. A record-valued
row's own displayed text is a different short form — `{vocabulary slug}:{record slug}`,
`geology:granite` for a concept "granite" in a vocabulary slugged "geology". A link to a record
this site does not hold is shown as its URI, and is a link to that address when it is a web
address.

A CURIE abbreviates a URI, and both kinds on the page disclose the URI they stand for on hover
rather than printing it. A term's comes from `Namespaces.expand()` in
`controlled_vocabularies.predicates`, which expands a CURIE against the six prefixes the package
fixes (`skos`, `dcterms`, `owl`, `rdf`, `rdfs` and `xsd`) and returns any other key unchanged. A
record-valued row's is the record's own canonical identifier. Hovering is not the only way to reach
either. A term is not interactive, so its URI sits beside it in a visually-hidden element a screen
reader reads out in place. A record-valued row's short form is a link, so its URI lives in a
visually-hidden element the link points at as its own description, which a screen reader reads out
and which keyboard focus reveals along with the tooltip.

Below the definition list and outside it, the page also names every collection that gathers the
concept, under a heading reading "Member of". Membership is a statement other records make about
this one — SKOS gives a collection's own membership property no inverse — so this section's heading
is plain language rather than a CURIE, and it names the direction, since a heading of "Collections"
would read as collections belonging to the concept. Each entry links to that collection's own page.
A concept no collection gathers shows no such section at all, never an empty one.

A file often states a hierarchy from one side only. A concept's page shows the broader, narrower and
related concepts it states itself, and also the ones other concepts of the vocabulary state about
it, turned around: a concept that names this one as its broader concept appears here as narrower,
and `skos:related` is read from either end.

Labels, definitions, notes, titles and descriptions are shown in the language the site is being
read in. Where the concept has none in that language, they fall back to the vocabulary's own default
language, one language at a time, never every language a value was recorded in, and then to values
that carry no language. Every other predicate shows all its values.

The concept's own identifier is shown as a link, the same treatment its vocabulary's own page gives
a vocabulary's: for an imported concept it is its publisher's identifier. An identifier is a link
only when it is an `http` or `https` address. One in any other scheme, such as a `urn:`, is shown as
text, so nothing an imported file names is handed to another program by a click. The page is
**read-only**, it carries no editing or deletion control, and it has no permission rule beyond what
the project mounting these routes chooses to add. Concepts are added by [importing](importing.md).

An address naming no concept is reported not found, and so is one whose vocabulary segment names no
vocabulary — the two are not distinguished. A concept slug held by more than one vocabulary resolves
to the one the address actually names.

Reverse the page by name, passing the vocabulary's slug and the concept's own:

```python
reverse(
    "controlled_vocabularies_ui:concept-detail",
    kwargs={"slug": vocabulary.slug, "concept_slug": concept.slug},
)
```

The page is served by `ConceptDetailView`, in `controlled_vocabularies.ui.views`, and is subclassed
the same way as the pages above. The rows themselves come from `PropertyRows(record, language)`,
in `controlled_vocabularies.ui.rows`, whose `build()` returns the ordered rows — the seam a project
reaches for to build its own page, or its own rendering of a report, over the same rows this one
renders. `PropertyRows.in_reading_language()` is the rule that picks which entries of a translated
predicate to show.

## A collection's own page

Every collection has its own address too, at a distinct segment from a concept's,
`{mount}/{vocabulary-slug}/collection/{collection-slug}/`. The page is a definition list built the
same way a concept's is: its name (`skos:prefLabel`), a type row distinguishing an ordered
collection from an unordered one (`skos:Collection` or `skos:OrderedCollection`), and its members
under the membership property matching its kind — `skos:member` for an unordered collection,
`skos:memberList` for an ordered one, whose members appear in the sequence the file gave them.
Membership is one row however many members a collection holds — the property is stated once, with
every member listed beside it, rather than repeated per member. A collection holding no members says
so in plain language rather than showing an empty membership row.

Every record-valued row links to that record's own page here and discloses its canonical identifier
the same way a concept's page does. The collection's own identifier leads the page beneath its
title, its breadcrumb trail names the vocabulary holding it, and the page is equally **read-only**.

An address naming no collection is reported not found, and so is one whose vocabulary segment names
no vocabulary — the two are not distinguished, exactly as for a concept's page.

Reverse the page by name, passing the vocabulary's slug and the collection's own:

```python
reverse(
    "controlled_vocabularies_ui:collection-detail",
    kwargs={"slug": vocabulary.slug, "collection_slug": collection.slug},
)
```

The page is served by `CollectionDetailView`, in `controlled_vocabularies.ui.views`, and is
subclassed the same way as the pages above. Its rows come from the same `PropertyRows` a concept's
page uses.

## Try it: the demo project

The repository carries a runnable demo of the pages above, wired the same way this page
documents. From a fresh clone, with dependencies installed:

```bash
uv sync --extra ui

uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py build_docs
uv run python manage.py runserver
```

The four commands run through `uv run` so they use the environment the install just built,
whatever `python` on the shell's path happens to be — on many systems there is no `python` there
at all.

`migrate` builds the database, `seed_demo` loads two small vocabularies and a set of sign-in
accounts into it, `build_docs` builds this documentation with Sphinx, and `runserver` serves the
site at `http://127.0.0.1:8000/`.

The demo's pages are this documentation: the root address opens its front page at
`http://127.0.0.1:8000/docs/`, served inside the application shell by
[django-mvp-sphinx](https://github.com/django-mvp/django-mvp-sphinx), a development dependency.
The sidebar on every page, the documentation's and the browsing pages', holds the documentation's
contents, then a Demo group whose Vocabularies entry leads to the populated, searchable vocabulary
list at `http://127.0.0.1:8000/browse/`. Edit a page under `docs/` and run `build_docs` again to
see the change on the next request. An open page reloads itself when a template, static file or
Python module changes, through `django-browser-reload` and `django-watchfiles` from the
development dependencies. The seeded
content is the DCMI Type Vocabulary, a real vocabulary published by the Dublin Core Metadata
Initiative, imported from a SKOS file that declares its own vocabulary, and Data Collection
Methods, a short vocabulary loaded from a file that declares none, so the command creates the
vocabulary for it first and imports into that. Both are declared in the demo's
`CONTROLLED_VOCABULARIES` setting, and `seed_demo` loads them with `sync_vocabularies`. Data Collection Methods' own page also carries one of
each kind of collection — "Primary data collection methods" (unordered) and "Typical project
workflow" (ordered) — both loaded through the same SKOS file, so the side panel's collections are
never empty on a fresh checkout.

Following "Fieldwork" from that page reaches a concept's own page: its definition, its narrower
concept "Survey" (stored as "Survey" carrying `skos:broader` to "Fieldwork", shown here as the
derived `skos:narrower`), and, below the definition list, the two collections that gather
it — including "Typical project workflow", whose own page in turn shows every method it orders,
"Fieldwork" among them. `seed_demo` seeds this pair, and a related pair besides
("Remote sensing" / "Laboratory experiment"), so the concept and collection pages are never empty
on a fresh checkout either.

"Fieldwork" also carries a note only in German, alongside its English-only definition. Reading the
page in German — `curl -H "Accept-Language: de" http://127.0.0.1:8000/browse/data-collection-methods/fieldwork/`,
or a browser configured for German — shows the German note directly and falls back to the English
definition, exactly as [a concept's own page](#a-concepts-own-page) above describes.

`seed_demo` is destructive and idempotent: it clears every vocabulary before loading, so running
it again returns the demo to the same seeded state whatever was added or removed before —
including anything entered through the admin.

The seeded accounts are `regular.user`, `staff.user` and `super.user`, all with the password
`password`. `super.user` can sign in at `http://127.0.0.1:8000/admin/` to look at the stored
vocabularies and records. The admin there belongs to the demo project, not to the package:
`demo/admin.py` registers `ConceptScheme` and `Record` with the demo's own admin site. The package
registers nothing, so installing it adds no admin of its own — a project decides for itself which
of its models it manages that way.

The demo is not a production configuration: `DEBUG` is on, the database is a local SQLite file,
and the secret key is a throwaway value committed in `demo/settings.py`. Do not deploy it as-is.

---

Next: [importing a published vocabulary](importing.md).
