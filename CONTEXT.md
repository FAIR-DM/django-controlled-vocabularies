# CONTEXT.md — Ubiquitous language

The shared vocabulary for this project. Every core concept is named once here so specs, issues,
and code speak the same language. Where a term has a tempting synonym, the synonym is called out.
This is a seed — it grows as the code does.

## RDF / SKOS foundations

| Term | Definition | Notes / synonyms to avoid |
|---|---|---|
| **SKOS** | W3C [Simple Knowledge Organization System](https://www.w3.org/TR/skos-reference/) — the RDF vocabulary this package targets exclusively. | Not "ontology" (that implies OWL). |
| **Triple** | The atom of RDF: **subject** (the thing described), **predicate** (a property), **object** (the value). | In this package: subject = a Concept/Scheme, predicate = a JSON key, object = a JSON value. |
| **URI** (`uri`) | The globally stable identifier of a scheme, concept, or collection — always present, never `None`. Static once fixed (see **Static URI**), otherwise dynamic: composed from the site's configured address and follows the record until it is fixed. **Identity lives here, never in the database PK.** | Every record has one; it is never "missing," only dynamic or static. |
| **Static URI** (`static_uri`) | The identifier once it is fixed: assigned by an external publisher and held exactly as given, or frozen when this site publishes the vocabulary (R4). Empty (`None`) means the record's `uri` is still dynamic. Held fixed by `save()`/`full_clean()` — a bulk queryset write bypasses that, as it bypasses every model-level rule. | Was called "Permanent URI". Fixed once externally assigned or once published; never rewritten before then, either. Not the same as **URI** — it is one of the two states `uri` can be in. |
| **Local URL** | This site's own address for a record, always composed from the site's configured address and the record's slugs, regardless of what its `static_uri` is. For a locally authored, unpublished record the two are the same string; for an imported record they differ, because the record is viewable here even though its identity belongs to its publisher. Never moves once assigned to an imported record, because it is composed entirely from **slugs** that are themselves identifier-derived and permanent (see **Slug**). | The address a record is viewed at, not necessarily its identity. |
| **Slug** | The URL-safe segment a scheme or a concept contributes to its **Local URL**. For an imported record, derived once from its **Static URI** — the fragment where it has one, otherwise the last segment of its path — and never recomputed by a later import, so a publisher rename or a vocabulary name arriving in a different language cannot move it. For a locally authored record with no `static_uri`, derived from its label/name and kept in sync with it, exactly as before this rule existed. | Not the same thing as the identifier itself; an opaque published identifier yields an opaque slug. |
| **CURIE** | Compact URI, `prefix:name` (e.g. `skos:prefLabel`), expanded against known namespaces. | The shorthand form, not a full URI. |
| **Turtle / TTL / RDF-XML / JSON-LD** | Serialization formats produced on export and accepted on import (via rdflib). | Formats, not the data model. |

## Domain model

> **Storage status (as of R1, #16).** The JSON-**document** + **projection** storage described in
> this and the next table is the *intended* direction for the import and editor features
> (R2/R5). The shipped R1 slice stores labels and notes as **relational models**
> (`ConceptLabel`, `ConceptNote`) with the default-language preferred label held on `Concept.label`.
> The document/predicate-registry design is deferred to the features that consume it
> (`specs/002-multilingual-concepts/research.md` R1). Read the JSON rows below as design intent, not
> current implementation.

| Term | Definition | Notes / synonyms to avoid |
|---|---|---|
| **ConceptScheme** | A vocabulary: the `skos:ConceptScheme` container. A Django model. | The formal container. Don't call it a "namespace". |
| **Curator** | A signed-in user who may create, edit or delete vocabularies on the browsing pages, by holding the `add_conceptscheme`, `change_conceptscheme` and `delete_conceptscheme` permissions. The package defines no group or role for it. | Not "admin" or "editor": the pages never need Django's admin. |
| **Concept** | A term within a scheme — `skos:Concept`. A Django model whose editable state is a JSON **document**; core fields are projected into indexed columns. | Avoid "term"/"entry"; the type is **Concept**. |
| **Collection** | A `skos:Collection` — a grouping of concepts within a scheme, optionally ordered. | Distinct from a scheme; a grouping *inside* it. |
| **Label** | A language-tagged name for a concept: `prefLabel` (one per language), `altLabel` / `hiddenLabel` (many per language). Stored as translated JSON, indexed via a projected `pref_label` column. | Multi-valued per language — the reason plain per-object translation frameworks don't fit. |
| **Definition / Note** | Descriptive predicates: `definition`, `scopeNote`, `editorialNote`, `example`, etc. Language-tagged. | `definition` is the primary; treat foreign `dcterms:description` as an import alias for it. |
| **Notation** | A `skos:notation` — a typed, language-*independent* code for a concept. | Language-independent → shared document, not translated. |
| **Relation** | An intra-vocabulary link between two concepts: `broader` / `narrower` (inverse pair), `related` (symmetric). Stored as a self-referencing M2M with a `relationship_type` through-model. | Only one canonical direction is stored, and the inverse is derived. |
| **Mapping** | A cross-vocabulary link: `exactMatch`, `closeMatch`, `broadMatch`, … usually pointing at concepts in *other* vocabularies (URIs with no local row). | Lives in the JSON document, **not** the relation M2M. |

## This package's mechanisms

| Term | Definition | Notes |
|---|---|---|
| **Document** | The JSON representation of a concept's predicate→object pairs — the **sole source of truth** for its literal-valued and unknown predicates. | Split into a **shared** document (language-independent) and a **translated** document (language-tagged). |
| **Projection / index column** | A concrete, read-only DB column (`uri`, `pref_label`, `definition`) synced from the document on save, existing purely to be indexed and queried. | Materialised index, not a second source of truth. |
| **Escrow** | The role the JSON document plays for predicates the schema doesn't model — stored verbatim, re-emitted on export, so round-tripping is lossless. | Nothing imported is ever silently dropped. |
| **Predicate registry** | A curated map: CURIE → `{value_type: literal\|uri\|typed, cardinality: one\|many, translatable: bool}`. Drives the editor dropdown, per-row widget, validation, shared-vs-translated routing, and import aliases. | Design intent. Unregistered predicates still work as free-text escrow. |
| **ConceptField** | The single-value consumption API: a `ForeignKey` to `Concept` a consuming project declares on its own model, naming one or more vocabularies by slug and constraining choices to them, optionally narrowed further by a **Restriction**. The term a consuming project's own `models.py` writes into its code. | Delivered by #86. Replaces choice-iterable style entirely. Its many-to-many counterpart is **ConceptsField**, below; it renders by default as the **concept search control**, below. |
| **ConceptsField** | The multi-value consumption API: a `ManyToManyField` to `Concept` a consuming project declares on its own model, naming zero, one, or several vocabularies by slug, optionally narrowed further by a **Restriction**. Naming zero restricts nothing — every concept in the database is a valid choice. The term a consuming project's own `models.py` writes into its code for a keywords-style field, or one drawing on more than one vocabulary. | Delivered by #87. Shares `ConceptField`'s delete protection, label/URI readback, and required-means-at-least-one rule regardless of how many vocabularies (if any) it names; only the choice restriction depends on that. See [`docs/fields.md`](docs/fields.md). |
| **Restriction** | An optional further narrowing of a `ConceptField` or `ConceptsField` to part of its one named vocabulary: `collection` (a curator-made grouping), `concepts` (an explicit, named list), or `branch` (a hierarchy root plus everything narrower than it). A field carries at most one, and declaring one requires the field to name exactly one vocabulary. A restriction naming a target that does not exist offers no choices at all rather than raising, reported by `manage.py check` (`controlled_vocabularies.W005`). | Delivered by #164. Not the same thing as `vocabulary` itself, which is the field's coarser, always-available constraint. A restriction only ever narrows inside it. See [`docs/fields.md`](docs/fields.md). |
| **Concept search control** | The search-as-you-type widget `ConceptField` and `ConceptsField` render as by default in any Django form built from a consuming model — no widget declared, no endpoint written. Backed by this package's own search endpoint (`controlled_vocabularies.urls`), restricted at search and validation time to whatever vocabularies the field declares, carrying no permission rule of its own. It is also what these fields render as on a consuming project's admin pages, once registered — the same control, with no related-object affordance to add, change, delete or view the chosen concept. | Delivered by #88; reached the admin by #89. Needs a browser running JavaScript; without one, the field still works as an ordinary required-relation form field. See [`docs/search.md`](docs/search.md). |
| **Lifecycle** | A concept's `status`: `draft` → `published` → `deprecated` (`owl:deprecated` on export). Referenced concepts are `PROTECT`ed, not deleted. | Design intent — the concept model carries no status field today. |

## Importing published vocabularies

| Term | Definition | Notes / synonyms to avoid |
|---|---|---|
| **Base language** | The first subtag of a language tag — `en` in `en-GB`, `zh` in `zh-Hans`. Matching a published tag against the site's configured languages runs on this, never on the whole tag. | Not the tag itself; two tags can share a base language and still differ. |
| **Variant** | A published language tag that shares a base language with a configured one without matching it exactly, such as a file's `en-gb` against a site configured for `en`. Where a value's kind holds only one per language, as a preferred label does, one variant is kept and the rest are set aside and reported under their own published tag. Where it holds many, as alternative labels, hidden labels and notes do, every variant offered is stored. | Distinct from an exact match, which always wins over a variant and is never displaced by one. |
| **Substitution** | A value stored under a configured language other than the tag it was published under, because only a variant match reached it. Reported alongside what was created and updated, distinguishable from a value that was not stored at all. | The value *was* kept — not the same as a value set aside. |
| **Dry run** | A `--dry-run` run of the `import_skos` management command: performs the entire import, in a transaction that is always rolled back, and reports exactly what a live run would. | Not a lightweight validation that never touches the database — it does the same work a live run does and takes as long, so its report reflects every outcome a live run would, including ones only a database write itself would refuse. |

## Architectural decisions

Design reasoning lives in [`docs/adr/`](docs/adr/), one record per decision. Start there for the
"why" behind static URI identity, canonical-direction relations, how a field's restriction is
derived, and how an upstream defect is handled.
