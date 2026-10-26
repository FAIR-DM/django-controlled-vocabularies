# Research — FS-016 Narrow a field's choices to part of a vocabulary

Phase 0. Every finding is read from the installed dependency or this repo's own source, with the
file and line named, because three of the seven decide the design and one of them contradicts what
the existing code appears to assume.

## R1 — Every enforcement path already converges on `get_limit_choices_to()`

**Question:** the restriction has to bite in three places — model validation, the choices a form
offers, and the search endpoint the control calls. How many seams is that?

**Finding: one.** All three read the same method.

| Path | Where | Call |
|---|---|---|
| Model validation, single-value | `django/db/models/fields/related.py:176` (5.2.16) | `qs.complex_filter(self.get_limit_choices_to())` |
| Form choices | `django/forms/models.py:128` | `limit_choices_to = formfield.get_limit_choices_to()` |
| Widget queryset | `controlled_vocabularies/forms.py:85` | `Concept.objects.complex_filter(self.model_field.get_limit_choices_to())` |
| Search endpoint | `controlled_vocabularies/views.py:116` | `queryset.complex_filter(field.get_limit_choices_to())` |

**Consequence:** the whole feature can be delivered by changing what `limit_choices_to` holds.
Nothing in `validate()`, the widgets, or the endpoint needs to learn about collections, concept
lists or hierarchies. This is the single most important finding in this document, and it is why
the plan below touches four files rather than a dozen.

## R2 — `limit_choices_to` may be a callable, and Django resolves it at every one of those points

**Question:** the branch restriction cannot be a static `Q` — a transitive closure over stored
edges has to be computed. Does that force a different mechanism for one of the three axes?

**Finding: no.** `RelatedField.get_limit_choices_to()`
(`django/db/models/fields/related.py:456-465`) invokes `limit_choices_to` when it is callable and
returns the result. Every path in R1 goes through that method, so a callable returning a `Q` is
resolved at validation time, at form-build time, at widget-render time and at search time alike,
and never while the declaration is merely being read.

**Consequence:** all three restrictions take the same shape — a callable that returns a `Q` — so
there is one mechanism, not two, and FR-007's "no query while the declaration is read" is satisfied
by construction rather than by care.

**Caveat carried into the plan:** `RelatedField.deconstruct()` emits `limit_choices_to` whenever it
is truthy, and a function is always truthy. `ConceptFieldMixin.deconstruct()`
(`fields.py:165-170`) already pops it unconditionally, so this is handled — but only because the
pop is unconditional today, which is worth a test rather than an assumption.

## R3 — The `Q` must be a subquery, not a join, and the reason is in this package rather than Django

**Question:** a collection restriction is naturally `Q(collection_memberships__collection__slug=…)`.
A reverse-FK join multiplies rows. Is that a problem?

**Finding: yes, and only on this package's own paths.** Django's
`apply_limit_choices_to_to_formfield` (`django/forms/models.py:133-137`) deliberately wraps the
filter in `Exists()` with the comment *"Use Exists() to avoid potential duplicates"*. But the two
paths this package added — `forms.py:85` and `views.py:116` — call `complex_filter()` **bare**, with
no such wrapper. A join-shaped `Q` would therefore be duplicate-free in a plain `ModelForm` and
duplicated in this package's own widget and its own search endpoint. That is the worst available
outcome: correct where it is tested by Django's machinery, wrong where it is tested by ours.

**Decision:** every restriction resolves to a membership test against a subquery —
`Q(pk__in=<queryset of concept ids>)` — which produces no join on `Concept` and therefore no
duplicates on any of the four paths. It also makes the three axes structurally identical, differing
only in how the inner queryset is built.

Rewriting `forms.py`/`views.py` to use `Exists()` instead was considered and rejected: it changes
two working code paths shared with the existing vocabulary restriction to fix a problem the
subquery form does not have, and Article II prefers not creating the problem.

## R4 — The many-valued field does **not** go through `limit_choices_to` for enforcement

**Question:** does the single seam in R1 cover `MultiConceptField`?

**Finding: for choices yes, for enforcement no.** Form choices go through
`apply_limit_choices_to_to_formfield` like any relation. But the *write* guarantee is a separate
mechanism: `_refuse_concepts_outside_vocabulary` (`fields.py:376-422`), an `m2m_changed` receiver
bound at `contribute_to_class` (`fields.py:607-612`), which tests membership directly:

- forward write — `model.objects.filter(pk__in=pk_set).exclude(scheme__slug__in=vocabulary)`
- reverse write — `instance.scheme.slug in vocabulary`

Both hard-code the vocabulary test. Neither consults `limit_choices_to`.

