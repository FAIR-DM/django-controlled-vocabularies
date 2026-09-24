# Browsing vocabularies

The `ui` extra adds an opt-in, reader-facing front end: a list of every vocabulary the site holds,
and a page of its own for each vocabulary, concept and collection.

```bash
pip install django-controlled-vocabularies[ui]
```

## Finding a vocabulary

The `ui` extra adds one reader-facing page: every vocabulary the site holds, in alphabetical
order, each entry showing its description, how many concepts it holds, and whether it was
authored here or imported from a publisher — with the publisher's own identifier shown for an
imported one. A site holding no vocabularies says so rather than showing an empty list.

A search box narrows that list by a vocabulary's name and description — not by the concepts it
holds; finding a concept without already knowing which vocabulary holds it is not something this
page does. The term travels in the page's address (`?q=`), so a narrowed list can be linked to or
bookmarked and returned to. A second word **widens** the results rather than narrowing them:
matching is OR across every word and both fields, not AND, which is the opposite of what a search
box usually implies. A search matching nothing says so and repeats what was searched for.

A sort control offers the list by name, A-Z or Z-A. That choice travels in the address as `?o=`,
next to any search term, so a searched and sorted list is still one link you can share. Only the
orderings the view declares are honoured. Anything else in `?o=` is ignored rather than passed to
the database, and the page comes back in its default order.

There is no way to filter the list. Filtering needs an axis, and a vocabulary has none that would
suit every site.

