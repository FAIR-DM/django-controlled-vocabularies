# Tasks — 007 Import keeps the languages the site supports and reports the rest

Every task is test-first (Article I): the failing test comes before the code that satisfies it, in
the same task. Task ids are stable and never reused. Stories here are **not** independently
dispatchable in parallel — they cut across the same four methods of `exchange/skos.py`
(`research.md` R5), so they run sequentially, each rebased on the last.

**Tasks have no issues** — this file is the whole task record.

## Phase 0 — Foundational (sequential, blocks every story)

- **T001** — `exchange/languages.py`: the `LanguageMatcher` class and the resolution result it
  returns. Construction takes the configured languages and the per-base-language predominance
  ranking, and the instance is immutable afterwards. Resolution rules, all in this task:
  - Comparison is case-insensitive, and **the value returned is the configured code exactly as
    declared in `settings.LANGUAGES`**. Case folding is for comparison only, never for the returned
    value — a project declaring `en-GB` that got `en-gb` back would raise `ValidationError` from
    `ConceptLabel.clean` on every write and fail the whole import.
  - An exact match always wins (FR-002); otherwise the least specific configured language sharing
    the base (FR-002); otherwise no match (FR-001).
  - **Where two configured candidates are equally specific and neither matches exactly, the lower
    code wins, ordered lexicographically.** Resolution is computed over a deterministically ordered
    sequence of configured codes, **never over the `set` that `configured_language_codes()` returns
    today** — that set's iteration order varies per process, and Django's 99-language default
    contains exactly one ambiguous base (`zh-hans` / `zh-hant`), so a file tagged `zh` would
    otherwise land under a different script on different runs.
  - The result carries the resolved configured code, and whether the match was exact is **derived**
    from it and the input rather than stored, so the pair cannot disagree with itself.

  Tests: every rule above as its own case; the case-mismatch case (a configured `en-GB` receiving a
  file's `en-gb`); the two-equally-specific-candidates case; and **the `sga` regression** — a site
  configured for a language Django ships no translation catalog for still resolves it — which is the
  test that stops a later maintainer replacing this with
  `django.utils.translation.get_supported_language_variant` (`research.md` R1). The docstring states
  that rejection and why, at the code.
- **T002** — The predominance count and the wiring (FR-003, `research.md` R2 as revised at S3R).
  One read-only method on `SkosGraph` returning how often each published tag appears across
  **the concept nodes' `skos:prefLabel` values** — that predicate and that node set, and no other,
  because it is exactly the population `determine_default_language` already walks
  (`skos.py:327`, `for node in concept_nodes`) and the only one a contest can turn on (D4, D5).
  The node scope is not a detail: counted graph-wide, the tally additionally sweeps the scheme node's
  own `skos:prefLabel` (`skos.py:320`, `:400`) and every collection's (`skos.py:1053`), so
  substituting it into `determine_default_language` would silently change a rule #50 already shipped
  and tested. Scoped to concept nodes it is provably behaviour-preserving, which is what makes R2's
  "one method feeds both" true rather than assumed. `LanguageMatcher` takes `(configured_languages, counts)` and **imports nothing from rdflib**;
  the graph stays behind `SkosGraph`, which is this codebase's RDF boundary. `SkosImporter.run`
  builds the matcher once from those counts and passes it to `SchemeResolver` and `ConceptImporter`
  as a constructor argument. Tests: the ranking reflects the whole file rather than any one concept,
  ties resolve by language code, a file whose predominant variant is a language the site does not
  hold at all decides nothing about which configured variant wins (spec Edge Cases); the matcher is
  constructible from a plain dict with no graph in sight; and **a file whose scheme and collections
  are labelled in a different language from its concepts resolves the same default language before
  and after this change**.
- **T021** — The winner rule, once, on `LanguageMatcher` (FR-002, FR-003; S3R SPEC-001 and ARCH-005).
  A method taking the candidate `(published tag, value)` pairs for one resolved configured language
  and returning the winner and the losers: exact-match-first, then predominance, then the
  lexicographic tie-break within one tag. It lives here rather than in `import_labels` because
  **two call sites need it** — `preferred_label_in` chooses `Concept.label` and `import_labels`
  computes `preferred_kept`, and today they agree only by the coincidence that both are
  `sorted(...)[0]`. Tests: the rule's three tiers as their own cases, and the property both call
  sites depend on — for one candidate set the method returns one winner, so the two agree by
  construction rather than by coincidence. Keeping it here also keeps the predominance ranking
  private to the matcher.
- **T003** — `report.py`: `NormalizedReason.LANGUAGE_SUBSTITUTION` with its translatable,
  named-placeholder template, naming the published tag and the language the value was stored under
  (FR-006, Article XII). Tests: the entry is inspectable as data, renders in the caller's active
  language, and sits in the normalised bucket rather than the set-aside one, so a caller filtering
  for "things that did not make it in" still gets a truthful answer (`research.md` R4).
- **T022** — `report.py`: a second `SetAsideReason` member for a **variant contest loser**, with its
  own translatable, named-placeholder template naming the published tag and the configured language
  the value lost to (FR-005, Article XII; S3R SPEC-002). **The published tag goes under the param
  name `language`**, identically to `UNCONFIGURED_LANGUAGE` (`skos.py:552`, `:585`, `:599`), and the
  configured destination goes under a different name — `kept_as`. Getting that round the wrong way
  keys T004's account under a language the site already holds, which is D14's own failure mode
  arriving through the member D14 created to prevent it. It is not `SURPLUS_PREFERRED_LABEL`, which
  means *more than one preferred label in one and the same language* and whose template says exactly
  that — a sentence that is factually false for a value published `en-us` and beaten by an `en-gb`
  sibling, since the file carries only one `en-us` preferred label. The two also have different
  remedies, which is what FR-008's account exists to tell apart: nothing recovers a same-language
  duplicate, while configuring its published tag recovers a contest loser. Tests: the rendered
  message is true of the case it names, the entry carries the published tag, and
  `SURPLUS_PREFERRED_LABEL`'s existing meaning and message are unchanged.
- **T004** — `report.py`: the per-published-language account (FR-008) as a method folding
  `set_aside`, not a field accumulated beside it (`research.md` R3). **The fold's membership is an
  explicit set of `SetAsideReason` members, not a heuristic** — `UNCONFIGURED_LANGUAGE` and the new
  contest-loser reason T022 adds, and nothing else. Deciding membership by "carries a `language`
  param" is wrong twice over: `SURPLUS_PREFERRED_LABEL` carries one and is a same-language duplicate
  no configuration change recovers, and its `language` is a configured code rather than a published
  one. **The account keys on `params["language"]`**, which is well-defined precisely because both
  members in the fold put the *published* tag there — see T022. Tests: counts cover every value not
  stored for a language reason and no value that was stored; **a contest loser published `en-us` is
  counted under `en-us` and not under the `en` it lost to**; **a same-language surplus is excluded
  from the account**; the result is present and empty
  after a run that left nothing behind; a caller can rank languages by what configuring them would
  recover without parsing any rendered message.
- **T005** — Fixture vocabularies under `tests/fixtures/skos/` (FR-015), alongside those #50 shipped
  there: one carrying several variants of one base language across preferred labels, alternative
  labels, and notes; one published as `en-gb` only, for the specific-to-general direction (SC-002);
  and one declaring itself in a variant of a configured language, for the default-language path
  (SC-010). **The `en`-only fixture is not written** — 51 existing fixtures in that directory are
  tagged `@en` and the spec's Assumptions already reuse #50's fixtures where they serve, so SC-001's
  direction names an existing file. Check the same way before writing the `de-at` fixture: 9 `@de`
  values already exist in that directory. Test: each is discoverable from the suite and parses.

## Phase US-1 — A vocabulary published in a variant of the site's language imports (#69, P1)

- **T006** — `SchemeResolver.determine_default_language` resolves through the matcher instead of
  testing set membership (FR-007, call site 1). Tests: a vocabulary declaring itself `de-at` on a
  site configured for `de` resolves its default language to `de`, and every concept is named rather
  than set aside for having no label in the default language — the failure `decisions.md` D9
  describes.
- **T007** — `Concept.label` is selected by T021's winner rule (call site 2), **without putting
  configured-language policy inside `SkosGraph`**. `preferred_label_in` returns the candidate
  `(published tag, value)` pairs for the node; `ConceptImporter.import_concepts` — its single caller
  (`skos.py:677`), which already holds the matcher — calls T021's winner method on them. Nothing is
  added: one method's return type changes and one call moves eight lines. The reason for that shape
  is the same one that moved the predominance count *onto* `SkosGraph` in T002 — that class is this
  codebase's RDF boundary and its charter is "the pure, read-only queries the importer runs against
  it" (`skos.py:73`), so a matcher must be neither stored on it nor threaded through it. Tests: a
  concept whose only preferred label is a variant of the default language still names the concept and
  derives its slug the way an exact match would (spec Edge Cases); and, for a candidate set carrying
  both an exact match and a predominant variant, the value stored on `Concept.label` is the one T021
  names — which is what makes SC-005 and SC-006 achievable at all, since both land on `Concept.label`.
- **T008** — `ConceptImporter.import_labels` and `_import_notes` stop comparing raw published tags
  and resolve instead, storing a matched value under its resolved configured language (FR-001, call
  sites 3, 4 and 5). **Both comparisons in `import_labels` change, not just the set-membership one**:
  the default-language skip at `skos.py:543` currently reads `language == default_language` with a
  raw published tag on the left and a resolved configured language on the right, so on the feature's
  own headline scenario the skip does not fire and the value reaches
  `concept.add_label(language="de", kind=PREFERRED)`, which raises an uncaught `ValidationError` from
  `models.py:970` and ends the run. The comparison must use the resolved language. Tests: the two
  directions of SC-001 and SC-002 end to end from a fixture file; **a `de-at`-published vocabulary on
  a `de`-configured site imports its preferred labels without raising** (SC-010's write half, which
  T006 and T007 stop short of); a tag differing only in case is an exact match (SC-004); a tag
  sharing no base language with any configured language is still stored nowhere and still named in
  the report (SC-003).

  Two more clauses belong here, both cheap and both things US-3 would otherwise have to rewrite:

  - **`SkosGraph.first_literal`'s `language=` filter resolves through the matcher too** — call sites
    6, 7 and 8, naming the vocabulary (`skos.py:430`), its description (`:441`) and each collection
    (`:1094`). One operand each. Without it, a `de` site importing a `de-at` file names every concept
    correctly and then falls through to `sorted(...)[0]` across every language in the file for the
    vocabulary's own name.
  - **Inside the default-language branch, name which set-aside reason a loser gets.** Once this task
    changes `skos.py:543` to compare the resolved language, that branch's surplus report at `:548`
    receives both populations. A loser whose published tag equals the winner's is
    `SURPLUS_PREFERRED_LABEL` with its existing meaning; one whose published tag differs is T022's
    contest-loser reason. Same rule as T014's, stated here so US-1 does not land an assertion US-3
    has to undo.

  Finally: **`configured_language_codes()` is deleted in this task**, once its three callers
  (`skos.py:319`, `:521`, `:570`) resolve through the matcher and it is unreferenced. Pure removal.
- **T009** — Every value stored under a language other than its published tag is reported as a
  substitution (FR-006). Tests: the substitution is named, is distinguishable from a value that was
  not stored at all, and does not appear in the not-stored account. *(This task delivers US-2's
  SC-009 while sitting in Phase US-1, where the substitution first becomes reachable. Phase US-2 does
  not repeat it.)*
- **T010** — The invariant test for FR-010: across every matching path in this feature, no content is
  stored in any language absent from the site's configuration (SC-017). This is the test that would
  fail if a later change made the matcher permissive. **One case runs under Django's own 99-language
  default, which the suite must name explicitly** —
  `@override_settings(LANGUAGES=django.conf.global_settings.LANGUAGES)` — because `tests/settings.py:13`
  declares its own three-language list, so "no override" means that list rather than Django's. Written
  the obvious way this case passes while pinning nothing. It exists because the ordinary consuming
  project declares no `LANGUAGES` at all, so its behaviour is what needs holding still.

## Phase US-2 — A curator can see what was left behind and what it would take to keep it (#70, P1)

- **T011** — The account populated from a real import rather than a hand-built report: a fixture
  carrying values in three languages the site does not hold produces counts per published language
  (SC-011, SC-012). Tests drive from the file, the way a curator reaches it.
- **T012** — The clean-run case end to end: an import that left nothing behind yields an account
  that is present and empty (SC-013), so #52 can render from it without asking which kind of run
  produced it.

## Phase US-3 — Competing variants resolve the same way every time (#71, P2)

- **T013** — The contest in `import_labels`: `preferred_by_language` keys on the resolved configured
  language rather than the raw tag, and the winner comes from **T021's method** rather than a second
  implementation of the rule (FR-003, call site 3). `preferred_kept` and `preferred_label_in` must
  therefore agree by construction, not by coincidence — assert that directly. Tests: SC-005 and
  SC-006, including that importing the same file twice stores the same value both times; and the
  spec Edge Case with no criterion of its own — **a concept whose exact-match preferred label is
  empty or slug-unusable is set aside on its own merits and the variant sibling is not promoted into
  its place**, which is the natural thing for an implementer to write and the opposite of what the
  spec says.
- **T014** — Contest losers are set aside and reported with their **published** tag, through
  **T022's** dedicated reason (FR-005, `research.md` R4 as revised at S3R). Two things this task must
  state, because T013's re-keying is what creates the ambiguity:
  - **The discriminator.** Once `preferred_by_language` keys on the resolved language, one group
    holds both populations — on an `en` site, `"A"@en`, `"B"@en` and `"C"@en-gb` are one group. A
    loser whose published tag equals the winner's (case-insensitively) is a same-language duplicate
    and keeps `SURPLUS_PREFERRED_LABEL`; a loser published under a different tag is a contest loser
    and takes T022's reason. Without this, T014 read literally routes every loser through T022 and
    folds same-language duplicates back into the account, which is the miscount D14 exists to stop.
  - **Both branches.** Losers surface at `skos.py:548` (the resolved language is the vocabulary's
    default) and at `:555` (any other configured language). The same rule applies in both. T008
    carries the first one so US-1 does not land an assertion this task has to undo.

  Tests: SC-008; the run still succeeds; and a group carrying both populations — three preferred
  labels, two under one tag and one under a variant — yields one entry of each reason, with only the
  variant one reaching T004's account.
- **T015** — The asymmetry, as its own task because it is the most likely thing to get wrong
  (FR-004): alternative labels, hidden labels, and notes have no per-language cardinality limit, so
  several variants resolving to one configured language are **all** stored and none set aside
  (SC-007). Test: a concept carrying `en-gb` and `en-us` alternative labels on an `en` site keeps
  both.

## Phase US-4 — Adding a language and re-importing fills it in (#72, P2)

- **T016** — The additive re-import guarantee (FR-009): import under one configured language,
  reconfigure for two, re-import the same file, and assert the new language's values are stored for
  concepts already present (SC-014). Test drives the whole path from files on disk.
- **T017** — The nothing-else-changed half of the same guarantee (SC-015, SC-016). **Scope the
  identity assertion explicitly:** it covers `Concept`, `ConceptScheme` and `Collection` records —
  URI, `static_uri`, slug, local URL, and pk — and **not** `ConceptLabel` / `ConceptNote` rows, which
  #50 deletes and recreates on every run by design (`skos.py:522`). Written literally over all
  records the test cannot pass, and the wrong fix — stopping the full replace — is a scope expansion
  this feature never asked for. What is asserted about label and note rows is their **values**: the
  content stored in languages already held is unchanged, and the newly stored values are no longer
  counted as left behind. That is FR-009's second clause, and it is the guarantee the requirement is
  for.

## Phase US-5 — Translatable messages, deliberate indexing, and reusable test material (#73, P3)

- **T018** — The standards test covers **both** of this feature's new messages (Article XII, SC-018):
  T003's `NormalizedReason.LANGUAGE_SUBSTITUTION` and T022's contest-loser `SetAsideReason`. Each
  translatable, with named placeholders, in the closed reason vocabulary it belongs to.
- **T019** — `CONTEXT.md` gains base language, variant, and substitution as glossary entries
  (FR-014, SC-019), so the vocabulary of the report matches the vocabulary of the documentation.
- **T020** — README's import section states the matching rule and its script caveat, and CHANGELOG
  records the behaviour change (Article VI). It must also say plainly **which languages a site
  actually holds**: the package stores content for every code in `settings.LANGUAGES`, Django's
  default is 99 languages for a project that declares none, and narrowing `LANGUAGES` is how a site
  narrows what an import stores. Without that, a curator who believes they run an English site can
  import a vocabulary published in sixty languages and get all sixty — the outcome #51 was written to
  prevent, arriving through the rule that fixes it. It must also say that **a concept's local URL can
  move between imports**: where a concept's preferred label arrives only by variant match, which
  variant wins is a property of the whole file, so a publisher's edits elsewhere in a later release
  can change that concept's stored label and therefore its slug, with nothing about the concept itself
  having changed (D18). Public markdown, so it is humanized before it lands.

## Not in this feature

- Rendering any of this at a terminal — #52 owns it, and FR-011 forbids adding a surface here.
- Any script-awareness narrowing of the base-language rule. Raised at the Spec gate, approved as
  specified, and a change to it is a new decision rather than an implementation choice
  (`decisions.md` D6).

## Phase FIX-1 — S6 review cycle 1 (sequential, one worktree)

Every task here is test-first in the strong sense the review demands: the test must be shown RED
against the current branch before the fix, because three of these four are regressions that a test
written after the fix would pass vacuously.

- ~~**T023**~~ — **DROPPED 2026-08-05, no code written.** It implemented the withdrawn FR-016. The
  defect it targeted is real and is now fixed at its source by Phase FIX-2 below (`decisions.md`
  D35).
- **T024** — SC-023 (S6 SEC-001): a vocabulary whose `effective_default_language` resolves to
  nothing configured is reported as **that one problem**, naming the unconfigured default, instead of
  emitting one `NO_PREFERRED_LABEL` per concept and storing nothing. **RED first** under
  `LANGUAGE_CODE` set outside `LANGUAGES` — note the current test settings make this class
  structurally unreachable, so the test must override both settings explicitly. A new closed-vocabulary
  reason with a translatable, named-placeholder template (Article XII).
- **T025** — SC-024 (S6 SEC-002): catch the model's refusal of a value the field cannot hold and set
  it aside rather than letting `ValidationError` abort the run and roll back records already written.
  Guard `add_label`, `add_note`, and the `concept.label` assignment, the way `EMPTY_SLUG` already
  guards the slug. **RED first**: a concept carrying a 300-character `skos:altLabel` in a variant tag
  currently raises and stores nothing. New `SetAsideReason` member, translatable template.
- **T026** — SC-025 (S6 CORR-001): a concept set aside for having no usable preferred label
  contributes its own published language tags to the account before the run continues, so the
  language whose configuration would recover it is visible. **RED first**: a concept whose only
  content is `@fr` on an `en`-only site currently yields `language_account() == {}`. Account the
  concept's published tags, not the configured default it lacks — the existing `NO_PREFERRED_LABEL`
  entry carries the configured code and must not be folded in as though it were a published tag
  (that is D14's failure mode).
- **T027** — The non-blocking findings worth taking in this pass, each small and each with a test:
  CORR-003 and SEC-003 (the predominance tally and the account are case-sensitive over published
  tags, contradicting FR-001's case-insensitivity — `{"PT-br": 1, "pt-BR": 1}` should be one key);
  CORR-002 (a vocabulary's name and description, and a collection's name, substitute silently — they
  need the same `LANGUAGE_SUBSTITUTION` entry the concept path already emits, per FR-006 and Article
  XI); CORR-004 and SEC-005 (a tautological `assert "en" in rendered` that passes on the word
  "language" — assert the rendered message, not a substring of it); ARCH-002 (`resolve_winner`
  returns a `losers` list no caller consumes while `import_labels` re-derives the same set — consume
  it or drop it, do not keep both).
- **T028** — Re-run the full verification and record it: `forge verify` on the branch, plus a
  migrate-from-zero check, plus `makemigrations --check`. The three regressions above must each be
  demonstrated fixed by their own RED-then-GREEN transcript, not by the suite merely being green.

## Deferred from this cycle, with reasons

- **ARCH-003, ARCH-004, ARCH-006, SEC-004** — performance findings (a duplicated tally pass, an
  unmemoised linear scan, an expensive read before a cheap filter, a quadratic in distinct tags per
  node). All real, none reachable by a correctness path, and the spec sets no throughput target.
  They become an issue on the tracker after merge rather than expanding a review-fix cycle, which is
  what `decisions.md` and the retro's proposal list exist for.
- **ARCH-007** — CHANGELOG coverage of the two public-surface additions. Folded into T027's docs
  touch rather than carried as its own task.

## Phase FIX-2 — Local addresses come from published identifiers (FR-017 to FR-020)

Gated on the maintainer's re-approval of the amended spec. Every task is test-first, and the
re-import stability tests must be shown RED against the current branch first — this is behaviour
#50 shipped, so a test written after the change proves nothing about what it changed.

- **T029** — `Concept`: an imported record's slug is the last segment of its published identifier —
  the fragment where there is one, otherwise the last path segment — stored via the manual-slug
  mechanism R1 already built for this (`Concept.set_slug`'s own docstring names this use). It is
  never recomputed on a later import. Tests: SC-026 for both identifier shapes, and SC-027 — a
  publisher rename leaves the slug and local address alone, which is the case D6 deliberately let
  move.
- **T030** — `ConceptScheme`: the same rule for the vocabulary's own slug, which today re-derives
  from `name` on every save with no manual mechanism at all. This needs a **migration** adding the
  pinning field, and it is the only migration in this feature. Tests: SC-028 — a vocabulary name
  arriving in a different language moves neither the vocabulary's slug nor the address of any record
  inside it. The measured before/after is in `decisions.md` D35.
- **T031** — FR-019 and SC-030: a record authored on this site, with no publisher identifier, still
  derives its slug from its label and still follows a relabel. This is the guard that stops T029 and
  T030 from silently changing curator-authored behaviour, and it is the test most likely to be
  forgotten because nothing in the imported path exercises it.
- **T032** — FR-020 and SC-029: replace #50's order-dependent numeric suffix with a collision rule
  derived from the identifiers, so two records whose identifiers end in the same segment get stable,
  distinct slugs regardless of the order the file is read. Test: import the same file twice with the
  record order reversed and assert identical slugs both times.
- **T033** — Documentation and the superseded records. README's import section and `CONTEXT.md`
  describe addresses as identifier-derived and permanent; CHANGELOG records the behaviour change and
  names the cost D35 accepts (opaque identifiers give opaque addresses). Update
  `assign_unique_slug`'s docstring, which currently asserts the opposite rule in prose
  (`"Nothing is derived from concept.static_uri"`), and `Concept.set_slug`'s, which anticipated this
  use. Public markdown, so humanized before it lands.
- **T034** — Full re-verification: `forge verify`, migrate-from-zero, `makemigrations --check`, and
  a RED-then-GREEN transcript for SC-027 and SC-028 specifically.
