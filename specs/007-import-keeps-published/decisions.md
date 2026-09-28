# Decisions — 007 Import keeps the languages the site supports

Rationale too long to sit inside `spec.md`, plus every ambiguity resolved without asking the
maintainer. Each entry states what was unclear, what was chosen, and why the choice is defensible.
The spec is the contract. This file is why the contract reads the way it does.

## D1 — The feature survived intake, and what it survived on

This feature was very nearly absorbed by its own dependency. [#50](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/50)
delivered the language filtering #51 was written to own, mechanically, because `ConceptLabel` and
`ConceptNote` refuse an unconfigured language on the write path the import uses. #50's own
`decisions.md` D2 recorded that and named what it believed was left: the curator-facing quality of
the report, and an additive re-import guarantee that was true by side effect rather than by test.

Neither of those alone justifies a feature loop. A tested guarantee is a test, and a grouping
helper already existed. What kept #51 alive was a third thing neither issue had noticed: matching
was exact string equality against the codes in `settings.LANGUAGES`, so a site configured for
`en-gb` importing a vocabulary published as `en` stored nothing and reported the entire vocabulary
as unreadable. Regional variants are ordinary in published SKOS, so the issue's first sentence —
"keep the languages their site is configured for" — was not in fact satisfied.

The maintainer confirmed at intake that a variant should be kept, and separately that the match
runs in both directions. That is the feature.

## D2 — Matching is by base language, in both directions

Settled with the maintainer at intake rather than derived here, but the reasoning is worth keeping
because it bounds everything below.

*General to specific* — a file's `en` filling an `en-gb` site's slot — is uncontested: one source
value, one destination, no competition. *Specific to general* — a file's `en-gb` filling an `en`
site's slot — is the direction that creates contests, because published vocabularies routinely
carry several variants of one language and the destination may hold only one.

Refusing the second direction was considered. It avoids every contest below and it is the smaller
change. It was rejected because it leaves the exact failure the issue was written about intact: a
site on plain `en` importing a vocabulary published only as `en-gb` still stores nothing and still
reports the whole vocabulary as content it cannot read. A rule that fixes half of a symmetric
problem is harder to explain than either of the rules it sits between.

## D3 — An exact match always wins, and the least specific configured language receives an orphan

Two precedence rules, both following from the same principle: the site's own declaration is better
evidence of what a curator wants than anything inferred from the file.

An exact tag match is never displaced by a variant, because a publisher who tagged a value `en-gb`
and a site that configured `en-gb` agree, and no third value should come between them.

Where several configured languages share a base and none matches exactly — a site on both `en` and
`en-gb` receiving an `en-us` value — the value goes to the least specific, `en`. It is a variant of
neither, so neither has a claim by exactness, and the broader audience is the destination that
serves more readers. Sorting configured codes and taking the first happens to produce the same
answer here, but for the wrong reason, and would diverge on a site configured for `en-gb` and
`en-us` alone.

## D4 — The contest exists only where the destination has one slot

The draft of this spec got this wrong, and the coverage scan caught it. The first version of FR-003
said that where a file offers several variants of one configured language, one wins and the rest are
set aside. That is right for a preferred label and wrong for everything else.

`ConceptLabel`'s uniqueness constraint is `UniqueConstraint(fields=["concept", "language"],
condition=Q(kind="preferred"))` — conditional on the preferred kind. `ConceptNote` declares no
uniqueness constraint at all. So a concept may hold as many alternative labels, hidden labels, and
notes per language as a file offers, and collapsing `en-gb` "Colour" and `en-us` "Color" into one
alternative label would discard content the models were willing to store, inside a feature whose
entire purpose is to stop discarding content.

The rule is therefore scoped: a contest is resolved only where the models hold at most one value of
that kind per language. Everywhere else, every variant value is kept.

This is worth stating as a general shape rather than a fix. The destination's capacity, not the
source's shape, decides whether there is a contest at all.

## D5 — The predominant variant wins a contest, not the alphabetically first

Where a contest does exist and no exact match resolves it, the variant the vocabulary predominantly
publishes in is kept, with ties broken by language code.

Taking whichever variant sorts first is equally deterministic and one line simpler. It was rejected
because it hands a curator on `en` the `en-au` spelling of a vocabulary published overwhelmingly in
`en-gb`, and no reader of the file could reconstruct why. Predominance is a property of the document
the curator is importing, so the answer is at least explicable from the thing in front of them.

The rule is also not new to this codebase. #50 already resolves a vocabulary's default language as
"the language the vocabulary declares itself in, else the language most of its concepts' preferred
labels use, tied deterministically", so this reuses an established rule rather than introducing a
second one that a reader would have to hold separately.

## D6 — Script-differing variants are joined, and this is the rule's sharpest edge

`zh-Hans` and `zh-Hant` share the base language `zh` and are not mutually readable. Under the agreed
rule, a site configured for `zh-Hans` importing a vocabulary published as `zh-Hant` receives content
in a script its readers may not be able to use.

This is recorded rather than fixed. Three reasons:

- The alternative is a script-awareness rule, which the intake discussion never reached and which
  would need its own decision about what counts as a compatible script.
- It is not silent. Every variant substitution is reported as one (FR-006), so the curator can see
  that their `zh-Hans` slot holds `zh-Hant` content and act on it.
- The failure it replaces is worse. Before this feature, that same import stored nothing at all.

It is raised at the Spec gate rather than absorbed, because narrowing the agreed rule is a
maintainer decision and not this feature's to take.

## D7 — The account answers "what should I change", not "what happened"

The issue asks that a curator be "told plainly what was left behind". #50 already records every
set-aside value with its reason and its language, and already groups those records by reason, so
the literal reading of that sentence was satisfied before this feature started.

The gap is what the grouping is *for*. A per-reason total of 359 values in languages the site is not
configured for is a fact a curator can do nothing with. A breakdown showing 312 of them are French
tells them that configuring one language recovers most of the vocabulary, which is a decision.

So the account is a count per published language, exposed as data. Ranking languages by what
configuring them would recover is then arithmetic the caller does, and #52 renders.

It is present and empty after a clean run rather than absent. An absent account and an account of
zero read identically to a person and differently to a caller, and #52 renders from it without
knowing which kind of run produced it.

## D8 — A substitution is reported even though the value was stored

Article XI requires that nothing be applied silently. A value published as `en` and stored under
`en-gb` did make it in, so it is not a set-aside, but it also is not what the file said.

#50 already built the shape for exactly this: `NormalizedEntry`, a bucket separate from set-asides,
holding values that were stored under a different predicate than the file asserted. A variant
substitution is the same kind of event one axis over — stored under a different *language* than the
file asserted — so it belongs in that bucket rather than in a third one, and a caller filtering for
"things that did not make it in" keeps getting a truthful answer.

## D9 — The default language resolves by the same rule

`determine_default_language` in #50 checks `if declared_language in configured`, an exact match. Left
alone, a vocabulary declaring itself in `de-at` on a site configured for `de` would fall back to the
site default, and every concept whose preferred label is `de-at` would then have no label in the
vocabulary's default language — which #50 makes a set-aside, so the concepts would not import at all.

That is the same failure this feature exists to remove, arriving by a different path. The default
language therefore resolves by the same matching rule. This is the one place where the change
reaches beyond labels and notes into which records exist at all, which is why it carries its own
requirement and its own acceptance scenario rather than being left implicit.

## D10 — No compatibility path is owed, and that is a decision

This feature changes what an import stores. A site that imported a vocabulary, upgraded, and
re-imported would gain content it did not have before.

That would ordinarily oblige a migration note. It does not here, because no published release
carries the previous rule: the package is at `0.0.x`, and its first publish is the v0.1.0 milestone
this work sits inside. The absence of a compatibility path is recorded so that it reads as a
decision taken against a checked fact rather than a question nobody asked.

## D11 — New terms go in the glossary, not only in this spec

Base language, variant, and substitution are all new to this project's vocabulary, and two of the
three will appear in messages a curator reads. `CONTEXT.md` is where this project keeps its
glossary, so that is where they belong. A term defined only inside a spec is a term defined nowhere,
as far as a reader of the report is concerned.

## D12 — What the design review changed, and what it did not

The S3R panel — three reviewers, one lens each, run against the plan before any code existed —
returned `request_changes` on all three lenses: four verified high findings, eight medium, ten low.
Every high was checked against the code before it was accepted, and all four held. They are recorded
here as D13 to D16 because each settles something the plan had left to the implementer.

Two things the panel did **not** change are worth recording, so a later reader does not reopen them.
It found no task without spec or constitution provenance, so there was no scope creep to cut. And it
confirmed the two structural judgements the plan had already made: one `LanguageMatcher` with no base
class, no registry and no settings hook is right-sized, and `models.py::_configured_language_codes`
stays where it is, because folding it into `exchange` would invert the dependency.

The panel is also the reason `skos.py::configured_language_codes()` is deleted rather than left in
place. The plan cited that function as its own Article XIV justification and then would have shipped
it alongside the class that replaced it.

**Round two** ran the same three lenses against the revised artefacts and returned `approve` on all
three, risk `low`, with no critical or high findings — so the gate is green and one design-review
cycle was spent. Round two's mediums were applied in the same pass rather than carried as watch
items, because each was a one-sentence artefact edit and several corrected factual errors introduced
by the round-one fixes.

Two of those are worth naming, because they are the same mistake twice and a third occurrence is
plausible. The plan's call-site enumeration asserted "these are the whole surface" at four sites, was
falsified at five, reasserted it, and was falsified again at eight — `SkosGraph.first_literal`'s
`language=` filter decides what the vocabulary and its collections are *named*, and its any-language
fallback would have named a `de-at` vocabulary in whatever language sorted first on a `de` site. The
count now carries a warning to check it rather than grep it. Separately, the FR-010 test written to
run "under Django's default `LANGUAGES`" would have run under `tests/settings.py`'s own three-language
list and pinned nothing at all, while reading in the record as an obligation met — the shape of an
unconsumed declaration, and the reason D17's mitigation now names
`@override_settings(LANGUAGES=global_settings.LANGUAGES)` explicitly.

## D13 — The winner rule is one computation, not two that happen to agree

`Concept.label` is chosen in `preferred_label_in` (`skos.py:190`, called once, at `:677`); the
surplus report is computed from `preferred_kept` in `import_labels` (`:530`). They are independent,
and today they agree only because both are `sorted(...)[0]` over the same raw-tag group. The plan
changed the rule in one of them.

Left that way, the failure is not a mismatch a test would call cosmetic. `Concept.label` would hold
one value while the report named that same value as a surplus set-aside, and stored the true winner
nowhere — a report contradicting the database, inside a feature whose subject is telling a curator
the truth about what was kept.

The rule therefore lives on `LanguageMatcher` and both call sites read it. This also puts the
predominance ranking where it is used rather than reaching into the matcher from `import_labels`,
which is Article XIV — the article this plan cites as its own justification.

## D14 — A contest loser is not a surplus preferred label

`research.md` R4 reused `SetAsideReason.SURPLUS_PREFERRED_LABEL` for a value beaten by a sibling
variant, on the argument that a second reason would split one concept across two names. The argument
was wrong about the concept.

`SURPLUS_PREFERRED_LABEL` means a concept carries more than one preferred label **in one and the same
language**, and its message says so in the words a curator reads. For a value published `en-us` and
beaten by an `en-gb` sibling, the file carries exactly one `en-us` preferred label, so that sentence
is false. Article XI is not satisfied by surfacing something wrongly.

The deciding argument is FR-008's, though. The account exists so a curator can rank languages by what
configuring them would recover, and the two populations differ on exactly that: nothing recovers a
same-language duplicate, while configuring its published tag recovers a contest loser. One reason
carrying both makes the account tell the curator that configuring a language they already have would
recover content. A closed vocabulary is what keeps two causes with two remedies apart, so the second
member is the article's purpose rather than a departure from it.

## D15 — Determinism needs a rule for equally-specific candidates, and FR-002 has none

D3 settled that an orphan value goes to the least specific configured language sharing its base, and
noted in passing that sorting the codes would give the same answer "for the wrong reason". It never
answered the case where two candidates are **equally** specific and neither matches exactly.

That case is reachable without anyone configuring it. A project that never declares `LANGUAGES`
inherits Django's 99-language default, and `zh-hans` / `zh-hant` is the one base in that list with
two equally-specific variants and no bare base. `configured_language_codes()` returns a `set`, whose
iteration order varies between processes — measured, both orders came back across five fresh runs. So
the same file would store Simplified on one run and Traditional on the next, and SC-006 already
requires the same file to import the same way twice.

The lower code wins, ordered lexicographically, computed over an ordered sequence rather than a set.
This is FR-003's own tie-break one level up rather than a second rule a reader must hold, and it is
the only rule that makes an already-approved success criterion achievable. Recorded here rather than
taken back to the maintainer for that reason — it settles a gap inside an approved requirement, it
changes no approved behaviour, and it is flagged in the plan notification for veto.

## D16 — FR-009's identity guarantee is about concepts, not label rows

FR-009 forbids altering "any record's identifier, local address, or database identity" across a
re-import. Read literally over all records, it cannot hold: #50's importer runs
`concept.labels.all().delete()` and recreates every label and note row on every run, so their primary
keys change by design.

The requirement is not thereby unsatisfiable, it is unscoped. Its second clause — that no other
language's **stored values** are removed or altered — is the guarantee a curator cares about and is
exactly what the full replace preserves. So the identity assertion covers `Concept`, `ConceptScheme`
and `Collection` records, and the value assertion covers label and note rows.

The alternative reading would have made T017 a test that fails against approved, merged behaviour,
and the fix an implementer would reach for — stopping the full replace — is a redesign of the
dependency this feature explicitly extends rather than replaces.

## D17 — The site's configured languages are not what the spec's Assumptions imply

The spec assumes "the site's configured languages are whatever the project declares". That is true of
the code and misleading about the world: the ordinary consuming project declares nothing, and
`settings.LANGUAGES` falls back to Django's own 99-language list.

Base-language matching widens what an untrusted file may write into that default. A vocabulary
published in sixty languages now writes sixty languages' worth of rows into a project whose curator
believes they run an English site — which is #51's own complaint, arriving through the rule that
fixes it.

There is no safer setting to read, and inventing one would contradict the spec's deliberate choice
not to introduce a setting. So this is a documentation and test obligation rather than a guard:
README says plainly that the package stores content for every code in `settings.LANGUAGES` and that
narrowing that list is how a site narrows an import, and the FR-010 invariant test runs one case
under Django's own 99-language default — named explicitly as
`@override_settings(LANGUAGES=django.conf.global_settings.LANGUAGES)`, because `tests/settings.py`
declares its own three-language list and "no override" would mean that list rather than Django's.

## D18 — A concept's local address follows the file, not the concept

Predominance is a property of the whole vocabulary being imported (`research.md` R2), and
`assign_unique_slug` recomputes a concept's slug from its label on every run (`skos.py:769`). Put
together, those two facts have a consequence neither records on its own: where a concept's
default-language preferred label arrives only by variant match, which variant wins depends on the
rest of the file. A publisher's unrelated edits elsewhere in a later release can therefore move an
existing concept to a new local URL, with nothing about that concept having changed.

This is new with this feature. Under exact matching such a concept stored no label at all, so the
coupling could not arise. FR-009 and SC-015 do not cover it either: they hold identity still across a
re-import of *the same file*, and this is a different file.

It is recorded rather than guarded, for the same reason as D6. Pinning the previously-stored variant
would add state and contradict the rule #50 established that the file is authoritative for the
records it contains, and scoping predominance per concept is precisely what R2 rejected — it would
let two concepts in one file resolve the same base language differently. So the remedies are the two
cheap ones: README says a local URL derived from a variant-matched label can move when the published
vocabulary's predominant variant changes, and this entry carries the constraint into #52's and R6's
specification rather than leaving it to be discovered by a broken bookmark.

## D19 — Three names T005–T022's task text described but did not spell, chosen at implementation

`tasks.md` names the shape of three pieces of API surface without dictating their identifiers.
Recorded so a later story doesn't reinvent them differently.

- **`SetAsideReason.VARIANT_NOT_KEPT`** (T022) — the task text calls it "a contest loser" and "a
  second `SetAsideReason` member"; `VARIANT_NOT_KEPT` was chosen to read correctly in
  `set_aside_by_reason()` output and its own docstring without repeating "contest", which names the
  *mechanism* (T021's winner rule) rather than the *outcome* the report describes.
- **`ImportReport.language_account()`** (T004) — the spec's Key Entities name "Language account" as
  a noun; the method is the verb form of the same term, consistent with `set_aside_by_reason()`'s
  own naming (a plain description of what it returns, not "get_" or "compute_").
- **`NormalizedReason.LANGUAGE_SUBSTITUTION`'s params** — T022 states explicitly that a contest
  loser's published tag goes under `language` and its configured destination under `kept_as`.
  T003's own task text names only "the published tag and the language it was stored under" without
  naming params. `kept_as` was reused for T003 too, for the same reason T022 gives: a caller reading
  both a substitution and a contest-loser entry should not have to remember two different names for
  "the configured language something ended up under."

**Revisit if:** #52 (the rendering feature) finds any of the three read awkwardly from a curator-
facing surface — none of the three is exercised by a call site yet, so nothing downstream depends on
the exact spelling.

## D20 — `LanguageMatcher.resolve_winner`'s tie-break is one cascading sort key, not nested branches

T021 states three tiers — exact match, then predominance, then a lexicographic tie-break "within one
tag." Implemented as a single sort key `(tag != configured_language, -count, tag, value)` over the
candidate list, rather than three sequential `if`/`elif` branches testing each tier in turn.

The fourth element (`value`) is not named by T021's three tiers at all; it exists so two candidates
sharing an identical published tag (a literal duplicate, not a variant) still resolve
deterministically rather than by whichever the caller happened to list first. No call site
constructs such a candidate set yet — `import_labels`'s own raw-tag grouping (`skos.py:530`) already
reduces to one value per tag before this method would ever see it — so this tier is currently
unreachable in practice and is recorded rather than tested against a real call site.

**Revisit if:** a future story's candidate construction stops pre-reducing same-tag duplicates
before calling `resolve_winner`, at which point this tier becomes reachable and worth a dedicated
test.

## D21 — The three T005 fixtures share no scheme URI with any existing fixture, and are not `@en`

`variants.ttl`, `en-gb-only.ttl`, and `declares-de-at.ttl` each mint a fresh `http://example.org/...`
namespace (`colours`, `colours-gb`, `farben`) rather than extending `rocks.ttl`'s. `rocks.ttl` is the
base vocabulary a dozen other tests already assert exact content against; adding variant-tagged
values to it would risk an unrelated test's assumption about what languages it carries. None of the
three fixtures uses a bare `en` tag anywhere — deliberately, so each imports, under this phase's
unmodified call sites, as either an ordinary `UNCONFIGURED_LANGUAGE` set-aside (`variants.ttl`,
`en-gb-only.ttl`) or a `NO_PREFERRED_LABEL` set-aside excluding the whole concept from the predicate-
coverage sweep's evidence requirement (`declares-de-at.ttl`, whose only concept carries no `en`
label at all). Both outcomes are already-covered branches of the existing sweep, so no fixture here
needed its own exclusion entry.

