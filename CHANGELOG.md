# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Django 6.1 is supported, and tested on every change alongside 5.2 and 6.0.

### Changed

- The project is built and developed with uv instead of Poetry. Contributors run `uv sync` in
  place of `poetry install`, and `uv run` in place of `poetry run`. Published packages are
  unaffected.

## [v0.1.0] - 2026-08-26

## [v0.0.3] - 2026-08-25

### Added

- Finding a vocabulary: an opt-in `ui` extra (`pip install django-controlled-vocabularies[ui]`)
  adds one page listing every vocabulary the site holds, alphabetically and stably, each entry
  showing its description, its concept count, and whether it was authored here or imported from
  a publisher — with the publisher's own identifier shown for an imported one. A site holding
  none says so, in wording distinct from a search that matches nothing. No entry links to the
  vocabulary it names yet — nothing serves that address on the site until a later feature adds
  it. See the README.
- The same page's search box narrows the list by a vocabulary's name and description (not by
  the concepts it holds), travels in the page's address so a narrowed list can be linked to, and
  widens on a second word rather than narrowing — matching is OR across every word and both
  fields. A search matching nothing says so, repeats the term, and links back to the unsearched
  list. Letter case is ignored, with one limit belonging to the database rather than to this
  package: SQLite folds ASCII letters only, so on SQLite a vocabulary named *Ökologie* is found
  by *ÖKOLOGIE* and not by *ökologie*. PostgreSQL matches either way. See the README.
- A vocabulary's own page, at the address its identifier composes: its name as the page title,
  its description, and how it was obtained — an imported vocabulary's page links to the
  publisher's own identifier, one authored here links back to the page itself. Reversed by name
  as `controlled_vocabularies_ui:vocabulary-detail`. `manage.py check` reports
  `controlled_vocabularies.ui.W001`, a warning, when the browsing routes are mounted somewhere
  that disagrees with the path `CONTROLLED_VOCABULARIES_BASE_URI` composes against, since a
  vocabulary's identifier then does not lead back to its own page. See the README.
- The vocabulary's own page now lists every concept it holds — and only that vocabulary's — in
  one flat, paged list: nothing several levels down a broader/narrower chain is nested under one
  above it. Alphabetical order follows the label actually shown, falling back from the reader's
  own language to the vocabulary's own default one, at a flat query cost regardless of how many
  concepts the vocabulary holds. A row names a concept and nothing more — no definition, no note,
  no identifier, no relation, and nothing to follow: how concepts relate to one another is not
  shown here. A vocabulary holding none says so, distinct from the page's other empty state, and
  the rest of the page still renders. See the README.
- The vocabulary's own page can now be narrowed by a search box, matching a concept's preferred
  label in any language it carries, its alternative labels, and its hidden labels — never its
  definition or any other note. A hidden label is matched and never displayed, so a search can
  find a concept a reader was never shown a name for. The term travels in the page's own address
  (`?q=`), exactly as the list of vocabularies' own search does, and reaches every concept in the
  vocabulary before paging divides the results — not only the page being viewed. A search
  matching nothing says so, repeats the term, and — unlike the list of vocabularies — offers a
  working link back to the whole vocabulary, since this page has a template of its own to render
  it in. Letter case is ignored, with the same database-dependent limit disclosed above. See the
  README.
- The demo project's DCMI Type Vocabulary now seeds a concept (`Dataset`) carrying an alternative
  label and a hidden label, and the unattended demo walk (`demo/smoke.py`) follows the vocabulary
  list to that vocabulary's own page and searches inside it — including a search matching only
  the hidden label — failing the build if either does not work. See the README's "Try it"
  section.
- The vocabulary's own page now names its collections — curator-made groupings of its concepts
  (`skos:Collection` / `skos:OrderedCollection`) that the broader/narrower relations do not
  express — above the concept list, each one distinguishable as ordered or not. Nothing on the
  page links to a collection: that address is a later feature's (#142). A vocabulary holding none
  shows no collections section at all. The demo project's Data Collection Methods vocabulary now
  seeds one of each kind, loaded through the same SKOS file as its concepts. See the README.
