# Tasks: Narrow a field's choices to part of a vocabulary

**Feature**: `016-narrow-field-choices` · **Spec**: [`spec.md`](./spec.md) · **Plan**: [`plan.md`](./plan.md) · **Research**: [`research.md`](./research.md)

Every task is test-first per Article I: the test is written and seen to fail before the production
change that makes it pass. Test scope per task is one class or one file; the full suite runs once per
story, at the story's report.

`[P]` marks tasks that could run in parallel with their siblings.

**Nothing in this feature adds a model, a field or a migration to this package.** A task that finds
itself editing `controlled_vocabularies/models.py` has gone wrong — the restrictions read the
existing `Collection`, `CollectionMember` and `ConceptRelation` and write none of them.

**No enforcement code learns what a collection is.** Research R1 established that model validation,
form choices, this package's widget and this package's search endpoint all read
`get_limit_choices_to()`. A task that adds a collection or hierarchy test to `views.py`, or to
`ForeignKey.validate()`'s override, has gone around the design instead of using it. The two
deliberate exceptions are the many-valued write guard (T012, research R4) and the ordered-collection
sequence (T022, research R6), and both are named as such. Note what the second exception means: the
ordered sequence *is* a change to `views.py`, because that endpoint serves the browsable list.

**Every restriction is `Q(pk__in=…)` or a plain column filter, never a join.** Research R3: this
package's own two paths call `complex_filter()` bare where Django wraps it in `Exists()`, so a
join-shaped `Q` duplicates rows in exactly the places our own tests cover.

---

## Foundational — no story is dispatched until every task here is green