**Revisit if:** US-1/US-3 wire the matcher into the five call sites and these fixtures start
resolving differently — their own dedicated tests (`test_variants_fixture_...`,
`test_en_gb_only_fixture_...`, `test_declares_de_at_fixture_...`) assert only raw RDF content, not
import behaviour, so they should keep passing unchanged; the predicate-coverage sweep's behaviour
for these three files, however, will change once real values start landing instead of being set
aside, and is worth re-checking at that point.

## D22 — The predicate-coverage sweep's own evidence rules predate base-language matching, and T008 is where that catches up

D21 named this exactly: once `variants.ttl`, `en-gb-only.ttl` and `declares-de-at.ttl` stop being
wholly set aside and start landing real content, `TestEverySkosPredicateIsReadOrReported` needed a
second look. T008 is that point, and the sweep's own helpers — `_coverage_label_covered` and
`_coverage_note_covered` in `test_skos.py` — carried two assumptions this feature breaks by design,
not by accident.

The first: their landed-row query filtered on `language=language`, where `language` is the
literal's own **published** tag read straight from the graph. FR-001/FR-006 now store a value under
a *resolved* configured language that can differ from what was published — that is the entire
feature — so a value landing correctly under `de` for a `de-at`-published literal is invisible to a
query still asking for `language="de-at"`. The fix drops the language filter from both helpers'
landed-row checks (kind/text/concept — or kind/value/concept for notes — is specific enough for
this sweep's own purpose, which its docstring states as "read into a record or named in the
report," not "read into a record under this exact tag"; *which* language it landed under is what
T008's own dedicated tests verify).

The second: `_coverage_label_covered`'s recognised-reason list — `UNCONFIGURED_LANGUAGE`,
`SURPLUS_PREFERRED_LABEL` — predates `VARIANT_NOT_KEPT` (T022) ever actually firing. T022's reason
was added in the foundational phase but no call site wrote it until T008's default-language-branch
discriminator. `VARIANT_NOT_KEPT` joins the list, keyed by `language` exactly as
`UNCONFIGURED_LANGUAGE` already is (both carry the *published* tag under that param name).

Both gaps are unavoidable for any correct T008: storing under a resolved language and reporting a
losing variant under `VARIANT_NOT_KEPT` are what FR-001/FR-005/FR-006 require, not implementation
choices this story could have made differently. The sweep's own test function and its assertion —
"every predicate is read into a record or named in the report" — are unchanged; only the helpers'
stale assumption about *how* to find that evidence is corrected, which is the maintenance D21
already flagged as expected here.

## D23 — T006's own test is scoped to `determine_default_language`, not to a concept actually importing

`tasks.md`'s T006 entry names two things to test: the default-language resolution itself, and "every
concept is named rather than set aside." Both are true of US-1 once it is complete, but not both are
true after T006's own commit alone. `declares-de-at.ttl`'s one concept carries no exact-tag
preferred label anywhere — its only `skos:prefLabel` is `"Rot"@de-at` — so naming it needs T007's
winner rule (`preferred_label_in` returning candidates, `import_concepts` reading
`resolve_winner`), not just a corrected default language. Tested as written, T006's commit would be
red until T007 landed, which `craft-increments` treats as a stall condition, not a valid slice
boundary.

T006's own tests therefore assert directly against `SchemeResolver.determine_default_language`'s
observable effect — the scheme's own `default_language`/`effective_default_language` fields via
`resolve_scheme`, which runs and settles regardless of whether any concept later imports — covering
both the declared-language branch and the commonest-fallback branch resolving through the matcher,
plus the unconfigured-language regression. "Every concept is named" for exactly this fixture is
T007's own stated acceptance test ("a concept whose only preferred label is a variant of the default
language still names the concept and derives its slug the way an exact match would") — the same
claim, proven where it is actually achievable.

**Revisit if:** never — this is how the two tasks' test coverage was always going to divide once
`declares-de-at.ttl`'s exact content (no exact-tag label anywhere) is accounted for; it is recorded
so a later reader does not look for "every concept is named" inside T006's own commit and conclude
it is missing.

## D24 — A default-language-branch loser's reason is decided against the tag T007 actually chose, not against `default_language` itself

T008's task text says a loser's published tag is compared "against the winner's" to choose between
`SURPLUS_PREFERRED_LABEL` and `VARIANT_NOT_KEPT` — the same discriminator T014 (US-3) states for
every other configured language. Two readings were available for what "the winner" means inside
`import_labels`, and they disagree on one reachable case.

*Reading A* — compare the loser's tag against `default_language` itself (the configured code). A
raw-tag-group duplicate under a *variant* (two `de-at`-tagged preferred labels, no exact `de` tag
anywhere) would then read as `VARIANT_NOT_KEPT`, because `"de-at" != "de"`. But its message —
"another variant was kept for the site's `de` instead" — is false: the value that *was* kept is
tagged `de-at` too, the exact same variant, not another one. Article XI's "surfaced to the user,
never silent" is not met by surfacing something wrongly (the same argument D14 already made against
reusing `SURPLUS_PREFERRED_LABEL` for a true contest loser, run in reverse here).

