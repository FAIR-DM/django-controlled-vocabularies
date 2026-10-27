# CONTEXT.md — Ubiquitous language

The shared vocabulary for this project. Every core concept is named once here so specs, issues,
and code speak the same language. Where a term has a tempting synonym, the synonym is called out.
This is a seed — it grows as the code does.

## RDF / SKOS foundations

| Term | Definition | Notes / synonyms to avoid |
|---|---|---|
| **SKOS** | W3C [Simple Knowledge Organization System](https://www.w3.org/TR/skos-reference/) — the RDF vocabulary this package understands. | Not "ontology" (that implies OWL). |
| **Statement** | One fact about a subject: a **predicate** and a value. The value is a literal (optionally with a language or a datatype) or a link to another resource. | An RDF triple, read from the subject's side. |
| **URI** (`uri`) | The globally stable identifier of a vocabulary, concept or collection — always present. A row imported from a publisher keeps the URI the publisher gave it, held exactly as given. A row created without one is given one, once, composed from the site's configured base address and its slugs. **Identity lives here, never in the database PK.** | Never "missing", and never rewritten once set. |
| **Slug** | The URL-safe segment a vocabulary or record contributes to the address it is viewed at on this site. Made once, when the row is first saved, from the last part of its URI (the fragment, else the last path segment), or from its preferred label when it arrives without a URI, and never recomputed. Unique across vocabularies, and unique among the records of one vocabulary. | Not the identifier itself; an opaque published identifier yields an opaque slug. |
| **CURIE** | Compact URI, `prefix:name` (e.g. `skos:prefLabel`), expanded against known namespaces. | The shorthand form, not a full URI. |
| **Prefix** | One of the six fixed namespace abbreviations a stored document uses: `skos`, `dcterms`, `owl`, `rdf`, `rdfs`, `xsd`. A predicate in any other namespace is written as its full URI. | Not configurable, because every stored key is written with it. |
| **Turtle / RDF-XML / JSON-LD** | The serializations accepted on import (via rdflib). | Formats, not the data model. |

## Domain model

| Term | Definition | Notes / synonyms to avoid |
|---|---|---|
| **ConceptScheme** | A vocabulary: one row holding the vocabulary's own statements, with its URI, slug, default language and a copy of its name. A Django model. | The formal container. Don't call it a "namespace". |
| **Record** | One concept or collection of a vocabulary: one row holding every statement published about it, with its vocabulary, its type, URI, slug, and copies of its name and its labels. A Django model. | Concepts and collections are both records, told apart by **type**. |
| **Type** (`type`) | What a record is an instance of: `skos:Concept`, `skos:Collection` or `skos:OrderedCollection`. | Not a Python class: a concept and a collection are the same model. |
| **Concept** | A record of type `skos:Concept` — a term within a vocabulary. | Avoid "term"/"entry". |
| **Collection** | A record of type `skos:Collection` or `skos:OrderedCollection` — a grouping of concepts within a vocabulary, optionally in a deliberate order. Its members are the URIs under `skos:member`, or in sequence under `skos:memberList`. | Distinct from a vocabulary; a grouping *inside* it. |
| **Label** | A language-tagged name for a concept: `prefLabel`, `altLabel` or `hiddenLabel`. Stored as entries of the document. | Multi-valued per language. |
| **Definition / Note** | Descriptive predicates: `definition`, `scopeNote`, `editorialNote`, `example`, and so on. Language-tagged. | |
| **Notation** | A `skos:notation` — a code for a concept, language-independent. Kept in the document like any other statement. | |
| **Relation** | An intra-vocabulary link between two concepts: `broader` / `narrower` (inverse pair), `related` (symmetric). Stored as links in the document, as the file stated them. | A page shows the inverse of a stated link as well. |
| **Mapping** | A link to a concept in another vocabulary: `exactMatch`, `closeMatch`, `broadMatch`, … Stored as links in the document. | The target usually has no row here. |

## This package's mechanisms

| Term | Definition | Notes |
|---|---|---|
| **Document** (`data`) | The JSON object on a vocabulary or a record that holds every statement published about it. Each key is a predicate, as a CURIE or a full URI. Each value is a list of entries in JSON-LD's shape: `{"@value": "Granite", "@language": "en"}`, `{"@value": "GR-01"}` or `{"@id": "https://…"}`. | The **sole source of truth** for a row's statements. An import replaces it whole. |
| **Entry** | One item of a predicate's list in a document: a literal (`@value`, with at most an `@language` or an `@type`) or a link (`@id`). | Read with `values()`, `linked_uris()` and `first_value()`. |
| **Copied column** | A column filled from the document each time a row is saved, kept only so sorting and searching need no lookup inside the document: `pref_label` on both models, and `search_text` on a record. | Not a second source of truth. `pref_label` is the name in the vocabulary's default language. `search_text` holds every preferred, alternative and hidden label, one per line. |
| **Link** | A row of the `Link` table: one top-level `{"@id": ...}` entry of a record's document, with its `source` record, its `predicate` as stored and its `target` URI. Rebuilt from the document each time the record is saved, and by `refresh_links()` after a write that skips `save()`. | A copy, like a copied column, never a second source of truth. The target is a URI and not a foreign key, since it may name a concept held nowhere here. Literals and links inside an embedded node give no row. Read through `RecordQuerySet.linking_to()` and `RecordQuerySet.in_branch()`. |
| **Default language** (`default_language`) | The language of the preferred label copied into `pref_label`. Set on a vocabulary, and read by its records. A vocabulary the import creates takes the most common language among its records' preferred labels. | Not the site's `LANGUAGE_CODE`, though that is the fallback when no label has a language. |
| **ConceptField** | The single-value consumption API: a `ForeignKey` to `Record`'s URI, limited to concepts, that a consuming project declares on its own model, naming one or more vocabularies by URI and constraining choices to them, optionally narrowed further by a **Restriction**. | Its many-to-many counterpart is **MultiConceptField**, below; it renders by default as the **concept search control**, below. |
| **`Vocabulary`** | What a concept field names: a vocabulary's URI, with optionally the `source` it is published at and that source's `format`. A field may name a vocabulary by its URI alone. | A reference to a vocabulary, never a slug: a slug is this site's own name for one. `sync_vocabularies` loads every vocabulary an installed model's fields name. |
| **MultiConceptField** | The multi-value consumption API: a `ManyToManyField` to `Record`, limited to concepts. Naming zero vocabularies restricts nothing — every concept in the database is a valid choice. Shares `ConceptField`'s delete protection, name and URI readback, and required-means-at-least-one rule. | See [`docs/fields.md`](docs/fields.md). |
| **Restriction** | An optional further narrowing of a `ConceptField` or `MultiConceptField` to the members of one collection, named by its URI (`collection`), or to a **branch** (`branch`). A field carries at most one, and declaring one requires the field to name exactly one vocabulary. A restriction naming a collection or branch root that does not exist offers no choices at all rather than raising, reported by `manage.py check` (`controlled_vocabularies.W005`). | Not the same thing as `vocabulary` itself, which is the field's coarser, always-available constraint. See [`docs/fields.md`](docs/fields.md). |
| **Branch** | A concept and every concept below it in the hierarchy, within one vocabulary, named by the root's URI. A concept is below another when its own document states `skos:broader` the other or the other's document states `skos:narrower` it. The root is included, and nothing above it or beside it is. Read each time a choice is validated or searched, with one recursive query over the **Link** table. | Not a collection: a collection is a grouping the publisher states, a branch is the hierarchy. See [ADR 0027](docs/adr/0027-a-field-may-be-restricted-to-a-branch-read-from-the-links-table.md). |
| **Concept search control** | The search-as-you-type widget `ConceptField` and `MultiConceptField` render as by default in any Django form built from a consuming model. Backed by this package's own search endpoint (`controlled_vocabularies.urls`), restricted at search and validation time to whatever vocabularies the field declares, carrying no permission rule of its own. It is also what these fields render as on a consuming project's admin pages, with no related-object affordance to add, change, delete or view the chosen concept. | Needs a browser running JavaScript; without one, the field still works as an ordinary required-relation form field. See [`docs/how-to/choosing-a-concept.md`](docs/how-to/choosing-a-concept.md). |
| **Deprecated** | A concept its publisher has marked `owl:deprecated`. The statement is kept like any other, and the package keeps no lifecycle of its own on a concept. | Referenced concepts are `PROTECT`ed, not deleted, whatever their publisher says. |

## Importing published vocabularies

| Term | Definition | Notes / synonyms to avoid |
|---|---|---|
| **Import** | Reading a published SKOS file into one vocabulary row and one record row per concept and collection, keeping every statement in every language. Re-running it upserts by URI, and the file is authoritative for each record it contains. | A record the file no longer mentions is left alone and named in the report. |
| **Report** (`ImportReport`) | What a run did: `created`, `updated`, `absent_from_source`, and `fatal`. | A plain dataclass, never parsed text. |
| **Fatal finding** | A reason a whole run is refused: a subject with no usable identifier (a blank node, or a `javascript:`, `data:` or `vbscript:` URI), or a file whose vocabulary cannot be determined. A refused run writes nothing. | The only reasons a run is refused. |
| **Declared vocabulary** | An entry in the `CONTROLLED_VOCABULARIES` setting: the slug a site gives a vocabulary, and the source `sync_vocabularies` loads it from. The slug is the vocabulary's own once loaded. A declared vocabulary a field also names is loaded from the declaration, never from the field's source. | Not a record of where a vocabulary was fetched from in the database — the settings are the only place a source is remembered. |
| **Dry run** | A `--dry-run` run of the `import_skos` or `sync_vocabularies` management command: performs the entire import, in a transaction that is always rolled back, and reports exactly what a live run would. | Not a lightweight validation that never touches the database — it does the same work a live run does and takes as long. |

## Architectural decisions

Design reasoning lives in [`docs/adr/`](docs/adr/), one record per decision. Start there for the
"why" behind storing a vocabulary as documents, how a field's restriction is derived, and how an
upstream defect is handled.