This phase is US-4 (issue #168): what a declaration accepts and refuses. Nothing resolves until it
exists, and every later story adds an axis behind arguments defined here.

### T001 — Both fields accept the three arguments and refuse a malformed slug

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

`ConceptFieldMixin` gains `collection`, `concepts` and `branch`, each defaulting to `None`, threaded
through both `__init__` signatures the way `vocabulary` already is. Normalisation follows
`_normalise_vocabulary`'s existing rules exactly (`fields.py:60-86`): each slug must be a non-empty
string or it is a `TypeError` naming the class, and `concepts` collapses duplicates with
`dict.fromkeys` and stores a tuple.

An empty `concepts` list is refused (FR-003, decisions D4) — same `TypeError`, same reasoning as an
empty vocabulary slug: it reads as a restriction and offers nothing.

Store the normalised values on the instance. Nothing resolves yet; a field declared with a
restriction still behaves exactly as one declared without.

**Test scope**: one class in `tests/test_fields.py` per testing standard §4, covering both field classes.

### T002 — A restriction needs exactly one vocabulary

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

FR-005. Any restriction present while `len(self.vocabulary) != 1` raises `TypeError` naming the
class and stating the rule. Checked after `_normalise_vocabulary` has run, so "several" and "none"
are one condition rather than two branches.

Raised from `_apply_vocabulary`'s neighbourhood, beside the existing `limit_choices_to` refusal
(`fields.py:97-101`), so every declaration rule is in one place.

`TypeError` and untranslated, matching every existing refusal in this file (research R7). Article XII
exempts developer-facing diagnostics; the curator-facing refusals in T011/T013 are translated.

### T003 — At most one restriction

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

FR-006, decisions D1. Two or more of the three present raises `TypeError` stating the rule. Cover
each pair and the triple.

Do **not** implement an intersection or a union for any combination. The refusal is the specified
behaviour, not a placeholder.

### T004 — The restriction survives `deconstruct()` and rebuilds

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

FR-011, plan A7. `ConceptFieldMixin.deconstruct()` emits each of the three only when set, so a
declaration using none produces byte-identical output to today (FR-014) — assert that explicitly, as
its own case.

`Field.clone()` rebuilds from the emitted kwargs on every `makemigrations`, `migrate` and
test-database build, so a kwarg `__init__` refuses is a hard failure everywhere at once. Assert the
round-trip directly: deconstruct a restricted field of each kind, rebuild from the result, and
confirm the restriction survives.

The unconditional `kwargs.pop("limit_choices_to", None)` at `fields.py:168` is what keeps the
callable T005 installs out of migration output. Assert that a restricted field's deconstructed
kwargs carry no `limit_choices_to`, so a later change to that pop fails here rather than in a
generated migration.

### T005 — `limit_choices_to` becomes a callable, with today's behaviour

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

The seam, installed with no restriction behind it yet. `_apply_vocabulary` sets `limit_choices_to`
to a **callable** returning the vocabulary `Q` it currently sets directly (research R2:
`RelatedField.get_limit_choices_to()` invokes a callable at every path in R1).

This task changes no observable behaviour and every existing field test must still pass unmodified —
that is the point of doing it alone. What it must additionally prove:

- calling `get_limit_choices_to()` returns the same `Q` the attribute held before;
- constructing a field and reading its declaration issues **no query** (FR-007) — assert with
  `django_assert_num_queries(0)`, per testing standard §4;
- a declaration naming no vocabulary still sets no restriction at all, rather than a callable
  returning an empty `Q` that matches everything.

---

## US-1 — A field is restricted to a collection's members (P1, issue #165)

### T006 — The collection restriction resolves to a subquery

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

FR-002, plan A2. The callable from T005 returns, when `collection` is set:

`Q(scheme__slug=<the one vocabulary>) & Q(pk__in=CollectionMember.objects.filter(collection__slug=…, collection__scheme__slug=…).values("concept"))`

Both halves matter. The vocabulary term is never dropped, so a collection slug that happens to exist
in another vocabulary cannot widen the field. The membership term is a subquery, never a
`collection_memberships__…` join (research R3).

Assert the resolved `Q` selects exactly the members and nothing else, including for a second
collection of the same name in a different vocabulary.

### T007 — A member validates, a non-member does not

**Files**: `tests/test_fields.py`

FR-008 for the single-value field. Through a real consuming model, not a `Q` inspection: assign a
member and validate; assign a non-member of the same vocabulary and confirm `ValidationError`.

`ForeignKey.validate()` reaches this through `get_limit_choices_to()` (research R1) with no override
needed. If this task finds itself editing `ConceptField.validate()`, the seam is not being used.

### T008 — The refusal names the collection

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

`ConceptField.validate()`'s existing re-raise (`fields.py:230-270`) currently chooses between
`invalid` and `invalid_unrestricted` and interpolates `vocabulary`. Add the restricted case: a
message naming what the field is restricted to.

Article XII, following the existing pattern exactly (`fields.py:210-220`): one static msgid, the
restriction joined into a **single** named placeholder, so the identifier does not change with the
restriction's contents. A consumer's own `error_messages` override must still work, and the
`ForeignKey`'s own `params` must still be carried through — the comment at `fields.py:260-263`
explains why dropping them reproduces the `KeyError` that override exists to prevent.

### T009 — The offered choices are exactly the members

**Files**: `tests/test_forms.py`

FR-008's choices half. Build a `ModelForm` from a consuming model and assert the field's queryset is
exactly the collection's members.

Assert **no duplicate rows** explicitly — count as well as membership. That is the assertion research
R3 exists for, and it is the one that fails if a later change makes the `Q` a join.

Cover both the plain `ModelForm` path (Django's `Exists()` wrapper) and this package's widget
`get_queryset()` (bare `complex_filter`), because only the second is ours and only the second is
unprotected.

### T010 — Membership changes reach the field without a restart

**Files**: `tests/test_fields.py`

FR-002's "resolved live". Read the choices, add a concept to the collection, read again, confirm the
new member appears. No cache to invalidate — this passes because T005 made the attribute a callable,
and this test is what stops someone "optimising" it into a value later.

### T011 — Migrations are unaffected

**Files**: `tests/test_fields.py`

`makemigrations` on the test app produces a migration for a restricted declaration and
`makemigrations --check` is then clean. Run `makemigrations --check` across **all** apps, never
scoped to one.

### T012 — The many-valued write guard reads the restriction

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

Research R4, plan A4 — the one enforcement path that does not read `limit_choices_to`.
`_refuse_concepts_outside_vocabulary` (`fields.py:376-422`) currently hard-codes the vocabulary test
in both branches. Re-express both against the resolved restriction:

- **forward**: the incoming concepts are `pk_set`; refuse any the restriction does not admit.
- **reverse**: the incoming concept is `instance`, and `pk_set` holds the *owner's* keys — the
  distinction FS-010 recorded as D16. Refuse on the same test.

Bind the receiver with the field rather than with `vocabulary`, so one resolution serves both
branches and they cannot drift apart the way the two field classes once did (#111).

Rename the function to match what it now tests — it no longer tests membership of a vocabulary, it
tests admission by the resolved restriction, of which the vocabulary-only case is one. Leaving an
inaccurate name is how the next reader learns the wrong thing about the guard.

**Leave the `if self.vocabulary` binding guard at `fields.py:607` alone.** A restriction implies
exactly one vocabulary (T002), so it is already true whenever a restriction exists, and changing it
would disable Django's `bulk_create` fast path for unrestricted fields — FS-010's R6.

Cover: forward write refused whole with the record's existing set untouched; reverse write refused;
a mixed `set()` refused whole (it is `remove()` then `add()`); and every existing vocabulary-only
test still passing unmodified.

---

## US-2 — A field is restricted to a named list of concepts (P1, issue #166)

### T013 — The concepts restriction resolves, validates and refuses

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

FR-003. The one axis needing no subquery: `Q(scheme__slug=…) & Q(slug__in=<the tuple>)`. No join, no
`pk__in`, nothing that can duplicate.

Listed concepts validate; an unlisted concept of the same vocabulary is refused with a message
naming the permitted concepts, following T008's placeholder rule. Duplicates were already collapsed
by T001 — assert here that the field offers the concept once.

Covers both fields: single-value validation and the many-valued guard from T012, which needs no
further change if T012 was written against the resolved restriction rather than against a
collection.

### T014 — [P] The offered choices are exactly the listed concepts

**Files**: `tests/test_forms.py`

As T009, for this axis. Both the `ModelForm` path and the widget path.

---

## US-3 — A field is restricted to a branch of the hierarchy (P1, issue #167)

### T015 — The downward closure

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

Plan A3, research R5. One function, iterative widening over the stored edges:

1. the named root's id, resolved within the declaration's vocabulary;
2. repeatedly `ConceptRelation.objects.filter(kind=BROADER, target_id__in=<frontier>)`, taking
   `source_id` as the next frontier, minus everything already seen;
3. stop when a round adds nothing new.

The direction is not obvious and is easy to invert: a `BROADER` row has `source` = the **narrower**
concept and `target` = the broader one (`models.py:1161-1174`), and `narrower` is a reverse read
rather than a stored edge. Walking downward means matching on `target` and collecting `source`.

**No raw SQL, no `WITH RECURSIVE`.** Both backends support it and neither is used here — Article II
and the spec's Assumptions both defer that to R7, and this function is deliberately the only thing
that would have to change then.

Unit-test the closure directly: a three-level tree, a root with no children, a wide level, and a
root whose vocabulary does not hold it.

### T016 — Cycles terminate

**Files**: `tests/test_fields.py`

FR-004, SC-006, decisions D5. Build a two-edge cycle with two ordinary calls —
`a.add_broader(b)` then `b.add_broader(a)` — and assert the closure returns each concept once and
returns at all.

Both calls validate and both save. The relation model refuses a self-relation
(`concept_relation_not_self`) and a mirror-order *related* duplicate (via `_canonicalise`), and the
comment at `models.py:1209-1211` says outright that a reversed broader edge is a different,
permitted edge. Nothing walks the graph, so a cycle is storable through the public API. **Do not
weaken the relation model to make this test constructible** — Article I forbids modifying
pre-existing behaviour without an approved decision, and D5 already says closing that gap is a
separate question.

Bound the test so a regression fails fast rather than hanging the suite.

### T017 — Inclusive of the root, downward only

**Files**: `tests/test_fields.py`

FR-004, decisions D3. Through a real consuming model: the root itself validates, a grandchild
validates, a sibling branch is refused, and the concept the root sits *below* is refused. The last
two are the ones an inverted walk (T015) passes anyway, so neither is optional.

### T018 — [P] Resolution, choices and live updates for the branch axis

**Files**: `controlled_vocabularies/fields.py`, `tests/test_forms.py`, `tests/test_fields.py`

The branch's `Q` is `Q(scheme__slug=…) & Q(pk__in=<closure>)`. Offered choices are exactly the
closure, with no duplicates, on both the `ModelForm` and the widget path. A concept added below the
root appears on the next read, as T010 asserts for membership.

---

## US-5 — A restriction naming something absent is reported, not silent (P2, issue #169)

### T019 — W005 reports an absent target

**Files**: `controlled_vocabularies/checks.py`, `controlled_vocabularies/apps.py`, `tests/test_checks.py`

FR-009, plan A6, research R8. A new function beside `check_concept_field_vocabularies`, registered
in `apps.ready()` alongside the existing four, emitting `controlled_vocabularies.W005`.

**A new id, not W001.** A project silences by id, and having silenced "this vocabulary is not
imported yet" says nothing about a mistyped collection slug.

Walk every installed model's fields once and batch the lookups by target kind — three queries, not
one per field. Warn per (field, absent target), naming the specific target: the one missing member
of a ten-item `concepts` list, never the list.

**Resolve on the (vocabulary slug, target slug) pair, not on a flat set of slugs.** The existing
function matches `slug__in={…}` because a vocabulary slug is globally unique. A collection or
concept slug is unique only *within* its vocabulary — `unique_collection_slug_per_scheme`, and the
same for concepts — so a flat set cannot tell "absent from the named vocabulary" from "present in
some other one", which is exactly the state FR-009 exists to surface. Build the resolved set with
`values_list("scheme__slug", "slug")` and test each declared target against the pairs.

### T020 — [P] The check stays quiet when it should

**Files**: `tests/test_checks.py`

FR-009's three silences, each its own case:

- a database whose tables do not exist — reproduce the existing `DatabaseError` guard
  (`checks.py:65-68`) and its reasoning: `migrate` runs the checks first, so this is a fresh
  install's normal state, not an error;
- a collection that exists and holds no members — present and empty is not missing;
- a project silencing W005 by id.

And one case it must *not* stay quiet for: a target whose slug exists in a different vocabulary is
still reported absent from the one the field names.

### T021 — [P] Nothing about an absent target stops the project

**Files**: `tests/test_checks.py`

FR-007 end to end for this feature: with every named target absent, importing the models,
`makemigrations` and `migrate` all succeed. This is the assertion that would catch someone
"helpfully" turning the check into an `Error` or resolving a target at declaration time.

---

## US-6 — An ordered collection's sequence reaches the choices (P2, issue #170)

*Droppable. One method override; no other story depends on it. If it turns out to require reworking
the selection control, stop and record why in `decisions.md` rather than pressing on.*

### T022 — The endpoint serves an ordered collection's members in order

**Files**: `controlled_vocabularies/views.py`, `tests/test_views.py`

FR-010, plan A5, research R6. Override `apply_ordering()` on `ConceptAutocompleteView`. It applies
the collection's member order when — and only when — both hold: the restriction is a collection
whose `ordered` flag is set, and the request carries no search term. Everything else falls through
to `super()` and the inherited `("label", "pk")`.

**Not the widget.** `ConceptWidgetValidationMixin.get_queryset()` feeds validation and the render of
an already-attached value; the browsable list is served entirely by this endpoint. Ordering the
widget queryset changes nothing a person sees (research R6). `forms.py` is not touched by this task.

**Order on a `Subquery` annotation, never on a `collection_memberships__` lookup.** A concept may
belong to several collections, and that lookup joins `CollectionMember` onto a queryset reaching
`complex_filter()` bare — duplicate rows, silently. Annotate the position from `CollectionMember`
filtered by `concept=OuterRef("pk")` and the declaration's own collection and vocabulary slugs, and
order on the annotation.

Cover: an ordered collection whose sequence differs from both alphabetical and creation order; a
position change reflected on the next read; a typed search term returning to relevance order; an
unordered collection still restricted with no sequence promised; a removed member leaving the
survivors in relative order; **no duplicate rows, asserted by count**, for a concept that also
belongs to a second collection.

---

## US-7 — Translatable messages, documentation, and vocabulary (P3, issue #171)

### T023 — `help_text` describes a restricted field

**Files**: `controlled_vocabularies/fields.py`, `tests/test_fields.py`

Both fields' `default_help_text` (`fields.py:222`, `fields.py:535`) currently say the field takes
"a concept from this field's configured vocabulary or vocabularies", which is wrong for a restricted
field.

A restricted field with no `help_text` of its own gets a default describing a field restricted
within its vocabulary. Static messages, never one interpolating the restriction — the annotation at
`fields.py:52-58` explains why: `%` on a `gettext_lazy()` proxy evaluates it immediately, defeating
the laziness the default exists to keep.

### T024 — [P] Every added message is translatable

**Files**: `tests/test_fields.py`

Article XII. Every curator-facing string this feature adds is wrapped with named placeholders and
static msgids. The developer-facing `TypeError`s from T002 and T003 are exempt and stay
untranslated, matching every existing refusal in the file (research R7) — assert that deliberately,
so a later "consistency" pass does not translate them.

### T025 — [P] README, CONTEXT.md, CHANGELOG

**Files**: `README.md`, `CONTEXT.md`, `CHANGELOG.md`

FR-013. The README shows each of the three restrictions with a real declaration, says when to reach
for which, states that they need exactly one vocabulary and exclude one another, and says what
happens when a named target is absent.

Under the branch restriction, one sentence on what it costs: the descendant set is recomputed on
every search request rather than cached, so a deep branch on a public form is a knowing choice
(decisions D9).

Under the collection restriction, say what an `ordered` collection buys — the curator's sequence
while the search box is empty, relevance order once someone types (decisions D8). Do not promise a
sequence anywhere else.

`CONTEXT.md` defines the restriction and reconciles the existing `ConceptField`/`ConceptsField`
entries (lines 49-50), which currently describe the vocabulary restriction as the whole story.

Public markdown: humanize before commit, and no internal handles.

---

## Verification, once per story

`poetry run pytest` full suite · `ruff` via pre-commit, not bare · `mypy` · `deptry` ·
`makemigrations --check` across all apps.

Coverage floors: project ≥ 90%, patch ≥ 85%.

**Migrations.** No migration to `controlled_vocabularies/migrations/` is expected at any point — one
appearing means a task edited this package's `models.py`. The **test app** is the opposite case: every
restriction is a declaration argument, so each axis needs a consuming model in
`tests/testapp/models.py`, and a migration for it is required, not a defect. `tests/testapp` already
holds one per prior feature. Consolidate this feature's into a single file before the PR, per
Article XIII, and run `makemigrations --check` across all apps afterwards.