*Reading B (chosen)* — compare the loser's tag against the tag `import_concepts`' own
`resolve_winner` call actually chose for the default-language slot (`default_language_winner_tag`,
recomputed in `import_labels` from the identical `preferred_label_in`/`resolve_winner` call —
T021's "one winner, one computation" guarantees it agrees with `import_concepts`' own answer without
threading the value through `_import_concept_content`'s parameters). A same-tag duplicate — the
loser's tag equals whichever tag actually won — keeps `SURPLUS_PREFERRED_LABEL`, true regardless of
whether that shared tag happens to equal `default_language` exactly or is itself a variant. A
different-tag loser takes `VARIANT_NOT_KEPT`. This is the literal reading of T014's own words ("a
loser whose published tag equals the winner's *tag*") and the only one that keeps
`SURPLUS_PREFERRED_LABEL`'s message true in every case T008 can reach.

Reported under `SURPLUS_PREFERRED_LABEL`, the `language` param is always the *resolved* configured
code (`default_language`), never the raw tag that happens to be shared — consistent with T004's own
invariant that this reason's `language` names a configured code the site already holds, not a
published tag configuring something would recover.

**Revisit if:** T013/T014 (US-3) re-key `preferred_by_language` onto the resolved language for every
configured slot, not only the default one — at that point this same discriminator should read
identically for both, and worth checking that `import_labels`'s two now-separate computations (this
one, and T013's) still agree by construction rather than by coincidence.

## D25 — A pre-existing test class lost its `class` statement during US-1's insertions, and is reinstated

**Decided at:** US-1 convergence review (orchestrator), after `tamper-check` flagged
`tests/test_exchange/test_skos.py` and the flag was triaged line by line.

T007–T009 inserted three new test classes immediately above
`TestConceptsImpliedByMembershipButNeverGivenAnRdfType`. The insertion landed *between* that class's
`class` statement and its docstring: the `class` line was removed and the docstring left behind as a
bare string expression, so its five node-typing tests were silently re-parented onto
`TestLanguageSubstitutionIsReported` — a class about language substitution, which has nothing to do
with them.

Nothing failed. The methods still ran, the count was unchanged at 745, and every gate was green,
because pytest neither knows nor cares which class a test method hangs off. That is what makes this
worth a decision record rather than a silent fix: the defect is invisible to every machine check the
loop runs, and only the tamper-check flag plus a by-hand read of the deleted lines surfaced it.

**Chosen:** reinstate the `class` statement verbatim above its own docstring. No test body, name or
assertion is touched, and the count stays at 745.

**Rejected:** leaving it. Article X's testing structure requires class grouping to carry meaning, and
a class whose name says "language substitution" holding tests about `rdf:type` inference defeats
that. It would also have made the next reader of a failure in those five tests look in the wrong
place entirely.

**Revisit if:** a later story again inserts classes adjacent to an existing one — the same shape can
recur, and the only thing that caught it was reading the diff's deletions rather than trusting a
green suite.

## D26 — T011 and T012 are test-only tasks, and their tests passed on the first run

`ImportReport.language_account()` (T004) and the set-aside population it folds over
(`UNCONFIGURED_LANGUAGE` since #50, `VARIANT_NOT_KEPT` since US-1's T008) were both already
implemented and merged before this phase started. US-2's own tasks.md text asks only that the
account be exercised "from a real import rather than a hand-built report" (T011) and "end to end"
for a clean run (T012) — neither names a production change, and none was needed or made.

`craft-tdd`'s warning that a test passing on first run is usually testing nothing just written does
not apply the same way here: both tests assert a specific, falsifiable claim — an exact per-language
breakdown with distinct multiplicities for T011, and `report.set_aside == []` alongside
`language_account() == {}` for T012 — rather than a tautology, an unexercised fixture, or a wrong
import. Each was written before being run, and each was run and read before being trusted; both
happened to confirm behaviour already correct rather than drive new behaviour into existence. This
is recorded so a later reader does not look for a code change in either commit and conclude one is
missing, the same shape D23 recorded for T006.

**Revisit if:** never — this is simply what a coverage task looks like when the feature it covers
was implemented in an earlier phase.

## D27 — T013 unifies the default-language and general-language winner computations into one dict, closing the gap D24 flagged

D24 (US-1) resolved a discriminator question for the default-language branch and named exactly what
it was leaving open: "T013/T014 (US-3) re-key `preferred_by_language` onto the resolved language for
every configured slot, not only the default one — at that point this same discriminator should read
identically for both, and worth checking that `import_labels`'s two now-separate computations (this
one, and T013's) still agree by construction rather than by coincidence."

Before T013, `import_labels` ran two independent computations: `default_language_candidates` /
`default_language_winner_tag`, built via `preferred_label_in` and `resolve_winner` (T008, correct);
and `preferred_by_language` / `preferred_kept`, grouped by the *raw published tag* and reduced with
`sorted(values)[0]` — the same shape D13 named as the pre-T021 defect, never actually removed from
this call site because T008's own scope was the default-language branch alone. The second
computation is what the general (non-default) branch read, and grouping by raw tag meant two
*different* tags resolving to the same non-default configured language were invisible to each other
— each was its own singleton "winner" — so both reached `concept.add_label()` and the second call
raised `ConceptLabel.clean()`'s own uniqueness `ValidationError`, uncaught. This was a live, minimal
crash: `surplus_preferred_label.ttl` doesn't reach it (its two `de`-tagged values are the same raw
tag), so no test in the suite before T013 exercised a two-*different*-tag contest in a non-default
language.

**Chosen:** one dict, `preferred_winner_by_language: dict[str, tuple[str, str]]`, built once from
`preferred_label_in(node)` grouped by *resolved* language and reduced with `resolve_winner` per
group — literally the same call `import_concepts` makes for `Concept.label`, over the identical
candidate source. `default_language_winner_tag` is now a read of this dict's `default_language`
entry rather than a second traversal. This is what makes D24's "agree by construction, not by
coincidence" checkable at all: before T013 there were two independently-derived winners that
happened to answer the same question the same way; after, there is one.

**Rejected:** leaving the two computations separate and only patching the general branch's grouping
key. That would still let the default and general branches drift independently if a later change
touched one and not the other — the exact failure mode D13 and D24 both named, just deferred rather
than closed.

## D28 — T014's discriminator is copied logic, not a shared helper

The default-language branch's own tag comparison (`published_tag.lower() != winner_tag.lower()`)
and T014's general-branch version are the identical two lines, not factored into a shared method.
Considered and rejected: the two branches differ in what happens *after* the comparison — the
default branch's winner path is a bare `continue` (the value already lives on `concept.label`), the
general branch's winner path falls through to `concept.add_label(...)` and a possible
`LANGUAGE_SUBSTITUTION` normalisation — so a shared helper would need to either return a tri-state
the caller re-branches on (no simpler than the two lines it replaces) or grow a callback parameter
for "what to do with the winner", which is exactly the kind of hook `craft-increments`' simplicity
rule warns off building for two call sites. Two identical comparisons reading the same
`preferred_winner_by_language` dict is the smaller diff.

**Revisit if:** a third call site ever needs this same discriminator — at that point a named helper
earns its complexity.

## D29 — T015 needed no production change, and its own test proves why

FR-004's asymmetry — alternative labels, hidden labels and notes carry no per-language cardinality
limit — was never something T013/T014 touched: both changes are scoped to
`if kind == ConceptLabel.Kind.PREFERRED:` branches, and every other kind already fell straight
through to the unconditional `concept.add_label(...)` at the bottom of the loop, both before and
after T013/T014. `variants.ttl` (T005) already carries `en-gb`/`en-us` variants of an alternative
label and a note for exactly this population, built and reserved for this purpose since the
foundational phase (its own comment: "the contest population US-3 needs is exercised"). T015's tests
run this fixture and assert both variants land — SC-007 — with no code change, the same shape D26
recorded for T011/T012: a coverage task for behaviour a design decision (D4) already delivered.

The one thing worth naming: `colour`'s *preferred* label also carries an `en-gb`/`en-us` contest
(the concept's default-language slot), and it correctly produces exactly one loser entry. A test
asserting "no set-aside entry for this subject" would have been wrong — it would pass today and
break the moment someone (correctly) added a second preferred-label fixture value — so the test
asserts `len(losses) == 1` (the expected preferred-label loser, and nothing more), not `== 0`. A
`SetAsideEntry` carries no predicate or kind, only `language`, so a loss can't be attributed to "the
alternative label" versus "the preferred label" by inspecting the entry itself; count is the
distinguishing signal here, not membership.

**Revisit if:** never — the asymmetry's underlying rule is a `craft-simplify` case for staying
where it is: no cardinality contest is not an omission needing a control-flow branch, it is the
model's own constraint (or its absence) already deciding whether one is needed.

## D30 — T016 needed no production change, and its two tests are the same shape as D26/D29

FR-009's additive guarantee — a re-import after a language is added stores that language's values
for the concepts already present — is, per its own spec section, already true as a consequence of
`import_labels`/`import_concepts` resolving every published tag through `LanguageMatcher` on every
run: nothing in the matching path remembers which languages a previous run saw configured, so a
second run under a wider `LANGUAGES` simply matches more of the same file's tags than the first did.
T016 is a coverage task by tasks.md's own text, the same shape D26 recorded for T011/T012 and D29
for T015: two tests, each asserting a falsifiable claim rather than a tautology, both passed on
first run, no production code changed.

`rocks.ttl` — already the reference fixture per D16 — was reused rather than a new one written: its
`igneous`/`granite`/`sedimentary` concepts each carry an exact `fr` preferred label with no variant
contest to entangle, and the file's `fr` occurrences are countable by hand (three, one per concept),
which is what makes `first_report.language_account().get("fr") == 3` a real assertion rather than a
guess at the fixture's shape. The two-run scenario is driven through `import_skos` from the file on
disk both times, `override_settings(LANGUAGES=...)` between them, per the brief's acceptance text —
no report or model object is hand-built.

**Revisit if:** never — the same reasoning as D26/D29 applies: a coverage task for behaviour a prior
phase's design already delivers has nothing left to drive into existence.

## D31 — T017's identity assertion is scoped to Concept/ConceptScheme/Collection exactly as D16 requires, and it too needed no production change

T017's own tasks.md text spells out the scope D16 already settled: `Concept`, `ConceptScheme` and
`Collection` keep their URI, `static_uri`, slug, local URL and pk across the re-import; `ConceptLabel`
and `ConceptNote` rows do not, by #50's design, and are asserted on their values instead. Nothing
about adding a configured language touches identity assignment at all — `assign_unique_slug` and
`static_uri` resolution both run from the concept's own URI and label exactly as before, unrelated to
which languages are configured — so, like T016, this needed no production change. The same shape as
D26/D29/D30, recorded here rather than re-derived.

The identity test snapshots `(pk, uri, static_uri, slug, local_url)` for the scheme, all five
`rocks.ttl` concepts, and both collections before the second run and compares after — over every
record the fixture defines, not a sample, so a regression in any one of them would be caught. The
content test checks `granite`'s alternative label, hidden label and scope note alongside its and
`igneous`'s preferred label and definition — the label kinds T013/T014's contest could plausibly
disturb if the winner computation were ever keyed on the *set* of configured languages rather than
resolving each value independently, which it is not, but which is exactly the kind of coupling this
test would catch if introduced later.

**Revisit if:** never, for the same reason D30 gives — this is what a coverage task looks like when
the guarantee is already true by construction.

## D32 — T018's coverage lives in `test_standards.py` alongside `test_report.py`'s existing sweep, deliberately overlapping it

`tests/test_exchange/test_report.py` already parametrizes `TestSetAsideReasonVocabulary`,
`TestNormalizedReasonVocabulary`, and `TestReasonTemplatesUseOnlyNamedPlaceholders` over
`list(SetAsideReason)` and `list(NormalizedReason)`. Both closed vocabularies already contain
`VARIANT_NOT_KEPT` (T022) and `LANGUAGE_SUBSTITUTION` (T003), added in the foundational phase, so
those three sweeps already assert every claim T018's own text asks for — translatable, named
`%(subject)s`, no positional placeholder anywhere — for both reasons, without any new code. A
`TestSetAsideReasonVocabulary`-shaped test for either would be redundant with what already runs.

T018's own text names a different target: "the standards suite," not "the reason vocabulary's own
test module," and its acceptance says to follow the form of `test_standards.py`'s existing
translatable-message tests specifically. That module (Article XII home for validation-message
translatability) had no coverage of either reason at all — its own walk is over model field
metadata and `ValidationError` messages, not over `report.py`'s closed vocabularies. Two tests were
added there, `test_language_substitution_reason_message_uses_named_placeholders` and
`test_variant_not_kept_reason_message_uses_named_placeholders`, each following the file's own
form: a `Promise` check, a named-placeholder check against the raw template, and a rendered-message
check with real values substituted in — the same shape as
`test_static_uri_unsafe_scheme_message_uses_named_placeholders` two sections up.

The overlap with `test_report.py` is real and intentional, not an oversight to collapse. The two
suites hold two different things to the same standard from two different angles: `test_report.py`'s
sweep proves the *whole vocabulary* — present and future members alike — never regresses to a
positional placeholder; `test_standards.py`'s two new tests are this feature's own, targeted
evidence that its two specific additions meet Article XII, living where `tasks.md` and the brief
both said to put it. Neither makes the other redundant enough to delete.

**How RED was proven**, since neither test's assertion had ever failed before this task: `report.py`
was edited locally, twice in turn — once to make `LANGUAGE_SUBSTITUTION`'s template a bare,
non-lazy string with a positional `%s`, once to make `VARIANT_NOT_KEPT`'s template keep its
`gettext_lazy` wrapper but swap both its named placeholders for positional ones — running the two
new tests after each edit to observe the correct test fail for the reported reason, then reverting
with `git checkout` before the next edit. Neither edit was committed; `report.py` is byte-identical
to `HEAD~3` in this story's final diff.

**Revisit if:** never — this is the shape T018's own acceptance text specifies, and the redundancy
with `test_report.py` is documented here precisely so a later reader does not "simplify" one suite
away believing it duplicates the other for no reason.

## D33 — The identity-anchoring label never moves because of configuration

The S6 architecture lens found, and I reproduced independently, that adding a configured language
sharing a base with one the site already holds changes an existing concept's stored name, its slug,
and therefore its public URL — with the imported file byte-identical. On the branch's own
`variants.ttl`, configuring `en-gb` alongside `en` moved a concept from
`/vocabularies/colours/colour` to `/vocabularies/colours/color`.

The cause is a composition rather than a bug in any one place. `Concept.label` is the preferred
label in the vocabulary's default language. That default is frozen after the first import, and
correctly so, because it anchors every concept's identity. But the *winner* of the contest for that
slot is a function of which variants are configured: the moment `en-gb` becomes configured in its
own right, it stops being a candidate for `en`, and the `en` slot falls to the `en-us` value. The
slug is then re-derived from the new name on every run, by D6's own rule.

This breaks FR-009 and SC-015, and it is the harm Article IX exists to prevent — a local address
that downstream data already holds, moving for a reason that has nothing to do with the vocabulary.
SC-015's test could not catch it, because it only ever adds a language sharing no base with an
existing one.

**Two fixes were available and the choice is not close.**

*Pin the slug for an existing concept*, as `default_language` is already pinned. Rejected on two
counts. It leaves `Concept.label` itself still flipping, so the displayed name changes and only the
URL is held still — half a fix. And it overturns D6 from
[#49](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/49), a landed,
merged decision that a local URL follows a publisher's rename while the identifier does not.
Breaking a shipped decision to patch a symptom of a different one is the wrong trade.

*Resolve the default-language contest over the whole base-language group*, independent of which
variants happen to be configured. Chosen, and narrowed to that one slot: it is the only slot that
anchors identity, so it is the only one where configuration must not reach. Every other slot keeps
FR-002's placement, which is what maximises stored content.

**The cost, stated plainly.** A value can now fill both its own exact slot and the default-language
slot, so `Colour@en-gb` is stored under `en-gb` *and* under `en`. And the `en-us` spelling remains a
reported contest loser rather than being stored. That second point is the one worth sitting with,
and it is why this is defensible: it is *exactly what already happened* before the language was
added. The curator's picture does not change when they configure `en-gb`, which is the entire
guarantee US-4 promises. Stability across the re-import is the property being bought, and paying for
it with an outcome that was already true is a cheap price.

The rule states in one sentence, which is how it will be remembered and how the README will carry
it: **the label a concept is named by never moves because of configuration.**

Spec amended rather than worked around: FR-016 added, FR-002 annotated with the carve-out, SC-022
added with the explicit requirement that its test add a *base-sharing* language. Sam delegated this
decision explicitly ("your choice ... you make an informed decision") after I put both options and
their consequences to him, so it is recorded here rather than re-gated.

## D34 — Three defects the panel found, and why each is a real regression

Recorded together because they share a shape: each is a case where variant matching newly routes a
value down a path that was previously unreachable, and the path was not ready for it. All three were
reproduced against the branch and shown to behave correctly on `main`.

**SEC-001 — an unconfigured default language stores nothing.** `effective_default_language` falls
back to `settings.LANGUAGE_CODE`, which is validated nowhere against `settings.LANGUAGES`. The
matcher can only ever return a configured code, so when the default is unconfigured, no published
tag can resolve to it and every concept is set aside for want of a preferred label. Django's own
defaults are precisely this shape: `LANGUAGE_CODE = "en-us"`, and the 99-code default `LANGUAGES`
contains no `en-us`. The previous exact-equality comparison matched, so this is a regression against
a configuration most consuming projects have by simply never overriding it. It is reported as one
problem naming the unconfigured default, not as one missing-label entry per concept — a curator
reading ten thousand identical entries learns nothing from the tenth.

**SEC-002 — an over-long label aborts the whole run.** Values in a variant tag now reach
`Concept.add_label`, whose `full_clean` raises on text beyond 255 characters. Nothing catches it, so
one verbose alternative label in a hostile or merely careless file rolls back an entire import.
Guarded the way `EMPTY_SLUG` already guards the slug: catch the refusal, set the value aside with
its own reason, carry on. Article V names imported RDF untrusted, and a single field length should
not be able to deny the whole import.

**CORR-001 — the account is blind exactly where it matters most.** A concept skipped for having no
preferred label never reaches the code that records its other values, so none of its languages enter
the account. The failure lands precisely on the concept that was wholly lost, which is the one a
curator most needs to be told about. FR-008's sufficiency clause and SC-012 both fail. Fixed by
accounting the skipped concept's own published tags before continuing.

## D35 — A local address is derived from the published identifier, never from a translated label

Supersedes D33, which is withdrawn before any code implemented it, and overturns
[#50](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/50)'s D6.

**The maintainer's correction, which is the right one.** A published vocabulary gives every record
an identifier with a stable path. That path does not move when a label is translated, corrected, or
read in a different language, because it was never made of a label. This application's own addresses
must behave the same way: `/{vocabulary}/{record}` is composed from published identifiers and never
from a translated value.

**D33 was the wrong layer, and worth naming as such.** It held the default-language label still so
that a slug derived from that label would stay still. That is a symptom treated one step away from
its cause: the slug should not have been derived from a translated value in the first place, and
every rule built to stabilise the label was scaffolding around a mistake. It also cost a carve-out
in FR-002, which now stands as the Spec gate approved it.

**R1 already built the mechanism, and #50 declined to use it.** `Concept.set_slug` marks a slug
manual so `save()` stops re-deriving it, and its docstring says why it exists: *"this same mechanism
later carries an imported vocabulary's own slugs unchanged (spec R2)."* #50's `assign_unique_slug`
went the other way and said so plainly — *"Nothing is derived from `concept.static_uri` — identity
and slug are deliberately independent"* — and pinned the reasoning in D6: an identifier made of
opaque codes produces an unreadable local address. That is a real cost and it is the smaller one.
Readability of a URL is a preference. A URL that moves under data already pointing at it is a
correctness failure, and Article IX names downstream-data safety as the thing that must not break.

**The scope is wider than the case the review found.** `ConceptScheme.save()` re-derives its slug
from its name on every save with no manual mechanism at all, so a vocabulary's name arriving in a
different language moves the address of *every record it holds*. Measured:

```
before: scheme.slug=colours | concept.local_url=.../vocabularies/colours/clay
after : scheme.slug=colors  | concept.local_url=.../vocabularies/colors/clay
```

`static_uri` was unchanged throughout. Both segments of the address were label-derived, so both are
in scope, and the vocabulary needs the pinning mechanism the concept already has.

**Two rules decided here rather than escalated, because both follow from the identifier itself.**

*Which part of the identifier.* The fragment where the identifier has one, otherwise the last
segment of its path. SKOS vocabularies use fragment identifiers constantly
(`http://example.org/scheme#clay`), and for those the fragment is the record's name in every sense
that matters.

*Collisions.* Two records in one vocabulary can end in the same segment when their paths differ.
The suffix that separates them is derived from the identifiers, not from read order, so the same
file yields the same slugs however it is traversed. #50's existing suffix rule is order-dependent
and is replaced rather than reused.

**Why this lands in this feature rather than its own.** It changes behaviour #50 shipped, which
normally argues for separate work. FR-009 is the reason it cannot wait: this feature's approved spec
already promises that a re-import does not alter a record's local address, and with label-derived
slugs that promise is unkeepable. The fix is not scope added on top of FS-007, it is what makes
FS-007's own approved requirement true. Shipping D33's workaround instead would mean landing code
written to be deleted.

**Cost, named rather than hidden.** Local addresses for vocabularies published under opaque codes
become opaque — `/vocabularies/v-113/00123` where today they read `/soil-types/clay`. D6 called that
out and it remains true. It is accepted because the addresses are correct and permanent, which is
what a vocabulary's consumers need from them, and because a readable-but-unstable address is worse
than an opaque stable one for every use a URL is put to.

## D36 — Fix cycle 1 landed the withdrawn FR-016, and removing it is booked rather than reverted now

The fix-cycle implementer was dispatched before FR-016 was withdrawn, so T023 built
`LanguageMatcher.resolve_identity_winner()` and three tests around it. A subagent's brief is fixed
at dispatch, so the withdrawal could not reach a child already running. The code is on the branch
and it is green.

It is not reverted in place. `git revert` on T023 conflicts against T024–T027, which touch the same
region of `skos.py`, and hand-resolving a revert is exactly the kind of edit that lands untested.
Removal is instead a task in the FR-017–FR-020 dispatch: delete `resolve_identity_winner` and its
call sites, restore the FR-002 rule the carve-out displaced, and replace T023's three tests with
slug-level stability assertions — which is where the guarantee belongs once a local address is
derived from the published identifier rather than from a label.

Until that task lands, the branch carries an implementation of a withdrawn requirement. Named here
so it cannot be mistaken for an intended behaviour by a later reader of the diff.

## D37 — The craft-skill receipt gate red-blocked a clean report, and the cause is a mid-flight registry bump

`forge check-receipts` failed the fix-cycle report: it echoed `craft-tdd/2026-08-04/c95488d8` where
the registry now holds `craft-tdd/2026-08-05/eae3b6c7`.

The child was honest. Its transcript shows it loaded the skill and that the body it was given —
staged under `/tmp/openclaw/openclaw-claude-skills-*` at dispatch — ended with the 2026-08-04
receipt. A concurrent run on another repo edited `craft-tdd` and bumped its receipt in both the file
and the registry *while this child was running*. The dispatch brief, written at dispatch, recorded
the receipt that was then current; `forge check-skills` passed for the same reason.

So the gate compares a value fixed at dispatch against a registry that moves, and any skill edit
during a long child run retroactively fails a report that did nothing wrong. Overridden here on the
evidence above, which is a human judgement over a red gate and is recorded as such. The delta the
child missed is the per-task test-scope narrowing of 2026-08-05 — a cost rule, not a correctness
rule, and its only effect was that the child ran the full suite more often than it needed to.

**The deeper defect the diagnosis exposed.** The brief hands the child the receipt it is supposed to
echo, so echoing it has never proved a read. That is a kit fix, not a feature fix, and it is booked
as a retro proposal with the two gaps already recorded there.

## D38 — T029 rewrites the pre-existing tests and fixture that encoded D6, rather than leaving them red

`craft-tdd`/`craft-increments` both prohibit editing or deleting a test not authored in this cycle,
on pain of exactly the failure D25 and the FIX-1 note about broadened assertions describe: an
implementer quietly weakening coverage to make their own bug disappear. Five pieces of pre-existing
test material did not survive T029 unedited, and none of the five is that failure — each is the
literal, named codification of D6, which D35 (this same story, maintainer-approved) states in its
own words "overturns."

- `tests/test_exchange/test_skos.py::TestConceptSlugs` — its class docstring cited "decisions.md
  D6" by name and asserted a concept's slug is "never derived from the identifier." Rewritten to
  assert FR-017/D35's opposite rule instead of left red: `test_slug_is_never_derived_from_the_identifier`
  is gone, replaced by two identifier-shape tests (SC-026) and a publisher-rename stability test
  (SC-027, using the existing `rocks.ttl`/`rocks_updated.ttl` pair rather than a new fixture — T014's
  own test already proves the label change lands, this one adds that the slug and `local_url` do not
  follow it). `test_two_concepts_sharing_a_label_get_distinct_deterministic_slugs`'s expected values
  changed from `"quartz"`/`"quartz-2"` to `"quartz-a"`/`"quartz-b"`, because `duplicate_slug.ttl`'s
  two concepts collide on label, not on identifier, and D35 slugs from the identifier —
  demonstrating the collision no longer exists is the point, not an incidental side effect.
  `test_reimporting_the_identical_file_keeps_each_concept_s_slug` needed no change: it asserts
  before/after equality with no literal value, so it is agnostic to what changed.
- `tests/test_exchange/test_skos.py::TestConceptLabelIsSelectedByTheWinnerRule::test_an_exact_match_is_not_displaced_by_a_more_predominant_variant` —
  asserted `target.slug == "alpha"` as a side effect of asserting `target.label == "Alpha"`. The
  label assertion (the test's actual subject) is untouched; the slug assertion is corrected to
  `"target"`, the URI's own last path segment.
- `tests/fixtures/skos/empty_slug_label.ttl` and its two tests
  (`TestEmptySlugLabelIsSetAsideNotCrashed`) — FIX 5/D39's `EMPTY_SLUG` guard existed because a
  label made only of characters `slugify()` strips (`"±"`) used to produce an unusable *slug*. Under
  D35 the slug no longer reads the label at all, so that fixture's `symbol` concept now imports
  cleanly with slug `"symbol"` — the guard is real but nothing in the story's existing test material
  reaches it any more. The fixture's `symbol` concept was renamed to carry the unusable value in its
  own identifier instead (`<.../emptyslug/symbol#±>`), which is what can produce an empty slug under
  the new rule, and the two tests' expected subject URI updated to match. The guard itself
  (`assign_unique_slug`'s pre-write `slugify(...)` check) is untouched; only what triggers it moved.
- `tests/test_exchange/test_skos.py::TestExactMatchPreferredLabelFailingOnItsOwnMeritsIsNotBackfilledByAVariant` —
  demonstrated the spec's "exact match wins the contest and then fails on its own merits, and the
  variant does not silently take its place" edge case through the same `EMPTY_SLUG` mechanism, using
  an inline `"±"` label. That mechanism no longer reaches through the label either, so the edge case
  needed a different, still-live way for an exact match to "fail on its own merits": the label is
  now 300 characters, which trips the pre-existing, label-keyed `VALUE_TOO_LONG` guard (SEC-002,
  D34) instead — a real, unrelated failure mode this story does not touch, chosen because it is
  still driven by the label's own content rather than the identifier's.

None of the five was weakened: every rewritten assertion is exact-value equality, same as what it
replaced, and every test that needed no change (the two before/after comparisons) was left alone.
The full suite was green (335/335 in `test_skos.py`, 792/790 overall) before this entry was written.
**Revisit if:** a later reviewer wants these five kept as their own dated regression tests against
D6 specifically — they are not, on the view that a superseded rule's test is not evidence worth
preserving once the rule it tested is gone, the same position D25 takes about a test's home
mattering more than its literal survival.

## D39 — `SchemeResolver.resolve_scheme` recomputes the scheme's slug on every touch, not only on creation

T030's own task text reads naturally as "assign once, at creation" — the same shape T029 gives a
concept. Concept's own mechanism does not actually work that way, though: `assign_unique_slug` runs
unconditionally for every concept `import_concepts` touches, created or matched-existing alike, and
that is safe only because `concept.static_uri` is invariant once a concept is matched — recomputing
the base from it always reproduces the value already stored.

The same invariant holds for a scheme: `_get_or_create_scheme(declared_uri)` matches an existing row
by `get_by_uri(declared_uri)`, so on every re-import of the same vocabulary, `declared_uri` is by
construction the identifier that row was already matched on. Recomputing
`identifier_slug_segment(declared_uri)` on every call therefore always reproduces the slug already
stored, exactly as for a concept, so gating on `created` would add a branch that changes nothing
observable. Doing it unconditionally is also what keeps a scheme created outside the importer (a
curator's own row, given a `static_uri` directly, matched by a later import) reachable by the same
rule the moment it is: a scheme's `slug_is_manual` defaulting `False` on creation is exactly the
guard T031 relies on for locally-authored records with no `static_uri` at all, and it stays correct
for a scheme that is never matched by an import.

**Revisit if:** never — this is the same reasoning `assign_unique_slug` already relies on,
transplanted to the one call site that creates or matches a scheme rather than a concept.

## D40 — T032 needed no production change beyond T029's own

FR-020/SC-029 asks that a collision between two identifiers resolve "from the identifiers, not from
read order." `ConceptImporter.import_concepts` already sorts `concept_nodes` by the full identifier
string before ever processing one (`sorted(..., key=str)`, present since #50), so the order a file's
own author declares its concepts in was never actually consulted — a fact D6's own suffix rule
happened not to depend on either, because a fixture demonstrating it (`duplicate_slug.ttl`) collided
concepts on their *label*, and D6 derived the suffix base from the label, not the identifier.

Once T029 changed `assign_unique_slug`'s base to `identifier_slug_segment(concept.static_uri)`, two
concepts colliding on their identifier's own last segment resolve through the same pre-existing
`taken_slugs` mechanism (FIX 16, D49) T029 left untouched: the URI-sort decides who claims the bare
slug on a first import, and `taken_slugs`, seeded from each concept's own stored slug on every
re-import, reads a concept's prior answer back before ever minting a new suffix — so a slug never
depends on which pass of the file assigned it first. This is the same shape D26/D29/D30/D31 already
recorded: a coverage task (`TestConceptSlugCollisionIsIdentifierDerived`, two tests, both a specific
falsifiable claim rather than a tautology) that passed on first run because the design was already
correct, this time as a consequence of T029 rather than of an earlier phase.

**Revisit if:** never — the same shape as D26/D29/D30/D31, recorded so a later reader does not look
for a second collision algorithm and conclude one is missing.

## D41 — T035 (fix cycle 2): T030 gave a vocabulary's own slug a collision, and no mechanism to resolve one

A regression against `cd4f1c6`, reproduced and confirmed on both branches by the orchestrator before
dispatch. T030 (D39) moved a scheme's own slug from `slugify(row.name)` to
`slugify(identifier_slug_segment(declared_uri))`, mirroring T029's concept-side change, but stopped
short of also mirroring T029's collision handling: `resolve_scheme` wrote the identifier-derived
candidate straight onto `row.slug` and called `row.save()`, and `ConceptScheme.save()` refuses
rather than resolves a collision (research R4). Two published vocabularies whose identifiers happen
to end in the same segment — `.../a/colours` and `.../b/colours`, or any pair sharing a generic
final path component such as `/scheme`, `/vocab`, `/thesaurus`, `/core` — are ordinary in SKOS, not
an edge case. Reproduced exactly: importing `<http://a.org/colours>` then
`<http://b.org/colours>`, both `skos:ConceptScheme` with distinct `prefLabel`s, imported cleanly on
`cd4f1c6` (each slug came from its own distinct name) and raised an uncaught
`ValidationError({'slug': ["A vocabulary with the slug 'colours' already exists."]})` out of the
second scheme's `save()` on this branch, rolling back the whole second run.

**Resolved by reusing, not reinventing, `assign_unique_slug`'s own shape.** The importer — not the
model — resolves its own collisions: a numeric suffix minted only when the identifier-derived
candidate already belongs to a *different* record, matched on `static_uri` so a record always reads
its own prior slug back to itself (stable across a re-import) and the resolution is
identifier-derived rather than order-dependent (FR-020). Rather than duplicate that computation for
`ConceptScheme`, it is factored out of `assign_unique_slug` into a shared function,
`unique_slug_for_identifier(static_uri, taken_slugs)`, called by both
`ConceptImporter.assign_unique_slug` and `SchemeResolver.resolve_scheme` — Article XIV's cohesion
rule read literally: a concept's collision and a scheme's collision are the same computation over
two record kinds, and this story's own conventions text named the reuse explicitly rather than
leaving it to be noticed at review. `ConceptScheme.save()`'s own refusal is untouched: a curator
setting two vocabularies' slugs equal by hand is still refused, never silently auto-suffixed — only
the importer's own collisions, which a publisher cannot avoid by hand, are resolved here.

**Revisit if:** never — the same reasoning D35 and D39 already give for the scheme slug generally,
extended to its collision case.

## D42 — T036 (fix cycle 2): an unusable derived scheme slug must be fatal, and the concept-side guard was never mirrored

A second regression against `cd4f1c6`, reproduced and confirmed the same way. T030 changed what a
scheme's slug is derived from without carrying over T029's own guard: `import_concepts` checks
`slugify(identifier_slug_segment(uri))` for emptiness *before* ever calling `assign_unique_slug`,
and sets the concept aside under `EMPTY_SLUG` (D39) rather than let `Concept.save()`'s identical
refusal raise. `resolve_scheme` had no equivalent check at all — it wrote whatever
`unique_slug_for_identifier` returned (including `""`) straight onto `row.slug` and called
`row.save()`. Reproduced exactly: importing `<http://c.org/vocab/#±> a skos:ConceptScheme ;
skos:prefLabel "Symbols"@en` imported cleanly on `cd4f1c6` (the slug came from 'Symbols', which
slugifies fine) and raised an uncaught `ValidationError({'slug': ['An explicit slug must not be
empty.']})` on this branch, because the identifier's own fragment (`±`) is made up only of
characters `slugify()` strips.

**Fatal, not set aside — the two guards land differently on purpose.** A concept with an unusable
derived slug is one record the rest of the file can still be imported around; a vocabulary with an
unusable derived slug leaves nothing for the rest of the file to import *into*, so the whole run is
refused rather than reporting one unusable-slug problem and then reporting every concept in the file
as belonging to no resolvable vocabulary. Added `FatalReason.VOCABULARY_SLUG_UNUSABLE` alongside the
other `VOCABULARY_*` fatals, with a translatable, named-placeholder template (Article XII), and
checked in `resolve_scheme` ahead of `row.save()` — the same discipline `EMPTY_SLUG` already applies
on the concept side — rather than letting `ConceptScheme.save()`'s own refusal raise. No fallback to
`row.name`: that would reinstate the exact defect FR-018 exists to remove, for the one case where
the identifier-derived slug happens not to work.

**Revisit if:** never — the same reasoning `EMPTY_SLUG` (D39) already gives for the concept side,
with the fatal-versus-set-aside split accounted for by what each record kind's absence costs the
rest of the file.

## D43 — T038 (fix cycle 3): a collection is the third imported record with a published
identifier, and it was the one D35 missed

Round two of the S6 review panel returned all three lenses red, and every lens independently
found the same gap: `Collection` never received the identifier-derived, pinned slug D35 gave
`Concept` (T029) and `ConceptScheme` (T030). Reproduced exactly: importing a collection whose
identifier segment is `colours`, then re-importing the same file with only its `skos:prefLabel`
changed, moved the collection's slug from `colours` to `colors` and its `local_url` with it —
`Collection.local_url` is a real public address a curator can bookmark or cite, so Article IX
applies to it identically to a concept's or a vocabulary's.

**Fixed the way `Concept` and `ConceptScheme` were fixed, and no other way**, per the maintainer's
own instruction: `Collection` gains `slug_is_manual` (mirroring `Concept.slug_is_manual`) and
`set_slug()`; `Collection.save()` leaves a manual slug alone instead of re-deriving it from `name`
on every save; `CollectionImporter.import_collections` derives the slug from
`identifier_slug_segment(uri)` through `unique_slug_for_identifier`, with a per-scheme
`taken_slugs` map seeded the same way `ConceptImporter.import_concepts` already seeds one. One
migration (0007), the only one across T038–T042. A collection created on this site (never
imported, no `static_uri`) keeps deriving its slug from its name — FR-019's carve-out applies to
it exactly as it already does to a concept and a vocabulary.

**Revisit if:** never — this closes the third address space FR-017 was written to pin; the
reasoning is identical to D35's and D39's, extended to the one record kind they didn't reach.

**ADR:** none — applies D35's existing identifier-derived-slug rule to the third record kind it had missed. The rule is the decision; extending it to Collection is completing it, not choosing anything.

## D44 — T039 (fix cycle 3): an unusable derived collection slug is set aside; a name collision
is no longer reachable at all

Two triggers from the same round-two review, both reproduced against `b3e1e1d` and against `main`
identically — pre-existing, not a regression introduced by this story. **(a)** Two collections in
one vocabulary named `'Rock Types'@en` and `'rock types'@en` raised an uncaught
`ValidationError({'slug': ["A collection with the slug 'rock-types' already exists..."]})` and
stored nothing at all — zero schemes, zero concepts, because the whole run sits in one
transaction. **(b)** A collection named `'---'@en` raised
`ValidationError({'name': ['Name must produce a non-empty slug.']})`, likewise storing nothing.

**Trigger (a) needed no second mechanism.** T038 already removes it: two collections with
distinct identifiers no longer produce one slug to collide on, the same way T029 already removed
the equivalent concept-side collision (D35's `TestConceptSlugs` note: "there is no collision left
for this fixture to exercise"). Asserted directly as resolved behaviour rather than re-fixed.

**Trigger (b) is restated by T038, not removed.** A collection's slug no longer reads `name` at
all, so an unusable *name* can no longer produce an unusable slug — but an unusable *identifier
segment* now can, exactly the shape `EMPTY_SLUG` already guards for a concept
(`import_concepts`'s pre-write `slugify(identifier_slug_segment(uri))` check, D39). Mirrored for
`CollectionImporter.import_collections`: checked ahead of the write, the collection is set aside
under the existing `EMPTY_SLUG` reason rather than left to `Collection.save()`'s own manual-slug
refusal. Unlike a vocabulary (`VOCABULARY_SLUG_UNUSABLE`, D42), a collection is not something the
rest of the file needs in order to import, so this is a set-aside, never fatal.

**Revisit if:** never — the same reasoning D39/D42 already give, split the same way between "the
rest of the file can import around this" (set-aside) and "nothing can" (fatal).

**ADR:** none — a defect fix. Two reproduced crashes given the set-aside treatment their sibling paths already used.

## D45 — T040 (fix cycle 3): the default-language commonest fallback now folds tag case exactly
as the tally it echoes

`SchemeResolver.determine_default_language`'s commonest-concept-language fallback held its own,
character-for-character copy of the walk `SkosGraph.preferred_label_tag_counts` already performs
over the identical `concept_nodes` and the identical `skos:prefLabel` predicate — except without
that method's case fold (`key = language.lower()`, CORR-003/SEC-003, D34). FR-001 makes matching
case-insensitive throughout, so `EN-GB` and `en-gb` are one published tag, not two; the unfolded
copy split one tag's vote across two tally keys instead.

Reproduced exactly: ten concepts, four tagged `fr`, three `EN-GB`, three `en-gb`, under
`LANGUAGES=[('en','English'),('fr','French')]`. The folded tally (what should have run) gives
`{'fr': 4, 'en-gb': 6}` — `en-gb` wins and resolves to `en` (its shared base). The unfolded copy
(what actually ran) gives `{'fr': 4, 'en-gb': 3, 'EN-GB': 3}` — `fr` wins by a plurality that only
exists because the real majority was split — so a vocabulary that is 60% English by its own
publication imported as French, wrongly setting aside six of its ten concepts as
`NO_PREFERRED_LABEL`.

**The fix is a deletion, not an edit (Article XIV)**: `determine_default_language` now calls
`self.skos_graph.preferred_label_tag_counts(concept_nodes)` in place of its own copy of the same
walk. The existing lowest-code tie-break (D15) is unchanged — it runs over whichever tally it is
handed.

**Revisit if:** never — one computation, one shape, the same rule D13 and D27 already state for
the two other places this codebase once kept a winner computed twice.

**ADR:** none — removes a hand-copied walk that had drifted from the one it copied. No position is taken that a future change could contradict.

## D46 — T041 (fix cycle 3): a record's slug is read back from storage, never recomputed, once it
has one

Three reproductions, all the same defect at three granularities, all confirmed against `b3e1e1d`.
**(a)** Two vocabularies whose identifiers both end in `#terms` import as `terms` and `terms-2`;
deleting the first and re-importing the second's *unchanged* file moves the second's address from
`.../terms-2` to `.../terms` — a record's own address moving for a reason that has nothing to do
with its own identifier. **(b)** The same shape at concept granularity: an externally-identified
concept colliding on its base slug with a locally authored record occupying it gets suffixed on
first import; deleting the local record and re-importing the *same* file moves the external
concept's slug onto the now-vacant base. **(c)** A locally authored scheme `Rocks`
(slug `rocks`, `static_uri` NULL) holding a locally authored concept `Granite`
(slug `granite`, `static_uri` NULL); importing a file naming those exact composed local URIs
ended with `scheme.slug` `rocks-2` and **two** concept rows for one real `Granite` — the scheme's
own slug self-collided against its own not-yet-written `static_uri` (`taken_slugs` seeded `None`
for its row, compared against the new `static_uri`, never equal), and once the scheme's slug
moved, the concept's local-URI-parse match (`{base}/rocks/granite`, textually encoding the *old*
scheme slug) no longer found the scheme it was actually about.

**The cause, common to all three**: `assign_unique_slug`, `resolve_scheme` and (after T038)
`import_collections` all recomputed *every* record's slug through `unique_slug_for_identifier` on
*every* touch, matched-and-existing records included. That was safe in isolation — the base is a
pure function of a record's own `static_uri`, invariant once assigned — but not stable, because
`taken_slugs` is reseeded fresh from the database on every run: whatever else currently occupies
the scheme (or the app-wide scheme table) decides whether a given base is "taken", and that can
change between two imports of the identical file for reasons that have nothing to do with the
record being resolved.

**The fix: mint only for a record this run is creating.** A slug is computed through
`unique_slug_for_identifier` only when `created` is true; a matched record's slug is read back
exactly as stored and left alone — `taken_slugs` is still seeded from the database up front (so a
*sibling* created in the same run still resolves its own collision against every existing record,
matched ones included), but a record is never asked to re-derive an answer it already gave. Fixing
this for the scheme is what fixes (c): once the scheme's own slug stops moving, the concept's
local-parse match finds it correctly and is recognised as itself rather than duplicated — no
separate "key the read-back on identity, not on a possibly-`None` `static_uri`" mechanism was
needed once the scheme-level defect that caused it was closed at its source.

**`ConceptScheme.set_slug()` is now the importer's own write path.** It was public API this
feature added (T030) with no caller and no test — `resolve_scheme` set `slug`/`slug_is_manual`
directly and called `save()` itself. Routed through `set_slug()` instead, for both a freshly
minted slug and a matched row's unchanged one, so a locally-authored scheme the importer matches
for the first time also gets pinned (`slug_is_manual = True`) through the one path, rather than
left un-pinned until some later, unrelated save. `Concept.assign_unique_slug` keeps its own direct
attribute assignment rather than routing through `Concept.set_slug()`, unchanged from T029/D35:
its docstring already states why (avoiding a second write per imported concept), and nothing in
this cycle's review touched that reasoning.

**Revisit if:** never — the read-back rule is the same one `assign_unique_slug`'s own docstring
already stated as the intent behind seeding `taken_slugs` from a record's prior slug; this cycle
makes it load-bearing for every call site rather than true only by the coincidence that nothing
had yet vacated a slot.

**ADR:** docs/adr/0002-an-address-is-minted-once-and-read-back-forever.md — this is the durable half of the addressing rule: a minted slug is read back, never recomputed. It binds every future record kind and every future importer, and the failure it prevents (an address moving because a sibling was deleted) is not one a reader would anticipate.

## D47 — T042 (fix cycle 3): a derived slug is bounded to its field, and a name gets the guard
`Concept.label` already has

Reproduced against `b3e1e1d`: a concept identified as `<http://pub.example/L#>` plus 400 `a`
characters imported with `fatal=[]` and stored a 400-character slug in a `SlugField(max_length=255)`
— a row `full_clean()` then refuses (`"Ensure this value has at most 255 characters"`), so no
`ModelForm` can ever save it again. `local_url` came out 435 characters. `static_uri` accepts up to
500 and no `save()` on this path calls `full_clean()`, so nothing catches it — silent on SQLite,
which does not enforce `VARCHAR` length; a bare `DataError` on PostgreSQL, aborting the whole run
(the failure SEC-002's own code comment already names). The same hole reaches `ConceptScheme.name`
and `Collection.name`, and the scheme's own slug — a scheme is the whole file, so that one takes
the run down with it rather than losing one record.

**Two independent guards, because the two failures are different shapes.** `unique_slug_for_identifier`
now takes `max_length` (read from the calling model's own `SlugField`, via `Model._meta.get_field(
"slug").max_length` — never a literal `255` written a second time) and truncates its derived base
to fit, leaving room for a numeric collision suffix, so the returned candidate never exceeds the
field regardless of how many collisions it resolves. `ConceptScheme.name` and `Collection.name`
get the same pre-write length check `Concept.label` already has (`VALUE_TOO_LONG`, SEC-002, D34):
checked before the write, the record is set aside rather than written with a value the model would
refuse; the record still imports, holding whatever name it already had (or none, if this is its
first import) rather than an unchecked over-long one.

**Revisit if:** never — the same discipline SEC-002/D34 already established for a label, applied
to the two other free-text fields and the one length this codebase had not yet bounded.

**ADR:** none — bounds a derived value to its own field and reuses the guard Concept.label already had. Applying an existing guard to a new field.

## D48 — SC-022's `name` clause is struck: it belonged to the withdrawn FR-016

**Decided:** 2026-08-05, by the orchestrator, on the S6 round-two architecture lens's ARCH-103.
No re-gate — this removes a criterion that contradicts an approved requirement rather than
changing any approved behaviour.

SC-022 required that adding a configured language sharing a base with one the site already holds
leaves every concept's **name**, slug, and local address exactly as they were. The slug and address
clauses are right and FR-017 delivers them. The `name` clause cannot be met and should never have
been written, because it was drafted for FR-016 — the rule that pinned a concept's *displayed label*
so that an address derived from that label would stay still.

FR-016 is withdrawn. The address no longer comes from the label at all, so the reason for pinning
the label is gone, and the clause now requires the opposite of FR-002 as restored: a site adding
`en-gb` correctly moves an `en-us` value out of the `en` slot, because `en-gb` then resolves exactly
to itself and stops being a candidate for `en`. That is FR-002 working, not a defect.

**The stability this criterion exists to guarantee is the address, and FR-017 guarantees it at the
right layer.** A displayed name following the site's language configuration is what a curator
configuring a language is asking for. An address following it is the harm.

The clause is struck through and forward-tagged in place rather than deleted, the same treatment
D6 received. SC-022's test requirement stands unchanged and is still owed: it MUST add a
base-sharing language, because the test written for SC-015 only ever added an unrelated one and so
could not fail. The test fix cycle 1 wrote for this was removed with the T023 revert (D36), so
there is currently no test on the branch covering it.

**Revisit if:** FR-002 is ever narrowed again, in which case the two need re-reading together.

**ADR:** none — strikes a success criterion that contradicted an approved requirement. Bookkeeping on the spec, superseded by FR-017-FR-020.

## D49 — T044 (fix cycle 4): an over-long name on a *first* import has nowhere to fall back to,
and the fallback differs by what the record costs the rest of the file

Round-three review (ARCH-301/CORR-303/SEC-302) found the residue D47 left: the `VALUE_TOO_LONG`
guard sets an over-long name aside and falls through to the write without assigning `row.name`.
For a *matched* row that is correct — D47's own words, "row.name keeps whatever it already
held." For a row this run is *creating*, there is no earlier value to keep, so `row.name` stays
the field default, `''`, and both `ConceptScheme.name` and `Collection.name` are
`CharField(blank=False)` — the stored row then fails its own `full_clean()`, the exact shape D47
was written to remove, just moved from the slug to the name.

Reproduced against `10c069a`: a scheme (or a collection) whose only `skos:prefLabel` is 300
characters imports with `report.fatal == []`, `name == ''`, and `full_clean()` raising `{'name':
['This field cannot be blank.']}`.

**Two different outcomes, because a scheme and a collection cost the rest of the file
differently on creation, exactly as D42 already splits an unusable *slug*.** A vocabulary is what
the rest of the file imports into: a created scheme with an unusable name is now
`FatalReason.VOCABULARY_NAME_UNUSABLE`, the whole run refused, nothing written — the same
reasoning `VOCABULARY_SLUG_UNUSABLE` already gives. A collection is not something the rest of the
file needs: a created collection with an unusable name is set aside *entirely* (the existing
`VALUE_TOO_LONG` reason, `continue`d before `row.save()` ever runs) rather than persisted with a
name it cannot legally carry — the whole record, not merely its name field, because there is
nothing else to keep it for.

The matched-row half of both guards is untouched: a scheme or collection that already has a name
keeps it, set aside rather than fatal or skipped, exactly as D47 left it.

Two round-three tests asserted only `len(name) <= max_length` on the created path, which `''`
also satisfies. Both are strengthened in place (`test_a_scheme_name_longer_than_the_field_is_set_aside_not_written_unchecked`
renamed `..._is_fatal_on_first_import`; `test_a_collection_name_longer_than_the_field_is_set_aside_not_written_unchecked`
renamed `..._sets_aside_the_whole_collection_on_first_import`) to assert the outcome this cycle
overturns, and a matched-row counterpart is added for each so the surviving half of D47 stays
proven.

**Revisit if:** never — the same fatal-versus-set-aside split D42 already gives an unusable slug,
applied to the one other field a first import can leave unusably empty.

**ADR:** none — decides what a created record does when a matched record's fallback is unavailable to it. Local to the import path and fully described by docs/adr/0003-a-report-reason-is-an-outcome-and-its-message-must-always-be-true.md's outcome rule.

## D50 — T045 (fix cycle 4): a matched record's stored slug is now on the write path, so it must
be caught, not merely trusted

Round-three security review (SEC-301) reproduced: after T041, a matched record's slug is read
back and given straight to `set_slug()`/`save()` rather than recomputed. That is correct for a
slug that was always written through a model's own `save()` — it already passed the manual-slug
validation once. It is not correct for a slug written out of band: `.update()`, `loaddata`,
`bulk_create()`, or a data migration all bypass `save()` entirely, so a malformed value can sit in
the database untouched by validation until an import later matches that row and calls
`set_slug()`/`save()` again — at which point the model's own refusal (`ValidationError`) escaped
`import_skos` entirely, outside its own (`SkosImportError`/`SkosImportFailed`) exception
hierarchy, aborting the whole run for a hostility the imported *file* had no part in.

Reproduced against `10c069a` for all three kinds: create the row normally, plant an invalid slug
with `.filter(pk=...).update(slug="has spaces/and-slash")`, then import a file that matches the
row by its published identifier. All three raised the bare `ValidationError` out of `import_skos`.

**Fixed by wrapping the write, not by re-validating before it.** `ConceptScheme.set_slug()`
(inside `resolve_scheme`), `Concept.save()` (inside `import_concepts`) and `Collection.save()`
(inside `import_collections`) are each wrapped in `except ValidationError`, converting the escape
into `SetAsideReason.STORED_SLUG_INVALID` — the same discipline `import_labels`/`_import_notes`
already apply to a value's own `add_label`/`add_note` call. The record is left exactly as stored
(nothing about it is touched or removed) and the rest of the file still imports around it. For a
scheme specifically, this means `resolve_scheme` returns `(None, None)` without adding a fatal
finding — the run completes normally with nothing created or updated for that vocabulary, named by
the one set-aside entry, rather than refusing a file that is not itself at fault. Chosen over
treating it as `FatalReason` (the shape a broken *identifier* takes, D42): the file publishing the
scheme is fine, and there is nothing else in the file to salvage or protect by rolling the whole
run back — a corrupted database row, once named, is exactly the shape `SetAsideReason` exists to
report.

**Revisit if:** never — the same discipline `EMPTY_SLUG`/`VALUE_TOO_LONG` already give a value the
model refuses, applied to a whole record's own write for a reason the published file did not
cause.

**Correction (CORR-407, 2026-08-05, fix cycle 5):** the description above of the scheme's call
site is stale within this same fix cycle — T050/ARCH-304 (D55, below) replaced
`row.set_slug(row.slug)` with the two statements it performed directly, so `resolve_scheme` has
never called `set_slug()`; see D55. The "no fatal finding" outcome this entry describes for the
scheme is also superseded, by T052/D57 (fix cycle 5): a matched scheme that cannot be written now
adds `FatalReason.VOCABULARY_RECORD_INVALID` alongside `STORED_SLUG_INVALID`, because nothing else
in the file has a resolved vocabulary to import into once the scheme itself is not written. The
underlying diagnosis and the choice to use `SetAsideReason` for the slug specifically remain
correct; only these two details are corrected here rather than rewritten in place, per this file's
own append-only convention.

**ADR:** docs/adr/0002-an-address-is-minted-once-and-read-back-forever.md — recorded there as the consequence of reading a stored slug back rather than regenerating it: a value the importer did not mint cannot be assumed valid, so it is validated at the point of use.

## D51 — T046 (fix cycle 4): a collision suffix as long as the field slices the base away

SEC-303: `unique_slug_for_identifier`'s collision retry computed `base[: max_length -
len(suffix_text)] + suffix_text`. Once `len(suffix_text) >= max_length` that slice bound is zero
or negative, and Python slices from the *end* of the string rather than raising — at
`max_length == len(suffix_text)` the candidate is the bare suffix, with no relationship to the
base at all (`unique_slug_for_identifier('http://e.org/#ab', {'ab': 'other', 'b-2': 'other2'},
2)` returns `'-2'`).

Unreachable at any of the three current call sites — `Concept`, `ConceptScheme` and `Collection`
all pass their own `SlugField(max_length=255)`, and a suffix would need roughly 250 decimal
digits (≈10^250 colliding records sharing one base) to reach it. Fixed by construction anyway,
the same reasoning D47 already gives a helper this cycle keeps handing a new caller: `base[:
max(max_length - len(suffix_text), 1)]` always keeps at least one base character, so the
candidate is never merely the disambiguator. This does not guarantee `len(candidate) <=
max_length` in the (equally unreachable) case where `max_length` is smaller than `len(suffix_text)
+ 1` — there is no value that both fits the field and still carries any of the base at
`max_length < 2` — but it never again discards the base to make room for a suffix that alone
exceeds the field.

**Revisit if:** never — a one-line unit test on the helper (`TestUniqueSlugForIdentifierTruncationNeverSlicesNegative`)
covers it directly; no call site needs to change.

**Correction (SEC-405, 2026-08-05, fix cycle 5):** the "does not guarantee" caveat above is
resolved, not merely documented — see D63, below. The docstring's own claim that the candidate
"never exceeds `max_length`" was left false for the case this entry already named as unreachable
in practice; D63 makes it true by construction instead of leaving the gap between the code and its
own documented contract open.

**ADR:** none — an off-by-one in a slice bound, reproduced and fixed. A defect, not a position.

## D52 — T047 (fix cycle 4): the any-language name fallback now names its own language, not the
target it fell back from

CORR-305: `resolve_scheme` and `import_collections` both initialise `winning_tag` to the
scheme's effective default language before checking whether `_localized_literal` found a
matching-language name. When it does not — the scheme or collection publishes no name in the
default language at all — `name` falls back to `SkosGraph.first_literal` (any language), but
`winning_tag` was never reassigned, so a later `VALUE_TOO_LONG` set-aside on that name reported
the *default* language even when the value it names was never published in it.

Reproduced: a scheme whose only `skos:prefLabel` is a 300-character `fr` value, matched into a
scheme whose effective default language is `en` (frozen, since the file's own declared default is
never applied to a matched row per D46), set-aside `language=en` — the curator is told the
over-long value was published in a language it never carried.

**Fixed with one new query on the RDF boundary, not a second copy of the fallback.**
`SkosGraph.first_literal_with_language` pairs the identical value `first_literal` (any language)
already selects with the language tag it was actually published under (`""` for an untagged
literal) — same sort key, so the two can never pick different literals. `resolve_scheme`'s and
`import_collections`' own any-language branches now unpack `(name, winning_tag)` from it instead
of discarding the tag.

**Revisit if:** never — the same shape `_localized_literal` already gives its own matched branch
(pairing a value with the tag that won it), extended to the branch where nothing won.

**ADR:** none — a variable that was never reassigned on its fallback branch, so the reported language named the target rather than what was actually stored. A defect.

## D53 — T048 (fix cycle 4): FR-020's owed tests for `Collection`, no production change

CORR-301/CORR-302/CORR-304 named a test gap, not a code defect — the round-three review's own
mutation testing already confirmed the guarded code is correct on all three record kinds; nothing
in `skos.py` or `models.py` changes for this task. Three additions, all test-only:

- `TestASlugAlreadyStoredIsReadBackNeverRecomputed` gains
  `test_a_collection_keeps_its_suffixed_slug_after_a_colliding_sibling_is_deleted`, mirroring the
  scheme case exactly (CORR-301): two collections in one vocabulary colliding on their identifier's
  last segment, one deleted, the other's unchanged file re-imported.
- Its existing `test_a_locally_authored_scheme_and_concept_are_matched_not_duplicated_when_first_imported`
  is extended in place into
  `test_a_locally_authored_scheme_concept_and_collection_are_matched_not_duplicated_when_first_imported`
  (CORR-302): a third, locally authored record (a `Collection`) is added to the fixture, and the
  assertions grow to check `slug_is_manual is True` on all three matched rows and that each
  address survives an unrelated rename afterward. This is a **rename and extension of a test from
  fix cycle 3**, not a new parallel test — CORR-302's own recommendation asked for exactly this
  ("extend ... with a third record"), and every assertion the original test made is still made,
  unweakened; only the fixture and the assertions grow.
- `TestCollectionOverridableSlug` gains `test_explicit_slug_that_is_empty_or_malformed_is_refused`
  (CORR-304/ARCH-303), mirroring `TestConceptOverridableSlug`'s existing malformed-slug coverage
  and additionally covering the empty-slug raise neither model had a test for.

**Revisit if:** never — these close the "two of three kinds" and "matched vs. created" shapes
this feature has now hit twice (round two's dominant finding, per CORR-301's own framing), and no
behaviour changed underneath them.

**ADR:** none — test-only. Closes an owed-coverage gap the review's own mutation testing had already shown the code passes.

## D54 — T049 (fix cycle 4): the slug-pinning machinery is extracted, the same way `static_uri`
already was

ARCH-302: `slug_is_manual` (the field declaration), `set_slug()`, and the manual-slug branch of
`save()` (the empty/malformed-slug raise) were declared three times — on `ConceptScheme`,
`Concept` and `Collection` — byte-identical apart from `help_text` wording. The repo had already
diagnosed and fixed this exact shape once, for `static_uri`: `_static_uri_field(help_text)`
exists so the field's shared attributes are declared once, and `tests/test_standards.py`'s
`TestStaticUriFieldAttributesAgree` guards the copies from drifting apart. There was no equivalent
for `slug_is_manual`, so the same drift was unguarded — and CORR-304/ARCH-303 had already found
one instance of it (Collection's copy untested while Concept's was).

**Extracted onto `StaticUriModel`, the abstract base all three already subclass, following the
`static_uri` precedent exactly**, not a new mechanism:

- `_slug_is_manual_field(help_text)` beside `_static_uri_field`, called once per concrete model
  with that model's own `help_text` (a concept's slug tracks its *label*; a scheme's or a
  collection's tracks its *name*) — the one legitimate difference, same as before.
- `StaticUriModel.set_slug(slug)` — the three-statement body was identical; the one prose
  difference between the three per-model docstrings is now one shared docstring naming both
  exceptions (`assign_unique_slug`/`import_collections` writing the two attributes directly
  rather than calling it, per D46).
- `StaticUriModel._validate_manual_slug()` — the empty/malformed-slug raise, called from each
  concrete `save()`'s manual branch. The auto-derivation branch beside it (tracking a label or a
  name, and the collision check against a different scope per model) stays on each subclass,
  since what it derives *from*, and what it collides against, legitimately differs.

**A bare `slug: str` annotation on `StaticUriModel`** (no field, no column — Django only turns a
*field instance* into a column, never a plain type annotation) lets `set_slug`/
`_validate_manual_slug` reference `self.slug` with a type mypy/django-stubs can resolve from the
base, even though the concrete `SlugField` is still declared per-subclass (its uniqueness scope
— app-wide for `ConceptScheme`, per-scheme for `Concept` and `Collection` — is the one thing that
does not belong on a shared base).

**Verified migration-neutral**, the task's own hard requirement: `slug_is_manual`'s field
attributes (`default`, `verbose_name`, `help_text` text) are unchanged by moving them into a
factory function called from the same three places — Django's migration state depends on a
field's attributes, not the Python expression that constructed it. `poetry run python -m django
makemigrations --check --dry-run --settings=tests.settings` reports "No changes detected" after
the extraction; the full suite (638 tests across `test_models.py`, `test_skos.py`,
`test_standards.py`) and `mypy` are both clean.

**Revisit if:** never — the same remedy the repo already chose for `static_uri`'s identical
drift, applied to the one other field this feature added to all three models.

**ADR:** none — applies the repo's existing _static_uri_field extraction pattern to a second shared field. Following an established convention, not setting one.

## D55 — T050 (fix cycle 4): the four small architecture cleanups (ARCH-304–307)

All four applied on their merits; none was judged wrong.

**ARCH-304 — `resolve_scheme`'s only write is now visible at the call site.** `row.set_slug(row.slug)`
read as a no-op (the argument is the object's own current attribute) and hid that it was also the
row's only write of `default_language`/`name`/`description`/`static_uri`. Replaced with the two
statements `set_slug()` itself performs — `row.slug_is_manual = True` then `row.save()` (now
wrapped for T045's `STORED_SLUG_INVALID`, unchanged) — so the write is legible without tracing
into a method whose name promises only a slug change.

**Incidental consequence, not separately decided: ARCH-307 is now moot.** `ConceptImporter` and
`CollectionImporter` already assigned `slug`/`slug_is_manual` directly rather than calling
`set_slug()` (D46's stated reason: avoiding a second write per imported record); ARCH-304's fix
makes `SchemeResolver` do the same. `set_slug()` is no longer called from anywhere in the import
path — grep confirms zero production callers — so the three-way asymmetry ARCH-307 asked to have
documented no longer exists to document. `set_slug()` remains public API, exercised directly by
each model's own test class.

**ARCH-305 — one definition of "this identifier has no usable base."** `identifier_slug_base(uri)`
(module-level, beside `identifier_slug_segment`) replaces the hand-inlined
`slugify(identifier_slug_segment(uri), allow_unicode=True)` at both `EMPTY_SLUG` guards
(`import_concepts`, `import_collections`) and inside `unique_slug_for_identifier` itself. Not
folded together with the guards, per the review's own caution: a guard runs for a *matched*
record too (which never calls the minter), so merging them would silently change a matched
record's unusable-base handling from set-aside to updated.

**ARCH-306 — one narrowing for `Model._meta.get_field(...).max_length`.** The five reads of an
`Optional[int]` max_length were narrowed two ways in one commit: `cast(int, ...)` for the three
slug reads, an `is not None` runtime check for the three name/label reads. Picked `cast(int, ...)`
everywhere (the smaller change, and the one the existing comment at the slug reads already
justifies): Django's own field metadata always supplies a `max_length` for a `CharField`/
`SlugField` the model itself declares, so a runtime `None` check was dead code, not a genuine
guard.

**Revisit if:** never — all four are legibility/consistency cleanups with no behaviour change;
verified by the unchanged 847-test suite, `mypy`, and `makemigrations --check --dry-run`.

**ADR:** none — four small cleanups (ARCH-304-307), each local to one call site, none changing behaviour.

## D56 — T051 (fix cycle 5): the any-language name fallback picks a storable literal, not
merely the lexicographically first one

SEC-401 (round 4, high): T047's `SkosGraph.first_literal_with_language` selects the
lexicographically first literal of a predicate, full stop — it has no idea whether the caller can
store it. `resolve_scheme` and `import_collections` both use it as their any-language fallback
only when the effective default language carries no `skos:prefLabel` at all. When a publisher's
file carries, say, a 300-character `@de` name and a 16-character `@fr` one, and the site's default
language is neither, the fallback sorts on the raw string and can pick the 300-character value —
which T044 then measures against `name_max_length` and treats as "no name this application can
store," fatal for a created scheme, whole-record set-aside for a created collection — even though
the file plainly carries a storable name one triple away.

Reproduced against `540648a`: exactly that file (300-char `@de` scheme name plus a storable `@fr`
one, one concept) raised `SkosImportFailed` with zero rows written; the collection counterpart
dropped the whole collection. Removing either the `@de` triple or renaming it to sort after `@fr`
made the import succeed, which is the sort-order dependency by itself.

**Fixed at the one place the fallback is computed**, not at each of its two callers separately:
`first_literal_with_language` takes an optional `max_length` and, when given, restricts its
candidate pool to literals that fit before sorting. Both callers now compute their field's
`max_length` before the name/description block (previously computed after, since nothing earlier
needed it) and pass it to the fallback call. When nothing published fits — the genuine "no name
this application can store" case — the filtered call returns `None` and the caller falls through
to the original unfiltered call, purely to have a representative value for the fatal/set-aside
message; the length check immediately below still catches it and refuses (scheme) or drops
(collection) exactly as T044 already does when every candidate is unusable.

Deliberately narrow: this only fixes the fallback branch (`name_match is None` — no candidate in
the effective default language at all). CORR-402 (round 4, medium) names a related but distinct
shape — the effective-default-language match itself being over-long while another language has a
storable name — which fix cycle 5 addresses separately (T054, this file's own next entry) because
it is a different branch of the same function and the review scoped it as its own finding.

**Revisit if:** never — a caller wanting "the best value I can actually store" from an RDF literal
set is exactly what `max_length` on this one shared accessor gives both callers, without a second
copy of the filtering logic.

**ADR:** none — makes a fallback pick a literal the caller can actually store. Local to the name-selection path.

## D57 — T052 (fix cycle 5): a scheme's write failure is only a slug problem when it names the
slug, and either way the vocabulary is unresolved

CORR-401/SEC-402/SEC-403 (round 4, two high, one medium): T045's `except ValidationError` around
`resolve_scheme`'s `row.save()` converted *every* `ValidationError` `ConceptScheme.save()` can
raise into `SetAsideReason.STORED_SLUG_INVALID`, and its own `return None, None` was the one exit
from this method never preceded by `add_fatal` — unlike `VOCABULARY_UNDETERMINED`,
`VOCABULARY_TARGET_MISMATCH`, `VOCABULARY_SLUG_UNUSABLE` and `VOCABULARY_NAME_UNUSABLE`, all four
of which stop the run.

Two faults, reproduced separately against `540648a`. **Mislabelling:** `ConceptScheme.save()`
raises `ValidationError` for four reasons — the frozen-default-language check, the
configured-language check, `_validate_manual_slug()`, and the slug-collision check — and only the
last two are slug problems. A matched row's `default_language` is never reassigned by
`resolve_scheme` (D46), so a value that was a configured language when the row was written but has
since been dropped from `settings.LANGUAGES` reaches `save()` unchanged on every later import and
raises for `default_language`, not `slug`. The old handler reported `STORED_SLUG_INVALID` anyway —
false, since the stored slug is untouched and perfectly valid. **Success-shaped no-op:** whichever
field failed, `resolve_scheme` returned `(None, None)` with no fatal, `SkosImporter.run` gates the
whole concept/relation/collection phase on `target_scheme is not None`, and `report.fatal == []`
is what the module's own docstring defines as a successful run — so a file whose scheme could not
be written completed "successfully" having imported nothing, with only the one set-aside entry to
show for it.

**Fixed with two changes to the one `except` clause, not two separate try/except blocks.** The
caught `exc.message_dict` is checked for the key `"slug"`: only then does `STORED_SLUG_INVALID`
still fire, naming the actual cause `_validate_manual_slug()`/the collision check raises for.
Separately, a new `FatalReason.VOCABULARY_RECORD_INVALID` is always added alongside whatever
set-aside did or did not fire — the same precedent `VOCABULARY_SLUG_UNUSABLE` already sets for "no
resolvable vocabulary, nothing for the rest of the file to import into," generalised from "the
slug could never be minted" to "the write itself failed for any reason." `import_skos` now raises
`SkosImportFailed` for both scenarios instead of returning a report that looks like nothing was
wrong.

**Concept's and Collection's own `except ValidationError` wrappers are untouched.** `Concept.save()`
and `Collection.save()` under `slug_is_manual` raise only for slug reasons (empty, malformed, the
in-scheme collision), and a matched *record's* failure to write does not gate anything else in the
file the way an unresolved *vocabulary* does — the scheme is the one call site where both faults
apply.

**A pre-existing test is strengthened, not weakened.** T045's
`test_a_scheme_s_out_of_band_slug_failing_validation_does_not_escape_import_skos` asserted
`report.fatal == []`, which was exactly D50's now-corrected premise ("there is nothing else in the
file to salvage or protect by rolling the whole run back") — untrue, since nothing in the file
gets a chance to import once the scheme cannot be resolved. The test now asserts `import_skos`
raises `SkosImportFailed` with one `VOCABULARY_RECORD_INVALID` fatal, keeping its original
`STORED_SLUG_INVALID` set-aside assertion unweakened alongside it.

**Revisit if:** never — the same "unwritable vocabulary is fatal" rule `VOCABULARY_SLUG_UNUSABLE`
already gives an identifier that cannot be minted, applied to a write that fails after the
identifier was fine.

**ADR:** none — narrows an over-broad except clause and adds the missing fatal on the one exit that lacked it. A defect fix.

## D58 — T054 (fix cycle 5): a created record's over-long default-language name also gets a
second-chance storable fallback, not only the any-language branch

CORR-402 (round 4, medium): D56/T051 fixed the any-language fallback (`name_match is None` —
nothing published in the effective default language at all) to prefer a storable literal. It left
one branch untouched: when the default-language `skos:prefLabel` *does* exist but is itself
over-long, `_localized_literal` returns it directly, `name_match` is not `None`, and the
any-language fallback never runs at all — so a created scheme was still fatal
(`VOCABULARY_NAME_UNUSABLE`), and a created collection still dropped whole, even when a different
configured language published a storable name in the same file.

Reproduced against the D56 fix (before this entry): a scheme publishing `skos:prefLabel
"AAA…(300)"@en, "Roches"@fr` under a site whose default language is `en` still raised
`SkosImportFailed`, and the collection counterpart still dropped the whole record — the `@fr`
value was never considered because the `@en` one satisfied `_localized_literal` first.

**Fixed at the length check itself, not by restructuring the name-resolution branch.** Immediately
before a *created* record's name is declared unusable — the fatal for a scheme, the whole-record
`continue` for a collection — the same `first_literal_with_language(..., max_length=...)` call D56
already added is tried once more. Finding a storable value there reports the lost default-language
name as `VALUE_TOO_LONG` (the same reason a matched record's over-long name already gets) and uses
the storable value in its place; finding nothing storable falls through to the original fatal/
whole-record outcome exactly as before. A matched record's branch is untouched — it already keeps
its stored name regardless.

Deliberately no `NormalizedReason.LANGUAGE_SUBSTITUTION` for the value that wins here, matching
D52's own precedent: that reason names a matcher-resolved variant of the *target* language, not an
unrelated language stepped in for one that failed outright. The `VALUE_TOO_LONG` entry alone
already tells a curator which value was lost and why.

**Revisit if:** never — the same storable-first-literal fallback D56 introduced, reached from a
second call site the review named as the branch it does not yet cover.

**ADR:** none — extends D56's storable-fallback rule to the one branch it had not covered. Completing a fix.

## D59 — T054 (fix cycle 5): the blank-name guard also closes for a node with no
skos:prefLabel published at all

SEC-404 (round 4, medium): D49/T044 closed the blank-name shape only for the trigger it was
written against — an over-long name. The other way `name` stays unusable is a node publishing no
`skos:prefLabel` at all: `_localized_literal` returns `None`, the any-language fallback (T051's
`first_literal_with_language`) also returns `None` because there is nothing to select from, and
`name` itself is `None`. The over-long branch is skipped for falsiness (`if name and len(name) >
max_length`) and so is the assignment (`elif name:`), so a created scheme or collection reaches
`row.save()` with `name` still at the field default `''` — the identical `full_clean()` failure
D49 already declares impossible for a created record, reached by a route the length check does
not see.

Reproduced against the D58 fix (before this entry): a scheme node carrying only
`dcterms:description`, no `skos:prefLabel`, imported with `report.fatal == []` and
`ConceptScheme(name='', slug='...')` persisted; the collection counterpart persisted the same way.

**Fixed with one `elif created:` clause added after the existing name-assignment branch, at both
call sites**, taking the same created-record outcome the over-long branch already takes — fatal
(`VOCABULARY_NAME_UNUSABLE`) for a scheme, whole-record set-aside for a collection — rather than a
fourth `SetAsideReason`/`FatalReason` variant naming "no name published" specifically. The
collection's reused `VALUE_TOO_LONG` message is imprecise for this trigger (there is no over-long
value to name), a trade-off accepted deliberately: the record-level outcome a curator needs to
notice — this collection was not created — is identical to the sibling trigger's, and a query
against the language account (`report.set_aside`, grouped by reason) is unaffected either way,
since `VALUE_TOO_LONG` was never part of `_LANGUAGE_ACCOUNT_REASONS` in the first place.

**Revisit if:** the reused-message imprecision becomes a real curator complaint — at that point a
dedicated `RECORD_NAME_UNPUBLISHED`-shaped reason is worth minting for both the scheme and the
collection side together, rather than patched piecemeal.

**ADR:** none — extends D49's blank-name guard to the second way a name can be unusable. Completing a fix.

## D60 — T054 (fix cycle 5): a dropped collection gets its own reason, distinct from a value
lost off a record that still exists

CORR-404 (round 4, medium): a matched collection whose re-published name is unusable keeps its
stored name and stays exactly as it was — `SetAsideReason.VALUE_TOO_LONG`, whose message ("it was
not stored") accurately describes one field lost off a record that still exists. A *created*
collection in the same situation is dropped in full: no row, no membership, no `add_created`. Both
reported `VALUE_TOO_LONG` and nothing else, so the two outcomes — "this collection exists minus
its name" and "this collection does not exist" — were distinguishable only by querying the
database the report exists to describe. D59's own fix for SEC-404 (no `skos:prefLabel` published
at all) made this worse by reusing `VALUE_TOO_LONG` a third way, for a trigger with no over-long
value to name at all.

**Fixed with a new `SetAsideReason.COLLECTION_NOT_CREATED`**, added alongside (not instead of)
`VALUE_TOO_LONG` at the "over-long, created, nothing storable to fall back to" site — a curator
still learns which value was too long *and* that the record was dropped — and used alone at the
"no name published at all" site D59 introduced, since there is no over-long value to name there.
Neither site's existing `VALUE_TOO_LONG` assertions needed to change: the pre-existing T044 test
(`test_a_collection_name_longer_than_the_field_sets_aside_the_whole_collection_on_first_import`)
filters its own entries by `VALUE_TOO_LONG` specifically, so an additional `COLLECTION_NOT_CREATED`
entry alongside it is invisible to that assertion. D59's own new test, which had reused
`VALUE_TOO_LONG` for the no-name-at-all trigger, is updated in place to check the new reason —
authored in this same fix cycle, not a pre-existing test from an earlier one.

A scheme has no equivalent gap: an unusable created-scheme name is always fatal
(`VOCABULARY_NAME_UNUSABLE`), never a set-aside, so there is no "record exists minus its name"
sibling state to confuse it with.

**Revisit if:** never — the same "name the record-level outcome separately from the value-level
one" rule the report's other reasons already follow (e.g. `ALREADY_IN_ANOTHER_VOCABULARY` naming a
record decision, not a value), applied to the one place a collection's own creation is silently
implied by a value-level reason's absence of a record.

**ADR:** docs/adr/0003-a-report-reason-is-an-outcome-and-its-message-must-always-be-true.md — the first statement of the outcome rule: a value lost from a surviving record and a record dropped in full are different outcomes and take different reasons.

## D61 — T054 (fix cycle 5): assert the manual-slug refusal message, not only its type

CORR-405 (round 4, low): T048's `test_explicit_slug_that_is_empty_or_malformed_is_refused`
asserted only `pytest.raises(ValidationError)` for `set_slug("")`. `_validate_manual_slug`
(models.py) raises an empty-specific message for that case, but Django's own
`validate_unicode_slug` (`^[-\w]+\Z`) also rejects the empty string, so deleting the
empty-specific raise and falling through to the generic validator's own `ValidationError` left
the test green — confirmed by temporarily replacing the raise with `pass` and re-running
`TestCollectionOverridableSlug`: unchanged, 5 passed.

**Fixed by asserting `message_dict["slug"]` against the exact string each raise produces** rather
than only the exception's type — the empty-specific message for `set_slug("")`, and the
malformed-specific one (shared by `validate_unicode_slug`'s rejection) for `"foo/bar"` and `"has
spaces"`. Re-running the same mutation against the strengthened test now fails it for the right
reason (`AssertionError` on the message, not a swallowed `ValidationError`), confirmed and
reverted in the worktree before committing — the production code is unchanged.

Scoped to the one test CORR-405 named. `Concept`'s own manual-slug test
(`TestReviewHardening.test_explicit_slug_with_invalid_characters_is_refused`) has no empty-slug
case at all — a gap that predates this feature entirely and is out of this cycle's scope, since
CORR-405 named only the test T048 itself introduced.

**Revisit if:** never — the shared `_validate_manual_slug` means this one strengthened test
already proves both raises for all three models; there is nothing left to weaken again.

**ADR:** none — strengthens one test to assert the specific refusal rather than the exception type. Test hygiene.

## D62 — T054 (fix cycle 5): two documentation casualties from T049's extraction, restored

CORR-406/CORR-407 (round 4, both low): T049's extraction of `slug_is_manual` onto
`StaticUriModel` (D54) dropped the `No db_index: ...` comment both concrete field declarations
carried, with no replacement — `grep -rn db_index controlled_vocabularies/` returned nothing.
Separately, `StaticUriModel.set_slug()`'s shared docstring (also written by T049) claims "only
`SchemeResolver.resolve_scheme` routes an import through it," which T050 — later in the very same
fix cycle — made false: ARCH-304 replaced `resolve_scheme`'s `row.set_slug(row.slug)` with the two
statements it performed directly, so no production code calls `set_slug()` at all (D55 says so in
so many words). D50's own prose, describing the pre-ARCH-304 shape, went stale in the same cycle
that wrote D55 correcting it, and was never itself annotated.

**Both restored where the code now lives, not by reverting the extraction.** The `db_index`
rationale is added to `_slug_is_manual_field`'s own docstring — the one place the field is
declared now, covering all three models at once rather than three copies drifting again.
`set_slug()`'s docstring is corrected to state the actual routing (all three importers assign
`slug`/`slug_is_manual` directly and save once) instead of naming a call site that no longer
exists. D50 is corrected in place with an appended, dated note pointing at D55 and at this cycle's
own D57, rather than rewritten — this file's entries are a record of what was decided and why, not
a living description of the current call graph, so the correction is additive.

**Revisit if:** never — both are wording-only; `poetry run pytest tests/test_models.py
tests/test_standards.py`, `ruff`, and `mypy` are unchanged.

**ADR:** none — restores an indexing comment and corrects a docstring that T049's extraction had dropped or falsified. Documentation repair.

## D63 — T054 (fix cycle 5): unique_slug_for_identifier's candidate is clamped to max_length,
matching its own documented contract

SEC-405 (round 4, low): T046/D51 truncated the *base* to leave room for the suffix
(`base[: max(max_length - len(suffix_text), 1)]`), but the function's own docstring claimed the
returned candidate "never exceeds `max_length` however many collisions it resolves" — false once
`max_length` is smaller than `len(suffix_text) + 1`: keeping one base character plus the whole
suffix still overruns the field. Reproduced: `unique_slug_for_identifier('http://e.org/#ab',
{'ab': 'other', 'b-2': 'other2'}, 2)` returns `'a-2'`, three characters against a `max_length` of
two. D51 already named this gap and judged it unreachable at any of the three current call sites
(`SlugField(max_length=255)` everywhere; a suffix long enough to reach it needs on the order of
10^250 colliding records sharing one base) — correct as a risk assessment, but the docstring still
asserted a guarantee the code did not keep.

**Fixed by clamping the assembled candidate, not only the base:** `(base[: max(max_length -
len(suffix_text), 1)] + suffix_text)[:max_length]`. A new test,
`test_a_collision_suffix_longer_than_max_length_still_fits_within_max_length`, reproduced the gap
RED (`len('a-2') == 3 > 2`) before the fix and is green after it, alongside the existing
`TestUniqueSlugForIdentifierTruncationNeverSlicesNegative` cases, both unaffected since 255 never
reaches this branch either way.

**Revisit if:** never — the docstring's contract and the code now agree unconditionally, so there
is nothing left to reconcile if a future call site ever does pass a small `max_length`.

**ADR:** none — makes a function honour the length contract its own docstring already claimed. A defect.

## D64 — T054 (fix cycle 5): an empty language tag renders as a phrase, not empty quotes,
fixed at the one boundary every entry's message passes through

SEC-406 (round 4, low): `SkosGraph.first_literal_with_language` reports `""` for an untagged
literal (D52), deliberately — the two accessors must never disagree about *which* literal, and an
untagged one simply has no tag to report. When that value is over-long, `winning_tag` carries `""`
into `SetAsideReason.VALUE_TOO_LONG` (from either the scheme or the collection path) or
`FatalReason.VOCABULARY_NAME_UNUSABLE`, and the rendered message reads "...its published name in
'' is longer than..." — nothing unsafe or leaked (`craft-security`'s own review confirmed only the
URI and a grammar-constrained language tag ever reach a template), just uninformative.

**Fixed once, at `SetAsideEntry.render()`/`FatalFinding.render()`'s shared parameter-building
step**, not at each of the two call sites that can produce an empty tag: a new module-level
`_render_params(subject, params)` substitutes a translatable `"no language tag"` phrase for an
empty `"language"` value before formatting. Both `render()` methods (and `NormalizedEntry.render()`,
for symmetry, though `LANGUAGE_SUBSTITUTION` cannot currently receive an empty tag) call it instead
of building the `%`-format dict inline. A future reason carrying `language` gets the same
treatment automatically rather than needing its own guard.

**Revisit if:** never — one substitution point for every entry type, matching the "one computation,
one shape" rule the report module's other shared logic already follows.

**ADR:** none — substitutes a phrase for an empty language tag at the one boundary every message passes through. Covered by docs/adr/0003-a-report-reason-is-an-outcome-and-its-message-must-always-be-true.md; the placement is the obvious one once the rule is stated.

## D65 — T055 (fix cycle 6): an empty or whitespace-only literal is never a usable name, fixed at
every place one is selected

SEC-501/SEC-502/CORR-501/CORR-502/SEC-504 (round 5, three high, one medium, one low), all one root
cause reproduced from both directions. `SkosGraph.first_literal` applied no content filter at all;
`first_literal_with_language`'s `max_length` filter (T051, D56) tested only `len(str(literal)) <=
max_length`, which an empty literal always satisfies. Both sort on the raw string, so `""` sorts
ahead of every real value. Two opposite, independently reproduced symptoms:

**A file publishing a usable name was refused outright.** `skos:prefLabel ""@en, "Geology
Vocabulary"@en` on a site defaulting to `en` — `_localized_literal`'s own per-tag exact match
picked the empty literal for the `en` slot, `name` arrived at the length check as `''`, and
T054's `elif created:` guard (D59) fired `VOCABULARY_NAME_UNUSABLE`, refusing a file that plainly
carries a storable name one triple away.

**A created record was persisted with a blank name.** `skos:prefLabel "<300 chars>"@en, ""@de,
"Geologie Vokabular"@fr` — T054's own second-chance fallback (D58) called
`first_literal_with_language(..., max_length=...)` to find *something* storable when the
default-language name was over-long, and the empty `de` literal satisfied that filter and sorted
first, so the fallback returned `('', 'de')` and `row.name = ''` was written unconditionally. This
is exactly the state D49 declares impossible for a created record, reopened through the fallback
D58 itself added to close a different gap.

**Fixed at the two accessors that select a literal, not at either consequence.** `first_literal`
and `first_literal_with_language` both now require `str(literal).strip()` to be truthy, in
addition to whatever language or length filter already applied — an empty or whitespace-only
(SEC-504) literal is excluded from the candidate pool before sorting, at every call site, rather
than reaching `name` and being caught (or not) after the fact. `_localized_literal` needed no
change of its own: its per-tag candidates are built by calling `first_literal(node, predicate,
language=tag)` (skos.py:412), so a tag whose only literal is empty now yields no candidate for
that tag automatically, the same way a missing predicate already does.

**Determinism was checked, not assumed**, per the round-5 brief's own instruction — two literals
equally usable (same value, or a genuine tie after the emptiness filter) still resolve through
`sorted()` over `(str, str)` tuples, a total order with no set or dict iteration reaching the
comparison at any point in either accessor. Unaffected by this fix, since it is a filter on the
candidate pool, not a change to how the pool is ordered.

**Revisit if:** never — the same "unusable is unusable at the point of selection, not the point
of consequence" rule the round-5 review's own recommendation states, applied once at both
accessors rather than patched at each of the four call sites (`resolve_scheme`'s exact match, its
any-language fallback, `import_collections`'s identical pair) that would otherwise each need their
own guard.

**ADR:** none — applies the empty-literal rule at every place a name is selected. The rule is what matters and it is a validation detail, not an architectural position.

## D66 — T056 (fix cycle 6): `unique_slug_for_identifier`'s collision loop gives up rather than
looping forever

CORR-503 (round 5, medium) claimed SEC-405's own clamp (D63) turns the collision loop
non-terminating. Established real before touching anything, per the brief's own instruction: the
review's exact repro, `unique_slug_for_identifier('http://e.org/#ab', {'ab': 'other', 'a-':
'other2'}, 2)`, was run under a 20-second `timeout` ahead of any fix and killed (exit 143, no
return) — confirmed hanging, not merely slow.

**Why it hangs.** Once `len(suffix_text) >= max_length`, `max(max_length - len(suffix_text), 1)`
is pinned at `1`, so the base contributes exactly one character every subsequent iteration, and
the final `[:max_length]` clamp (D63) keeps only that one base character plus the first
`max_length - 1` characters of `suffix_text`. At `max_length=2` those two facts together mean the
assembled candidate is always `base[0] + suffix_text[0]` — the base's first character, plus
literally the leading `-` every `suffix_text` starts with — regardless of which suffix number is
being tried. If that one resulting string is already taken by a different record, no value of
`suffix` can ever produce a different candidate, and the `while` condition never becomes false.

**Fixed by detecting the repeat, not by pre-judging `max_length` against `len(suffix_text)`.** A
`tried` set records every candidate this call has already produced; a candidate reappearing proves
the search has cycled back to a string it already rejected, so the loop cannot make progress and
returns `""` — the same "unusable" signal an empty base already returns, which every caller
already knows how to handle (fatal for a vocabulary, a set-aside for a concept or collection). A
simpler `return "" if len(suffix_text) >= max_length` at the top of each iteration was considered
and rejected: it fires the moment the *first* retry needs a suffix as long as `max_length`, which
is exactly the shape the two pre-existing SEC-303/SEC-405 tests exercise
(`{'ab': 'other', 'b-2': 'other2'}`, `max_length=2`) — and in both of those, the very first retry's
candidate (`'a-'`) is *not* taken, so the call correctly succeeds today. A length-only pre-check
would have turned those two passing, correct results into a give-up, weakening behaviour the
existing tests (not touched by this cycle) already prove correct. Repeat-detection only gives up
once the loop has actually failed to progress, never before.

**Revisit if:** never — a repeat is the only condition under which this loop cannot terminate;
detecting it directly is simpler than deriving, and keeping in sync with, a closed-form condition
on `max_length` and `suffix_text` that would have to be re-derived if the clamp in D63 ever
changed shape again.

**ADR:** none — a non-terminating loop, reproduced hanging under a timeout before the fix. A defect.

## D67 — T057 (fix cycle 6): `exc.message_dict` raises `AttributeError` for a non-dict
`ValidationError`; read `error_dict` with a default instead

CORR-505/SEC-503 (round 5, low and medium): `django.core.exceptions.ValidationError.message_dict`
is a property that does `getattr(self, "error_dict")` before anything else, so it raises
`AttributeError` whenever the exception was constructed from a bare message
(`ValidationError("...")`) or a list rather than a field dict. T052's handler
(`resolve_scheme`'s `except ValidationError`) reads `"slug" in exc.message_dict` unconditionally —
correct for every raise this package's own `ConceptScheme.save()` chain produces, all of which are
dict-form, but not obliged to hold for a consuming project's own `pre_save` receiver on
`ConceptScheme` or a subclass `save()` override, both of which conventionally raise the ordinary
non-dict form. Reproduced by monkeypatching `ConceptScheme.save` to `raise
ValidationError("a plain refusal, no field dict")`: `import_skos` raised `AttributeError` instead
of `SkosImportFailed`, escaping outside its own documented exception hierarchy — precisely the
guarantee this `except` clause exists to give (D50), broken by the line refining what it reports.

**Fixed by reading the attribute `message_dict` itself guards on, with a default.**
`"slug" in getattr(exc, "error_dict", {})` — `error_dict` is present only for the dict form, its
keys are the same field names `message_dict` would expose, and a missing attribute now falls
through to `{}` rather than raising. The non-dict form then correctly skips
`STORED_SLUG_INVALID` (there is no field name to report one for) and still reaches the
unconditional `add_fatal(VOCABULARY_RECORD_INVALID)` below it, so `import_skos` raises
`SkosImportFailed` exactly as D57 intends for any write failure, dict-shaped or not.

**Revisit if:** never — the same defensive-read shape the round-5 recommendation names directly,
and the only change needed to keep every shape of `ValidationError` inside this handler's own
exception contract.

**ADR:** none — reads ValidationError.error_dict with a default instead of a property that raises for a non-dict error. A Django API detail, corrected.

## D68 — T058 (fix cycle 6): a vocabulary refused for publishing no name gets its own reason, and
two round-5 refusals gain success criteria

CORR-504 (round 5, medium): D59/T054's `elif created:` guard for a scheme with no
`skos:prefLabel` published at all reused `FatalReason.VOCABULARY_NAME_UNUSABLE`, whose template
is written for one trigger only — "its published name in '%(language)s' is longer than this
application can store." On the no-prefLabel path nothing is published in any language, so both
halves of that sentence are false: there is no over-long value, and `winning_tag` names the site's
effective default language, not a language anything was actually published in. D59's own text
already flagged this as a live risk ("a dedicated `RECORD_NAME_UNPUBLISHED`-shaped reason is worth
minting... if the reused-message imprecision becomes a real curator complaint") — the round-5
review is exactly that complaint, materialising the case D59 predicted rather than a new one.

**Fixed by minting `FatalReason.VOCABULARY_NAME_UNPUBLISHED`**, scoped to the scheme side only —
the collection side already has its own distinct `COLLECTION_NOT_CREATED` reason for this trigger
(D60), whose message the round-5 review's own `checked_and_clear` section confirmed already holds
on both the over-long and the no-prefLabel path. A scheme has no such second reason to reuse
correctly, because an unusable created-scheme name is always fatal, never a set-aside, so there
was nothing but the wrong-shaped `VOCABULARY_NAME_UNUSABLE` to fall back to. The new reason takes
no `language` param — there is no language to name — and its own template says plainly that no
`skos:prefLabel` was published.

**A pre-existing test's assertion is overturned, not merely extended**, and is named here per this
cycle's own rule for doing so. `TestNoPublishedNameAtAllIsUnusableTheSameAsOverLong
.test_a_created_scheme_with_no_preflabel_at_all_is_fatal_not_persisted_blank` (T054, fix cycle 5,
D59) asserted `report.fatal[0].reason is FatalReason.VOCABULARY_NAME_UNUSABLE` — true of the old
code and false of the corrected code, since this task's whole point is that the no-prefLabel
trigger is not the same reason as the over-long one. The assertion is changed to the new reason,
and a `render()` check is added (`assert "longer than" not in message`) that the previous
type-only assertion could not have made, per CORR-504's own observation. T055's own
`test_a_node_publishing_only_an_empty_literal_is_treated_as_no_usable_name_at_all` (committed
earlier in this same fix cycle) reaches the identical branch — an empty-only literal is, by T055's
own fix, indistinguishable from nothing having been published — and is updated to the same new
reason for the same cause, not a second, independent overturn.

**CORR-506** (round 5, low): two refusal behaviours this feature added had no success criterion —
a matched vocabulary whose own write fails (T052/D57) and a created vocabulary or collection
publishing no preferred label at all (T054/D59) — while SC-024's amendment and SC-031 cover only
the sibling over-long-value trigger. Both already have tests; this is the spec catching up to
behaviour, not new behaviour. Added as SC-032 (D57) and SC-033 (D59) at the end of the existing
list, per this file's own append-only numbering — nothing renumbered, nothing struck.

**Revisit if:** never — the same "a message must hold on every path that reaches it" rule D60
already applied to the collection side, extended to the one place it had not yet reached; the two
new success criteria describe behaviour already proven by an existing test, so there is nothing
further to reconcile.

**ADR:** docs/adr/0003-a-report-reason-is-an-outcome-and-its-message-must-always-be-true.md — one of the four instances that established the rule: a refusal message that named a trigger which did not hold on the path raising it.

## D69 — T059 (fix cycle 7): the empty-literal-is-never-a-name rule reaches a concept's own
label, structurally rather than as a third copy of the check

SEC-601/CORR-602 (round 6, high and medium): D65 (T055, fix cycle 6) applied "an empty or
whitespace-only literal is never a usable name" inline in exactly two places —
`SkosGraph.first_literal` and `SkosGraph.first_literal_with_language`. A vocabulary's name and a
collection's name are both selected through one of those two accessors, so both were fixed. A
concept's label is selected through a third accessor, `SkosGraph.preferred_label_in`, which D65
never touched — reproduced end to end: a concept published as `skos:prefLabel ""@en, "Real
Name"@en` stored `Concept.label == ''` and reported `"Real Name"` as `SURPLUS_PREFERRED_LABEL`,
discarded rather than merely passed over. This is the fourth time this feature's review has found
a rule reaching some record kinds and not all (round 2's FR-017 reaching `Concept`/
`ConceptScheme` but not `Collection`; round 5's SEC-501/SEC-504 scoped to the scheme/collection
name paths; this round's own SEC-602 finding the identical gap in the predominance vote).

**Fixed by naming the check once and routing every literal-to-name-candidate read through it**,
rather than adding a third inline copy. `SkosGraph.is_usable_literal` is a static predicate —
`isinstance(literal, rdflib.Literal) and bool(str(literal).strip())` — and `first_literal`,
`first_literal_with_language`, `label_languages` and `preferred_label_in` all call it. A fourth
record kind's own accessor, or a fifth call site reading the graph directly, now has to actively
avoid this predicate to reintroduce the defect, rather than simply being written without knowing
the rule exists.

**Audited for other paths reaching a stored name field without going through the predicate, per
the brief's own instruction, and found one:** `ConceptImporter.import_labels` reads
`skos:altLabel`/`skos:hiddenLabel` (and a non-default-language `skos:prefLabel`) directly off the
graph, not through `preferred_label_in` — the fifth call site the structural fix exists to catch.
A true empty string was already refused before this task (`ConceptLabel.text` is `blank=False`,
and `add_label` calls `full_clean()`), but Django's blank check does not treat a whitespace-only
string as blank, so `"   "` passed straight through and was stored as a visible-nothing
alternative label. Routing this loop through `is_usable_literal` too closes it, and is not
optional: without it, closing `preferred_label_in`'s own gap makes a concept whose *only*
candidate for a configured non-default language is empty raise `KeyError` in this same loop —
`preferred_winner_by_language` would no longer have an entry for that language once its one
candidate is excluded, and the raw loop's own lookup for a `PREFERRED`-kind literal in that
language has to find one. Both fixed by the same one-line change: an unusable literal is skipped
before this loop asks the matcher anything about it, silently, exactly as `SkosGraph`'s own
accessors already treat one.

No other path was found. `_import_notes` and the `dcterms:description` alias are documentary
text, not a name a curator identifies a record by, and are out of the predicate's scope on that
basis (`is_usable_literal` is a *name* rule, not a general emptiness rule — an empty note is
already storable content, just an unhelpful one, and changing that is no part of this task).

**Revisit if:** a fifth name-selection path is added anywhere in this module and does not read
through one of the four `SkosGraph` accessors above or `ConceptImporter.import_labels`'s own now-
guarded loop — at that point the predicate needs a fifth caller taught about it explicitly, the
one shape this decision exists to make rare.

**ADR:** none — replaces two inline copies of a check with one shared predicate. Structural tidying inside one module; no future choice is constrained by it.

## D70 — T060 (fix cycle 7): the collision loop's give-up seeded `tried` with `base` itself,
abandoning a resolvable collision; the give-up return is now guarded at all three call sites

CORR-601/SEC-604 (round 6, high and low). D66 (T056, fix cycle 6) added a give-up to
`unique_slug_for_identifier`'s collision loop, returning `""` once a candidate repeats one
already recorded in `tried`. `tried = {candidate}` seeded that set with `base` itself, before the
loop had generated anything — the `while` condition above had already tested `base` on its own,
so recording it a second time as a *tried candidate* was never necessary and, at one specific
shape, actively wrong. Reproduced exactly as the round-6 review reported it: at `max_length=255`
with `base` exactly 255 characters long and ending in `-2`, the clamp (D63) makes the first
retry's candidate `base[:253] + "-2"` — identical to `base` itself — which then looked like a
repeat of the seeded entry and gave up on the very first retry, abandoning a collision the next
suffix (`-3`) resolves without difficulty. Two concepts whose identifiers both slugify to that
one 255-character base — a real shape, not a contrived one, since any published identifier
segment of 255 or more characters produces it — imported as one concept and one
`STORED_SLUG_INVALID` set-aside, where they should both import.

**Fixed by only ever recording a candidate the loop itself produced**: `tried: set[str] = set()`,
seeded empty. The repeat-detection logic below is otherwise unchanged — it still gives up once a
*generated* candidate repeats one already generated, the genuine non-termination case D66 exists
to catch (verified: the round-5 `{'ab': 'other', 'a-': 'other2'}`, `max_length=2` repro still
gives up; the SEC-303/SEC-405 fixtures and a normal 255-length chain still resolve on their first
or second retry as before).

**SEC-604**, closed in the same task since an unresolvable collision must be reported, never
silently written: D66's own text claimed "every caller already knows how to handle it," true only
of `SchemeResolver.resolve_scheme`'s call site (`if not slug: add_fatal(VOCABULARY_SLUG_UNUSABLE)`).
`ConceptImporter.import_concepts` and `CollectionImporter.import_collections` both assigned the
return value straight onto the row and let an empty slug reach `save()` unguarded, where it was
caught only by the model's own manual-slug validation and reported `STORED_SLUG_INVALID` — a
reason whose own message says a *stored* slug fails validation, false for a slug that was never
written at all. Both call sites now check `if not <field>.slug:` immediately after minting one for
a newly created record and report `EMPTY_SLUG` — the same reason the identifier's own unusable
base already gets just above each call site — before ever reaching `save()`. Unreachable through
`import_skos` today at either fixed call site (both still pass `max_length=255`, and D51/D63 put
the collision count needed to exhaust that space at roughly 10^250), verified instead by
monkeypatching `unique_slug_for_identifier` to always give up, the shape a reachable-in-principle
exhaustion would produce.

**Revisit if:** never for the seeding fix — recording only generated candidates is simply correct,
not a tuned threshold that could need re-deriving. Revisit the two new guards only if a fourth
record kind gains its own slug-minting call site and its own author does not know to copy them —
at which point folding the guard into `unique_slug_for_identifier` itself (raising, or returning a
tri-state) is worth reconsidering; not done here because that would change the contract for
`SchemeResolver`'s own, already-correct call site too, which this task's scope does not require.

**ADR:** none — a set seeded with the wrong initial value, abandoning collisions that were resolvable. Reproduced and fixed.

## D71 — T061 (fix cycle 7): the round-6 mediums and lows — a predominance vote already closed by
D69, two refusal messages made true, and a hanging test made fail-fast

**SEC-602** (round 6, medium): an empty or whitespace-only literal could never itself win a name
slot after D65, but still counted toward its published tag's predominance in
`preferred_label_tag_counts`, built entirely from `SkosGraph.label_languages`. Already closed as a
consequence of T059's structural fix (D69) — `label_languages` is one of `is_usable_literal`'s
four call sites — rather than needing a change of its own in this task. Verified as its own
regression: reverting only the `label_languages` line and rerunning
`TestAnEmptyLiteralDoesNotVoteOnPredominance` reproduces the round-6 evidence exactly (`c1`'s
stored value flips from `"Alpha DE"` to `"Alpha AT"`), confirming the fix is doing the work and
not merely coincidentally passing.

**SEC-603/CORR-603** (round 6, medium and low, one message): `FatalReason.VOCABULARY_NAME_UNPUBLISHED`'s
template said "no skos:prefLabel was published for it at all," true when T058 (D68) minted it for
a scheme publishing no `skos:prefLabel` whatsoever, false on a path T055 opened in the same cycle
(fix cycle 6) — a scheme publishing only a whitespace-only `skos:prefLabel` reaches this identical
fatal (T055's filter makes `name` arrive `None`, exactly as if nothing had been published), and a
triple *was* published. **Reworded** to name the actual condition rather than a fact about the
file that does not always hold: "no skos:prefLabel with a usable value was published for it in
any language." One template change closes both findings (SEC-603 diagnosed the whitespace
trigger, CORR-603 the same message from the correctness lens).

**A pre-existing test's substring assertion is overturned**, named here per this cycle's own rule
for doing so (D68's own precedent): `TestNoPublishedNameAtAllIsUnusableTheSameAsOverLong
.test_a_created_scheme_with_no_preflabel_at_all_is_fatal_not_persisted_blank` asserted `"no
skos:prefLabel was published" in message` — true of the old template, false of the reworded one
(the new template does not contain that literal substring). Updated to the new substring; the
reason and the "longer than" absence it also checks are unchanged, since the rewording did not
touch what the message must *not* say.

**CORR-604** (round 6, low): `TestUniqueSlugForIdentifierGivesUpRatherThanLoopingForever`'s
primary test asserted only the return value of a call whose own failure mode, pre-D70, was to
never return — a regression of the give-up hangs the test process rather than failing it, and CI
cannot tell that apart from a stuck runner. No `pytest-timeout` dependency is added for one test:
the call now runs in a daemon worker thread with a bounded `join(timeout=5)`, the same "fail
within seconds, not never" property using only the standard library, verified directly (a
throwaway infinite loop run the identical way reports `is_alive() is True` within the 2-second
join used to check it, rather than blocking).

**Revisit if:** never for SEC-602 (already covered by D69's own revisit condition) or for the
message reword (the same "must hold on every path that reaches it" rule already governs it, with
nothing further to reconcile). Revisit CORR-604's thread-based bound only if this suite ever needs
a *general* per-test timeout policy across many tests, at which point `pytest-timeout` earns its
place as a real dependency rather than infrastructure for one test.

**ADR:** docs/adr/0003-a-report-reason-is-an-outcome-and-its-message-must-always-be-true.md — the round that made the pattern visible: two more refusal messages found false on paths added after they were written, which is what motivated stating the rule rather than fixing each message.

## D72 — CORR-701 (review round 7, fix cycle 8): `EMPTY_SLUG`'s message names its outcome, not
a cause that is false at every one of its call sites

**CORR-701** (round 7, medium): `EMPTY_SLUG` rendered "'%(subject)s' has a preferred label made
up only of characters this application strips when deriving a URL slug, so no usable slug could
be derived from it; it was set aside." That sentence was written for FIX 5/D39, when the slug
*was* derived from the preferred label. T029/decisions.md D35 moved the derivation onto the
published identifier's own segment, and nothing revisited the message. It is now false at all
four call sites, verified by reproduction rather than by reading:

- `import_concepts`' and `import_collections`' pre-write guards (D35, D39) fire on an unusable
  *identifier segment*. The `empty_slug_label.ttl` fixture's own concept publishes
  `skos:prefLabel "Symbol"@en`, which slugifies perfectly well.
- The two give-up guards T060 added (D70) fire when `unique_slug_for_identifier` exhausts its
  collision candidates. There the identifier and the label are both fine and nothing the
  publisher wrote is at fault.

A curator reading the old message is sent to correct a preferred label that is not the problem,
and on the give-up paths there is no published value to correct at all.

**Reworded** to name the outcome, which is the one thing true on every path that reaches this
reason: "'%(subject)s' could not be given a usable URL slug, so it was set aside." The enum's
own short label moves the same way, from "preferred label produces no usable slug" to "no usable
URL slug could be derived". This is the reviewer's own preferred remedy (a) over minting a
separate `SLUG_COLLISION_UNRESOLVED` reason: the two causes have the same remedy for a curator
(none — the record has no address and was set aside), so telling them apart in the closed
vocabulary would add a member that no caller would ever branch on differently.

**No pre-existing test asserted the old wording.** Every existing test matches on
`entry.reason is SetAsideReason.EMPTY_SLUG`, so unlike D71's reword nothing needed updating —
checked before editing, not assumed. Two new tests pin the property that failed: one on the
identifier-segment path via the existing fixture, one on the give-up path with
`ConceptImporter.assign_unique_slug` stubbed to leave the slug empty. Both were proven red
against the old template before the change.

**Revisit if:** a caller ever needs to branch on *why* a slug could not be minted — at that
point the distinction belongs in the closed vocabulary as its own reason, not in the message
text. The "a message must hold on every path that reaches it" rule from D71 governs unchanged.

**ADR:** none — a message-wording correction inside an existing closed vocabulary. It changes no
structure and binds no future choice: the rule it applies ("a reason's message must be true on
every path that reaches it") is D71's, already recorded, and this is its second application
rather than a new position.
