# Implementation Plan: Import keeps the languages the site supports and reports the rest

**Branch**: `007-import-keeps-published` | **Date**: 2026-08-04 | **Spec**: [`spec.md`](./spec.md)

**Input**: Feature specification from `specs/007-import-keeps-published/spec.md`

## Summary

One new class decides which configured language a published tag belongs to, and every place the
importer currently compares a raw published tag against a configured language calls it instead.
There are **five such comparisons across four methods**, and they are not all the same shape: three
are set-membership tests (`language not in configured`), and two are exact tag equality — the
literal-selection test inside `SkosGraph.preferred_label_in`, and the default-language skip at
`skos.py:543`. An implementer grepping only for the set-membership form finds three of the five and
believes the job done, which is why they are enumerated below rather than described.

The matcher is built once per run from the graph, because settling a contest by the variant the
vocabulary predominantly publishes in needs the whole file counted before the first concept is
written (`research.md` R2). The graph traversal that produces those counts stays on `SkosGraph`,
which is this codebase's RDF boundary, so `languages.py` imports nothing from rdflib and is testable
with a dict (`research.md` R2). The report gains one new normalisation reason for a substitution, one
new set-aside reason for a contest loser, and one derived method for the per-language account
(`research.md` R4).

No new models, no migration, no new dependency. Django's own `get_supported_language_variant` was
evaluated and rejected with a measurement: it refuses any language Django ships no translation
catalog for, including ones the project declares in `LANGUAGES`, which would make this feature
silently useless for the research vocabularies it exists to serve (`research.md` R1).

## Technical Context

**Language/Version**: Python 3.11+ (package floor), tested on 3.12 and 3.13

**Primary Dependencies**: Django ≥5.2, rdflib 7.6 — all existing. **No new dependency.**

**Storage**: the existing models, unchanged. `ConceptLabel` and `ConceptNote` keep refusing an
unconfigured language on the write path, and this feature keeps writing through
`Concept.add_label` / `Concept.add_note` rather than around them. **No migration.**

**Testing**: pytest + pytest-django. New fixture vocabularies under `tests/fixtures/skos/` carrying
variant tags, alongside the 51 `@en` files #50 shipped there. `@override_settings(LANGUAGES=...)` is
the lever for every scenario, since the site's configuration is the input under test. The FR-010
invariant additionally runs one case under **Django's own 99-language default**, which the suite must
name explicitly — `@override_settings(LANGUAGES=django.conf.global_settings.LANGUAGES)` — because
`tests/settings.py:13` declares its own three-language list, so "no override" means that list rather
than Django's. That case pins the behaviour a real consumer gets: the ordinary consuming project
declares no `LANGUAGES` at all.

**Target Platform**: any Django project installing this app

**Project Type**: installable Django app (library)

**Performance Goals**: none set. The new pre-pass counts language tags across the graph once, which
is linear in triples and runs beside the traversals already there. Nothing here may be quadratic in
concept count (G5).

**Constraints**: matching must not depend on Django translation catalogs (`research.md` R1). The
account must be derived from report entries rather than accumulated beside them (R3). Article XIV
requires the new behaviour to be grouped in a class rather than added as further module-level
functions in `skos.py`.

**Scale/Scope**: one new module, four changed methods, two report additions, five stories, no
schema change.

## Constitution Check

