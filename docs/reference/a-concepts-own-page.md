# A concept's own page

Every concept has its own address, `{mount}/{vocabulary-slug}/{concept-slug}/`. The page is a
definition list of everything the concept's document states, other than its hidden labels, each row
labelled by the predicate it was stored under: its type (`rdf:type`), and then each predicate the
document holds. The ones the package knows come first, in a fixed order: labels, notation,
definition and notes, broader, narrower and related concepts, mappings to other vocabularies,
membership, and the publication details. Any other predicate follows, in alphabetical order, so a
statement in a namespace other than SKOS is shown too. Every record-valued row links to that
record's own page here. A predicate the concept carries no value for contributes no row at all —
never an empty one — so a concept carrying nothing beyond its label shows only its label, its type,
its identifier and its vocabulary.

The concept's own canonical identifier leads the page, directly beneath its title, so a reader
citing the record does not have to scroll past everything it says about itself to find it. The
breadcrumb trail above names the site's home, the vocabulary holding the concept, and the concept
itself.

Each row's own term — `skos:definition`, `skos:broader`, and the rest — is the predicate as the
document stores it: a CURIE for a known namespace, and the full URI for any other. A record-valued
row's own displayed text is a different short form — `{vocabulary slug}:{record slug}`,
`geology:granite` for a concept "granite" in a vocabulary slugged "geology". A link to a record
this site does not hold is shown as its URI, and is a link to that address when it is a web
address.

A CURIE abbreviates a URI, and both kinds on the page disclose the URI they stand for on hover
rather than printing it. A term's comes from `Namespaces.expand()` in
`controlled_vocabularies.predicates`, which expands a CURIE against the six prefixes the package
fixes (`skos`, `dcterms`, `owl`, `rdf`, `rdfs` and `xsd`) and returns any other key unchanged. A
record-valued row's is the record's own canonical identifier. Hovering is not the only way to reach
either. A term is not interactive, so its URI sits beside it in a visually-hidden element a screen
reader reads out in place. A record-valued row's short form is a link, so its URI lives in a
visually-hidden element the link points at as its own description, which a screen reader reads out
and which keyboard focus reveals along with the tooltip.

Below the definition list and outside it, the page also names every collection that gathers the
concept, under a heading reading "Member of". Membership is a statement other records make about
this one — SKOS gives a collection's own membership property no inverse — so this section's heading
is plain language rather than a CURIE, and it names the direction, since a heading of "Collections"
would read as collections belonging to the concept. Each entry links to that collection's own page.
A concept no collection gathers shows no such section at all, never an empty one.

A file often states a hierarchy from one side only. A concept's page shows the broader, narrower and
related concepts it states itself, and also the ones other concepts of the vocabulary state about
it, turned around: a concept that names this one as its broader concept appears here as narrower,
and `skos:related` is read from either end.

Labels, definitions, notes, titles and descriptions are shown in the language the site is being
read in. Where the concept has none in that language, they fall back to the vocabulary's own default
language, one language at a time, never every language a value was recorded in, and then to values
that carry no language. Every other predicate shows all its values.

The concept's own identifier is shown as a link, the same treatment its vocabulary's own page gives
a vocabulary's: for an imported concept it is its publisher's identifier. An identifier is a link
only when it is an `http` or `https` address. One in any other scheme, such as a `urn:`, is shown as
text, so nothing an imported file names is handed to another program by a click. The page is
**read-only**, it carries no editing or deletion control, and it has no permission rule beyond what
the project mounting these routes chooses to add. Concepts are added by [importing](../how-to/load-the-vocabularies-your-site-uses.md).

An address naming no concept is reported not found, and so is one whose vocabulary segment names no
vocabulary — the two are not distinguished. A concept slug held by more than one vocabulary resolves
to the one the address actually names.

Reverse the page by name, passing the vocabulary's slug and the concept's own:

```python
reverse(
    "controlled_vocabularies_ui:concept-detail",
    kwargs={"slug": vocabulary.slug, "concept_slug": concept.slug},
)
```

The page is served by `ConceptDetailView`, in `controlled_vocabularies.ui.views`, and is subclassed
the same way as [a vocabulary's own page](a-vocabularys-own-page.md). The rows themselves come from `PropertyRows(record, language)`,
in `controlled_vocabularies.ui.rows`, whose `build()` returns the ordered rows — the seam a project
reaches for to build its own page, or its own rendering of a report, over the same rows this one
renders. `PropertyRows.in_reading_language()` is the rule that picks which entries of a translated
predicate to show.