**Consequence:** this receiver is the one place the feature cannot avoid touching, and the reverse
branch is the subtle half — on a reverse write `pk_set` holds the *owner* model's keys and the
concept is `instance` (recorded as D16 in FS-010). The plan re-expresses both branches against the
resolved restriction rather than against `vocabulary`, so the two halves cannot drift apart the way
`ConceptField` and `MultiConceptField` themselves once did (#111).

**Second consequence, easy to miss:** the receiver is connected only `if self.vocabulary`
(`fields.py:607`), deliberately, so that a field with nothing to enforce does not keep Django's
`bulk_create` fast path disabled for no gain (recorded as R6 in FS-010). A restriction always
implies exactly one vocabulary (FR-005), so that condition stays true whenever a restriction
exists, and the existing guard needs no change.

## R5 — Transitive closure: recursive CTE, with an iterative fallback

**Question:** how is "this concept and everything below it" computed, and what does it cost?

**Finding.** The hierarchy is stored one direction only: `ConceptRelation` rows with
`kind=BROADER`, `source` = the narrower concept, `target` = the broader one
(`models.py:1161-1174`). `narrower` is a reverse read, not a stored edge. So the closure is a
downward walk over `ConceptRelation.objects.filter(kind=BROADER, target__in=<frontier>)`.

Both supported backends can express this in one statement. SQLite has supported `WITH RECURSIVE`
since 3.8.3 (2014) and PostgreSQL since 8.4. Django has no ORM construct for it, so it is either
raw SQL inside a subquery or an iterative widening in Python — one query per level, terminating
when a level adds nothing new.

**Decision: iterative widening, not raw SQL, for this feature.** Article II and Article X both
point the same way. The iterative form is roughly ten lines, is backend-agnostic, needs no raw SQL
in a package that has none today, and terminates naturally on a cyclic graph because a level that
adds no new concepts ends the loop — which is exactly what FR-004 requires, obtained from the
algorithm rather than bolted on. Its cost is one query per level of depth, and SKOS hierarchies are
wide rather than deep. Raw recursive SQL is the right optimisation when someone measures a problem;
the maintainer deferred that measurement to R7 explicitly, and Article II forbids taking it now on
speculation.

**Recorded for R7:** if this needs to become one query, the change is confined to the function that
builds the branch's inner queryset, because R3's subquery shape means nothing downstream knows how
the id set was produced.

## R6 — An ordered collection's sequence cannot travel through `limit_choices_to`

**Question:** US-6 wants the curator's order to reach the offered choices. `limit_choices_to` is a
filter. Can it carry an ordering?

**Finding: no, and this is the one requirement the single seam does not serve.** `complex_filter()`
applies a `Q`; it cannot impose an `order_by`. The ordering has to be applied where a queryset is
built, and R1 lists three such places, of which two belong to this package:

- `forms.py:85`, `ConceptWidgetValidationMixin.get_queryset()` — **not** the browsable list.
  Verified against the resolved `django_tomselect` 2026.6.2:
  `templates/django_tomselect/render/select.html` emits a bare `<select></select>` with no option
  loop, and `tomselect.html:360-377` seeds the client only from `widget.selected_options`. This
  queryset therefore feeds validation (`django_tomselect/forms.py:209-215`) and the render of a
  value the record already holds (`widgets.py:965`). Ordering it changes nothing a person sees.
- `views.py`, `ConceptAutocompleteView` — **this is the browsable list.** Every option a person
  scrolls arrives over the autocomplete URL, ordered `("label", "pk")` (`views.py:40`) and
  paginated at 20 (`views.py:39`).
- Django's own `apply_limit_choices_to_to_formfield` — not ours to change.

**Decision: apply the ordering in the autocomplete view, and only while the search box is empty.**
The library gives a seam for exactly this — `AutocompleteModelView.apply_ordering()`
(`autocompletes.py:686-727`) is a single method reading `self.ordering`, and the declaration is
already resolved on that request by `_restrict_to_declaration()`. So the change is one override,
not a rework of search. Restricting it to the empty-query case settles the tension the earlier
reading missed: browsing a small ordered collection wants the curator's sequence, and a typed query
wants match quality. Both are served, neither is guessed at.

The ordering key comes from `CollectionMember.position`, obtained as a `Subquery` annotation keyed
on the declaration's own collection — never through a `collection_memberships__` lookup, which
joins and duplicates rows for a concept belonging to more than one collection (see R3).

This is the concrete form of the maintainer's "if it's not too complicated": one method, one
annotation, one condition.

**Consequence for sequencing:** US-6 depends on US-1 only. The plumbing that makes the declaration
reachable from the endpoint — the `field=` autocomplete parameter and `_restrict_to_declaration()`
— already ships on `main`, so nothing in this feature has to build it. US-6 stays droppable:
dropping it leaves the inherited `("label", "pk")` ordering untouched.

## R7 — The declaration rules have an existing precedent to copy exactly

**Question:** where do FR-005 and FR-006 raise, and as what?

**Finding.** `ConceptField.__init__` raises `TypeError` for `on_delete`
(`fields.py:225-226`), `MultiConceptField.__init__` raises `TypeError` for `through`
(`fields.py:538-542`), and `_apply_vocabulary` raises `TypeError` for `limit_choices_to`
(`fields.py:97-101`). `_normalise_vocabulary` raises `TypeError` for a non-string or empty slug
(`fields.py:83-85`).

**Decision:** both new rules raise `TypeError` from the same place, in the same style, with the
class name interpolated the same way. These are developer-facing diagnostics, so Article XII's
translation requirement does not reach them — the article exempts developer-facing diagnostics
explicitly, and every existing refusal in this file is an untranslated `TypeError`. The messages a
*curator* sees when validation refuses a concept are a different matter and are translated, exactly
as the existing `default_error_messages` are.

## R8 — The system check extends rather than multiplies

**Question:** FR-009 adds three kinds of absent target. New check functions, or one?

**Finding.** `check_concept_field_vocabularies` (`checks.py:36-81`) already walks every installed
model's fields once, collects the distinct slugs, and resolves them in **one** query, then emits one
warning per (field, absent slug) pair under `controlled_vocabularies.W001`.

**Decision:** one additional check function, registered alongside, emitting a **new** id
(`controlled_vocabularies.W005`) rather than reusing W001. A project silences by id, and a project
that has deliberately silenced "vocabulary not imported yet" has not thereby said anything about a
mistyped collection slug. Reusing the id would fold two independent decisions into one switch. The
existing `DatabaseError` guard and its reasoning are reproduced, because the trigger — `migrate`
running the checks before the tables exist — is identical.

Three target kinds, resolved in three queries rather than one per field: collections by
`(scheme__slug, slug)`, concepts by `(scheme__slug, slug)`, branch roots by the same. Batching
across fields is the existing function's own pattern and costs nothing to keep.
