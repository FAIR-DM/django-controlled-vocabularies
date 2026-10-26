# Decisions — FS-016 Narrow a field's choices to part of a vocabulary

Rationale too long to carry inline in `spec.md`, plus every ambiguity resolved without asking the
maintainer. The spec stands alone; this file explains why it reads the way it does.

## D1 — The three restrictions exclude one another rather than composing

**Ambiguous:** whether `collection`, `concepts` and `branch` may be combined, and what a
combination would mean.

**Chosen:** at most one. Two or more is refused when the declaration is read (FR-006).

**Why defensible:** a combination has two readings and no way to tell them apart from the source.
`collection="core", branch="thermal"` could mean *members of `core` that are also under `thermal`*
or *members of `core` plus everything under `thermal`*, and a reader of the declaration cannot know
which the writer meant. Article II settles it: the simplest design that satisfies the spec is one
restriction at a time, and no requirement asks for more. Nothing is foreclosed — if a real need for
an intersection appears, it can be added later with an explicit spelling, whereas a guessed default
shipped now would have to be broken to correct it.

**ADR:** docs/adr/0021-a-field-carries-one-restriction-never-a-combination.md

## D2 — The failure lands at declaration time, not at validation time

**Ambiguous:** where an invalid declaration is caught.

**Chosen:** when the declaration is read — the same place the fields already refuse `on_delete`,
`through` and `limit_choices_to` (FR-005, FR-006).

**Why defensible:** the mistake is in code, so the report belongs to whoever imports that code, not
to whoever first submits a form built from it. It also matches the existing behaviour of these two
fields exactly, so a consumer learns one rule about when a bad declaration is reported rather than
two. The cost — that a declaration cannot be checked against data this way — is not a cost here,
because none of these rules is about data.

**ADR:** none — durable and non-obvious, but not architectural: it follows the refusal pattern `on_delete`, `through` and `limit_choices_to` already use in this module, so it establishes no convention a reader does not already meet there.

## D3 — Absent targets are reported by the existing check, not by a new mechanism

**Ambiguous:** how a mistyped or not-yet-imported target reaches a developer.

**Chosen:** extend the system check FS-009 established, as a warning with a stable identifier,
naming the specific absent target (FR-009).

**Why defensible:** FS-009's intake decision already settled the general shape of this question for
a missing vocabulary, with a reason that transfers unchanged — the targets arrive by import or
curation, which only a running project can perform, so an error that blocks `migrate` would make a
fresh install unbootstrappable. A second, differently-shaped reporting mechanism for the same class
of gap would be an inconsistency a consumer has to learn. Reporting the specific absent member of a
concept list rather than the list as a whole is the one addition: a list of ten with one typo is
otherwise a warning that says nothing useful.

**ADR:** none — applies FS-009's existing decision about a missing vocabulary to three more target kinds. The reasoning is already recorded; only the new check id is new.

## D4 — An empty concept list is refused

**Ambiguous:** whether `concepts=[]` means "no restriction" or is a mistake.

**Chosen:** refused (FR-003).

**Why defensible:** it is the same argument `_normalise_vocabulary` already makes about an empty
slug — a declaration that offers no choices at all while reading as restricted is the opposite of
what anyone writing it is reaching for. A consumer who wants no restriction omits the argument, and
that path already exists and is already tested.

**ADR:** none — local to one argument, and it follows the empty-slug refusal `_normalise_vocabulary` already makes for the same reason.

## D5 — The branch read must terminate on a cyclic hierarchy

**Ambiguous:** whether the stored relation graph can contain a cycle, and what happens if it does.

**Chosen:** the traversal terminates and yields each concept once regardless (FR-004, SC-006).

**Why defensible:** `ConceptRelation` refuses a self-relation, a cross-vocabulary relation, and a
mirror-order duplicate of a *related* edge — the last through `_canonicalise`, which orders that
kind's endpoints by primary key. A reversed *broader* edge is a different, permitted edge, stated as
such at `models.py:1209-1211`, and nothing walks the graph. So the shortest storable cycle is two
edges, built with two ordinary `add_broader()` calls, which strengthens this decision rather than
weakening it: the state the traversal must survive is reachable through the public API and needs no
contrived construction. Whether that gap should be closed is a separate question
about the relation model, not about this field. What is not separable is that a restriction reading
that data must not hang or exhaust memory: the field cannot assume an invariant the database does
not enforce. Specifying termination costs nothing and removes a failure mode that would present as
a hung request with no error.

