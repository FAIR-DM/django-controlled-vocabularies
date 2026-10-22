# Tasks — 006 Import a published SKOS vocabulary from a file

Every task is test-first (Article I): the failing test comes before the code that satisfies it, in
the same task. Task ids are stable and never reused. Story phases after the foundational one are
independently implementable; within a phase the order is the sensible one, not a hard dependency
unless stated.

**Tasks have no issues** — this file is the whole task record.

## Phase 0 — Foundational (sequential, blocks every story)

- **T001** — Declare `rdflib` and `defusedxml` as runtime dependencies, with the justification in
  `plan.md` Complexity Tracking. **Lands in the same commit as T004, not before it.** Both were
  installed during planning to answer `research.md` R1 and R3 by measurement, and the declaration
  was then reverted: `deptry` fails a declared-but-unused dependency, which is Article VII's rule
  ("runtime deps are declared alongside the code that imports them, never ahead of it") working as
  intended. The commit that declares them is the commit that imports them.
- **T002** — Create the `controlled_vocabularies/exchange/` package and the mirroring `tests/test_exchange/`
  and `tests/fixtures/` directories, with the public surface re-exported from `exchange/__init__.py`.
  Test: importing the public names from `controlled_vocabularies.exchange` succeeds.
- **T003** — `report.py`: `ImportReport` and `SetAsideEntry`, with the four outcome buckets FR-015
  requires — created, updated, set aside with a reason, and present-here-but-absent-from-source —
  plus the reason vocabulary. Tests assert the report is inspectable as data, that counts and
  groupings are derivable without parsing prose, and that every reason is translatable with named
  placeholders. **This is the contract #51 and #52 consume, so it lands before the reader.**
- **T004** — `safety.py`: the pre-flight scan of untrusted RDF/XML through `defusedxml.sax`
  (`research.md` R3). Tests: the eight-level entity bomb is refused with a translatable message
  naming the cause; an ordinary RDF/XML document passes untouched; a document with an external
  entity reference is refused rather than silently emptied. **Reinstate the measured bomb as the
  test input** — the gate is proven against the real defect, not a mock.
- **T005** — Fixture vocabularies under `tests/fixtures/`: one small published vocabulary in
  Turtle, RDF/XML, and JSON-LD carrying multilingual labels, notes of several kinds, a hierarchy, a
  related pair, an unordered and an ordered collection; plus the edited copies the re-import
  scenarios need (a corrected label, a removed value, a removed concept, a changed collection
  order) and the malformed ones the fatal paths need. Test: each fixture is discoverable from the
  suite and parses.

## Phase US-1 — A published file becomes a vocabulary here (#61, P1)

- **T006** — Reading a file into a graph: serialization stated by the caller or determined from the
  file (`research.md` R1), routed through the T004 scan for RDF/XML. Tests: each of the three
  serializations parses; an unknown serialization and an unparseable file each fail the run with a
  translatable message and leave the database unchanged.
- **T007** — The vocabulary: created from the file's declaration when its identifier is not held
  here, updated when it is, matched via `get_by_uri` (`research.md` R6). Tests: creation; update of
  an existing match; a named target that matches; a named target that contradicts the file, which
  fails with nothing written; a file declaring no vocabulary, which fails without a named target
  and succeeds with one.
- **T008** — The imported vocabulary's default language, per FR-005: declared language, else the
  commonest preferred-label language, else the site default, and only ever one the site is
  configured for. Tests: a vocabulary published in a configured non-default language; one in an
  unconfigured language falling back.
- **T009** — Concepts: created inside the vocabulary, each holding its published identifier and its
  default-language preferred label as `Concept.label`. Tests: identifiers held verbatim; scheme
  membership via `inScheme` / `topConceptOf` / `hasTopConcept`; a concept claiming a different
  vocabulary is set aside and reported.
- **T010** — Slugs: derived by the model's own rule, disambiguated by a deterministic suffix within
  the vocabulary (FR-007). Tests: two concepts whose labels derive the same slug both import with
  distinct slugs; the same file imported twice gives each concept the same slug both times; no slug
  is derived from an identifier.
- **T011** — Fatal findings and atomicity: an absent identifier, a blank-node concept, and an
  identifier the identity rules refuse each fail the run; every problem in a file is collected
  rather than raised at the first; the transaction rolls back so the database is exactly as it was
  (`research.md` R7). Tests cover each fatal kind and a multi-problem file.
- **T012** — The report, populated by a real run: created and updated records and set-aside entries
  all present with their reasons, as data.

## Phase US-2 — Running the same import again brings the vocabulary up to date (#62, P1)

