# Introduction

Import published SKOS controlled vocabularies into Django, and reference their concepts from your
own models.

The [README](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/README.md) is the
front door — what this package is, what it deliberately is not, how to install it, and the
shortest example that works. These pages are the manual.

## Using the package

- **[Tutorial](tutorial.md)** — run the demo project and look around it.
- **[How-to guides](how-to/index.md)** — attach concepts to your models, load vocabularies, add the
  browsing pages.
- **[Reference](reference/index.md)** — settings, the import report and the pages the browsing app serves.
- **[Explanation](explanation/index.md)** — how identifiers are made, what an import keeps and why.

```{toctree}
:caption: Using the package
:hidden:

tutorial
how-to/index
reference/index
explanation/index
```

## Contributing

- **[Testing standards](contributing/standards/testing.md)** — what gets a test, the test-first
  cycle, how tests and fixtures are structured, and the coverage floors.
- **[Code documentation standards](contributing/standards/code-documentation.md)** — docstrings,
  component annotations and comments.
- **[Django standards](contributing/standards/django.md)** — where code lives, and when a new
  abstraction is worth adding.
- **[Documentation standards](contributing/standards/documentation.md)** — how pages are split into
  tutorial, how-to, reference and explanation, and how the README quickstart is written.

```{toctree}
:caption: Contributing
:hidden:

contributing/standards/testing
contributing/standards/code-documentation
contributing/standards/django
contributing/standards/documentation
```

## Direction and decisions

- **[Roadmap](ROADMAP.md)** — which release delivers what, and how versions are gated.
- **[Goals](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/GOALS.md)** — the
  enduring directions the project steers toward.
- **[Decision records](adr/index.md)** — one file per architecturally significant decision, kept
  for the reasoning behind it.
- **[Domain terminology](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/CONTEXT.md)**
  — what a vocabulary, a concept and a collection mean here.
- **[Changelog](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/CHANGELOG.md)**
  — what changed in each release.

```{toctree}
:caption: Direction and decisions
:hidden:

ROADMAP
adr/index
```