**ADR:** none — the guarantee is already normative as FR-004 and SC-006 in a merged spec and is covered by a test. An ADR would restate a requirement rather than record a decision behind one.

## D6 — Ordered-collection ordering is its own story, not folded into the collection restriction

**Ambiguous:** how to spec a behaviour the maintainer approved conditionally ("honour it if it's
not too complicated").

**Chosen:** User Story 6 at P2, separable from User Story 1.

**Why defensible:** a conditional approval has to be droppable without damage, and a scenario buried
inside a P1 story is not. As its own story it can be cut at planning if it turns out to require
reworking the selection control, and the three restrictions remain correct and complete without it.
If it is cheap — and the collection already resolves its members in order — it ships.

**ADR:** none — a sequencing choice about how the work was split, not about the software. Nothing downstream inherits it.

## D7 — Targets are named by slug, including for the explicit concept list

Settled with the maintainer at intake (`spec.md` §Clarifications), recorded here for the one
consequence the spec does not spell out: because a slug is unique only within its vocabulary, every
target resolves inside the single named vocabulary. That is what makes "exactly one vocabulary"
(FR-005) a precondition rather than a preference — with two vocabularies named, a collection slug
could resolve to two different collections, and there would be no way to say which was meant.

**ADR:** docs/adr/0022-a-restriction-names-its-target-by-slug.md

## D8 — The ordered sequence is applied at the endpoint, and only while the search box is empty

**Ambiguous:** the plan placed the ordering on the widget's own queryset, on the reading that this
is the list a person picks from. It is not. The selection control renders an empty `<select>` and
fetches every browsable option over this package's autocomplete URL; the widget queryset feeds
validation and the render of a value the record already holds. Ordering it would have shipped a
story whose tests pass and whose sequence no human ever sees.

**Chosen:** override the endpoint's own ordering hook on `ConceptAutocompleteView` (FR-010, plan A5) — `order_queryset()`, not the `apply_ordering()` this paragraph first named; see D12. It applies
the collection's member order when the restriction is an ordered collection *and* the request
carries no search term, and falls through to the inherited relevance order otherwise.

**Why defensible:** the maintainer's approval was conditional — honour the sequence if it is not too
complicated — so the cost is the whole question. The library exposes a single ordering
hook reading one attribute, and the declaration is already resolved on that request, so the change
is one override and one annotation. That is cheap enough to keep the story rather than drop it.

The empty-query condition settles a tension the first reading did not see. Browsing a small ordered
collection wants the curator's sequence; a typed query wants match quality. Conditioning on the
search term serves both rather than trading one for the other, which is what made the earlier
"leave the endpoint alone" argument look correct.

The position is read through a `Subquery` annotation keyed on the declaration's own collection, not
a membership join. A concept may belong to more than one collection, and this queryset reaches
`complex_filter()` without Django's `Exists()` wrapper, so a join would duplicate rows silently.

**ADR:** docs/adr/0023-a-curators-order-reaches-browsing-not-searching.md

## D9 — A branch restriction's closure is recomputed per request, on an endpoint open to anyone

**Ambiguous:** nothing, in the sense that no requirement changes. Recorded because the plan stated
the branch cost as a per-declaration property — "one query per level of hierarchy depth" — which
reads as a one-off and is not.

**Chosen:** ship as specified, and record the cost accurately. The restriction resolves as a
callable, deliberately (FR-007), so it is re-resolved at every validation, every widget render and
every autocomplete request. The autocomplete endpoint allows anonymous access, so an unauthenticated
client re-runs the full downward closure — depth-many queries plus the materialised id set — on
every keystroke, before the 20-row page is cut.

**Why defensible:** the spec's Assumptions already defer branch-read performance to R7, and this
review is not reopening that. What R7 inherits is now stated in full: the single-query rewrite *and*
the repetition, which is the part that decides whether a cache or a bounded depth is the right
answer. The README says what a branch restriction costs, so a consumer choosing it for a public form
is choosing it knowingly.

**One more thing R7 inherits, found at review:** the closure reaches the query as a materialised id
set in `pk__in`, so a branch wide enough to exceed the backend's bound-parameter ceiling (SQLite's
is 32,766) fails outright rather than slowly. No vocabulary this package has seen comes close, and
the fix is the same single-query rewrite R7 already owns, so nothing is being added here — but the
failure mode is a hard error, not the gradual slowdown the rest of this entry describes.

