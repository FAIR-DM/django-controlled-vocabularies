# django-controlled-vocabularies

[![Tests](https://github.com/FAIR-DM/django-controlled-vocabularies/actions/workflows/tests.yml/badge.svg)](https://github.com/FAIR-DM/django-controlled-vocabularies/actions/workflows/tests.yml)
[![Build](https://github.com/FAIR-DM/django-controlled-vocabularies/actions/workflows/build.yml/badge.svg)](https://github.com/FAIR-DM/django-controlled-vocabularies/actions/workflows/build.yml)
[![Publish](https://github.com/FAIR-DM/django-controlled-vocabularies/actions/workflows/publish.yml/badge.svg)](https://github.com/FAIR-DM/django-controlled-vocabularies/actions/workflows/publish.yml)
[![Coverage](https://codecov.io/gh/FAIR-DM/django-controlled-vocabularies/branch/main/graph/badge.svg)](https://codecov.io/gh/FAIR-DM/django-controlled-vocabularies)
[![PyPI](https://img.shields.io/pypi/v/django-controlled-vocabularies)](https://pypi.org/project/django-controlled-vocabularies/)
[![Development status](https://img.shields.io/pypi/status/django-controlled-vocabularies)](https://pypi.org/project/django-controlled-vocabularies/)
[![Python](https://img.shields.io/pypi/pyversions/django-controlled-vocabularies)](https://pypi.org/project/django-controlled-vocabularies/)
[![Django](https://img.shields.io/pypi/djversions/django-controlled-vocabularies)](https://pypi.org/project/django-controlled-vocabularies/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Licence](https://img.shields.io/github/license/FAIR-DM/django-controlled-vocabularies)](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/LICENSE)

Manage, publish, and consume SKOS controlled vocabularies in Django.

Research data infrastructure runs on controlled vocabularies, but Django has no native way to manage
or consume them, and the existing editors are foreign stacks, unmaintained, or deployment-heavy.
This app closes that gap for research organisations by treating a vocabulary as ordinary relational
data: no hand-edited RDF, no code release to add a term, and no triplestore to operate. It
supersedes and retires `skos-builder` and `django-research-vocabs`.

**v0.1.0 covers the consuming half.** You can import a published SKOS vocabulary from a file or a
URL, attach its concepts to your own models through a single field, pick one through a
search-as-you-type control in your forms and in the Django admin, and browse what the site holds
through an opt-in set of pages. A curator can also create, edit and delete a vocabulary from those
pages. Managing the concepts inside a vocabulary and serving RDF back out at those addresses are the
next releases — see
[the roadmap](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/ROADMAP.md).

- [Scope and philosophy](#scope-and-philosophy)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Changelog](#changelog)
- [License](#license)

## Scope and philosophy

A vocabulary here is **relational data, not a document**. Concepts are Django models, the database
is the source of truth, and RDF is a projection produced only at the import and export boundary.
That puts everything Django already does well — forms, permissions, indexed search, referential
integrity — to work on vocabulary management, and lets a vocabulary scale to tens of thousands of
concepts and evolve as data rather than as code.

**It deliberately is:**

- SKOS-focused.
- A Django app — installable into any Django project (notably FairDM) and runnable standalone.
- Both a **manager** (author, edit, version, publish) and a **consumer** (attach concepts to your
  models via a field, and serve RDF at stable URIs).
- Multilingual — a concept holds labels and definitions in any number of languages, with one
  preferred label per language. Each vocabulary picks the language that anchors its concept
  addresses, and a curator can override any concept's slug.
- A graph, not a flat list — concepts link to one another through a broader/narrower hierarchy
  (navigable both ways, and a concept may sit under several broader concepts) and a symmetric
  related association, all within one vocabulary.
- Organisable into collections — a curator can gather a vocabulary's concepts into named
  collections, optionally in a deliberate order, separate from the hierarchy and from any other
  collection a concept belongs to.

**It deliberately is not:**

- A general RDF/OWL toolkit — the SKOS-only scope is intentional.
- A triplestore or SPARQL endpoint — the relational database is the store.
- A replacement for rdflib — rdflib is used only to parse and serialize at the boundary.
- A reasoner — no OWL inference.
- An editor for external vocabularies — imported vocabularies are read-only references, and
  extending one with your own terms is out of scope.
- A faithful mirror of an imported vocabulary — imports are normalised to what the app supports
  (its configured languages, for one), and unsupported languages and constructs are not stored.
  Nothing is dropped in silence: everything set aside is named in the import report.

**Tie-breaks, when principles collide:** the database is the source of truth over RDF fidelity in
memory, lossless round-tripping over schema neatness, stable concept URIs over convenient
identifiers, vocabulary-as-data over vocabulary-as-code, and SKOS fidelity over generality.

## Requirements

- Python 3.11 or later. The optional `ui` extra needs 3.12 or later.
- Django 5.2 or later.

## Installation

```bash
pip install django-controlled-vocabularies
```

Add the app, include its routes, and run the migrations:

```python
# settings.py
INSTALLED_APPS = [
    ...
    "controlled_vocabularies",
    "django_tomselect",
]

MIDDLEWARE = [
    ...
    "django_tomselect.middleware.TomSelectMiddleware",
]

CONTROLLED_VOCABULARIES_BASE_URI = "https://vocab.example.org/vocabularies"
```

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    ...
    path("vocab/", include("controlled_vocabularies.urls")),
]
```

```bash
python manage.py migrate
```

`django_tomselect` and its middleware carry the search-as-you-type control the concept fields
render by default. `manage.py check` names anything still missing, and the reader-facing browsing
pages are an opt-in extra — both are covered in the
[documentation](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/index.md).

## Quick start

Import a published vocabulary, then attach one of its concepts to your own model:

```bash
python manage.py import_skos https://example.org/vocabularies/rock-type.ttl
```

```python
from django.db import models

from controlled_vocabularies.fields import ConceptField


class Specimen(models.Model):
    name = models.CharField(max_length=200)
    rock_type = ConceptField(vocabulary="rock-type")
```

The field is a `ForeignKey` to a concept, restricted to the vocabulary you name. A form built from
the model offers that vocabulary's concepts through a search box, a concept from anywhere else is
refused, and a concept a record still points at cannot be deleted. Read it back by label or by
address:

```python
specimen.rock_type              # the attached Concept, or None
specimen.get_rock_type_label()  # its preferred label in the active language
specimen.get_rock_type_uri()    # its URI
```

## Documentation

The full manual lives in
[`docs/`](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/index.md):
[configuration](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/configuration.md),
[attaching concepts to your models](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/fields.md),
[choosing a concept](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/search.md),
[browsing vocabularies](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/browsing.md),
and [importing a published vocabulary](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/importing.md).

## Contributing

Bug reports and feature requests are welcome on the
[issue tracker](https://github.com/FAIR-DM/django-controlled-vocabularies/issues). The repository
carries a runnable demo project, and
[getting it running](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/browsing.md#try-it-the-demo-project)
is the shortest route to a working development checkout.

## Changelog

Every release is recorded in
[CHANGELOG.md](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/CHANGELOG.md).

## License

MIT — see [LICENSE](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/LICENSE).

---

Where the project is going:
[GOALS.md](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/GOALS.md) and the
[roadmap](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/ROADMAP.md).
