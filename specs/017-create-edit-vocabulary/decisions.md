# Decisions — 017-create-edit-vocabulary

Decisions taken without asking the maintainer, and the rationale too long to sit inline in
`spec.md`. Each records what was ambiguous, what was chosen, and why the choice is defensible
against the intake decisions, the shipped models, `CONTEXT.md`, `GOALS.md` and the constitution.

The maintainer's own intake decisions are in `spec.md` under `## Clarifications`, not here.

---

## D1 — Not signed in means sign in. Signed in without the permission means refused

**Ambiguity**: the issue says only someone trusted to curate should reach these pages. It does not
say what everyone else gets at the address.

**Chosen**: someone not signed in is sent to the project's sign-in address and returned afterwards.
Someone signed in without the permission is refused outright.

**Why defensible**: this is what Django's own permission handling does, and what a curator expects.
Someone not signed in may well be a curator who has not signed in yet, so sending them to sign in is
the useful answer. Someone already signed in has nothing to gain from signing in again, so a refusal
is the honest one. The package adds no sign-in of its own. It uses whatever the mounting project
configures, which keeps it embeddable (G9).

**ADR:** none. This follows Django's default and sets no rule of the package's own.

---

## D2 — The date a vocabulary last changed is offered on the form

**Ambiguity**: the publication details include the date a vocabulary last changed, "as its publisher
states it". For a vocabulary authored here, the curator is the publisher. The date could be typed in
by the curator or set automatically on every save.

**Chosen**: the curator types it, like every other publication detail.

**Why defensible**: the field records what the vocabulary says about itself, and an import fills it
from the publisher's file without touching it on later saves. Setting it on every save would make the
field mean two different things depending on where a vocabulary came from, and would change behaviour
the import already relies on. When a vocabulary authored here is published (R4), that feature can
decide whether publishing stamps the date. Until then a curator keeps it as accurate as they keep the
version.

**ADR:** none. It is the existing field's meaning, unchanged.

---

## D3 — A vocabulary in use is never deleted, and its references are never cleared for it

**Ambiguity**: when a project's records point at a concept in a vocabulary being deleted, the page
could refuse, or offer to clear those references and then delete.

**Chosen**: refuse, naming the kinds of record that use the vocabulary's concepts.

**Why defensible**: the consumption fields already protect a referenced concept from deletion, so
the database refuses this whatever the page does. The decision is only how the page meets that
refusal. Clearing the references would change records that belong to the consuming project, not to
this package, and could break that project's own rules (a required field left empty, for one). The
curator who needs the vocabulary gone takes it up with whoever owns those records. This matches what
#176 asks for when a single concept is removed.

**ADR:** none. It applies the existing delete protection rather than setting a new rule.

---

## D4 — Design review findings carried as edits to the plan

**Ambiguity**: the design review returned one high, three medium and six low findings, all verified.

**Chosen**: every one applied as an edit to `plan.md`, `tasks.md` or `research.md`. Tests mirror the
source tree (`test_views.py`, `test_forms.py`). The delete page's `back` is checked with
`url_has_allowed_host_and_scheme`. The default language keeps a blank choice distinct from an
absent field. Language names come from the existing `language_name()`. A test proves no `ui` module
imports the admin, and the translation sweep covers the new modules. The edit view drops the
re-query of the stored slug. Counting the records that use a vocabulary's concepts takes one query
per consuming model.

**Why defensible**: each remedy is the smallest edit that meets the requirement or standard the
finding named, and none changes what the maintainer approved.

**ADR:** none. Plan corrections, not standing rules.

---

## D5 — The editing pages sit behind a `-` segment

**Ambiguity**: the editing pages need addresses in the same space as vocabularies and concepts,
whose slugs this package does not choose.

**Chosen**: `/-/new/`, `/<vocabulary>/-/edit/` and `/<vocabulary>/-/delete/`. Research R7.

**Why defensible**: `-` cannot be a slug, so nothing is shadowed and no word is reserved. The
maintainer saw the addresses at the sketch gate and left the choice to the plan.

**ADR:** docs/adr/0020-curator-pages-sit-behind-a-dash-segment.md
