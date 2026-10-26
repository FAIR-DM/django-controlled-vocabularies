# Decisions — 009 Attach a concept from a chosen vocabulary to a model

Rationale too long to sit inside `spec.md`, plus every ambiguity resolved without asking the
maintainer. Each entry states what was unclear, what was chosen, and why the choice is defensible.
The spec is the contract. This file is why the contract reads the way it does.

## D1 — A missing vocabulary is a warning, never a failure to start

The maintainer's decision at intake, recorded here because it is the one that shapes most of the
rest of the spec.

A model field is read when Python imports the module holding it. A vocabulary is rows in a table.
The two arrive at completely different times, and there is no ordering that lets a declaration
assume its vocabulary is present: on a fresh install the vocabulary is imported by a management
command, which needs the tables, which need `migrate`, which needs the models to import cleanly.
A declaration that refused to load without its vocabulary would make the package impossible to
bootstrap, and would break every CI run that starts from an empty database.

So the declaration carries the vocabulary's name and nothing more, and the gap is reported by a
system check. That puts it where a developer already looks — `manage.py check` runs in CI, and
`migrate` and `runserver` run it too — rather than in an exception at an arbitrary import.

**ADR:** none — a feature-level decision about this field's failure behaviour, not a standing rule.

## D2 — The declaration names its vocabulary by slug

Three candidates, and the intake decision eliminates one of them outright.

A reference to the vocabulary row itself is out, because resolving one needs a database query at
declaration time, which D1 forbids.

The URI is the tempting answer, because `CONTEXT.md` is emphatic that identity lives in the URI and
never in the primary key. It does not survive contact with the detail underneath that sentence. A
vocabulary's `uri` is only fixed once `static_uri` is set, which happens when an external publisher
assigned it or when this site publishes the vocabulary — and publishing does not exist until R4.
Until then the URI is *dynamic*: composed from the site's configured base address. The same
vocabulary therefore has one URI on a developer machine, another in staging, and another in
production, and a declaration naming any of them is wrong in the other two. A key that varies by
deployment is not a key.

The slug is unique app-wide, is the segment the local address is built from, and is a plain string
that needs no database to write down.

Its weakness is real and worth stating plainly: for a locally authored vocabulary the slug is
re-derived from the name on every save, so renaming a vocabulary moves its slug and orphans every
declaration naming it. Three things make that acceptable. The failure is loud, because it is
precisely the state D1's check reports. It is avoidable, because `slug_is_manual` already exists to
pin a slug that must not move. And it is temporary in the direction that matters, because a
published vocabulary's slug is frozen by the same mechanism that freezes its URI.

**ADR:** none yet — if #87, #88 and #89 all confirm the slug as the declaration key, the rule is
worth promoting to an ADR at the end of R3 rather than at the start.

## D3 — The check is a warning, and it is silent when it cannot ask

Django runs the system check framework before most management commands, including `migrate`. A
check returning an `Error` stops the command. So a check that errored on a missing vocabulary would
block the migration that creates the table the vocabulary is imported into, which is D1 inverted.
It has to be a `Warning`.

A warning that cannot be turned off is noise for the project that knows perfectly well the
vocabulary arrives in a later deployment step, so it carries a stable identifier and
`SILENCED_SYSTEM_CHECKS` handles the rest. That is Django's own mechanism for exactly this, and
inventing a package setting to duplicate it would be the anti-abstraction Article III warns about.

The third part is the one most likely to be missed in implementation. The check queries the
database, and it runs in states where the database has no tables yet — the first `migrate` on an
empty database is precisely that state. A missing table is not evidence that a vocabulary is
absent, so the check reports nothing rather than either raising or claiming the vocabulary is
missing. The same holds for a database that cannot be reached at all.

**ADR:** none — an implementation-shaping constraint inside one feature.

## D4 — The vocabulary constraint is validation, the delete guard is the database

These two guarantees sound like one guarantee and are enforced in different places, which is worth
being explicit about because the difference shows up in exactly one scenario a reviewer will ask
about: bulk queryset operations.

The vocabulary constraint is a model-layer rule. `Model.full_clean()` and form validation refuse a
concept from the wrong vocabulary, and the choices a form offers make one unreachable in the first
place. A `queryset.update()` writes around all of it. That is not a gap peculiar to this feature —
`CONTEXT.md` already records the same for `static_uri`, and it is true of every `clean()` method in
every Django project. Closing it at the database would mean copying each concept's vocabulary onto
the consuming table so a check constraint could compare them, which buys a bypass nobody reaches by
accident at the cost of a denormalised column that must be kept in step forever.

The delete guard is different, and it does not have that weakness. Article IX requires
`on_delete=PROTECT`, which lives in the relation itself, so it holds against a bulk delete and
against a cascade arriving from the vocabulary above it. That asymmetry is deliberate and is stated
in the spec's Assumptions so it is not read later as an inconsistency.

**ADR:** none — Article IX already carries the standing rule this applies.

