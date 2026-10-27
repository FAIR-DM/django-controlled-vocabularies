# Finding a vocabulary

The `ui` extra adds one reader-facing page: every vocabulary the site holds, in alphabetical
order. Each entry is laid out as a concept is on [a vocabulary's own page](a-vocabularys-own-page.md)
and carries:

- its publisher, above its name, when it names one
- its name, linking to the vocabulary's own page
- its description, cut to 30 words
- how many concepts it holds, how many collections when it has any, and when it was last updated
  when it gives a date
- its identifier (`ConceptScheme.uri`), as a link when it is a web address

A site holding no vocabularies says so rather than showing an empty list.

A search box narrows that list by a vocabulary's name and description, not by the concepts it
holds. Finding a concept without already knowing which vocabulary holds it is not something this
page does. The term travels in the page's address (`?q=`), so a narrowed list can be linked to or
bookmarked and returned to. A second word **widens** the results rather than narrowing them:
matching is OR across every word and both fields, not AND, which is the opposite of what a search
box usually implies. A search matching nothing says so, repeats what was searched for, and offers
**Clear all** as the way back to the full list.

A sort control offers the list by name, A-Z or Z-A, by most concepts, or by most recently
updated, with vocabularies giving no date last. That choice travels in the address as `?o=`,
next to any search term, so a searched and sorted list is still one link you can share. Only the
orderings the view declares are honoured. Anything else in `?o=` is ignored rather than passed to
the database, and the page comes back in its default order. Two vocabularies with the same name
keep the same order across pages. Names sort by the vocabulary's name in its own default language,
which is the copy stored in `pref_label`.

Searching, sorting and moving between pages update the list in place, and the address bar follows,
so the back button and a copied link behave as they would after a full page load.

## Narrowing by publisher, licence and language

Beside the list, a filter panel narrows it by a vocabulary's publication details (see "The
vocabulary's own details" in [importing](../explanation/what-an-import-keeps.md#the-vocabularys-own-details)):

- **Publisher**, from the vocabulary's `dcterms:publisher`
- **Licence**, from its `dcterms:license`. A Creative Commons licence given by its address is
  named by its short name, such as *CC BY 4.0*. Any other licence is shown as given.
- **Language**, the vocabulary's default language.

Ticking several options of one facet keeps the vocabularies carrying any of them. Facets combine
with each other and with the search. Each option says how many vocabularies it would leave, counted
among those the search and the other facets leave, so the counts of a facet do not change when one
of its own options is ticked. A facet is offered only when at least two of the site's vocabularies
differ on it, so a site holding vocabularies from one publisher shows no publisher facet.

The choices travel in the address beside the search and the sort (`?publisher=…&license=…`), and
each applied one is shown above the list with a way to remove it. The panel is django-mvp's filter
panel, placed as the side panel on a vocabulary's own page is.

Case is ignored, with one limit that belongs to the database rather than to this package. SQLite
folds case for ASCII letters only, so a vocabulary named *Ökologie* is found by *ÖKOLOGIE* and not
by *ökologie*. PostgreSQL folds the whole of Unicode and matches either way. Django
[documents this](https://docs.djangoproject.com/en/stable/ref/databases/#substring-matching-and-case-sensitivity)
and does not work around it, and neither does this package, because nothing above the database can.
It matters for any site whose vocabularies are named in German, French, Greek or Russian.

The page carries **no permission rule of its own**. Every vocabulary in the database is listed to
anyone who reaches the URL, exactly as the concept search endpoint serves anyone who reaches
it, and for the same reason: a package cannot guess a project's access policy. A site that needs the
page restricted wraps the include where it mounts these routes.
