# Decisions — 010 Attach several concepts from a chosen vocabulary to a model

Rationale too long to sit inside `spec.md`, plus every ambiguity resolved without asking the
maintainer. Each entry states what was unclear, what was chosen, and why the choice is defensible.
The spec is the contract. This file is why the contract reads the way it does.

The single-value field ([#86](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/86),
`specs/009-attach-concept-to-model/`) settled naming by slug, the missing-vocabulary check, the
constraint's enforcement layer and the label readback, and those decisions are inherited here rather
than retaken. What follows is only what a *set* of concepts makes different.

## D1 — The set is unordered

The maintainer's decision at intake.

An order over a record's concepts is not free. It has to live somewhere, and the only place it can
live is on the membership itself, which means every consuming model in every project carries a
position column forever, written on every attachment and read on every access. That is a permanent
cost paid by every consumer.

Against it, the use the issue actually describes: a dataset tagged with several methods, a
publication covering several topics. Neither reads as a sequence. Nobody asks which method came
first.

The package already has an answer for concepts that genuinely belong in an order, and it is on the
other side of the relationship. A collection (FS-004) is a curator's deliberately grouped set of
concepts with an optional order, and it lives in the vocabulary, where the person who knows the
order owns it. A consumer that needs an ordered set of concepts is describing a collection, not a
tagging field.

If ordered tagging on the consumer side is ever wanted, it arrives then as its own feature, with a
use case to shape it. Adding it now would be speculation, which Article II rules out.

**ADR:** none — a feature-level decision about this field's shape, not a standing rule.

## D2 — The constraint must bite on the relation's own write path, not only at validation

This is the one place where copying the single-value field's answer would produce a field that does
not work.

FS-009 put the vocabulary constraint at model and form validation, and that was right there,
because a single-value field's value is an attribute of the record: assign it, validate the record,
and the check runs over what you assigned. `CONTEXT.md` records the resulting rule for the whole
package — model-level rules are enforced at validation, and a bulk queryset write goes around them.

A many-valued relation breaks the premise that argument rests on. Its contents are not an attribute
of the record. They live in a separate table, they are written through the relation's own manager
after the record is saved, and validating the record does not look at them at all. The ordinary,
documented, entirely non-exotic way to attach a concept is to write the relation — and that path
would carry no constraint whatsoever. A developer would follow the obvious usage, put a concept
from the wrong vocabulary into a record, get no complaint from anything, and the field's central
guarantee would be decorative.

That is a different situation from the bulk-write bypass `CONTEXT.md` describes. A bulk write is a
deliberate step around the model layer, taken by someone who knows they are taking it. Writing a
relation through its manager is not a step around anything; it is the interface.

So the refusal holds wherever a membership is created. A write carrying several concepts is refused
whole rather than partially applied, because a half-applied write leaves the record in a state
nobody asked for and the caller has no way to discover which members landed.

What stays bypassable is a write aimed straight at the join table, which is the true equivalent of
the bulk-write case and is left exactly as permissive as every other model-level rule in this
package.

**ADR:** none yet — this is a feature-level reading of an existing standing rule rather than a new
one. If a third feature needs the same distinction, the rule in `CONTEXT.md` should be amended to
state it, and that amendment is an ADR.

## D3 — Required means at least one concept, checked at validation

"Required" has an unambiguous meaning for an ordinary field: the column rejects null. A many-valued
relation has no column and therefore no empty state to reject, so the word has to be given a
meaning deliberately or every consumer will invent one.

The meaning chosen is the one Django's own forms already use for this shape: a required
many-valued field demands at least one selection. Taking it any further — enforcing it in the
database — is not possible without a trigger, because the record must exist before its memberships
can be written, so there is an instant in every single successful save where the set is empty and
correct.

That instant is also why this is a validation rule and not a save-time refusal. Refusing to save a
record whose set is empty would refuse the first half of every legitimate write.

A project that writes memberships without validating gets the same latitude it gets from every
other model-level rule here, which is the consistency `CONTEXT.md` already documents.

**ADR:** none — a feature-level decision about this field's declaration options.

## D4 — Attaching a concept twice is a set operation, not an error

A record either holds a concept or it does not. There is no reading of the feature under which a
record holds a concept twice, and no consumer has anything to do with the information that it was
attached again.

Refusing the second attachment would mean every caller checks membership before every write, which
is work for no benefit and a race in any concurrent path.

**ADR:** none — this is what a set means, not a rule this project chose and could have chosen
differently, so there is nothing for a standing record to carry.

## D5 — Deleting a consuming record removes its memberships and keeps the concepts

The protection Article IX requires runs one way: a curator must not be able to pull a concept out
from under a record. It says nothing about the record, and a record that could not be deleted
because it happened to be tagged would make the field a liability to declare.

This matches the single-value field exactly, where deleting the record leaves the concept alone,
and it is the only reading consistent with what the concepts are — shared reference data that
outlives any particular consumer of it.

**ADR:** none — it restates Article IX's existing one-way protection for a second field type and
matches the single-value field exactly, so it adds no standing rule.

## D6 — Whether the two fields share an implementation is a design question, not a spec one

The obvious move on reading this feature is to factor the vocabulary constraint, the check and the
readback out of the single-value field and have both fields use the shared thing. It may well be
right. It is not the spec's decision, and this feature does not assume it.

Article III is explicit that an abstraction is earned by a present, concrete second use rather than
assumed, and this feature is exactly that second use — which is an argument for extracting, not a
licence to have already done so. The judgement belongs in `plan.md`, made against the two
implementations once both shapes are known, and the outcome has to hold up at design review either
way. What the spec fixes is that the two fields present the same idea to a developer, not that they
are built the same way.

**ADR:** none at spec time. If the plan does extract a shared base, that is a public extension point
and Article VIII makes it part of the Python API contract, so it wants an ADR then.

## D7 — The two fields do not share an implementation (resolves D6)

Taken at S3 with both shapes in view, which is what D6 said it would take.

The overlap is smaller than the two features' matching prose suggests. `research.md` R1 to R6
establish that every mechanism differs: `ForeignKey` against `ManyToManyField`, `validate()` against
an `m2m_changed` receiver, an inherited `on_delete=PROTECT` against a generated through model, a
column's `null=False` against a validation hook installed on the consuming class. What actually
repeats is storing and stripping the `vocabulary` kwarg — about six lines — and the shape of the
contributed accessors.

A base class holding six lines of kwarg handling would have to sit above two classes with different
parents, so it would be a mixin invented to avoid a small duplication rather than a shared concept.
Article III's own instruction covers the case: prefer duplication over the wrong abstraction. The
next reader of a declaration should find out what it does in one hop.

One thing is genuinely shared and is treated that way: the system check already walks every field of
every model, and gains a second type in its filter. A widened filter is not an abstraction.

**ADR:** none — declining to extract is the status quo, and nothing downstream inherits it. If a
third consumption field ever arrives, the question is properly reopened then, and by that point an
extraction would have three uses to shape it.

## D8 — The required-set rule is installed onto `full_clean`, guarded on the primary key

D3 fixed the meaning of required. This fixes where it runs, and the constraints are not stylistic.

Django gives a field no hook into model validation for a many-valued relation: `full_clean()` calls
`clean_fields()`, which iterates `_meta.fields`, which excludes many-to-many by an explicit filter
(`research.md` R2). Either the rule runs at the form layer only — which would leave FR-010's first
half unimplementable as approved — or the field installs the check itself. It installs it, once per
consuming class, delegating to the original.

**One installation, every field.** The wrapper is installed once per class, so it cannot be bound to
the field that triggered the installation — a second required `MultiConceptField` on the same model would
then go unenforced with nothing raising. It resolves the class's required `MultiConceptField`s at call
time and applies FR-010 to each.

Two further constraints came out of the probe rather than out of taste:

- **An unsaved record is skipped.** Touching the relation descriptor when the primary key is `None`
  raises `ValueError`, and `full_clean` catches only `ValidationError`, so an unguarded check turns
  an ordinary `ModelForm.is_valid()` on a new object into an uncaught crash. It is also the correct
  semantic: a record exists before its memberships can, so an empty set on an unsaved record is the
  right intermediate state of every legitimate creation.
- **Other errors survive.** The wrapped `full_clean` raises before the added check runs, so the check
  catches that `ValidationError`, merges its own message into the error dictionary under the field's
  name, and re-raises. A record with a bad character field and an empty required set reports both.

The cost is honest: this is the most invasive thing the feature does, because it modifies a class the
package does not own. It is bounded — one wrapper per class, delegating, merging — and it is the
price of `full_clean()` meaning what the spec says it means. A consuming model that overrides
`full_clean` after declaring the field would shadow it, which the README states.

**ADR:** none — a mechanism internal to this field, not a rule anything else inherits. It becomes
ADR-worthy only if a second feature needs the same installation trick, at which point the pattern is
the decision rather than this instance of it.

## D9 — A declaration names zero, one, or several vocabularies

Raised by the maintainer on 2026-08-12, after the design review and before any code existed. It
supersedes the part of D2's context that assumed exactly one vocabulary, and it replaces FR-002's
refusal of an unnamed one.

The original requirement was written from the single-value field's shape, where naming exactly one
vocabulary is the whole point, and it carried that assumption across without re-examining it. The
argument for refusing an unnamed vocabulary — that an unconstrained field is a plain many-to-many
and offers none of this field's guarantees — turns out to be wrong on its own terms. An
unconstrained `MultiConceptField` still protects its references from deletion, still reads back labels
and identifiers, and still enforces the required-set rule. Those are three of the five guarantees,
and they are the three a plain many-to-many does not give you.

The use case is ordinary rather than exotic. Research metadata routinely carries keywords drawn
from whatever the project has imported, and more often from a named handful of published schemes
than from exactly one. A field that cannot express either shape sends those projects back to the
hand-rolled relation this package exists to remove.

**Three shapes, one parameter.** `vocabulary="rock-type"` restricts to one. `vocabulary=["gcmd",
"agu-index"]` restricts to the union. Omitting it restricts nothing. All three are the same `Q`
construction — `scheme__slug`, `scheme__slug__in`, or no filter at all — so the list form costs
almost nothing beyond the bare omission, and it is the form most research profiles actually want:
"keywords from GCMD or AGU" is a boundary, and without a list the only way to name two vocabularies
would be to accept every vocabulary.

**What is given up, stated rather than implied.** A field naming no vocabulary makes no promise
about which concepts land in it. The write-path refusal has nothing to enforce, the form offers
every concept, and the system check has no vocabulary that could be missing so it reports nothing.
The README says this in as many words. A field that quietly offers a weaker guarantee than its
siblings is worse than one that says what it does not do.

**ADR:** none — a decision about this field's declaration options, taken before release, with no
existing behaviour to supersede. Article VIII's data contract is untouched: nothing here changes a
concept's URI or its serialized form.

## D10 — Two of T001's six consuming models land with T003, not held for T001 (Implementer, US0)

`tasks.md` lists the brief order T002, T003, T001, and T001 itself says its models can be written
either before or after T002/T003, "either way the phase is one sequential unit and exits green as a
whole." T003's own acceptance criteria say its tests run "against a real model from T001, none
against the helper in isolation" — so T003 cannot be proven without at least one consuming model
existing first, and its "two declarations on one model" case needs a second.

Rather than build all six of T001's models ahead of T003 (which would generate a throwaway
migration under the stock `CASCADE` through model, replaced the moment T003's `PROTECT` override
lands), or write T003 against a synthetic helper call the task explicitly rules out, this
Implementer added exactly the two models T003's own acceptance scenarios require —
`Deposit` (one required `MultiConceptField`, proves the generated membership model's `PROTECT`/`CASCADE`
split) and `Survey` (two `MultiConceptField`s with `related_name="+"` on one model, proves the hidden
related_name rewrite and the absence of a double-registration warning) — as part of the T003 commit,
with their own migration. T001 adds the remaining four models and a second migration.