- **T013** — Idempotent re-run: importing the identical file twice creates nothing new, recreates
  nothing, and every record keeps its database key. Tests assert primary keys are stable and
  references still resolve.
- **T014** — Authoritative update for records the file contains: a corrected preferred label lands;
  an alternative label, a note, and a relationship the publisher removed are removed here too.
- **T015** — Records the file no longer mentions: untouched, still holding their identifiers, and
  named in the report's absent-from-source bucket. Test includes a concept referenced by another
  record, asserting the reference survives.
- **T016** — The vocabulary's own metadata — name, description — updated from the file, identifier
  unchanged.
- **T017** — A run that fails partway leaves the database exactly as it was, asserted against a
  populated database rather than an empty one.

## Phase US-3 — The concepts arrive with their labels and notes (#63, P2)

- **T018** — Labels: preferred labels in other configured languages, alternative and hidden labels,
  each with kind and language, written through `Concept.add_label` (`research.md` R5). Test the
  default-language preferred label is `Concept.label` and is *not* duplicated as a `ConceptLabel`
  row — the model refuses that, and the importer must not attempt it. Also carries T014's deferred
  case (decisions.md D20): a re-import of `rocks_updated.ttl` removes the alternative label the
  publisher dropped, leaving the concept itself intact.
- **T019** — Notes: definition and the six note kinds, each with its language, via
  `Concept.add_note`. Also carries T014's deferred case (decisions.md D20): a re-import of
  `rocks_updated.ttl` removes the note the publisher dropped, leaving the concept itself intact.
- **T020** — A label or note in a language the site is not configured for: stored nowhere, named in
  the report with its language and a count, concept still imported.
- **T021** — Values the models have no place for — a notation, a mapping to another vocabulary, a
  non-SKOS predicate — set aside and reported, run still successful. Includes a normalisation case
  (a foreign description read as a definition) asserted to be reported, never silent (FR-009).
- **T022** — A concept with no preferred label in the vocabulary's default language: set aside,
  reported, rest of the vocabulary imported.

## Phase US-4 — The relationships between concepts arrive (#64, P2)

- **T023** — `broader` and `narrower` both producing the single canonical row, with the ends the
  right way round; both directions stated for one pair still producing exactly one row.
- **T024** — `related` stored once as a symmetric relationship, including when the file states it
  twice.
- **T025** — A relationship end that is neither in the file nor in the database: set aside,
  reported with both ends, run successful. An end already in the database from an earlier import:
  stored.
- **T026** — A re-import with a relationship removed removes it, leaving both concepts. This is
  T014's third deferred case (decisions.md D20); `rocks_updated.ttl` already drops granite's
  `related` edge to quartz.

## Phase US-5 — Collections arrive, ordered ones in order (#65, P2)

- **T027** — Collections created inside the vocabulary holding their published identifiers, with
  `skos:member` membership.
- **T028** — Ordered collections: `skos:memberList` walked in order via the RDF list
  (`research.md` R2), `ordered` set, positions assigned. Test asserts the order survives a
  re-import that changes it.
- **T029** — A member neither in the file nor in the database: collection still created, member set
  aside and reported. A re-import that adds and removes members leaves membership matching the
  file.
- **T030** — A blank-node collection fails the run, on the same rule as concepts (D3), while an
  ordered collection's blank-node list nodes are read normally.

## Phase US-6 — Standards and documentation (#66, P3)

- **T031** — Standards test extension: every failure message and report reason this feature
  introduces is translatable and uses named placeholders; developer-facing diagnostics exempt.
- **T033** — Closes decisions.md D27's own gap: a test asserting that every SKOS predicate
  appearing anywhere in the fixture corpus is either read by the importer or named in the report.
  D27 silently skips a SKOS predicate that has a model home but no read path yet, which is correct
  only while a later story still owes that read path. Once every story has landed, a silent skip is
  the disappearance D1 forbids, and this test is what turns "revisit if" into a check that fails.
- **T034** — Closes the gap US-5 left named rather than invented: a collection an earlier import
  created that the current file no longer mentions is not reported anywhere. A concept in that
  position is named in the report's absent-from-source list; a collection is a record with its own
  identity and should be too. Report it, and test it.
- **T032** — Documentation in the same PR as the code (Article VI): README gains the import
  surface, CHANGELOG gains its entry, the public callable and the report carry docstrings. The
  README text and any other public markdown get the humanizer pass before the PR leaves draft.

## Verification at every task

`poetry run pytest` green, `poetry run ruff check .`, `poetry run mypy`, `poetry run deptry .`,
and `pre-commit run --all-files` — the repo's own gate, run through `forge verify` at each stage
exit. No migration is expected at any point; `makemigrations --check` staying clean is itself an
assertion this feature adds no schema change.