| Article | Status | Note |
|---|---|---|
| I — Test-First | Pass | Every task is a test-first pair. The `sga` regression test — a configured language Django has no catalog for — lands with the matcher, because it is the test that stops a later maintainer swapping in Django's resolver. |
| II — Simplicity | Pass | One class, no registry, no strategy object per matching rule. The report additions are two closed-vocabulary members and one derived method. The second member is not drift: a value beaten by a *sibling variant* and a value beaten by a *duplicate in its own language* have different causes and different remedies, and one reason cannot carry both without rendering a false sentence to a curator (`research.md` R4, revised). |
| III — Anti-Abstraction | Pass | No base class, no interface. The matcher is a plain class with an immutable table built at construction, and it has exactly one implementation because there is exactly one rule. |
| IV — Integration-First | Pass | The account and the substitution entry are the contract #52 consumes, so they are specified and tested before the call sites that populate them are polished. |
| V — Security & data-safety | Pass, with one watch item | Language tags come from an untrusted file. They are used as dictionary keys and reported back, never as paths, queries, or format strings. The pre-pass counts tags, so a file declaring very many distinct tags grows one dictionary — bounded by the graph already held in memory, and noted in Complexity Tracking rather than dismissed. |
| VI — Documentation | Pass | README's import section gains the matching rule, CHANGELOG entry, and `CONTEXT.md` gains the three new glossary terms (FR-014). The rejection of Django's resolver is documented at the code, not only in `research.md`. |
| VII — Dependency discipline | Pass | Nothing added. |
| VIII — Compatibility | **Pass, and the reason is checked rather than assumed** | This changes what an existing import stores. No published release carries the old rule — the package is `0.0.x` and its first publish is the v0.1.0 milestone — so no compatibility path is owed (spec Assumptions, `decisions.md` D10). |
| IX — URI identity | Pass | Untouched. FR-009 forbids this feature from altering any identifier, local address, or database identity, and US-4 tests exactly that across a re-import — scoped to `Concept`, `ConceptScheme` and `Collection` records, since #50 deletes and recreates label and note rows on every run by design (see "Rules the implementer must not have to invent"). |
| X — Stack & architecture norms | **Pass, with a documented departure** | Django's own resolver answers "which language should this request be served in", where refusing an uncatalogued language is correct. Filing a stored record under a language is a different question, and the measurement in `research.md` R1 is why the framework mechanism is not used here. |
| XI — RDF fidelity | Pass | A substitution is reported as one, never applied silently — the article's own requirement, one axis over from the normalisation #50 already reports. Re-import stays additive and upserts by URI. |
| XII — Internationalization | Pass | This feature adds **two** messages — the normalisation reason for a substitution (T003) and the set-aside reason for a contest loser (T022) — each a translatable template with named placeholders, in the closed vocabularies the existing reasons live in. |
| XIII — Data-model conventions | Not applicable | No field added, so no indexing decision to record. FR-013 stands as a conditional this feature does not trigger. |
| XIV — Test structure & fixtures | Pass | The new module gets its mirroring `tests/test_exchange/test_languages.py`, grouped into `Test<Subject>` classes. Fixtures are files on disk loaded from the suite, not vocabularies built inline. |
| XV — Cohesion | **Central to the design** | `configured_language_codes()` is today a module-level function in `skos.py`, and this feature would otherwise add three or four siblings around the same subject. They go on one class instead, which is also the extension point a consuming project would subclass. |

## Project Structure

### Documentation (this feature)

```
specs/007-import-keeps-published/
├── spec.md              # approved at the Spec gate
├── decisions.md         # D1–D11, plus anything self-resolved from here on
├── research.md          # R1–R5
├── plan.md              # this file
├── tasks.md             # the task graph
├── progress.md          # append-only stage log
└── feature-state.json   # the ledger
```

### Source Code (repository root)

```
controlled_vocabularies/
├── exchange/
│   ├── languages.py     # NEW — LanguageMatcher, its resolution result, and the winner rule
│   ├── report.py        # CHANGED — one NormalizedReason member, one SetAsideReason member,
│   │                    #           one derived account method
│   └── skos.py          # CHANGED — five raw-tag comparisons resolve through the matcher;
│                        #           configured_language_codes() deleted; one counting method added
└── ...

tests/
├── test_exchange/
│   ├── test_languages.py    # NEW — mirrors the new module (testing standard §4)
│   ├── test_report.py       # CHANGED — the account
│   └── test_skos.py         # CHANGED — the behavioural scenarios
└── fixtures/
    └── skos/                # the 51 @en fixtures #50 shipped, plus:
        ├── variants.ttl         # NEW — several variants of one base language (FR-015, SC-020)
        ├── en-gb-only.ttl       # NEW — the specific-to-general direction (SC-002)
        └── declares-de-at.ttl   # NEW — declares itself in a variant (SC-010)
```

