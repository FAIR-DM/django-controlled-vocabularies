# django-controlled-vocabularies

Import published SKOS controlled vocabularies into Django, and reference their concepts from your
own models.

The [README](../README.md) is the front door — what this package is, what it deliberately is not,
how to install it, and the shortest example that works. These pages are the manual.

## Using the package

- **[Configuration](configuration.md)** — the base address identifiers are composed from, and how a
  row's URI and slug are made and kept.
- **[Attaching concepts to your models](fields.md)** — `ConceptField` and `MultiConceptField`,
  restricting either to the vocabularies you name, and narrowing further to the members of a
  collection.
- **[Choosing a concept](search.md)** — the search-as-you-type control in your own forms and on
  Django admin pages, and the three wiring steps it needs.
- **[Browsing vocabularies](browsing.md)** — the opt-in `ui` extra: the list of vocabularies, a
  page for each vocabulary, concept and collection, and the runnable demo project.
- **[Importing a published vocabulary](importing.md)** — reading SKOS from a file or a URL, what an
  import keeps, what the import report tells you, and the management command.

## Contributing

- **[Testing standards](contributing/standards/testing.md)** — what gets a test, the test-first
  cycle, how tests and fixtures are structured, and the coverage floors.
- **[Code documentation standards](contributing/standards/code-documentation.md)** — docstrings,
  component annotations and comments.
- **[Django standards](contributing/standards/django.md)** — where code lives, and when a new
  abstraction is worth adding.

## Direction and decisions

- **[Roadmap](ROADMAP.md)** — which release delivers what, and how versions are gated.
- **[Goals](../GOALS.md)** — the enduring directions the project steers toward.
- **[Decision records](adr/)** — one file per architecturally significant decision, kept for the
  reasoning behind it.
- **[Domain terminology](../CONTEXT.md)** — what a vocabulary, a concept and a collection mean here.
- **[Changelog](../CHANGELOG.md)** — what changed in each release.