**Revisit if:** a later story finds the two-migration split (0002 under T003, 0003 under T001)
awkward to review. Migrations are squashed at convergence regardless, so this is not expected to
matter past this branch.

**ADR:** none — a sequencing choice inside one phase of one branch, with no consequence that
survives the squash.

## D11 — Two T005 tests wrap the refused write in its own `transaction.atomic()` (Implementer, US2)

Not anticipated by `tasks.md`, `plan.md` or `research.md` — a mechanical consequence of how Django
implements the relation manager, surfaced only once the receiver from T005 actually raised inside a
test.

`ManyRelatedManager.add()` and `.set()` (`related_descriptors.py`) both run inside
`transaction.atomic(using=db, savepoint=False)`. When the `pre_add` receiver raises a
`ValidationError` from inside that block, and the block holds no savepoint of its own, the exception
poisons the whole connection: pytest-django's own transaction wrapping each test is left needing a
rollback, and the next query issued in that same test raises `TransactionManagementError` instead of
running. Two of T005's tests read the record's set back after the expected raise (to assert it is
unchanged, per the acceptance criteria), so both hit this.

The fix is the pattern Django's own docs use for asserting a raise from inside code that itself uses
`atomic(savepoint=False)`: give the raising call its own nested `transaction.atomic()`, which opens a
savepoint the exception rolls back to on its way out, leaving the outer test transaction usable
afterwards. No production code changed; this is a test-authoring detail, not a behavioural choice
about the field.

