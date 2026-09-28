# Progress — 007 Import keeps the languages the site supports and reports the rest

Append-only log of stage transitions and gate outcomes.

## 2026-08-04

- **S0 INTAKE** — issue #51 grilled. Grounding first: the issue, its dependency #50 (merged), the
  sibling #52, roadmap R2, `GOALS.md`, and the landed importer. That grounding showed two of the
  issue's three clauses already delivered by #50, and the feature was reported back to Sam as
  probable residue. What kept it alive is that language matching was exact string equality against
  `settings.LANGUAGES`, so a site on `en-gb` importing a vocabulary published as `en` stored
  nothing — the issue's own first sentence, unsatisfied. Three questions, all answered: match by
  base language, match in both directions, and this feature owns *what* a curator is told while #52
  owns *where* they read it. A fourth question drifted into rule design and was pulled back on
  Sam's correction. Feature statement confirmed. Issue labelled `accepted`.
- **S1 SPECIFY** — repo synced first at Sam's instruction: `main` was two commits behind
  (PR #68, constitution Articles XIV and XV), and Article XIV constrains this feature's shape.
  Branch `007-import-keeps-published` created. `spec.md` written: 5 user stories (2×P1, 2×P2,
  1×P3), FR-001..015, SC-001..021. Clarify coverage scan run and self-answered — eight ambiguities
  resolved into the spec across two sessions, rationale in `decisions.md` (D1–D11). The scan caught
  a defect in the draft: FR-003 as first written collapsed competing variants to one winner
  everywhere, which is correct for a preferred label (whose uniqueness constraint is conditional on
  `kind="preferred"`) and wrong for alternative labels, hidden labels, and notes, which carry no
  such constraint. Spec lint green: no unresolved markers, every FR carried by a story scenario,
  goal ids cited (G8, G6, G4).
- **S2 SETUP** — spec committed and pushed as `forge-aeo[bot]`. Issue #51 promoted to the epic in
  place (intake paragraph preserved under `## Original request`). Story sub-issues #69–#73 created
  and linked, no lifecycle labels, milestone `v0.1.0`. Draft PR #74 opened by the bot, title
  byte-identical to the epic, `Closes` block covering the epic and all five stories, milestone set.
  `check-issue-titles` green, `stage-exit --stage S2` green (clarifications, issue-titles,
  pr-title).
- **Spec gate — APPROVED** by Sam (SamuelJennings), 2026-08-04, in session. Scope as specified,
  including all five self-resolved decisions surfaced in the brief: script-differing variants
  joined by base-language matching, the variant contest scoped to kinds the models hold one of per
  language, the predominant variant winning a contest, the vocabulary default language resolving by
  the same rule, and no compatibility path owed. Sam also flagged that the S3R design-review gate
  is newly added and this run is its first trigger, to be watched. Proceeding to S3 PLAN.

## 2026-08-05

- **S3 PLAN** — `plan.md`, `research.md` R1–R5, `tasks.md` T001–T020, ledger schema-valid, committed
  as `28f69e6`. One new `LanguageMatcher` class, four changed methods in `skos.py`, no model, no
  migration, no new dependency. Research R1 measured and rejected Django's own
  `get_supported_language_variant`: it refuses any language Django ships no translation catalog for,
  *including ones the project declares in `LANGUAGES`*, so a site configured for `sga` would store
  nothing.
- **S3R DESIGN REVIEW — first live run of the gate.** `check-skills --role design_reviewer` green
  before dispatch. Three reviewers in parallel, one lens each, against the plan with no diff in
  existence. `check-receipts` green on all three returned reports, all three schema-valid against
  `review-findings.schema.json`.
  - **Verdict `request_changes` on all three lenses.** 22 findings: 4 high (all `verified`), 8
    medium, 10 low. Every high was re-checked against the code before it was accepted, and all four
    held.
  - **SPEC-001** — the winner rule was assigned to one of the two places that compute a winner, so
    `Concept.label` and the surplus report could disagree and the report would contradict the
    database. Fixed by moving the rule onto `LanguageMatcher` (new T021) and having both call sites
    read it.
  - **SPEC-002** — reusing `SURPLUS_PREFERRED_LABEL` for contest losers loaded one reason with two
    populations FR-008 needs kept apart, and rendered a factually false sentence for the new one.
    Fixed by a dedicated set-aside reason (new T022) and an explicit fold membership in T004.
  - **ARCH-001** — the plan's "four call sites" missed a fifth raw-tag comparison at `skos.py:543`,
    which would have crashed the feature's own headline scenario with an uncaught `ValidationError`.
    Fixed in T008; one comparison changes operand.
  - **SEC-001** — `configured_language_codes()` returns a `set`, and Django's default `LANGUAGES`
    contains one ambiguous base (`zh-hans` / `zh-hant`), so a `zh`-tagged file would store under a
    script chosen by per-process hash order. Verified independently: five fresh processes returned
    both orders. Fixed by a stated lexicographic tie-break over an ordered sequence (T001, D15).
  - **Findings that removed work:** the `en`-published fixture in T005 was redundant against 51
    existing `@en` fixtures, and T002's second constructor was deleted in favour of one method on
    `SkosGraph`. No task was found without spec or constitution provenance.
  - Mediums and lows applied in the same pass: fixture paths corrected, the predominance denominator
    stated, the returned code's spelling pinned, FR-009's identity guarantee scoped, the FR-010
    invariant test extended to Django's default `LANGUAGES`, README obligation added, and one
    Complexity Tracking row added for the report bucket that now grows on the success path.
  - Three findings were spec-adjacent rather than plan faults and are recorded as D15, D16 and D17
    rather than resolved silently. None changes an approved behaviour, and all three are named in
    the plan notification for veto.
  - `design_review_cycles` 1 of 1 used.
- **S3R ROUND TWO** — the same three lenses re-run against the revised artefacts, `check-skills`
  green before dispatch and `check-receipts` green on all three returned reports, all schema-valid.
  **Verdict `approve` on all three lenses, risk `low`, zero critical and zero high.** The gate is
  green and the run proceeds to the plan notification.
  - Each lens confirmed its own round-one blocker was closed by the edit made rather than merely
    named, and checked the two added tasks (T021, T022) on its own terms. The architecture lens
    independently re-derived the `research.md` R4 overturn and agreed with it; the security lens
    re-measured the Django `zh-hans`/`zh-hant` reachability rather than trusting its own prior note.
  - Twelve non-blocking findings (8 medium, 4 low), applied in the same pass rather than carried as
    watch items, since each was a one-sentence edit. Three lenses converged independently on the same
    three: `SkosGraph.first_literal`'s `language=` filter is a sixth, seventh and eighth comparison
    that decides what the vocabulary and its collections are *named*; T002's predominance count fixed
    its predicate but not its node set, which would have silently changed #50's merged
    default-language rule; and T013's re-keying makes one candidate group hold both same-language
    duplicates and variant losers, with no stated discriminator between them.
  - Two findings caught factual errors introduced by the round-one fixes. The plan's "whole surface"
    claim was falsified for the second time, and the FR-010 test written to run "under Django's
    default `LANGUAGES`" would have run under `tests/settings.py`'s own three-language list and
    pinned nothing while reading as an obligation met. Both are recorded in D12.
  - One low finding became a decision rather than an edit: D18, that a concept's local URL follows the
    file rather than the concept, because predominance is file-wide and the slug is recomputed every
    run. Carried into #52's and R6's specification.
- **Plan notification (veto window, not a gate)** — sent to Sam carrying the panel's verdict.
  Silence is consent; the run proceeds to S4 IMPLEMENT.
- **S4 IMPLEMENT — US0 (foundational phase, T001/T002/T021/T003/T022/T004/T005), Implementer.**
  `craft-tdd` and `craft-increments` loaded by name, receipts verified against the brief before
  any task started. Baseline confirmed green (668 tests, HEAD `06a7760`) before touching anything.
  Seven commits, one per task, tree green and clean after each:
  - **T001** — `exchange/languages.py`: `LanguageResolution` and `LanguageMatcher.resolve`. Exact
    match wins; otherwise the least specific configured language sharing the base, computed over a
    deterministically ordered sequence (D15); case-insensitive; returns the code exactly as
    declared. `sga` regression pins the rejection of Django's own resolver (research.md R1).
  - **T002** — `SkosGraph.preferred_label_tag_counts` (concept nodes' `skos:prefLabel` only, per
    D4/D5); `SkosImporter.run` builds one matcher per run and passes it to `SchemeResolver` and
    `ConceptImporter` as a keyword-only constructor argument. Neither collaborator's body reads
    `self.matcher` yet — the five raw-tag comparisons are out of this phase's scope by the brief's
    own prohibition.
  - **T021** — `LanguageMatcher.resolve_winner`: one cascading sort key implements exact-match-first,
    then predominance, then a lexicographic tag tie-break, so `preferred_label_in` and
    `import_labels` will read the identical rule once their stories wire it in (S3R SPEC-001).
  - **T003** — `NormalizedReason.LANGUAGE_SUBSTITUTION`, in the normalised bucket (a substitution
    *was* stored).
  - **T022** — `SetAsideReason.VARIANT_NOT_KEPT`, a dedicated reason for a contest loser —
    `SURPLUS_PREFERRED_LABEL`'s message is false for this case (S3R SPEC-002, D14). Regression test
    pins `SURPLUS_PREFERRED_LABEL`'s own message unchanged.
  - **T004** — `ImportReport.language_account()`: a fold over `{UNCONFIGURED_LANGUAGE,
    VARIANT_NOT_KEPT}`, explicit membership rather than "carries a `language` param" (D14's own
    failure mode, guarded against directly).
  - **T005** — three fixtures (`variants.ttl`, `en-gb-only.ttl`, `declares-de-at.ttl`); no `en`-only
    fixture (51 already exist). Pass the existing predicate-coverage sweep unmodified — every
    variant tag is still `UNCONFIGURED_LANGUAGE` under this phase's untouched call sites.
  Full verify green throughout: `poetry run pytest -q` (724 passed), `ruff check .`, `ruff format
  --check .`, `mypy controlled_vocabularies`, `deptry .`, `pre-commit run --all-files`. Worktree
  clean. Three naming/shape choices not dictated by the brief are recorded as D19–D21. Next:
  US-1 (T006–T010) wires the matcher into the five call sites.

- **S4 IMPLEMENT — US-1 (#69, T006–T010), Implementer.** `craft-tdd` and `craft-increments`
  loaded by name, receipts verified against the brief before any task started. Baseline confirmed
  green (724 tests, HEAD `5c31ce2`) before touching anything. Five commits, one per task, tree
  green and clean after each:
  - **T006** — `SchemeResolver.determine_default_language` resolves both its declared-language and
    commonest-fallback branches through `LanguageMatcher.resolve()` instead of raw set membership,
    so a vocabulary declaring itself `de-at` on a `de` site resolves its default language to `de`
    (D9). Tested directly against the scheme's own `default_language`/`effective_default_language`
    fields rather than end-to-end concept import — a concept whose only preferred label is a
    variant still needed T007 to actually import, so "every concept is named" is T007's own test.
  - **T007** — `SkosGraph.preferred_label_in` returns every `(published tag, value)` candidate a
    node's `skos:prefLabel` carries, unfiltered by language (configured-language policy stays off
    the RDF boundary, Article XIV); `ConceptImporter.import_concepts`, its one caller, filters for
    candidates resolving to the target default language and reads `LanguageMatcher.resolve_winner`
    (T021) for `Concept.label`. An exact match is proven not displaced by a more predominant
    variant.
  - **T008** — `import_labels` and `_import_notes` resolve every published tag through the matcher
    before comparing against the default language or storing, fixing both raw-tag comparisons the
    plan named — the crash on the feature's own headline scenario needed both, not just one.
    Inside the default-language branch, a loser is discriminated against the tag T007's winner rule
    actually chose (re-derived from the same `preferred_label_in`/`resolve_winner` computation,
    never threaded as a parameter): a same-tag duplicate keeps `SURPLUS_PREFERRED_LABEL`, a losing
    variant takes `VARIANT_NOT_KEPT` (D14). A new module-level `_localized_literal()` resolves a
    vocabulary's name/description and a collection's name through the matcher from outside
    `SkosGraph` (call sites 6/7/8); `CollectionImporter` gained the `matcher` constructor argument
    this needs. `configured_language_codes()` deleted, its three callers now reading through the
    matcher. `TestEverySkosPredicateIsReadOrReported`'s own evidence helpers
    (`_coverage_label_covered`/`_coverage_note_covered`) carried two assumptions this feature
    breaks by design — a landed value's language can now differ from its published tag, and
    `VARIANT_NOT_KEPT` can now actually fire — corrected per D22, which D21 had already
    anticipated; the sweep's own test function and assertion are unchanged.
  - **T009** — every value stored under a language other than its published tag — `Concept.label`
    (in `import_concepts`, when the default-language slot is filled by a variant), a `ConceptLabel`
    row, or a `ConceptNote` row (including the `dcterms:description` alias, as a second,
    independent normalisation axis alongside `FOREIGN_DEFINITION`) — reports
    `NormalizedReason.LANGUAGE_SUBSTITUTION`, distinguishable from `language_account()`'s
    not-stored bucket and never fired for a pure case-only match (D8).
  - **T010** — the FR-010 invariant: no `ConceptLabel`, `ConceptNote`, or scheme
    `effective_default_language` ever holds a language outside `settings.LANGUAGES`, checked after
    each of the feature's own fixtures, plus one case run explicitly under Django's own
    99-language default (`@override_settings(LANGUAGES=global_settings.LANGUAGES)`) rather than
    relying on "no override," which would silently mean `tests/settings.py`'s own three-language
    list instead (D12/D17).
  Full verify green throughout: `poetry run pytest -q` (745 passed), `ruff check .`, `ruff format
  --check .`, `mypy controlled_vocabularies`, `deptry .`, `pre-commit run --all-files`. Worktree
  clean. One non-obvious choice recorded as D22. Next: US-2 (#70, T011–T012) — the account
  populated from a real import.

- **S4 IMPLEMENT — US-2 (#70, T011–T012), Implementer.** `craft-tdd` and `craft-increments`
  loaded by name, receipts verified against the brief before any task started. Baseline confirmed
  green (745 tests, HEAD `aa0d122`) before touching anything. Two commits, one per task, tree green
  and clean after each:
  - **T011** — `TestTheLanguageAccountReflectsARealImport`, driving `ImportReport.language_account()`
    from a real import through `import_skos` rather than a hand-built report: a fixture (built via
    `tmp_path`, not a checked-in fixture — this scenario is not reused elsewhere) carrying three
    languages the test site is not configured for (`es`, `ja`, `it`), with distinct multiplicities
    (2, 1, 3) so the breakdown is a real assertion rather than a total that could pass by accident,
    proves the account covers every value not stored for a language reason and no value that was
    stored.
  - **T012** — a second test in the same class: `rocks.ttl` — #50's own established clean-run
    fixture, already pinned elsewhere as importing with `report.set_aside == []` — reused rather
    than duplicated (D21), proving the account is present and empty rather than absent after a run
    that left nothing behind (SC-013).
  Both tests passed on their first run, since `language_account()` (T004) and the set-aside
  population it folds over were already implemented in earlier phases; T011/T012 are test-only
  tasks by tasks.md's own text, and no production code changed. Recorded as D26 so this reads as a
  characterization choice rather than a skipped RED step.
  Full verify green throughout: `poetry run pytest -q` (747 passed), `ruff check .`, `ruff format
  --check .`, `mypy controlled_vocabularies`, `deptry .`. Worktree clean. Next: US-3 (#71,
  T013–T015) — competing variants resolve the same way every time.

- **S4 IMPLEMENT — US-3 (#71, T013–T015), Implementer.** `craft-tdd` and `craft-increments`
  loaded by name, receipts verified against the brief before any task started. Baseline confirmed
  green (747 tests, HEAD `f22ede7`) before touching anything. Three commits, one per task, tree
  green and clean after each:
  - **T013** — `import_labels`'s preferred-label contest (call site 3) re-keyed on the *resolved*
    configured language rather than the raw published tag, with the winner read once from
    `LanguageMatcher.resolve_winner` (T021) per resolved language — the identical computation
    `import_concepts` already runs for `Concept.label` over the identical `preferred_label_in`
    candidates (D27). Grouping by raw tag was a live crash: two *different* tags resolving to one
    non-default configured language were each their own singleton "winner" under the old grouping,
    so both reached `add_label()` and the second raised the model's own uniqueness
    `ValidationError`, uncaught — no fixture before this task exercised a two-*different*-tag
    contest outside the default language, so nothing had caught it. Six new tests: the crash no
    longer happens, the predominant (not alphabetically-first) variant is stored, the same file
    imports the same value twice (SC-006), an exact match in a non-default language still wins over
    a more predominant variant (SC-005), `import_labels`'s own winner agrees with `Concept.label`
    for a predominance-driven default-language case, and the spec's own Edge Case — an exact match
    that fails on its own merits (`EMPTY_SLUG`) is never backfilled by its variant sibling, already
    true via `import_concepts`'s existing pre-write check and pinned here as a regression.
  - **T014** — the general (non-default-language) branch's contest losers now get the same
    discriminator the default-language branch has carried since T008 (D24): a loser sharing the
    winner's published tag (case-insensitively) is a same-language duplicate
    (`SURPLUS_PREFERRED_LABEL`); a loser under a different tag is a genuine contest loser
    (`VARIANT_NOT_KEPT`, T022, D14), recoverable by configuring its published tag and reaching
    `language_account()`, unlike the duplicate (D28: the two branches' post-comparison paths differ
    enough that copying the two-line comparison reads simpler than a shared helper). Test: a group
    of three preferred labels for one non-default language — two under one tag, one under a
    variant — yields exactly one entry of each reason, only the variant one in the account, and the
    run succeeds (SC-008).
  - **T015** — the asymmetry (FR-004, SC-007): alternative labels, hidden labels and notes carry no
    per-language cardinality limit, so T013/T014's contest — scoped to
    `kind == ConceptLabel.Kind.PREFERRED` — never touches them; every other kind already fell
    through to the unconditional store, before and after T013/T014. Test-only, reusing
    `variants.ttl` (T005, built and reserved for exactly this population): both an `en-gb` and an
    `en-us` alternative label land on the `en` site, and both variants of a note do too, with no
    production change (D29, the same shape D26 recorded for T011/T012).
  Full verify green throughout: `poetry run pytest -q` (747 → 753 → 755 → 758 passed), `ruff check
  .`, `ruff format --check .`, `mypy controlled_vocabularies`, `deptry .`. Worktree clean. Two
  non-obvious choices recorded as D27–D28, one characterization choice as D29. Next: US-4 (#72,
  T016–T017) — adding a language and re-importing fills it in.

- **S4 IMPLEMENT — US-4 (#72, T016–T017), Implementer.** `craft-tdd` and `craft-increments` loaded
  by name, receipts verified against the brief before any task started. Baseline confirmed green
  (758 tests, HEAD `1cbf596`) before touching anything.
  - **T016** — `TestReimportAfterAddingALanguageStoresItsValues`, driving the whole path from
    `rocks.ttl` on disk through `import_skos` twice, `override_settings(LANGUAGES=...)` between
    the runs, per the brief's acceptance text: first under `LANGUAGES=[en]` alone, then under
    `LANGUAGES=[en, fr]`. Two tests: the concepts already present (`igneous`, `granite`,
    `sedimentary`) carry their exact `fr` preferred labels after the second run, having carried
    none after the first (SC-014); and the second run's `report.language_account()` no longer
    counts `fr` (three occurrences, one per concept, counted by hand against the fixture) as left
    behind, while the first run's did (SC-016). Both passed on first run — no production code
    changed, recorded as D30, the same shape D26/D29 recorded for T011/T012 and T015.
  - **T017** — `TestReimportAfterAddingALanguageKeepsEveryOtherRecordUnchanged`, scoped exactly as
    D16 and the task text require: the identity test snapshots `(pk, uri, static_uri, slug,
    local_url)` for the scheme, all five `rocks.ttl` concepts and both collections before the
    second run and compares after, over every record the fixture defines rather than a sample
    (SC-015); the content test checks `granite`'s alternative label, hidden label and scope note
    alongside `granite`'s and `igneous`'s preferred label and definition are unchanged in `en`,
    the language already held before the re-import. `ConceptLabel`/`ConceptNote` pks are
    deliberately not asserted (#50 deletes and recreates them every run). Both passed on first
    run — no production change, recorded as D31, the same shape as D30.
  Full verify green throughout: `poetry run pytest -q` (758 → 760 → 762 passed), `ruff check .`,
  `ruff format --check .`, `mypy controlled_vocabularies`, `deptry .`. Worktree clean. Two
  characterization choices recorded as D30–D31. Next: US-5 (#73, T018–T022) — translatable
  messages, deliberate indexing, and reusable test material.

- **S4 IMPLEMENT — US-5 (#73, T018–T020), Implementer.** `craft-tdd` and `craft-increments` loaded
  by name, receipts verified against the brief before any task started. Baseline confirmed green
  (762 tests, HEAD `e669de1`) before touching anything. Three commits, one per task, tree green and
  clean after each. T021 and T022 (the foundational-phase reason additions themselves) were already
  done; this dispatch's own brief scoped it to T018–T020.
  - **T018** — Two tests added to `tests/test_standards.py`,
    `TestImportLanguageMessagesUseNamedPlaceholders`, following that file's own
    translatable-message form: each asserts `NormalizedReason.LANGUAGE_SUBSTITUTION`'s and
    `SetAsideReason.VARIANT_NOT_KEPT`'s templates are lazily translatable, carry only named
    placeholders, and render correctly with real values. `tests/test_exchange/test_report.py`
    already sweeps every member of both closed vocabularies (`TestSetAsideReasonVocabulary`,
    `TestNormalizedReasonVocabulary`, `TestReasonTemplatesUseOnlyNamedPlaceholders`) and so already
    covered both reasons before this task; the brief named `test_standards.py` specifically, so the
    two are additional, deliberately overlapping coverage rather than a gap being filled (D32). RED
    proven by hand: `report.py` was locally edited twice — a bare non-lazy string with a positional
    `%s`, then a lazy string with two positional placeholders instead of named ones — running the
    two new tests after each edit and observing the correct one fail for the reported reason, then
    reverting with `git checkout` before the next edit and before committing. No test or production
    file outside this task's own new tests was touched.
  - **T019** — `CONTEXT.md` gains a new "Importing published vocabularies" glossary table: base
    language, variant, and substitution, worded to match `report.py`'s own reason labels and
    templates rather than paraphrasing them (FR-014, SC-019). No test — verified by reading the
    file, per the acceptance scenario's own terms.
  - **T020** — README's "Importing a published vocabulary" section gains three paragraphs between
    the upsert paragraph and the `ImportReport` bucket list: the base-language matching rule in both
    directions and its script caveat (D6), that the package stores content for every code in
    `settings.LANGUAGES` and Django's own 99-language default applies when a project declares none,
    and that a concept's local URL can move between imports when the file's predominant variant
    changes (D18). CHANGELOG's `[Unreleased]` → `Added` section gains one new bullet, alongside the
    existing `import_skos` entry, stating the same behaviour change at changelog length. Public
    markdown, written plainly, no internal process language.
  Full verify green throughout: `poetry run pytest -q` (762 → 764 passed, T019/T020 doc-only and
  added no tests), `ruff check .`, `ruff format --check .`, `mypy controlled_vocabularies`,
  `deptry .`. Worktree clean, diff scoped to `tests/test_standards.py`, `CONTEXT.md`, `README.md`,
  and `CHANGELOG.md` — no importer behaviour touched. One non-obvious choice recorded as D32. This
  is the last story of the feature.

## 2026-08-05 (continued)

- **S4 IMPLEMENT — FIX-2 (T029–T034, FR-017 to FR-020), Implementer.** `craft-tdd` and
  `craft-increments` loaded by name, receipts verified before any task started. Baseline confirmed
  green (790 tests, HEAD `cd4f1c6`) before touching anything. Six commits, one per task, tree green
  and clean after each.
  - **T029** — `assign_unique_slug` now derives a concept's slug from `identifier_slug_segment(concept.static_uri)`
    (a new shared helper: the identifier's fragment, else the last path segment) instead of from
    `label`; the pre-write `EMPTY_SLUG` check moved with it. RED proven first against the current
    branch: `test_a_publisher_rename_leaves_the_slug_and_local_url_unchanged` failed
    `'granite-revised' == 'granite'` (the slug still tracking the renamed label) before the fix, and
    three related new/updated tests failed the same way. Five pieces of pre-existing test material
    directly encoded D6 ("never derived from the identifier," by name) and were rewritten rather than
    left red or silently deleted — `TestConceptSlugs` and one assertion in
    `TestConceptLabelIsSelectedByTheWinnerRule` in `test_skos.py`, the `empty_slug_label.ttl` fixture
    and its two tests (retargeted from a bad label to a bad identifier segment, since the label no
    longer drives slug validity), and the `EMPTY_SLUG`-based edge-case test in
    `TestExactMatchPreferredLabelFailingOnItsOwnMeritsIsNotBackfilledByAVariant` (now demonstrated via
    `VALUE_TOO_LONG` instead, still label-driven). Full rationale for each in D38.
  - **T030** — `ConceptScheme` gains `slug_is_manual` (migration `0006_conceptscheme_slug_is_manual`)
    and `set_slug()`, mirroring `Concept`'s own mechanism; `save()` only re-derives the slug from
    `name` when unset. `SchemeResolver.resolve_scheme` now sets the slug from
    `identifier_slug_segment(declared_uri)` on every touch (D39 records why recomputing is safe
    rather than gating on `created`). RED proven first: a scheme re-imported with its name arriving
    in a different language moved `scheme.slug` from `"colours"` to `"color"` and the held concept's
    `local_url` with it — the exact case `decisions.md` D35 measured — before the fix.
  - **T031** — A dedicated guard class, `TestConceptSlugFollowsTheLabelWithNoPublisherIdentifier` in
    `test_models.py` (FR-019/SC-030), written before relying on the pre-existing US-2 coverage to
    keep proving it. Passed on first run — no production change, since T029/T030 only touch the
    importer's own slug assignment and `Concept.save()`'s `slug_is_manual` branch, which a
    locally-authored concept never sets.
  - **T032** — `TestConceptSlugCollisionIsIdentifierDerived` (FR-020/SC-029): two identifiers sharing
    a last segment get distinct slugs, and each keeps its own slug when the same content is
    re-imported with the records declared in reverse file order. Passed on first run: `concept_nodes`
    was already sorted by the full identifier string before T029 (never by file order), and
    `assign_unique_slug`'s existing `taken_slugs` mechanism (FIX 16, D49) already reads a concept's
    own prior slug back before minting a new suffix — once T029 moved the suffix base to the
    identifier, those two pre-existing pieces already satisfy FR-020 together (D40).
  - **T033** — README's import section, CHANGELOG's `[Unreleased]` entry, and `CONTEXT.md` (new
    **Slug** glossary row, updated **Local URL** row) now describe a local address as
    identifier-derived and permanent, and name the accepted cost plainly: opaque identifiers give
    opaque addresses. `assign_unique_slug`'s docstring was corrected in T029's own commit rather than
    deferred here, since leaving it asserting the opposite of the code it documents for even one
    commit was not defensible; `Concept.set_slug`'s docstring, which anticipated this use in future
    tense, now states it in present tense and cross-references `assign_unique_slug`. Public markdown
    reviewed against the humanizer checklist by hand; no rewrites needed.
  - **T034** — Full re-verification: `poetry run pytest -q` (790 → 798 passed), `ruff check .`,
    `ruff format --check .` (25 files), `mypy controlled_vocabularies` (11 source files),
    `deptry .`, `makemigrations --check --dry-run` (clean), and a standalone migrate-from-zero run
    against a fresh file-based SQLite database (all six `controlled_vocabularies` migrations plus
    `auth`/`contenttypes` applied cleanly, ending at `0006_conceptscheme_slug_is_manual`).
  Three non-obvious choices recorded as D38–D40. Worktree clean. `T023` (FIX-1's dropped,
  never-committed FR-016 implementation) confirmed absent from the branch — nothing to remove.
  A record's local address can now move for exactly one reason: the publisher reassigning its own
  identifier. Next: FS-007 re-gate and convergence.

## 2026-08-05 (continued further)

- **S4 IMPLEMENT — FIX-2 (T035–T037), Implementer.** `craft-tdd` and `craft-increments` loaded by
  name, receipts verified before any task started. Baseline confirmed green (798 tests, HEAD
  `936c7b7`) before touching anything. Two regressions, each proven RED with the orchestrator's own
  reproduction before any production code changed, two commits, tree green and clean after each.
  - **T035** — `SchemeResolver.resolve_scheme` wrote an identifier-derived slug straight onto
    `row.slug` with no collision handling, so two published vocabularies ending in the same
    identifier segment (e.g. two `/colours` schemes) hit `ConceptScheme.save()`'s refusal as an
    uncaught `ValidationError` and rolled back the run. RED proven first: importing
    `<http://a.org/colours>` then `<http://b.org/colours>` raised exactly that on this branch and
    imported cleanly on `cd4f1c6`. Fixed by factoring `assign_unique_slug`'s own collision shape
    into a shared `unique_slug_for_identifier(static_uri, taken_slugs)`, called by both
    `ConceptImporter.assign_unique_slug` and `SchemeResolver.resolve_scheme` (Article XIV) — a
    numeric suffix minted only when the candidate already belongs to a different record's
    `static_uri`. `ConceptScheme.save()`'s own refusal is untouched. Full rationale in D41.
  - **T036** — The scheme path had no guard for an identifier segment that `slugify()` strips to
    nothing, unlike the concept path's pre-write `EMPTY_SLUG` check; `resolve_scheme` let
    `ConceptScheme.save()` raise `ValidationError({'slug': ['An explicit slug must not be
    empty.']})` instead. RED proven first: importing `<http://c.org/vocab/#±> a
    skos:ConceptScheme ; skos:prefLabel "Symbols"@en` raised exactly that on this branch and
    imported cleanly on `cd4f1c6`. Fixed by checking `unique_slug_for_identifier`'s result ahead of
    `row.save()` and adding `FatalReason.VOCABULARY_SLUG_UNUSABLE` — fatal rather than set aside,
    since without a resolvable vocabulary there is nothing for the rest of the file to import into.
    No fallback to `row.name`. Full rationale in D42.
  - **T037** — Full re-verification: `poetry run pytest -q` (798 → 806 passed), `ruff check .`,
    `ruff format --check .` (25 files), `mypy controlled_vocabularies` (11 source files),
    `deptry .`, `makemigrations --check --dry-run` (clean), and a standalone migrate-from-zero run
    against tests' in-memory SQLite database (all six `controlled_vocabularies` migrations plus
    `auth`/`contenttypes` applied cleanly, ending at `0006_conceptscheme_slug_is_manual`, no new
    migration). `decisions.md` gains D41–D42, one entry per defect, each recording the regression
    against `cd4f1c6`, the reproduction that established it, and the resolution chosen.
  Two non-obvious choices recorded as D41–D42. Worktree clean. A vocabulary's own slug now resolves
  a collision or an unusable derivation exactly as a concept's already did, closing the one gap
  T030 left between the two paths. Next: FS-007 re-gate and convergence.

## 2026-08-05 (fix cycle 4)

- **S4 IMPLEMENT — fix cycle 4 (T044–T050), Implementer.** `craft-tdd` and `craft-increments`
  loaded by name. Baseline confirmed green (828 tests, HEAD `10c069a`) before touching anything.
  Round-three review reports (correctness/security/architecture) read in full; seven tasks, one
  commit each, tree green after every one. RED proven first for T044/T045/T046 per the brief.
  - **T044** (ARCH-301/CORR-303/SEC-302) — a *created* scheme or collection with an over-long
    only name was persisted with `name == ''`, a blank required `CharField` `full_clean()` then
    refuses. RED: importing a 300-character `skos:prefLabel` gave `report.fatal == []` and a
    stored row with `name == ''` on this branch. Fixed by splitting on what the record costs the
    rest of the file (D42's own reasoning, applied to the name): a created scheme is now fatal
    (`FatalReason.VOCABULARY_NAME_UNUSABLE`); a created collection is set aside entirely
    (`continue`d before `row.save()`). A matched row of either kind is unaffected. Two round-three
    tests that asserted only `len(name) <= max_length` (satisfied by `''`) were strengthened in
    place — quoted and explained in the completion report as an intentionally overturned
    assertion, not a silent edit. D49.
  - **T045** (SEC-301) — T041's read-back means a matched record's stored slug now reaches
    `set_slug()`/`save()`'s manual-slug validation unchanged; a value written out of band
    (`.update()`, `bulk_create`, a migration) let `ValidationError` escape `import_skos` entirely
    for all three kinds. RED: planting an invalid slug via `.filter(pk=...).update(slug=...)`
    then re-importing a matching file raised uncaught on this branch, for scheme, concept and
    collection alike. Fixed by wrapping each of the three writes and converting to
    `SetAsideReason.STORED_SLUG_INVALID`, the same discipline `import_labels`/`_import_notes`
    already apply. D50.
  - **T046** (SEC-303) — `unique_slug_for_identifier`'s `base[: max_length - len(suffix_text)]`
    goes to zero or negative once the suffix is as long as the field, discarding the base
    entirely. RED: `unique_slug_for_identifier(..., max_length=2)` with a colliding suffix
    returned the bare suffix `'-2'`. Fixed by construction with
    `max(max_length - len(suffix_text), 1)`; unreachable at the three real call sites
    (`max_length=255`), a direct unit test added on the helper regardless. D51.
  - **T047** (CORR-305) — the `VALUE_TOO_LONG` set-aside for a scheme's or collection's
    any-language name fallback reported the effective default language even when the value was
    published in a different one. `SkosGraph.first_literal_with_language` now pairs the same
    value `first_literal` selects with the tag it actually carried. D52.
  - **T048** (CORR-301/CORR-302/CORR-304) — test-only, no production change (round-three's own
    mutation testing already confirmed the guarded code correct). Added the Collection collision/
    read-back case to `TestASlugAlreadyStoredIsReadBackNeverRecomputed`; extended its
    locally-authored-record test in place with a third record (a Collection) plus
    `slug_is_manual`/rename-stability assertions on all three; added `Collection`'s empty/
    malformed manual-slug refusal tests mirroring `Concept`'s. D53.
  - **T049** (ARCH-302) — `slug_is_manual`, `set_slug()`, and `save()`'s manual-slug validation
    branch were declared three times, byte-identical apart from `help_text`. Extracted onto
    `StaticUriModel` the same way the repo already fixed the identical `static_uri` drift
    (`_static_uri_field`): `_slug_is_manual_field(help_text)`, `set_slug()`,
    `_validate_manual_slug()`. Migration-neutral, verified: `makemigrations --check --dry-run` →
    "No changes detected". D54.
  - **T050** (ARCH-304/305/306) — three legibility cleanups, no behaviour change: `resolve_scheme`'s
    `row.set_slug(row.slug)` (a no-op-looking call that was also the row's only write) replaced
    with the explicit `slug_is_manual = True` + `save()`, which incidentally makes ARCH-307's
    asymmetry disappear (no importer calls `set_slug()` anymore); `identifier_slug_base(uri)`
    gives "no usable base" one definition shared by the `EMPTY_SLUG` guards and
    `unique_slug_for_identifier`; the five `Optional[int]` `max_length` reads narrowed one way
    (`cast`) instead of two. D55.
  - **Verification** — `poetry run pytest -q`: 847 passed. `ruff check .` / `ruff format --check .`
    / `mypy` / `deptry .`: clean. `makemigrations --check --dry-run --settings=tests.settings`:
    "No changes detected". Seven commits, `b722585`..`18b382c`.
  Seven non-obvious choices recorded as D49–D55. Worktree clean. Next: FS-007 re-gate and
  convergence.
