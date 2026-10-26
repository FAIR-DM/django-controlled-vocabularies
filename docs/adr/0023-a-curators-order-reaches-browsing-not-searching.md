# ADR 0023 — A curator's order reaches browsing, not searching

**Status:** accepted

## Decision

Where a field is restricted to a collection the curator marked **ordered**, the concept search
endpoint returns that collection's members in the curator's sequence — but only while the request
carries no search term. Once someone types, results return to relevance order.

The ordering lives on the endpoint, in `ConceptAutocompleteView.order_queryset()`. It is not applied
to the form field's own queryset, and no ordering is promised anywhere else.

## Why

The endpoint is the only place a person sees a list of choices. The selection control renders an
empty `<select>` and fetches its browsable options over this package's autocomplete URL. The form
field's queryset feeds validation and the redisplay of a value the record already holds. Ordering
that queryset would have satisfied a test and shown no human anything.

The empty-query condition resolves a genuine tension rather than splitting a difference. Browsing a
small ordered collection wants the sequence the curator arranged — that is what marking a collection
ordered means, and until now it had no reader anywhere a consumer looks. A typed query wants the
best match first, and a curator's position is not a better answer to "what did I mean by *cond*" than
match quality is. Conditioning on the search term serves both.

The position is read through a subquery keyed on the declaration's own collection, never a
membership join. A concept may belong to more than one collection, and this queryset reaches
`complex_filter()` without Django's `Exists()` wrapper, so a join would duplicate rows with nothing
reporting it.

## Revisit if

Ordered collections start being used for something other than presentation — a sequence with
semantic weight, where returning members out of order in a search response would be wrong rather
than merely unhelpful.