**ADR:** none — a Django transaction mechanic, not a decision about this feature's behaviour or
public surface.

## D12 — T010's "three vocabularies" scenario is tested against the existing two-vocabulary `FieldNote`, not a new fixture (Implementer, US6)

`tasks.md`'s T010 acceptance describes "a field naming three vocabularies of which one is absent"
as the case that proves the warning names only the absent slug, not the field's whole declaration.
The test app's only multi-vocabulary field is `FieldNote.keywords`, which T001 declared naming
two (`"rock-type"`, `"mineral"`), not three.

Adding a third vocabulary to `FieldNote` was rejected: US-8/T012's own acceptance criteria need a
concept from a vocabulary `FieldNote` does *not* name, to prove the write-path refusal, and widening
`FieldNote` to three named vocabularies would either remove that third, unnamed vocabulary or force
a fourth — changing a shared fixture another story's not-yet-landed task depends on. Adding a
wholly new model was rejected too: T001 already enumerated, deliberately, the one model per shape
`tasks.md` lists, and `craft-increments`' scope containment favours reusing what Phase F already
built over expanding shared test infrastructure for a scenario a smaller fixture already proves.

`test_reports_only_the_absent_vocabulary_when_a_field_names_several` uses `FieldNote` with only
`"Rock Type"` created, `"mineral"` left absent: the assertion is on the *mechanism* (iterate the
field's every named slug, warn only for the ones absent from the database), and two named
vocabularies with one absent exercises exactly the same code path three would — the only thing three
would additionally prove is that a second *present* vocabulary is also correctly excluded, which
`test_reports_nothing_once_the_multi_concept_fields_vocabulary_exists` and the pre-existing
`test_reports_nothing_once_every_named_vocabulary_exists` already exercise for `FieldNote` once both
its vocabularies exist.

**Revisit if:** a future story needs a genuine three-vocabulary fixture for its own reasons; this
test can then move onto it without weakening in the meantime.

**ADR:** none — a test-authoring scope decision, not a change to this feature's behaviour or public
surface.

## D13 — T008's collision-guard proof uses `isolate_apps`, not a new testapp model; the accessors also guard an unsaved record (Implementer, US4)

`tasks.md`'s T008 acceptance names the collision guard directly: "a model that already defines
either accessor name itself... keeps its own definition," the same guard `ConceptField`'s T011
proved against a real, purpose-built testapp model (`Artifact.get_mineral_label`). No existing
`MultiConceptField` testapp model both names no vocabulary (so the `multilingual_scheme`/
`single_language_scheme` fixtures' concepts can be attached without tripping T005's write-path
check) and already defines `get_keywords_labels()` itself — `Photograph` is the only
no-vocabulary model, and every other test in this file that uses it relies on the field-contributed
accessors being real, so adding a permanent pre-existing definition to it would either break those
or force a second no-vocabulary model. `TestMultiConceptFieldMembershipModel`'s own
`test_declaring_two_multi_concept_fields_on_one_model_warns_of_nothing` already establishes the pattern
for this exact situation — a throwaway model declared inside the test body under
`@isolate_apps("tests.testapp")` — so `test_a_models_own_definition_survives_the_contribution_guard`
follows that precedent rather than widening `tests/testapp/models.py` for a scenario the isolated
model proves just as directly, and without touching `tests/factories.py` (outside this story's
allowed files) to give it one.

Separately: `get_<name>_labels()`/`get_<name>_uris()` return `[]` for an unsaved instance
(`instance.pk is None`), not only for a saved one holding no concepts. `tasks.md` doesn't call
this out explicitly, but FR-008/FR-009 both say "a record holding nothing MUST return an empty
result rather than raise," and Django's many-to-many manager raises `ValueError` — not the
`AttributeError`-subclassing `RelatedObjectDoesNotExist` `ConceptField`'s singular accessors
already guard against — the moment its queryset is touched before the instance has a primary key.
Without the `pk is None` guard, `get_<name>_labels()`/`get_<name>_uris()` would crash on exactly the
required-`MultiConceptField`, not-yet-saved case `TestConceptFieldLabelAndUriAccessors`'s own
`test_both_accessors_return_none_on_a_required_field_with_nothing_attached` already covers for the
singular field. `test_both_accessors_return_an_empty_list_on_an_unsaved_record_rather_than_raising`
proves it against `Deposit`, the required `MultiConceptField`.

**Revisit if:** a future story needs a testapp model with its own pre-existing `get_<name>_labels`/
`get_<name>_uris` definition for other reasons; this test can then move onto it.

**ADR:** none — a test-authoring scope decision and a direct reading of FR-008/FR-009's own words,
not a change to this feature's behaviour or public surface beyond what those requirements already
state.

## D14 — the required-set wrapper is guarded on the method, not on a class flag

**Context.** T009 installs a `full_clean` wrapper once per consuming class. The design review's
correction to D8 made the wrapper resolve the class's required `MultiConceptField`s from
`type(self)._meta.get_fields()` at call time, so that a model declaring two required fields has both
enforced. tasks.md also carried the earlier instruction to guard the install on `cls.__dict__`
rather than `getattr`, on the reasoning that a subclass inheriting the flag would lose the check.

**Problem.** The two instructions interact. With call-time resolution the inherited wrapper already
covers a subclass's own fields, so the `__dict__` guard does not preserve a check — it installs a
second wrapper around the first. Verified structurally on a multi-table pair: the parent carries one
wrapper, the child carries a second nested around it, and each enumerates the same fields, so every
empty required field on the child is reported twice.

**Decision.** Guard on the resolved method instead. `_install_required_set_check` tags its wrapper
with `_multi_concept_field_required_set_check` and returns early when `cls.full_clean` already carries
that tag. A subclass that inherits the wrapper installs nothing; a subclass that overrides
`full_clean` itself gets an untagged method and is wrapped normally. The `__dict__` guard's original
purpose is served by call-time resolution, which is the mechanism that made it unnecessary.

**Verified.** `TestMultiConceptFieldRequiredSet::test_an_inheriting_model_does_not_get_a_second_wrapper`
fails against the `__dict__` guard and passes against the tag.

**Author.** Applied at convergence rather than by the story's implementer: the interaction was
visible only once T009's code and the review's correction were both in front of the same reader.

**ADR:** none — a mechanism internal to this field's own installation, the same class of decision as
D8, which it corrects. It becomes ADR-worthy only if a second feature installs a validation wrapper
the same way, at which point the pattern is the decision rather than this instance of it.

## D15 — The i18n sweep recognises a metadata key in any dict literal, not only `error_messages`

**Context.** T011 audits every string this feature's code puts in front of a person. T003's
generated through model builds its `Meta` as a plain dict passed to `type("Meta", (), {...})`,
carrying `verbose_name` and `verbose_name_plural` — both already wrapped in `gettext_lazy` in the
real code, but a shape the sweep's existing keyword-argument checks (`ForeignKey(verbose_name=…)`,
`kwargs.setdefault("verbose_name", …)`) cannot see, because the dict is a positional argument to
`type(...)`, not a keyword.

