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

Import published SKOS controlled vocabularies into Django, and reference their concepts from your
own models.

Research data infrastructure runs on controlled vocabularies, and the ones worth using are already
published: by standards bodies, by research communities, by other projects. Django has no native
way to bring one in and point a record at its terms. This app closes that gap by importing a
published vocabulary as ordinary relational data, so a model references a concept the way it
references any other row, with no hand-edited RDF and no triplestore to operate. It supersedes and
retires `skos-builder` and `django-research-vocabs`.

You can declare the published SKOS vocabularies your site uses and load them all, from files or
URLs, with one command, attach their concepts to your own models through a single field, pick one
through a search-as-you-type control in your forms and in the Django admin, and browse what the
site holds through an opt-in set of read-only pages.

- [Scope and philosophy](#scope-and-philosophy)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Changelog](#changelog)
- [License](#license)

## Scope and philosophy

This package **imports published vocabularies and lets your models reference their concepts.** A
vocabulary belongs to whoever published it. The package's job is to hold it faithfully and make
its concepts something a Django model can point at, not to author it.

A vocabulary here lives **in the database, not in an RDF file or a triplestore**. Each vocabulary,
and each concept and collection in it, is one row holding a JSON document of the statements its
publisher made, the database is the source of truth, and RDF is read only at the import boundary.
That puts everything Django already does well — forms, permissions, indexed search, referential
integrity — to work on referencing vocabularies, and lets a vocabulary of tens of thousands of
concepts change as data rather than as a code release of every project that uses it.

**It deliberately is:**

- SKOS-focused.
- A Django app — installable into any Django project (notably FairDM) and runnable standalone.
- A **reference** — a field attaches a concept to your model, and a concept a
  record still points at cannot be deleted. Whether a concept is deprecated is what its publisher
  says.
- A faithful keeper of what was published — an import keeps every statement it reads, in every
  language, including statements in vocabularies other than SKOS.
- Multilingual — a concept holds labels and definitions in any number of languages.
- A graph, not a flat list — concepts link to one another through a broader/narrower hierarchy
  (shown from both ends, and a concept may sit under several broader concepts) and a symmetric
  related association, and may point at concepts in other vocabularies through mappings.
- Organised into collections where the publisher defines them — named groupings of a vocabulary's
  concepts, optionally in a deliberate order, separate from the hierarchy.

**It deliberately is not:**

- A vocabulary editor or publisher — vocabularies arrive by import and are read-only references.
  Authoring a vocabulary and serving vocabularies as RDF are set aside until a project needs them,
  and extending an imported vocabulary with your own terms is out of scope.
- A general RDF/OWL toolkit — SKOS is what the package understands. Statements in other
  vocabularies are kept and shown, but not interpreted.
- A triplestore or SPARQL endpoint — the relational database is the store.
- A replacement for rdflib — rdflib is used only to parse at the boundary.
- A reasoner — no OWL inference.

**Tie-breaks, when principles collide:** the database is the source of truth over RDF fidelity in
memory, keeping what was published over schema neatness, stable concept URIs over convenient
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

Attach a concept to your own model. The field names its vocabulary by URI, and says where the
vocabulary is published. A file shipped with the project is the most dependable source, and an
http(s) address works too:

```python
from pathlib import Path

from django.db import models

from controlled_vocabularies.fields import ConceptField, Vocabulary

ROCK_TYPE = Vocabulary(
    "https://vocab.example.org/rock-type",
    source=Path(__file__).parent / "vocabularies" / "rock-type.ttl",
)


class Specimen(models.Model):
    name = models.CharField(max_length=200)
    rock_type = ConceptField(vocabulary=ROCK_TYPE)
```

Load every vocabulary your models name, on first install and again on every deploy:

```bash
python manage.py sync_vocabularies
```

A vocabulary no field names, for a field open to any concept, is declared in settings and loaded
by the same command:

```python
# settings.py
CONTROLLED_VOCABULARIES = {
    "keywords": {"source": BASE_DIR / "vocabularies" / "keywords.ttl"},
}
```

The field is a `ForeignKey` to a `Record`, the model that holds each concept, restricted to the
vocabulary you name. Its column holds the concept's URI, so the value reads on its own without a
join. A form built from
the model offers that vocabulary's concepts through a search box, a concept from anywhere else is
refused, and a concept a record still points at cannot be deleted. Read it back by label or by
address:

```python
specimen.rock_type  # the attached Record, or None
specimen.get_rock_type_label()  # its name in the active language
specimen.get_rock_type_uri()  # its URI
```

## Documentation

The full manual lives in
[`docs/`](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/index.md):
[configuration](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/configuration.md),
[attaching concepts to your models](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/fields.md),
[choosing a concept](https://github.com/FAIR-DM/django-controlled-vocabularies/blob/main/docs/how-to/choosing-a-concept.md),
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