## D5 — The label readback falls back to the vocabulary's default language

`Concept.preferred_label(language)` returns `None` when the concept has no preferred label in that
language. Handing that behaviour straight to a consuming record would mean a site running in German
against an English-only vocabulary renders empty strings everywhere, and every consumer writes the
same two-line fallback the package should have written once.

The fallback target is the vocabulary's own default language, because a concept is guaranteed to
carry a preferred label there — that is the label its identity is anchored on. So the readback is
total for any concept that exists, which is what lets a template use it without a guard.

This adds a resolution rule rather than replacing one. `preferred_label(language)` keeps its exact
current behaviour for a caller that genuinely wants to know whether a specific language is present,
which import reporting and the future editor both need.

**ADR:** none — a behaviour of this field, layered over an existing model method that is unchanged.

## D6 — Observed drift: Article IX still describes a per-concept lifecycle

Not a decision, recorded because this feature is the first to read Article IX in anger.

Article IX says referenced concepts are removed via deprecation, "`draft` → `published` →
`deprecated`". The closing comment on
[#19](https://github.com/SamuelJennings/django-controlled-vocabularies/issues/19) supersedes that
model: publication is a vocabulary-level, one-way release event, and a concept carries only a
deprecated marker rather than a three-state status. `CONTEXT.md` still carries the old shape too.

Nothing in this feature depends on which is right, because neither publication nor deprecation
exists yet and this spec assumes only that a concept is present or absent. The clause that *is* in
force — `on_delete=PROTECT` — is unambiguous and is implemented here. The reconciliation belongs to
R4, where publication is actually built. Raised to the maintainer at the Spec gate so it is a known
inconsistency rather than a surprise found during R4.

**ADR:** none from this feature. R4 should amend Article IX and the `CONTEXT.md` Lifecycle row
together.

## D7 — US-5's tamper flags are import lines, approved

`tamper-check` flagged `tests/test_fields.py` and `tests/test_models.py` as modified pre-existing
test files across `d07c48c..86227e4`. The check works at file granularity, so an append to a file
that also gains an import reads the same as a rewritten assertion.

The diff carries no change to any pre-existing test function. In `test_models.py` the modification
is one added import (`django.utils.translation`) and a new class inserted between two existing ones.
In `test_fields.py` it is two added imports (`ConceptLabel`, `translation`), an alphabetical reorder
of an existing `from django.db.models import` line, and a new class appended after the last test.
`TestConceptPreferredLabels` is untouched, which is what T010 relies on as its regression proof.

Approved under D4's "a legitimate refactor can be approved by Forge with a decisions.md entry".

**ADR:** none — a one-off triage of a tooling flag on one commit range, not a rule that outlives
this feature.

## D8 — T012's on_delete/vocabulary refusals are exempt from the translation sweep

`fields.py` raises two bare `TypeError`s from `ConceptField.__init__()`: a consumer-supplied
`on_delete`, and a missing or empty `vocabulary`. Neither is wrapped with `gettext_lazy`, and
T012's standards test does not ask them to be.

Both fire at Python import time, while a project's own `models.py` is being read — before a
request exists, before a user is involved, before there is anyone to localize the message for.
The reader is the developer who wrote the field declaration, working from a traceback in their
own terminal or CI log, exactly like Django's own `TypeError`s for a malformed field (an
unrecognised kwarg, an invalid `on_delete` value) which are equally untranslated. Wrapping them
would suggest an end user might see one, which they cannot: a model that raises at import time
never serves a page.

So `TestFieldsChecksI18nSweep`'s visitor (`tests/test_standards.py`) does not treat `TypeError`
as a sink at all — only `ValidationError`, `checks.Warning`, `checks.Error`, `help_text`/
`verbose_name` keyword literals, and `error_messages`/`default_error_messages` dict values,
every one of them a message that can reach an end user through a form, an admin page, or
`manage.py check`. The two `TypeError`s are exempt by construction rather than by a special case
the visitor has to carve out and someone later has to remember why.

**ADR:** none — a scope boundary for one feature's translation sweep, not a standing rule.

## D9 — `limit_choices_to` is refused, not merged (S6 review, F3)

`ConceptField` sets `limit_choices_to` to express the vocabulary constraint itself. A consumer
passing their own was silently discarded: `get_limit_choices_to()` returned only the scheme
filter, so a consumer narrowing choices further shipped a form offering more than they asked for
and nothing said so.

Refused with a `TypeError` at construction, the way `on_delete` already is. Combining the two `Q`
objects with `&` is the larger design change and is not what the failure demanded — a consumer who
needs a narrower set can filter the form field's queryset in their own `ModelForm`.

**ADR:** none yet — the same call as D2's. It is a feature-level choice about one field's
constructor today. If #87's `MultiConceptField` and #88's widget reach the same answer, "a field that
owns a relation option refuses a consumer's override rather than merging it" becomes a standing
rule for the package's field family and earns an ADR then.
