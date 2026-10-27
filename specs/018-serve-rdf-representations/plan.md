# Implementation Plan: Serve a vocabulary or record as RDF from its page

**Branch**: `018-serve-rdf-representations` · **Date**: 2026-10-27 · **Spec**: [`spec.md`](./spec.md) ·
**Research**: [`research.md`](./research.md)

## Summary

A row's stored document is turned back into an `rdflib.Graph` by a new core function, exposed as
`ConceptScheme.to_graph()` and `Record.to_graph()`. A core table lists every serialization the
installed rdflib can write a graph in, with its names, media type and file extension. A UI mixin on
the vocabulary, concept and collection views reads `?format=` or negotiates `Accept`, and either
serves the page as today or writes the subject's graph in the chosen format. Each of the three
pages names four RDF alternatives in its document head.

No model field, migration, setting or URL changes.

## Technical context

- **Language**: Python 3.11+ for core, 3.12+ for the `ui` extra (unchanged).
- **Dependencies**: Django ≥ 5.2, rdflib (already a core dependency), django-mvp and
  django-cotton for the `ui` extra. Nothing new.
- **Testing**: pytest with pytest-django, the repo's `tests/` tree mirroring the source tree.
  Graph equality is asserted with `rdflib.compare.isomorphic`.
- **Scale**: one row's document per response. The whole-vocabulary export is not this feature.

## Constitution check

- **Article I (test-first)**: every task below writes its tests first.
- **Article IX (URI identity)**: the subject node is the row's stored `uri`, unchanged (FR-004).
- **Article XI (RDF fidelity)**: the graph holds every statement of the document. FR-012 is tested
  as an isomorphism between the response, parsed back, and the graph built from the document.
- **Article XII (i18n)**: the two refusal messages are `gettext_lazy` strings.
- No article is in tension. No complexity tracking needed.

## Design

### 1. `controlled_vocabularies/exchange/graph.py` (new, core)

```python
def document_graph(uri: str, document: dict, rdf_class: str) -> rdflib.Graph: ...
```