**Decision.** Rather than add a third special case gated on the variable name `meta` (mirroring how
`error_messages`/`default_error_messages` are matched by name), `_FieldsChecksI18nVisitor` gained a
`visit_Dict` that flags any dict literal's value under a `help_text`/`verbose_name`/
`verbose_name_plural` key, wherever that dict appears. This is strictly broader than the one shape
T003 actually uses, but it costs nothing extra to check and it means a future dict-shaped `Meta` —
or any other dict carrying one of these keys — is covered without a fourth special case.
`verbose_name_plural` was added to `_FIELD_METADATA_KEYWORDS` for this, since the through model's
`Meta` carries both.

**Verified.** `TestFieldsChecksI18nVisitorCatchesAViolation::test_catches_a_bare_verbose_name_dict_literal_value`
proves the new visitor method against a synthetic snippet. Separately, `verbose_name` in the real
`fields.py` and `hint` in the real `checks.py` were each unwrapped by hand, in turn, and
`TestFieldsChecksI18nSweep`'s parametrized test against the real files was watched to fail on each
before being restored — proving the sweep catches a real regression in both modules it covers, not
only the synthetic snippets `TestFieldsChecksI18nVisitorCatchesAViolation` feeds it.

**Revisit if:** a third dict-literal shape needs a different key set than
`_FIELD_METADATA_KEYWORDS` covers; this generic match can then narrow back to a name-gated check
for that one shape instead.

