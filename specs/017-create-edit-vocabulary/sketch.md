# Sketch — 017-create-edit-vocabulary

## What exists

- **The vocabulary record** (`ConceptScheme`) has a name, a description, a default language and five
  publication details (publisher, creator, licence, version, last modified), plus a slug derived
  from the name and an optional fixed identifier (`static_uri`). Saving already refuses a slug
  collision, an empty slug, and a change of default language once the vocabulary holds concepts.
- **Imported or held here** is read from `static_uri`: set means a publisher fixed the identifier.
  The vocabulary page already shows this to anyone holding the change permission.
- **Deleting** a vocabulary cascades to its concepts, collections, labels, notes and relations. A
  concept a consuming project's record points at is protected (`PROTECT`) by both concept fields.
- **The browsing pages** are django-mvp list pages: the list of vocabularies, and a vocabulary's
  page with its concepts and an About side panel. Both have an empty actions slot beside the title.
- **django-mvp** provides create, update and delete views with crispy forms drawn by
  django-mvp-forms. The delete view already refuses a protected deletion and re-renders with an
  explanation.
- **The demo** had no sign-in and no accounts.

## What the screens need from the code

- The list of vocabularies needs to know whether the reader may add a vocabulary.
- A vocabulary's page needs to know whether the reader may edit this vocabulary (change
  permission and held here) and whether they may delete it.
- The edit form needs to know whether the vocabulary holds any concepts, to show the default
  language as fixed.
- The delete page needs the number of concepts and the number of collections the vocabulary holds.
- The delete page needs, when deletion is blocked, each kind of record that points at the
  vocabulary's concepts and how many of each.
- The form needs to refuse a name whose address is empty or already taken, as a field error, before
  saving.
- The editing addresses must not collide with a vocabulary's or a concept's own address. The sketch
  puts them behind a `-` segment (`/browse/-/new/`, `/browse/<vocabulary>/-/edit/`,
  `/browse/<vocabulary>/-/delete/`), which a generated slug can never be.
- The demo needs a sign-in page and the standard accounts, including a curator.

## What the sketch faked

- **The blocked deletion.** The demo has no model that points at a concept, so the delete page
  shows the blocked state with made-up records (Datasets: 3, Samples: 1) when the address carries
  `?preview=in-use`. The real state comes from the records protecting the concepts.
- **No tests, no documentation.** None of the views, the form or the templates has a test yet, and
  the package documentation does not describe these pages.
- **The form's layout imports crispy-forms directly**, which the package reaches only through
  django-mvp, so the dependency check fails on it. The plan decides whether crispy-forms becomes a
  declared dependency or the grouping is drawn another way.
- **The new demo seed** (a third, empty vocabulary and the sign-in accounts) lives in
  `seed_demo`. Whether it stays there is the plan's call.

## What was ruled by eye

Taste decisions taken for the first round, for review:

- The list of vocabularies gets one primary "New vocabulary" button beside its title.
- A vocabulary's page gets "Edit" and "Delete" as outline buttons beside its title, Delete in the
  error colour.
- The form starts with name, description and default language, untitled, then a "Publication
  details" group.
- The save button says what it does ("Create vocabulary", "Save changes"). Cancel is a quiet ghost
  button beside it.
- On the edit page, "Delete vocabulary" sits at the far end of the button row, as django-mvp
  places it.
- The delete page states the counts in a warning above the button, rather than listing every
  record that goes.