Case is ignored, with one limit that belongs to the database rather than to this package. SQLite
folds case for ASCII letters only, so a vocabulary named *Ökologie* is found by *ÖKOLOGIE* and not
by *ökologie*. PostgreSQL folds the whole of Unicode and matches either way. Django
[documents this](https://docs.djangoproject.com/en/stable/ref/databases/#substring-matching-and-case-sensitivity)
and does not work around it, and neither does this package, because nothing above the database can.
It matters for any site whose vocabularies are named in German, French, Greek or Russian.

The page carries **no permission rule of its own**. Every vocabulary in the database is listed to
anyone who reaches the URL, exactly as the concept search endpoint serves anyone who reaches
it, and for the same reason: a package cannot guess a project's access policy. A vocabulary has no
draft state, so one still being authored is listed from the moment it exists. A site that needs the
page restricted wraps the include where it mounts these routes.

## Wiring it up

This section adds to the package's base configuration rather than replacing it: `django_tomselect`
and its middleware are still required, as [choosing a concept by typing](search.md#choosing-a-concept-by-typing)
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
    # "mvp" before "crispy_tailwind": django-mvp ships an override of crispy-tailwind's
    # help-text template, and the first app to declare a template path wins.
    "mvp",
    "crispy_forms",
    "crispy_tailwind",
    "controlled_vocabularies.ui",
]

# crispy-forms 2.7's get_template_pack() has no default, and the {% crispy %} tag validates
# the pack against CRISPY_ALLOWED_TEMPLATE_PACKS at template-compile time — django-mvp's own
# templates carry the tag, so both settings are required even though this page renders no
# form of its own.
CRISPY_TEMPLATE_PACK = "tailwind"
CRISPY_ALLOWED_TEMPLATE_PACKS = ["tailwind"]

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

**One thing is still missing.** When a search on this page matches nothing, it names the term but
offers no link back to the unsearched list. Clearing the box and pressing the button does the same
job, so the page is not a dead end, but the link belongs there. It has to go in the page's actions
area, and django-mvp offers no way to add anything there without replacing the whole page template
([django-mvp#291](https://github.com/django-mvp/django-mvp/issues/291)).

Until django-mvp 0.19.2 the search box on this page could not be submitted at all: its input was
tied to a form only the filter control created
([django-mvp#282](https://github.com/django-mvp/django-mvp/issues/282), tracked here as
[#147](https://github.com/FAIR-DM/django-controlled-vocabularies/issues/147)). This package
waited for the upstream fix rather than shipping a patched copy of django-mvp's page, and the
version floor moved once the fix was released. An override in a package like this one outlives the
release that makes it unnecessary, and nothing ever reports that it has
([ADR 0015](adr/0015-upstream-defects-are-waited-on-not-worked-around.md)).

The page is served by `VocabularyListView`, in `controlled_vocabularies.ui.views`. A project that
wants a different presentation subclasses it and routes its own path at the same view — the
queryset, its ordering and its concept count come with the class, so an override that only changes
`list_item_template` keeps every guarantee above:

```python
from controlled_vocabularies.ui.views import VocabularyListView


class BrandedVocabularyListView(VocabularyListView):
    list_item_template = "myproject/vocabulary_card.html"
```

## A vocabulary's own page

Every vocabulary the site holds has its own address — the same one its identifier composes
(`ConceptScheme.uri`) when the site is configured as this page describes. The page's title is
the vocabulary's name. Above the list of concepts it holds it shows the vocabulary's description,
truncated the same way and for the same reason as the list entry above, and how the vocabulary was
obtained: an imported vocabulary's page shows the publisher's own identifier; one authored here
shows its own address instead. Either way the identifier is a link — to the publisher's site for
an imported vocabulary, or back to the page itself for one authored here.

Below that, every concept the vocabulary holds — and only that vocabulary's — in one flat,
alphabetical list: nothing several levels down a broader/narrower chain is nested under one above
it. Alphabetical order follows the label actually shown, not necessarily the one stored: a concept
carrying a preferred label in the reader's own language shows that one; a concept with none in that
language falls back to its label in the vocabulary's own default language. A row names a concept and
nothing more — no definition, no note, no identifier, and no relation to another concept.

**How concepts relate to one another is not shown here.** Broader, narrower and related links, and
a concept's own page, are a later feature's (#142); until then a concept on this list is not
something a reader can follow to anywhere else. A vocabulary holding no concepts says so, in
wording distinct from the page's other empty state, and the rest of the page — its description and
provenance — still renders.

Above the list of concepts, the page also names the vocabulary's **collections** — curator-made
groupings of its concepts (`skos:Collection` / `skos:OrderedCollection`) that the broader/narrower
relations do not express. Each is named, and one whose members carry a deliberate order is shown
distinguishably from one that does not. **A collection cannot be opened from here**: neither its
own page nor its members' names are reached by following anything on this page — that address
belongs to #142, the same feature that gives a concept its own page, so a collection is named and
nothing more until it lands. A vocabulary holding no collections shows no such section at all —
most vocabularies have none, and a section that is only ever present-but-empty would be noise on
every page but one.

A search box narrows the list of concepts by every name a term goes by: a concept's preferred
label in any language it carries, its alternative labels, and its hidden labels — never its
definition or any other note. A hidden label is matched and never shown: searching for one finds
the concept it names without ever displaying the label itself, which is the whole point of
keeping it hidden. As with the list of vocabularies above, the term travels in the page's own
address (`?q=`), so a narrowed list can be linked to, bookmarked and returned to, and it reaches
every concept in the vocabulary before paging divides the results — not only the page being
viewed. A search matching nothing says so, repeats what was searched for, and offers a link back
to the whole vocabulary.

Case is ignored, with the same database-dependent limit disclosed above: SQLite folds ASCII
letters only, so a concept labelled *Ökologie* is found by *ÖKOLOGIE* and not by *ökologie*;
PostgreSQL folds the whole of Unicode and matches either way
([ADR 0014](adr/0014-database-collation-differences-are-disclosed-not-repaired.md)).

Searching by address works the same as searching in the box: the demo project's own DCMI Type
Vocabulary carries a concept named *Dataset* with a hidden label of `Datset`, a plausible
misspelling — `?q=Datset` narrows the page to *Dataset* without the misspelling itself ever
appearing in the response, and the narrowed address can be shared and bookmarked the same as any
other. Unlike the list of vocabularies, a search here that matches nothing offers a link back to
the unsearched vocabulary: this page has a template of its own to put that link in, where the list
of vocabularies has none.

A sort control offers the concepts by label, A-Z or Z-A. The choice travels in the address as
`?o=`, next to any search term, exactly as it does on the list of vocabularies. It sorts by the
label a reader actually sees rather than the stored one, so a German reader gets the concepts in
German alphabetical order and not in the vocabulary's own default language.

Reverse the page by name, passing the vocabulary's slug:

```python
reverse("controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": vocabulary.slug})
```

**The browsing routes must be mounted at the same path `CONTROLLED_VOCABULARIES_BASE_URI`
composes against**, or a vocabulary's identifier does not lead back to its own page. Mounting the
routes at `browse/` means the setting's path has to be `/browse`, not the package's own default:

```python
CONTROLLED_VOCABULARIES_BASE_URI = "https://example.org/browse"
```

`manage.py check` reports `controlled_vocabularies.ui.W001` — a warning, not an error, since a
project may serve identifiers through a reverse proxy this package cannot see — when the two
disagree, naming the mismatched paths. It is silent once they agree, and silent too if the
browsing routes are not mounted at all.

The page is served by `VocabularyDetailView`, in `controlled_vocabularies.ui.views`, and is
subclassed the same way as the list above.

## A concept's own page

Every concept has its own address — the same one `Concept.uri` composes when the site is
configured as this page describes. The page is a definition list of everything the database
records about the concept, other than its hidden labels, each row labelled by the SKOS property it
was recorded under: its type (`rdf:type`), its preferred label (`skos:prefLabel`), its alternative
labels (`skos:altLabel`), each note it carries under the property of its own kind (`skos:definition`,
`skos:scopeNote`, and the rest of the six documentary notes SKOS defines), its broader concept, its
narrower concepts and its related concepts (`skos:broader` / `skos:narrower` / `skos:related`), and
the vocabulary it belongs to (`skos:inScheme`). Every record-valued row links to that record's own
page here. A property the concept carries no value for contributes no row at all — never an empty
one — so a concept carrying nothing beyond its label shows only its label, its type, its identifier
and its vocabulary.

The concept's own canonical identifier leads the page, directly beneath its title, so a reader
citing the record does not have to scroll past everything it says about itself to find it. The
breadcrumb trail above names the site's home, the vocabulary holding the concept, and the concept
itself.

Each row's own term — `skos:definition`, `skos:broader`, and the rest named above — is a CURIE
derived from the SKOS predicate the value was recorded under, by `skos_curie()` in
`controlled_vocabularies.exchange.mapping`; it refuses a predicate outside the SKOS namespace
rather than mangling one into a nonsensical short form. A record-valued row's own displayed text is
a different short form — `{vocabulary slug}:{record slug}`, `geology:granite` for a concept
"granite" in a vocabulary slugged "geology".

A CURIE abbreviates a URI, and both kinds on the page disclose the URI they stand for on hover
rather than printing it. A term's comes from `curie_uri()` in the same module, which expands a
prefixed name against the namespaces the package declares and refuses one it does not. A
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

Every value is shown in the language the site is being read in, exactly as the vocabulary page
above shows a concept's label: where the concept has none in that language, it falls back to the
vocabulary's own default language, one language at a time, never every language a value was
recorded in.

The concept's own identifier is shown as a link, the same treatment its vocabulary's own page gives
a vocabulary's: an imported concept shows its publisher's identifier, one authored here shows this
site's own composed address for it. Either way the page itself is **read-only** — it carries no
editing or deletion control of its own, and no permission rule beyond what the project mounting
these routes chooses to add.

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
the same way as the pages above. The rows themselves come from
`concept_property_rows(concept, language, default_language=None)`, in the same module — the seam a
project reaches for to build its own page, or its own rendering of a report, over the same ordered
rows this one renders. Passing no `default_language` asks for exactly what the concept carries in
`language`, with no fallback to the vocabulary's own default.

## A collection's own page

Every collection has its own address too, at a distinct segment from a concept's — the same one
`Collection.uri` composes — so a concept and a collection in one vocabulary may share a slug and
both stay reachable. The page is a definition list built the same way a concept's is: its name
(`skos:prefLabel`), a type row distinguishing an ordered collection from an unordered one
(`skos:Collection` or `skos:OrderedCollection`), and its members under the membership property
matching its kind — `skos:member` for an unordered collection, `skos:memberList` for an ordered
one, whose members appear in the sequence their positions record. Membership is one row however
many members a collection holds — the property is stated once, with every member listed beside it,
rather than repeated per member. A collection holding no members says so in plain language rather
than showing an empty membership row.

Every record-valued row links to that record's own page here and discloses its canonical identifier
the same way a concept's page does. The collection's own identifier leads the page beneath its
title, its breadcrumb trail names the vocabulary holding it, and the page is equally **read-only**,
carrying no editing or deletion control of its own.

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
subclassed the same way as the pages above. The rows themselves come from
`collection_property_rows(collection)`, in the same module — the same seam
`concept_property_rows` offers over a concept's own rows.

## Try it: the demo project

The repository carries a runnable demo of the pages above, wired the same way this page
documents. From a fresh clone, with dependencies installed:

```bash
uv sync --extra ui

uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py runserver
```

The three commands run through `uv run` so they use the environment the install just built,
whatever `python` on the shell's path happens to be — on many systems there is no `python` there
at all.

`migrate` builds the database, `seed_demo` loads two small vocabularies into it, and `runserver`
serves the site at `http://127.0.0.1:8000/`, which redirects straight to the populated,
searchable vocabulary list at `http://127.0.0.1:8000/browse/`. The seeded content shows both
kinds of entry the list distinguishes: the DCMI Type Vocabulary, a real vocabulary published by
the Dublin Core Metadata Initiative, imported from a SKOS file; and Data Collection Methods, a
short vocabulary authored here, with no publisher of its own. Data Collection Methods' own page
also carries one of each kind of collection — "Primary data collection methods" (unordered) and
"Typical project workflow" (ordered) — both loaded through the same SKOS file, so the collections
section described above is never empty on a fresh checkout.

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

To add a vocabulary by hand and watch it appear on the list, give yourself an account first and
sign in at `http://127.0.0.1:8000/admin/`:

```bash
uv run python manage.py createsuperuser
```

The admin form there belongs to the demo project, not to the package: `demo/admin.py` registers
the vocabulary model with its own admin site. The package registers nothing, so installing it
adds no admin of its own — a project decides for itself which of its models it curates that way.

The demo is not a production configuration: `DEBUG` is on, the database is a local SQLite file,
and the secret key is a throwaway value committed in `demo/settings.py`. Do not deploy it as-is.

---

Next: [importing a published vocabulary](importing.md).