**ADR:** none — a test-tooling decision internal to this file's own AST sweep, not a change to any
shipped behaviour or public surface.

## D16 — the write-path refusal checks both directions

**Context.** T005 connected the `pre_add` receiver and ignored reverse-direction writes, on the
reasoning that a reverse write carries the owner model's primary keys in `pk_set` rather than
concepts', so checking `pk_set` against the vocabulary would be meaningless.

**Problem.** The premise is true and the conclusion does not follow. Django gives every relation a
live reverse accessor unless the declaration hides it with `related_name="+"`, so
`concept.deposit_set.add(a_deposit)` reaches the same through model as
`deposit.rock_types.add(a_concept)`. Reproduced on the plainest possible declaration —
`Deposit.rock_types`, which names no `related_name` at all: the forward write of a Mineral concept
is refused, the reverse write of the same concept succeeds in silence, and the membership then reads
back through the plural accessors as if it were legitimate. FR-005 and SC-002 were both false as
implemented.

**Decision.** Check both directions, with a different question in each. On a forward write the
incoming concepts are `pk_set` and are resolved in one query, as before. On a reverse write the
single concept being attached is `instance`, and its scheme is what the vocabulary is checked
against. Same `ValidationError`, same message.

**Verified.** Three tests drive the real relation managers: the default reverse accessor, a named
one, and a valid reverse attach that must still succeed. The two refusal tests fail against the
`reverse` early return and pass against the fix.

**Author.** Found by the review panel as F1 (critical) and applied at convergence.

**ADR:** none — it closes a hole in an existing feature-level rule (D2) rather than adding a standing
one. The generalisation worth keeping is about testing rather than architecture: a guarantee stated
over "the relation" has to be exercised from both of the relation's ends, because Django gives every
relation a reverse accessor whether or not the declaration mentions one.
