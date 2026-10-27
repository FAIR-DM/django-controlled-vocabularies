# Choose a concept

`ConceptField` and `MultiConceptField` render as a search-as-you-type control, both in your own
forms and on Django admin pages.

## Choosing a concept by typing

`ConceptField` and `MultiConceptField` render as a search-as-you-type control by default. A project
declaring either gets it without naming a widget, writing an endpoint, or configuring anything
per field — an ordinary `ModelForm` built from the model already renders it.

Getting it working outside the admin takes three steps, done once per project rather than once
per field. In the order a developer does them:

1. **Include the route.** The package carries its own search endpoint in
   `controlled_vocabularies.urls`; include it once, at an address of your choosing:

   ```python
   from django.urls import include, path

   urlpatterns = [
       ...
       path("vocab/", include("controlled_vocabularies.urls")),
   ]
   ```

2. **Add `"django_tomselect"` to `INSTALLED_APPS`.** The control's templates and static assets
   live inside that package, and Django only finds another package's templates and static files
   through an installed app — no amount of work in this package moves that.

3. **Add `"django_tomselect.middleware.TomSelectMiddleware"` to `MIDDLEWARE`.** Without it, the
   control still renders, but as a plain `<select>` carrying no search box and no JavaScript at
   all — nothing errors, nothing warns at render time, and the control simply doesn't work.

Skip any of the three and `manage.py check` reports it: a missing route
(`controlled_vocabularies.W002`), a missing `INSTALLED_APPS` entry (`controlled_vocabularies.W003`),
or a missing middleware entry (`controlled_vocabularies.W004`), each naming exactly what to add.
A render that reaches the missing-route case despite the warning raises `ImproperlyConfigured`
naming both the route and the `INSTALLED_APPS` entry, rather than the underlying library's own
`NoReverseMatch` against a URL pattern you never wrote.

A search matches what a person types against every preferred, alternative and hidden label of a
concept, in any language, using the `search_text` copy kept on each `Record`. It returns, per
concept, its URI, its name in the active language, and the name of the vocabulary it belongs
to — nothing else, no notes or alternative labels. Only concepts are searched, so a collection is
never offered. The results are restricted to whatever vocabularies the field declares, the same restriction that
already governs which concepts a form accepts; a field naming no vocabulary searches every concept
in the database. The endpoint carries **no permission rule by default** — it serves the same
concept data the rest of this package publishes at stable URIs. A project holding vocabularies it
does not want searched restricts the include instead, at whatever access level fits.

The control is a form field and its widget, both in `controlled_vocabularies.forms`. A
`ConceptField` renders as `ConceptChoiceField` with `ConceptWidget`, and a `MultiConceptField` as
`MultiConceptChoiceField` with `MultiConceptWidget`. A form that declares one of these fields itself
uses the same classes. The control submits each chosen concept's URI.

The control needs a browser running JavaScript. Without it, both fields still work as an ordinary
required-relation form field; only the search-as-you-type behaviour is unavailable.

## Searching a large vocabulary

A search matches its text anywhere in a label, ignoring case, in the control and on a
vocabulary's page alike. How much of the database it reads depends on the database:

- **PostgreSQL.** The package's migrations add trigram indexes over each concept's preferred
  label and its `search_text`, so a search of three or more characters reads the index rather
  than every concept. A search of one or two characters is too short for a trigram index and
  reads every concept of the vocabulary.
- **Any other database.** The same search works unchanged, with no index behind it, and reads
  every concept of the vocabulary. That costs more as a vocabulary grows, so a site holding
  vocabularies of tens of thousands of concepts is better served by PostgreSQL.

The first page, shown before anything is typed, is read off an index in name order on every
database, so opening a vocabulary's page costs the same whatever its size. The control does the
same for a field naming one vocabulary. A field naming several, or none, sorts the concepts it
allows before taking the first page.

What PostgreSQL needs for this is in [preparing PostgreSQL for concept search](prepare-postgresql-for-concept-search.md).

## Choosing a concept in the admin

A model that declares `ConceptField` or `MultiConceptField` gets the same search-as-you-type control
on its Django admin pages once it's registered — nothing further to configure. `ModelAdmin` builds
the field the same way it builds any other, and the wiring is the three steps above: the route,
`django_tomselect` in `INSTALLED_APPS`, and its middleware. The admin adds nothing to that list.

A concept is chosen on these pages, never created or edited there. Django ordinarily puts an
add, change, delete or view link beside a related field so a person filling in a form can manage
the related record without leaving it. None of the four appears beside a concept field, whether or
not this package's own models are registered in the admin, and whatever permissions the signed-in
person holds. Concepts arrive by [importing](load-the-vocabularies-your-site-uses.md) a published vocabulary — a controlled
vocabulary stops being controlled the moment a data-entry form can invent or edit one.

Where the admin presents the field read-only — listed in `readonly_fields`, or because the signed-in
person may view the page but not change it — the concept is shown by its name and no control
renders. This is Django's own read-only presentation, not this package's: with `Record` registered,
a single concept links to its own change page. Several concepts, on a `MultiConceptField`, always
render as plain text. The package neither adds to this nor suppresses it.

A project can still ask for a different control the way it would for any other related field:

- `autocomplete_fields` renders Django's own autocomplete widget instead — Django requires the
  related model to be registered and searchable, as it does for any field named this way.
- `raw_id_fields` renders Django's plain identifier input, which takes the concept's URI, with the
  magnifying-glass lookup link Django gives every field named this way. That link opens a list to pick from — it selects a
  concept, it does not create one.
- A `ModelForm` declaring its own widget for the field via `Meta.widgets`, passed to
  `ModelAdmin.form`, renders that widget.
- `readonly_fields` renders the read-only presentation described above.

The first three still refuse the add, change, delete and view affordances, the same as the default
control, and saving and validation carry on unchanged: a concept outside the field's named
vocabularies is refused, and a legitimate one still saves.

One piece of text on these pages is Django's rather than this package's. Under a multi-value field
the admin adds *Hold down "Control", or "Command" on a Mac, to select more than one.* It is the
same sentence the admin puts under any multiple-select field, and it does not describe this
control: concepts are added by typing and picking, and removed one at a time.