- Every concept and every collection now has its own address and its own page: a definition list
  of everything the database records about it, each row labelled by the SKOS property it was
  recorded under and shown in the language the site is being read in, falling back to the
  vocabulary's own default where the record carries no value in the reading language. A concept's
  page shows its broader concept, its narrower concepts (derived — only the broader direction is
  ever stored) and its related concepts; a collection's page shows the concepts it gathers, in
  their curated order when it is an ordered collection, and says so in plain language when it
  holds none. A collection states its membership property once, with every member listed beside
  it. Every record-valued row is a short in-site form linking to that record's own page. Both a
  row's term and a record-valued row's short form are abbreviations of a URI, and both disclose
  the URI they abbreviate on hover, also carrying it where keyboard focus and a screen reader
  reach it. Both pages show what kind of record it is, lead with its own identifier as a link
  directly beneath the title, carry a breadcrumb trail naming the vocabulary that holds it, and
  are **read-only**, with no permission rule of their own. An address naming no record, or naming
  no vocabulary at all, is reported not found the same way. The number of queries either page
  runs does not grow with how much it shows. See the README.
- The vocabulary list, a vocabulary's own page, and a narrowed search of either now link every
  concept and every collection they name to that record's own page, in place of the plain text
  they showed before.
- A concept's own page now also names, below its definition list, every collection that gathers
  it — a statement other records make about it rather than one it makes about itself, so the
  section carries a plain-language heading, "Member of", rather than a SKOS property. A concept no
  collection gathers shows no such section.
- A concept's own page carries no link to a concept in a vocabulary this site does not hold, even
  where an imported file offered one: nothing in the package stores such a mapping yet, so nothing
  is shown for it. Labels, notes and publisher-supplied identifiers all reach the page as escaped
  text, never marked safe.
- The demo project's Data Collection Methods vocabulary now seeds a broader/narrower pair, a
  related pair, and a note carried only in German, and the unattended demo walk follows a concept
  from that vocabulary to its own page — once in the demo's own default language and once in
  German, to exercise the language fallback above — and then to one of its collections, failing
  the build if either page stops showing what the seed puts there. See the README's "Try it"
  section.
- `ConceptField` and `ConceptsField` can now be narrowed to part of the one vocabulary they name,
  with a new argument on top of `vocabulary`: `collection` restricts to a curator-made grouping,
  `concepts` restricts to an explicit, named list, and `branch` restricts to a hierarchy root and
  everything narrower than it, at any depth. A field carries at most one of the three, and
  declaring one requires the field to name exactly one vocabulary. Both rules are enforced when the
  declaration is read, before the app starts. A restriction naming a target that does not exist yet
  offers no choices at all rather than raising, and a new system check,
  `controlled_vocabularies.W005`, reports it by model, field and missing target. Reading a branch's
  descendants re-walks the stored hierarchy on every request rather than caching it, so a very deep
  branch on a form the public can reach is worth choosing deliberately. Marking a collection
  `ordered` in the vocabulary editor now also carries through to the concept search: a field
  restricted to that collection offers the curator's own sequence while the search box is empty,
  then falls back to relevance order as soon as someone types. A restricted field with no
  `help_text` of its own now describes itself as restricted within its vocabulary, in place of the
  unrestricted wording that no longer fit it. See the README's "Restricting a field to part of a
  vocabulary".

### Known limitations

