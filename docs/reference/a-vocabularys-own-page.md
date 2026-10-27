# A vocabulary's own page

Every vocabulary the site holds has its own address, `{mount}/{slug}/`, under wherever the routes
are mounted. The page's title is the vocabulary's name, and its lead text is the vocabulary's
description, truncated the same way and for the same reason as [the list entry](finding-a-vocabulary.md). A vocabulary
with no description has no lead text.

The main column is every concept the vocabulary holds, and only that vocabulary's, in one flat,
alphabetical list: nothing several levels down a broader/narrower chain is nested under one above
it. Alphabetical order follows each concept's `pref_label`, its preferred label in the
vocabulary's default language. A concept carrying a label in the reader's own language shows that
one, and a concept with none in that language shows its default-language label, but the order is
the same whichever language is read.

Each row in the list carries:

- the concept's broader concept, above its label, when it has one (the first, when it has several)
- its label, linking to [the concept's own page](a-concepts-own-page.md)
- its definition, in the reader's language or the vocabulary's default language, cut to 30 words
- its identifier (`Record.uri`), as a link to that identifier itself rather than to the page here
  when it is a web address
- the collections that hold it, each linking to [the collection's own page](a-collections-own-page.md)

Anything a concept does not have is left out of its row. Alternative and hidden labels are never
shown. A vocabulary holding no concepts says so, in wording distinct from the page's other empty
state, and the rest of the page still renders.

Beside the list, a side panel describes the vocabulary itself:

- its identifier, as a link when it is a web address
- its default language
- its publication details: its publisher, its creator, its licence, its version and when it last
  changed (see "The vocabulary's own details" in [importing](../explanation/what-an-import-keeps.md#the-vocabularys-own-details)).
  A detail held as a web address is a link to it, and a detail the vocabulary does not have is shown
  as a dash.
- how many concepts it holds
- its top concepts, the ones with no broader concept, each linking to its page. A concept has a
  broader concept when it states one with `skos:broader` or another concept names it with
  `skos:narrower`. A vocabulary with
  no broader/narrower relations at all lists none, since every concept would be listed twice
- its collections (`skos:Collection` / `skos:OrderedCollection`), each linking to its page, with
  how many members it has and whether those members carry a deliberate order. A vocabulary
  holding no collections shows a dash.

The panel behaves as django-mvp's filter panel does on a list page: a column at the end of the
page from the `xl` breakpoint up, starting level with the list rather than the title and staying
in view as the page scrolls, and a drawer opened from an **About** button in the toolbar below that
width. Its root element carries the id `vocabulary-about`.

A search box narrows the list of concepts by every name a term goes by: a concept's preferred
label in any language it carries, its alternative labels, and its hidden labels — never its
definition or any other note. A hidden label is matched and never shown: searching for one finds
the concept it names without ever displaying the label itself, which is the whole point of
keeping it hidden. As with [the list of vocabularies](finding-a-vocabulary.md), the term travels in the page's own
address (`?q=`), so a narrowed list can be linked to, bookmarked and returned to, and it reaches
every concept in the vocabulary before paging divides the results — not only the page being
viewed. A search matching nothing says so, repeats what was searched for, and offers **Clear all**
as the way back to the whole vocabulary.

Case is ignored, with the same database-dependent limit disclosed on [the list of vocabularies](finding-a-vocabulary.md): SQLite folds ASCII
letters only, so a concept labelled *Ökologie* is found by *ÖKOLOGIE* and not by *ökologie*;
PostgreSQL folds the whole of Unicode and matches either way
([ADR 0014](../adr/0014-database-collation-differences-are-disclosed-not-repaired.md)).

Searching by address works the same as searching in the box: the demo project's own DCMI Type
Vocabulary carries a concept named *Dataset* with a hidden label of `Datset`, a plausible
misspelling — `?q=Datset` narrows the page to *Dataset* without the misspelling itself ever
appearing among the results, and the narrowed address can be shared and bookmarked the same as any
other. The term you typed is still repeated above the results, as on any search.

A sort control offers the concepts by label, A-Z or Z-A. The choice travels in the address as
`?o=`, next to any search term, exactly as it does on the list of vocabularies. It sorts by the
preferred label in the vocabulary's default language, the copy kept in `pref_label`. The search and
the sort are `ConceptFilter`, in `controlled_vocabularies.ui.filters`, and only the first ten words
of a search are used.

Reverse the page by name, passing the vocabulary's slug:

```python
reverse("controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": vocabulary.slug})
```

**The browsing routes must be mounted at the same path `CONTROLLED_VOCABULARIES_BASE_URI`
composes against**, or the identifier of a vocabulary created here does not lead back to its own
page. Mounting the routes at `browse/` means the setting's path has to be `/browse`, not the
package's own default:

```python
CONTROLLED_VOCABULARIES_BASE_URI = "https://example.org/browse"
```

`manage.py check` reports `controlled_vocabularies.ui.W001` — a warning, not an error, since a
project may serve identifiers through a reverse proxy this package cannot see — when the two
disagree, naming the mismatched paths. It is silent once they agree, and silent too if the
browsing routes are not mounted at all.

The page is served by `VocabularyDetailView`, in `controlled_vocabularies.ui.views`, and is
subclassed the same way as [the list](finding-a-vocabulary.md). The publication details are read by
`PublicationDetails.of(vocabulary)`, in `controlled_vocabularies.ui.rows`.
