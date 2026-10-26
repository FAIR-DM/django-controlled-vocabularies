# ADR 0011 — A concept is chosen in the admin, never created there

**Status:** accepted

## Decision

On a consuming model's Django admin page, `ConceptField` and `MultiConceptField` render a control
that offers no way to add, change, delete or view the related concept. All four of Django's
related-object links are absent, whether or not this package's own models are registered in the
admin, and whatever permissions the signed-in person holds.

The refusal comes from the form field, not from anything a project has to declare. Django wraps
every relation in `RelatedFieldWidgetWrapper` unconditionally and offers no hook to decline it, so
the form field owns its `widget` attribute and unwraps the wrapper on assignment. A project applies
no mixin, and no Django method is patched.

Two boundaries belong to this decision:

- It governs the editable control. A field the admin renders read-only is excluded from the form
  entirely, so no widget is built and nothing can be declined. Django renders a read-only
  single-value relation as a link to that record's own admin page, which no package can suppress. A
  read-only field offers no selection, so it is not a selection surface.
- `raw_id_fields` is the one declaration Django itself never wraps, so it renders no affordance for
  a different reason. See ADR 0012 for what happens when a project declares its own control.

## Why

The curator interface is a planned feature in the same milestone. Once it registers the concept
model, every consuming project's data-entry page would grow a "create a concept" button, with no
code changed anywhere and nobody looking. A guarantee that holds only because a precondition
happens to be false is not a guarantee, and the failure would have arrived inside an unrelated
feature. So the tests register the concept model and sign in a superuser, which is the only
configuration under which the links appear at all.

The underlying reason is the point of the package. A controlled vocabulary stops being controlled
the moment someone entering a sample record can invent a term mid-form. Authoring belongs where
concepts are curated.

Two alternatives were weighed and rejected. A `ModelAdmin` mixin the project applies would mean the
guarantee depends on a project remembering it, and the failure mode is silence. Replacing
`ModelAdmin.formfield_for_dbfield` at app-ready is a monkey patch on a core Django method, changing
the behaviour of every field on every model in someone else's project to alter two.

The cost is that the unwrap depends on Django assigning to the widget attribute. The tests assert
the four links are absent from rendered output rather than asserting the mechanism, so a future
Django that built the wrapper differently fails a test rather than drifting quietly.

## Revisit if

Django gains a supported way for a field or widget to decline the wrapper, or the curator interface
introduces a role for whom creating a concept from a data-entry page is the intended workflow.