The general-to-specific direction (SC-001) needs no new file: 51 existing fixtures are tagged `@en`,
and the spec's Assumptions already say #50's fixtures are reused where they serve.

### The eight comparisons, across five methods

Naming them here is what keeps the stories from overlapping in ways their titles hide. The list was
wrong twice — it said four, then five — so treat the count as a claim to check rather than a fact to
grep, and confirm it against `skos.py` before starting.

1. `SchemeResolver.determine_default_language` — resolves the vocabulary's default language.
   Currently `if declared_language in configured` (set membership). This is the one place the change
   decides whether records exist at all, because a concept with no preferred label in the default
   language is set aside (`decisions.md` D9).
2. `SkosGraph.preferred_label_in` — selects `Concept.label` by exact tag equality. Must select
   through the matcher, or the default language resolves correctly and then finds no label. **It
   must select by the same winner rule call site 3 uses** — see "One winner, one computation" below.
3. `ConceptImporter.import_labels`, the unconfigured-language filter (`skos.py:552`, set
   membership) — the contest lives here. Its `preferred_by_language` grouping must key on the
   resolved configured language rather than the raw tag.
4. `ConceptImporter.import_labels`, the default-language skip (`skos.py:543`, exact tag equality) —
   `language == default_language` compares the **raw published tag** against a **resolved configured
   language**. Left alone it is not a cosmetic inconsistency, it fails the feature's own headline
   scenario: on a `de` site importing a `de-at` file, the skip does not fire, the value reaches
   `concept.add_label(language="de", kind=PREFERRED)`, and `ConceptLabel._reject_default_language_preferred`
   (`models.py:970`) raises an uncaught `ValidationError` that ends the run. The comparison must be
   between the *resolved* language and `default_language`. One operand changes; no new code.
5. `ConceptImporter._import_notes` — two branches plus the `dcterms:description` alias (set
   membership). Notes carry no per-language cardinality limit, so there is no contest here: every
   variant value is stored (FR-004). This asymmetry with `import_labels` is the single most likely
   place for an implementer to over-apply the contest rule.
6, 7, 8. `SkosGraph.first_literal`'s `language=` filter (`skos.py:176`, exact tag equality), reached
   with a **resolved configured language** at three sites that decide what records are *named*:
   `ConceptScheme.name` (`:430`), `ConceptScheme.description` (`:441`), and `Collection.name`
   (`:1094`). These resolve through the matcher too — one operand each, no new code. Leaving them is
   not harmless just because each has an any-language fallback on the next line (`:434`, `:445`,
   `:1098`): that fallback takes `sorted(...)[0]` across **every** language in the file, so on the
   feature's own headline scenario a `de` site importing a `de-at` vocabulary gets every concept
   named correctly and the vocabulary itself named in whatever language happens to sort first. That
   is the defect this feature exists to remove, one level up.

`skos.py::configured_language_codes()` is **deleted** by this feature, not left in place. Its one
remaining job — reading `settings.LANGUAGES` — becomes the matcher's default construction, so the
subject is not split across the new module and the function the plan cites as its own Article XIV
justification. `models.py::_configured_language_codes` stays exactly as it is: it is private, it
serves model validation, and `exchange` already imports `models`, so folding it the other way would
invert the dependency.

### One winner, one computation

`preferred_kept` in `import_labels` (`skos.py:530`) and `preferred_label_in` (`skos.py:190`, called
once, at `:677`) each choose a preferred label independently. Today they agree only because both
are `sorted(...)[0]` over the same raw-tag group. Once the winner rule becomes exact-match-first,
then predominance, two independent implementations can disagree — and when they do, `Concept.label`
holds one value while the report names that same value as a surplus set-aside and stores the other
nowhere. SC-005 fails and the report contradicts the database.

The rule therefore lives in **one place**: a `LanguageMatcher` method that takes the candidate
`(tag, value)` pairs for one resolved language and returns the winner and the losers. Both call sites
read it. That also keeps the predominance ranking private to the matcher rather than reaching into
it from `import_labels` (Article XIV, the article this plan cites as its own justification).

