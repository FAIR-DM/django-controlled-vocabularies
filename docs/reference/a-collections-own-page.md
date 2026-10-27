# A collection's own page

Every collection has its own address too, at a distinct segment from a concept's,
`{mount}/{vocabulary-slug}/collection/{collection-slug}/`. The page is a definition list built the
same way a concept's is: its name (`skos:prefLabel`), a type row distinguishing an ordered
collection from an unordered one (`skos:Collection` or `skos:OrderedCollection`), and its members
under the membership property matching its kind — `skos:member` for an unordered collection,
`skos:memberList` for an ordered one, whose members appear in the sequence the file gave them.
Membership is one row however many members a collection holds — the property is stated once, with
every member listed beside it, rather than repeated per member. A collection holding no members says
so in plain language rather than showing an empty membership row.

Every record-valued row links to that record's own page here and discloses its canonical identifier
the same way a concept's page does. The collection's own identifier leads the page beneath its
title, its breadcrumb trail names the vocabulary holding it, and the page is equally **read-only**.

An address naming no collection is reported not found, and so is one whose vocabulary segment names
no vocabulary — the two are not distinguished, exactly as for a concept's page.

Reverse the page by name, passing the vocabulary's slug and the collection's own:

```python
reverse(
    "controlled_vocabularies_ui:collection-detail",
    kwargs={"slug": vocabulary.slug, "collection_slug": collection.slug},
)
```

The page is served by `CollectionDetailView`, in `controlled_vocabularies.ui.views`, and is
subclassed the same way as the pages above. Its rows come from the same `PropertyRows` a concept's
page uses.