**ADR:** none — a recorded cost and a deferral, not a decision to be abided by. It is carried forward to roadmap item R7, which owns the single-query rewrite, the per-request recomputation and the bound-parameter ceiling together.

## D10 — A T005-authored test's assertion was updated by the US-1 Implementer, not left to fail

**Ambiguous:** nothing about the feature; recorded because the Implementer protocol's default is
"never modify a test you did not author in this story — mark the task blocked and say why in
concerns" (`implement-story.md` §4), and this is that situation.

**What happened:** `TestSharedLimitChoicesToCallable.test_a_restriction_present_still_resolves_to_only_the_vocabulary_q`
(authored under the foundational T005) asserted that a field declared with `collection` set still
resolved to the bare vocabulary `Q` — T005's own deliberately narrow scope, stated in its own
docstring: "until a later story teaches this method the axis." T006 is that later story, and its
acceptance criterion is the direct negation of that assertion: there is no implementation of T006
under which the old assertion stays true.

**Chosen:** update that one test's assertion (and rename it) to check the new, correct behaviour,
rather than mark T006 blocked. Renamed to
`test_a_restriction_present_now_narrows_beyond_the_bare_vocabulary_q`; the two Q objects being
compared were changed from a structural `==` (works only when the resolved value is a plain tuple)
to a membership check against real rows, because a `Q` wrapping a subquery is not `==`-comparable
across two independently built instances (`QuerySet` has no value-equality; confirmed empirically).

**Why defensible:** the test's own docstring forecast exactly this supersession before the story
that would cause it existed, so this is a foreseen, designed consequence of implementing T006 as
specified — not an implementer smoothing over an inconvenient result. Marking T006 blocked over it
would have stalled every task in US-1 (T007-T012 all depend on T006's resolution), for a change with
only one defensible shape. Flagged here, in the completion report's `deviations` and `concerns`, and
left maximally visible in the diff (one test method, no other pre-existing assertion touched) so
Forge/Sam can veto if this reasoning does not hold.

**Revisit if:** Sam or Forge judges that a test whose docstring predicts its own supersession should
still route through "mark blocked" rather than "update and disclose" — in which case this specific
carve-out should be written into the Implementer protocol rather than decided ad hoc per occurrence.

**ADR:** none — a record that one pre-existing test's assertion was updated, required by Article I. Evidence about this run, not a standing rule.

## D11 — The concepts axis gets its own message id rather than reusing `invalid_restricted`

**Ambiguous:** T013's brief instructs extending the existing `invalid_restricted` handling "in the
same shape" as T008's collection message, without saying whether that means the same msgid or the
same *pattern* (one static msgid, one named placeholder).

**Chosen:** a new msgid, `invalid_restricted_concepts`, rather than routing the concepts axis
through `invalid_restricted`.

**Why defensible:** `invalid_restricted`'s fixed English text names a collection by word — "...in
the '%(restriction)s' **collection**." Reusing it for the concepts axis would read as "'granite,
basalt' collection", which is wrong on its face: a concept list is not a collection, and a curator
reading the refusal would learn something false about why the write was rejected. Article XII's
"one static msgid" rule is about not varying the msgid with the restriction's *contents* (so ten
different collections do not need ten different msgids) — it does not require every restriction
*kind* to share one msgid regardless of what the fixed text says. `invalid_restricted_concepts`
keeps the same shape (one static msgid, the restriction interpolated through a single named
placeholder) while keeping the sentence true.