- The search box on the list of vocabularies cannot be submitted, and a search matching nothing
  there offers no link back to the full list. The search box on a vocabulary's own page shares
  the same submit limitation but does offer a working link back when a search matches nothing,
  since that page has a template of its own to render one in. Both come from the released
  django-mvp's search control, whose input is tied to a form only its filter control creates
  ([django-mvp#282](https://github.com/django-mvp/django-mvp/issues/282), tracked here as #147).
  Searching by address is unaffected on either page: `?q=soil` narrows the list of vocabularies
  and `?q=granite` narrows the concepts inside one, and either narrowed address can be shared. We
  are waiting on the upstream fix rather than shipping a patched copy of django-mvp's page — see
  `docs/adr/0015-upstream-defects-are-waited-on-not-worked-around.md`.
- A runnable demo project: `manage.py`, `demo/settings.py` and `demo/urls.py` bring up the
  vocabulary list configured exactly as the README documents. `migrate`, `seed_demo` and
  `runserver` put a populated, searchable list on screen from a fresh clone in three commands.
  `seed_demo` is destructive and idempotent, loading two vocabularies — one imported, one
  authored here — through the package's own import path. The demo project registers the
  vocabulary model with its own admin site, so a vocabulary can be added by hand and watched
  onto the list. An unattended check (`.github/workflows/demo.yml`, `demo/smoke.py`) walks the
  same path on every pull request. See the README's "Try it" section.

### Fixed

- `ConceptsField`: a required field on an existing record no longer refuses a valid submission
  through a `ModelForm` when the relation is still empty. The required-set check installed on
  `full_clean()` ran before `ModelForm._post_clean()`'s own `save_m2m()` attached anything a
  submission carried, so it read the relation exactly as it stood before the submission — the one
  path that would have populated it. The form field's own `required` flag already validates the
  submitted data correctly; the model-level check now defers to it during a `ModelForm`'s own
  clean and still applies in full to a direct `full_clean()` call. (#124)

## [v0.0.2] - 2026-08-14

### Added

- Choosing a concept by typing: `ConceptField` and `ConceptsField` now render, by default and in
  any Django form built from a consuming model, as a search-as-you-type control backed by this
  package's own search endpoint (`controlled_vocabularies.urls`). A project wires it in three
  steps — include the route, add `django_tomselect` to `INSTALLED_APPS`, and add
  `django_tomselect.middleware.TomSelectMiddleware` to `MIDDLEWARE` — each reported by
  `manage.py check` when missing (`controlled_vocabularies.W002`, `W003`, `W004`). A search
  returns a concept's identifier, its preferred label in the active language, and its
  vocabulary's name, restricted to whatever vocabularies the field declares and carrying no
  permission rule of its own; a project needing to restrict which concepts are searchable
  restricts the include instead. Matching runs case-insensitively across a concept's preferred,
  alternative and hidden labels in the active language and its default-language preferred label,
  a concept matching on several appearing once. Pages are bounded and stable: a page past the
  last returns nothing rather than re-serving the first. An already-attached concept still
  renders, under its active-language preferred label, even when its vocabulary is no longer named
  by the field's declaration. The control needs a browser running JavaScript; without one, both
  fields still work as an ordinary required-relation form field. See the README.
- Choosing a concept in the admin: the same search-as-you-type control now renders on a consuming
  model's Django admin pages once it's registered, with nothing further to configure — the wiring
  is the three steps above and the admin adds nothing to them. A concept is chosen there, never
  created or edited: no add, change, delete or view affordance for the related concept, whatever
  permissions the signed-in person holds. Where the admin presents the field read-only, the concept
  is shown by its preferred label and no control renders, Django's own read-only presentation.
  `autocomplete_fields`, `raw_id_fields`, a form's own declared widget, and `readonly_fields` each
  still work as they would for any other related field. The first three render what they asked for
  and keep the same no-affordance and validation guarantees as the default control. See the README.
- New runtime dependency: [`django-tomselect`](https://pypi.org/project/django-tomselect/)
  `^2026.6.2`, which the concept search control above is built on.
- `ConceptsField`: a `ManyToManyField` field a consuming project declares on its own model, naming
  zero, one, or several vocabularies by their `ConceptScheme` slugs. Naming one or several
  restricts form choices and the write path to those vocabularies, refusing a concept from any
  other and naming every accepted vocabulary in the refusal; naming none restricts nothing, for a
  plain keywords-style field. Every shape refuses deletion of a referenced concept
  (`on_delete=PROTECT` on the generated through model) whether the delete reaches it directly, via
  a bulk queryset delete, or cascades down from its scheme — for anything going through the ORM,
  since Django writes no `ON DELETE` clause into the schema for any relation. `blank=True` makes
  the field optional; without it, `full_clean()` refuses a record holding zero concepts, because
  Django's own field validation has no hook for a many-to-many field. Adds
  `get_<field>_labels()` / `get_<field>_uris()` accessors reading every attached concept's
  preferred label (falling back to the vocabulary's default language) and URI, returning an empty
  list rather than raising for a record holding nothing, without overwriting either name on a
  model that already defines it. See the README.
- `ConceptField`: a `ForeignKey` field a consuming project declares on its own model, naming zero,
  one, or several vocabularies by their `ConceptScheme` slugs. It takes the same three shapes
  `ConceptsField` takes and means the same thing by each. Naming one or several constrains form
  choices and `full_clean()` to those vocabularies and refuses a concept from any other, naming
  every accepted vocabulary in the refusal. Naming none restricts nothing. Every shape refuses
  deletion of a referenced concept (`on_delete=PROTECT`) whether the delete
  reaches it directly or cascades down from its scheme, and adds `get_<field>_label()` /
  `get_<field>_uri()` accessors reading the attached concept's preferred label (falling back to
  the vocabulary's default language) and URI, without overwriting either name on a model that
  already defines it. A named vocabulary that has not been imported yet does not stop the field
  from being declared or the app from starting. Instead, `manage.py check` reports a warning
  (`controlled_vocabularies.W001`) naming the model, field, and missing slug. See the README.
- Importing a published SKOS vocabulary: `import_skos(file, *, serialization=None, scheme=None)`
  reads a Turtle, RDF/XML, or JSON-LD file and creates or updates the vocabulary it declares, its
  concepts, their labels and documentary notes, their broader/narrower and related relationships,
  and their collection membership, every record matched by its static URI. Re-running an import
  upserts rather than deleting and recreating: a record the file still contains has its content
  matched to the file exactly, including removing a value the file no longer carries, while a
  record the file does not mention at all is left untouched and named in the report instead of
  being deleted. Returns an `ImportReport` — a plain dataclass, not rendered text — with `created`,
  `updated`, `set_aside` (a translatable, closed-vocabulary reason per value the app could not
  store, e.g. an unconfigured language, a notation, a mapping to another vocabulary, or a predicate
  the models have no place for), `absent_from_source`, `normalized` (a value stored under a
  different predicate than the file asserted, e.g. a foreign `dcterms:description` read as a
  concept's definition), and `fatal` buckets; a run either succeeds in full or writes nothing,
  raising `SkosImportFailed` (carrying the same report) on a fatal problem such as a missing or
  blank-node identity. `SkosImportError` covers every other reason a file could not be turned into
  usable SKOS at all (not found, unsupported serialization, unparseable, or refused by the safety
  scan). Code catching only `(SkosImportError, SkosImportFailed)` already catches everything else
  this function can raise. Reading a file never reassigns identity: a concept or collection
  whose URI is already held by a different vocabulary, or by a record of another kind, is set aside
  and reported rather than moved or duplicated. Imported files are treated as untrusted input.
  RDF/XML is scanned for unsafe constructs (entity expansion, external references) before it is
  parsed, and a JSON-LD document is refused rather than fetched if its `@context` names a remote
  location, whether a plain string reference or an `@import` reference inside an inline object
  context, at any nesting depth an array context reaches. Reading a file never makes a network
  request. Both refusals raise an exported, translatable
  `UnsafeRdfXmlError`/`UnsafeJsonLdError`, each a `SkosImportError` subclass. A management
  command wraps this for command-line use (see below). No web-facing entry point yet.
  See the README.
- A management command, `import_skos`, runs the same import from a terminal:
  `python manage.py import_skos <source> [--format FORMAT] [--dry-run]`. The source can be a
  local path or an `http://`/`https://` URL, fetched under a fixed read timeout, byte ceiling and
  transfer deadline, and read with its identifiers resolved against the address it was served from
  after any redirect, so a vocabulary published behind a PURL or a `/latest` alias is stored under
  its publisher's own URIs and a re-import updates the same concepts the first import created.
  `--format` names the source's serialization for one whose extension or `Content-Type` does not.
  `--dry-run` performs the entire import and reports the outcome exactly as a live run would,
  then rolls the database back to its state beforehand.
  Output is bucket counts by default — created, updated, set aside, normalized, and absent from
  source, plus the set-aside account grouped by reason and by language — with every individual
  set-aside entry added at `--verbosity 2` or above, and nothing at all at `--verbosity 0`.
  The command exits non-zero only on a refusal.
  A run that sets values aside — which importing a vocabulary published in more languages than a
  site configures for always does — exits zero.
- Importing now matches a published language tag by base language rather than by exact string
  equality. A file's `en` value fills a site configured for `en-gb`, and a file's `en-gb` value
  fills a site configured for `en`, matched case-insensitively in both directions, with an exact
  tag match always winning over a variant. A value stored under a variant match is reported as a
  substitution, which is distinct from a value set aside outright.
- Where a preferred label has several variants of one configured language and no exact match, the
  vocabulary's predominant variant is stored and ties are broken by language code. Each losing
  variant is set aside and reported under its own published language. Alternative labels, hidden
  labels, and notes have no such limit, so every variant offered is stored.
- `ImportReport` gains `language_account()`, a per-published-language count of everything left
  behind for a language reason. It is present and empty after a run that left nothing behind, so a
  caller can see what configuring a language would recover.
- The site's configured languages are still read from `settings.LANGUAGES`. A project that declares
  none inherits Django's 99-language default, so narrowing that list is how a site narrows what an
  import stores.
- Static, externally assigned identifiers: `ConceptScheme`, `Concept`, and `Collection` each gain a
  `static_uri` field holding an identifier assigned by an external publisher, held exactly as given
  and never recomputed by the app. Nothing in the package overwrites a stored value, and nothing
  stops you from editing one either, so make the field non-editable wherever you expose it once a
  record is published. A locally authored, unpublished record's `uri` instead stays dynamic,
  composed and reported live and following a rename, until one is assigned. `local_url` is a new,
  separate accessor for this site's own address for a record, always composed from the configured
  base address and the record's slugs regardless of what `static_uri` holds. `has_static_uri`
  reports whether the identifier is static rather than dynamic.
  `get_by_uri()` — already on `Concept.objects` — is now shared by `ConceptScheme.objects` and
  `Collection.objects` too, resolving a stored identifier first and falling back to the site's own
  composition. `validate_static_uri` is exported for reuse: it requires an absolute identifier with
  an accepted scheme and caps length at 500 characters.
- An imported concept's slug, and a vocabulary's own, is now derived from its own published
  identifier rather than from a translated label — the identifier's fragment where it has one,
  otherwise the last segment of its path. Assigned once, on first import, and never recomputed by a
  later one, so a publisher renaming a record, or a vocabulary's name arriving in a different
  language, no longer moves that record's local address. A record authored on this site rather than
  imported is unaffected and keeps deriving its slug from its label. The cost: a vocabulary
  published under opaque codes now gets an opaque local address.
- `CONTROLLED_VOCABULARIES_ALLOWED_URI_SCHEMES` setting: the schemes an externally assigned
  `static_uri` may use — `http`, `https`, `urn`, `doi`, `info`, `ark`, `tag`, `hdl`, and `oai` by
  default (see the README).
- Collections: a vocabulary's concepts can be gathered into named collections, optionally ordered,
  held on the new `Collection` and `CollectionMember` models and reached through `Collection.add()`,
  `remove()`, `members()`, `set_member_order()`, and `Concept.collections()`. Membership is
  many-to-many, held once per collection, and confined to the collection's own vocabulary. It asserts
  no relation between members, so a collection stays clear of the broader/narrower hierarchy. An
  ordered collection reads its members back in a deliberate sequence. Authored through the ORM. The
  editing interface comes later.

- Concept relationships: concepts within a vocabulary can be linked through a broader/narrower
  hierarchy and a symmetric related association, held on the new `ConceptRelation` model and reached
  through `Concept.broader()`, `narrower()`, `related()`, and the `add_`/`remove_` helpers. Only the
  broader direction is stored; narrower is derived, so the pair can never disagree. A concept may sit
  under several broader concepts. The model refuses a self-relation, a duplicate, a broader/related
  overlap on the same pair, and a link across vocabularies; a cycle in the hierarchy is not prevented
  (a deliberate non-guarantee for now). Authored through the ORM; the editing interface comes later.
- Multilingual concepts: each concept carries per-language labels (one preferred label per language,
  plus any number of alternative and hidden labels) and the full SKOS documentary note family:
  `definition`, `scopeNote`, `example`, `editorialNote`, `historyNote`, `changeNote`, and a generic
  note. All are language-tagged and held on the new `ConceptLabel` and `ConceptNote` models. Authored
  through the ORM. The editing interface comes later.
- Per-vocabulary default language: a `ConceptScheme` defaults to the app's `LANGUAGE_CODE` but can
  set its own default language, which is the one that anchors its concepts' slugs. A German
  vocabulary anchors its identifiers in German inside an English-default app.
- Overridable concept slugs: a slug still derives from the default-language preferred label, but a
  curator can set an explicit slug that survives later relabels.
- `multilingual` factory trait building a fully populated multi-language concept for downstream tests.
- `ConceptScheme` and `Concept` models: a vocabulary is a named container of concepts, each concept
  a term within it. Slugs derive from the scheme name and the concept label and track them while a
  vocabulary is unpublished.
- Stable concept identity: a locally authored concept's URI composes from
  `CONTROLLED_VOCABULARIES_BASE_URI`, the scheme slug, and the concept slug, and stays resolvable when
  a label is reworded. (An externally assigned identifier instead holds verbatim — see static,
  externally assigned identifiers, above.) `Concept.objects.get_by_uri()` resolves a URI back to its
  concept.
- `CONTROLLED_VOCABULARIES_BASE_URI` setting for the URI base address (see the README).
- Test factories (`ConceptSchemeFactory`, `ConceptFactory`) for use in downstream tests.
- Initial project scaffold: package metadata, CI, and early design notes (see `docs/brainstorm.md`).