### Rules the implementer must not have to invent

Each of these was unstated and would have been decided differently by two implementations both
satisfying the written plan.

- **The predominance denominator is `skos:prefLabel` only.** Not every label predicate, not notes.
  This is the reading consistent with D4 (a contest exists only where the destination holds one
  value) and D5 (the rule reuses `determine_default_language`'s existing count), and it lets the
  pre-pass and that existing count be the same traversal.
- **Equally-specific configured candidates are ordered lexicographically by code.** FR-002 says the
  least specific configured language receives an orphan value, which has no answer when two
  candidates are equally specific and neither is an exact match. This is reachable without anyone
  configuring it: a project that never sets `LANGUAGES` inherits Django's 99-entry default, in which
  `zh-hans` and `zh-hant` are the only base with two equally-specific variants and no bare base, so
  a file tagged `zh` lands under a script chosen by `set` iteration order. Measured across five fresh
  processes, `list({'zh-hans','zh-hant'})` came back both ways. SC-006 already requires the same file
  to import the same way twice, so this is the only rule that satisfies an approved criterion — and
  it is FR-003's own tie-break one level up, not a second rule to hold. **Resolution is computed over
  a deterministically ordered sequence of configured codes, never over the `set` today's
  `configured_language_codes()` returns.**
- **The matcher returns the configured code exactly as declared in `settings.LANGUAGES`.** Case
  folding is for comparison only and never for the returned value. A project declaring `en-GB` that
  received the normalised `en-gb` back would raise `ValidationError` from `ConceptLabel.clean` on
  every write and fail the whole import, making the package safe only for consumers who happen to
  spell their settings the way Django's own list does.
- **FR-009's identity guarantee covers `Concept`, `ConceptScheme` and `Collection` records** —
  `static_uri`, slug, local URL, and pk — and explicitly **not** `ConceptLabel` / `ConceptNote` rows,
  which #50 deletes and recreates wholesale on every run (`skos.py:522`). FR-009's second clause,
  that no other language's *stored values* change, is the guarantee that is both achievable and the
  one the requirement is for. Written literally over all records, T017 cannot pass, and the wrong fix
  — stopping the full replace — is a scope expansion this feature never asked for.

## Complexity Tracking

| Concern | Why it is accepted |
|---|---|
| A hand-rolled matcher beside an obvious Django utility | Measured, not assumed: Django's resolver refuses any language it has no translation catalog for, including ones the project declares. `research.md` R1 carries the transcript. The mitigation is a test named for that case, so the swap-it-back regression fails loudly. |
| A pre-pass over the graph before concepts are written | Predominance is a property of the file, and computing it per concept would let two concepts in one file resolve the same base language differently (`research.md` R2). One linear pass beside traversals already there. |
| One dictionary keyed by every distinct language tag in the file | A hostile file could declare many thousands of distinct tags. rdflib validates every tag against `^[a-zA-Z]+(?:-[a-zA-Z0-9]+)*$` before a `Literal` exists, so a tag cannot carry a control character, a path separator or anything else that would matter downstream; the count is bounded by the literals in a graph already fully in memory; and lookup is linear in tag length. Recorded rather than guarded, because a guard here would be a limit invented without a threshold. Django's own resolver truncates at 500 characters, but its stated reason is an HTTP header feeding an `lru_cache` — a different input from a tag in a file already parsed. |
| The normalised bucket now grows per stored value on the success path | FR-006 emits one `NormalizedEntry` per value stored under a substituted language, so on this feature's headline scenario the report grows one dataclass plus a params dict *per label and note in the file* — where #50's report only grew that way on failure. Recorded rather than capped, for the same reason as the row above: no threshold has been established. It is written down so #52 is specified against a bucket it knows is file-sized rather than run-sized, and it is carried into the implementation brief as a watch item. |
| Four stories touching one module | The decomposition is behavioural, not modular, so the stories cut across the same four methods. Dispatch is sequential and each story rebases on the last (`research.md` R5). Under parallel fan-out these would not be candidates. |