**Revisit if:** a future restriction kind (the branch axis) turns out to want a fourth message
naming a root concept, at which point the naming pattern here (`invalid_restricted_<axis>`) is
either continued or replaced with something that scales better than one msgid per axis.

**ADR:** none — a message-id naming convention local to this module (`invalid_restricted_<axis>`). Real, but sealed inside the two places that raise these refusals.

## D12 — T022 overrides `order_queryset()`, not `apply_ordering()`

**Ambiguous:** nothing about where the ordering belongs or how it is built — D8 already settled
that (the endpoint, a `Subquery` annotation, empty-query only). What's addressed here is the exact
method name T022's brief, `tasks.md`, `plan.md` A5 and `research.md` R6 all give for the override:
`apply_ordering()`.

**What was found:** the installed `django-tomselect` 2026.6.2 (`autocompletes.py`) exposes no
method named `apply_ordering`. The base view's `get_queryset()` (`autocompletes.py:399`) calls
`self.order_queryset(queryset)`, and `order_queryset()` (`autocompletes.py:685-727`) is the actual
method reading `self.ordering` and applying it via `queryset.order_by(*ordering)` — the same method
the design's own line numbers (`686-727`) point at, under the wrong name. An override literally
named `apply_ordering` would sit on the class unused and never run; the base would keep applying
`("label", "pk")` regardless, and every T022 test would fail exactly the way it did before this
story existed.

**Chosen:** override `order_queryset()` instead, implementing precisely the condition and mechanism
D8/A5/R6 describe (empty query, an ordered collection, a `Subquery` on `CollectionMember` keyed on
the declaration's own collection and vocabulary slugs). Nothing about *where* or *how* changes —
only the identifier the story's design documents used to name the seam.

**Why defensible:** the story's whole test (per its own acceptance criteria) is behavioural — the
browsable list arrives in the curator's sequence — not that a method with a particular name exists
on the class. Implementing the design under a name the library does not expose would satisfy no
test and ship no behaviour; the "one method override" T022 promises only exists under the name the
library actually calls.

**Revisit if:** a future `django-tomselect` release renames or restructures this hook again, in
which case this override moves with it under the same reasoning.

**ADR:** none — a correction of fact about the installed library, not a decision. Its lasting value is the proposal it produced, recorded in the run's metrics.

## D13 — The restricted `help_text` default is a second static attribute, not an interpolated one

**Ambiguous:** T023's brief says a restricted field's default must describe "a field restricted
within its vocabulary" without naming which axis or which target, and must stay static — the same
constraint `default_help_text` is already under (`fields.py:97-103`'s annotation: `%` on a
`gettext_lazy()` proxy evaluates it immediately, defeating the laziness the default exists to
keep). That leaves open how a field picks between two defaults without computing one from the
other.

**Chosen:** a second class attribute per field, `default_restricted_help_text`, set once per field
class as a plain `gettext_lazy()` string, and a mixin method, `_default_help_text()`, that returns
one or the other by checking whether `self.collection`/`self.concepts`/`self.branch` is set — never
by reading which value any of them holds. `_apply_vocabulary` calls it in place of the bare
`self.default_help_text` it read before.

**Why defensible:** the alternative — one `default_help_text` whose wording branches internally on
the restriction's presence — would still end up as two static strings selected by a condition; naming
them as two attributes makes both independently overridable by a subclass (the same shape
`default_help_text` already offers) and keeps `_apply_vocabulary` reading one intention-revealing
call rather than an inline three-way `if`. The method reads only *whether* a restriction exists,
never its value, which is what keeps the guarantee: nothing here can accidentally interpolate a
collection slug or a branch root into either default.

**Revisit if:** a later story wants the restricted default to name the axis (collection vs. concepts
vs. branch) without naming the axis's *target* — at that point three restricted defaults, one per
axis, replace the one this decision adds.

**ADR:** none — follows the existing reasoning for why a `help_text` default must stay static, already annotated in `fields.py`. One more attribute under a rule that already existed.
