(demo-project)=
# Try it: the demo project

The repository carries a runnable demo of the browsing pages, wired the same way
[the guide to adding them](how-to/add-the-browsing-pages-to-your-site.md) documents. From a fresh clone, with dependencies installed:

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
definition, exactly as [a concept's own page](reference/a-concepts-own-page.md) describes.

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