- Subject: `URIRef(uri)`.
- For each key: predicate `URIRef(Namespaces.expand(key))`. For each entry:
  - `@id` → `URIRef(entry["@id"])`.
  - `@value` → `Literal(value, lang=…)` when `@language` is present; `Literal(str(value),
    datatype=URIRef(Namespaces.expand(type)))` when `@type` is present; `Literal(value)` otherwise
    (a JSON number or boolean keeps rdflib's own datatype for it; a string stays plain).
  - Anything else is an embedded node: a fresh `BNode`, whose statements are added by the same
    function, recursively.
- `skos:memberList` is written as one RDF list (`rdflib.collection.Collection`) of its `@id`
  entries, in stored order, from a fresh blank-node head, not one triple per entry.
- `rdf:type` → `URIRef(Namespaces.expand(rdf_class))` is added when the document states no
  `rdf:type` (D1). When it states one, nothing is added, so an imported row comes out exactly as
  published.
- The graph binds the prefixes in `PREFIXES`, so Turtle and the like come out readable.

`Resource.to_graph()` on the abstract model calls it with the row's class: `"skos:ConceptScheme"`
for `ConceptScheme`, `self.type` for `Record`. Declared as a class attribute on `ConceptScheme`
(`rdf_class = "skos:ConceptScheme"`) and as a property on `Record` returning `self.type`, so
`to_graph()` is written once.

### 2. `controlled_vocabularies/exchange/serializations.py` (new, core)

```python
@dataclass(frozen=True)
class Serialization:
    name: str           # rdflib's short name, the one ?format= documents
    names: frozenset    # every name rdflib registers for the serializer, short and media type
    media_type: str     # what Content-Type carries
    negotiable: bool    # whether rdflib registers a media type for it, so Accept can pick it
    extension: str

    @classmethod
    def all(cls) -> list["Serialization"]: ...          # cached
    @classmethod
    def named(cls, name: str) -> "Serialization | None": ...
    @classmethod
    def for_media_type(cls, media_type: str) -> "Serialization | None": ...
    def serialize(self, graph: rdflib.Graph) -> bytes: ...
```

- Built from `rdflib.plugin.plugins(kind=Serializer)`, grouped by `(module_path, class_name)`.
  `patch` is excluded by name, with a comment saying why (research R2). `pretty-xml` is excluded
  too (D6).
- `name` is the shortest registered name with no `/` (`ttl`, `xml`, `nt`, `json-ld`, …), the
  spelling the alternate links and the refusal use. `media_type` is the registered name with a `/`
  if there is one, otherwise the override in `MEDIA_TYPES` (`pretty-xml`, `longturtle`, `nt11`,
  `hext`), otherwise `text/plain`.
- `extension`: `EXTENSIONS` override first, else the first suffix in
  `rdflib.util.SUFFIX_FORMAT_MAP` that maps to one of the names, else `name`.
- `serialize()` copies the graph into a `Dataset`'s default graph and writes that, for every
  format (D2).
- `all()` is computed once (`functools.cache`).

### 3. `controlled_vocabularies/ui/representations.py` (new, UI)

```python
class RepresentationMixin:
    def get_representation_subject(self): ...   # ConceptScheme or Record
    def get(self, request, *args, **kwargs): ...
    def dispatch(...): ...                      # patch_vary_headers(response, ["Accept"])
```

`get()`:

1. Decide the outcome first: the page, an RDF serialization, a 400 or a 406. When it is the page,
   call `super().get()` and resolve nothing here, since the page already resolves its record and
   is a 404 for a missing one. On every other path resolve the subject
   (`get_representation_subject()`) before answering, so an address naming nothing is a 404
   whatever is asked for (FR-011). The record views return `self.get_object()`; the vocabulary
   view returns `self.vocabulary`.
2. If `format` is in `request.GET`: `Serialization.named()`; unknown → 400 with the translatable message
   naming every short name, sorted (FR-007). Known → the RDF response, as a download.
3. Otherwise negotiate `["text/html", *negotiable media types]` with
   `request.get_preferred_type()`. `None` → 406 (FR-007). `text/html` → `super().get()`. An RDF type
   → the RDF response, inline, **unless** `request.accepted_type("text/html")` exists with a quality
   equal to the chosen type's, in which case the page (spec edge case, research R3).
4. The RDF response: `HttpResponse(s.serialize(subject.to_graph()), content_type=s.media_type)`,
   with `Content-Disposition` from `content_disposition_header(True, f"{slug}.{extension}")` on the
   `?format=` path only (FR-009).

Applied to `ConceptDetailView`, `CollectionDetailView` and `VocabularyDetailView`, leftmost in the
bases so its `get()` runs first. `VocabularyListView` is left alone (out of scope).

The template gets `rdf_alternates`: a context list of the four (`ttl`, `xml`, `json-ld`, `nt`) as
`{"media_type", "href"}`, `href` being `?format=<name>`.

### 4. Templates

- New Cotton component `cotton/controlled_vocabularies/rdf_alternates.html`: one
  `<link rel="alternate" type="…" href="…">` per entry of an `alternates` attribute.
- `concept_detail.html`, `collection_detail.html`, `conceptscheme_detail.html`: a
  `{% block head %}{{ block.super }}<c-controlled-vocabularies.rdf-alternates :alternates="rdf_alternates" />{% endblock %}`.

### 5. Documentation

- `docs/browsing.md` gains a section on the RDF a page returns: the two ways to ask, the formats,
  the precedence, the refusals, the alternates.
- `to_graph()` is documented in `docs/importing.md`, beside the import it mirrors.
- `CONTEXT.md` gains **Representation**.
- `docs/ROADMAP.md`, R4: the content-negotiation deliverable is recorded as delivered for a row's
  own statements, with the whole-vocabulary export and publication still to come.

## Project structure

```text
controlled_vocabularies/
  exchange/graph.py            new: document → rdflib.Graph
  exchange/serializations.py   new: the serialization table and serialize()
  models.py                    Resource.to_graph(), rdf_class on both models
  ui/representations.py        new: the mixin
  ui/views.py                  the mixin on three views
  ui/templates/cotton/controlled_vocabularies/rdf_alternates.html   new
  ui/templates/controlled_vocabularies/ui/{concept,collection,conceptscheme}_detail.html
tests/
  test_exchange/test_graph.py            new
  test_exchange/test_serializations.py   new
  test_models.py                          to_graph()
  test_ui/test_representations.py         new
  test_ui/test_templates.py               alternates
docs/browsing.md, docs/importing.md, CONTEXT.md, docs/ROADMAP.md
```
