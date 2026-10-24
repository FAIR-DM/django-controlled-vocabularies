# Curating vocabularies

The `ui` extra's browsing pages (see [Browsing vocabularies](browsing.md)) also let a curator
create, edit and delete a vocabulary without the Django admin. This page covers what a curator
does, the permissions the pages check, and what a project mounts to offer them.

A **curator** is a signed-in user holding the vocabulary permissions below. The package defines
no group or role for it: a project grants the permissions however it grants any others.

## Who may do what

Each page checks one of Django's model permissions on `ConceptScheme`. A user without it gets a
403 page, and an anonymous visitor is sent to the project's `LOGIN_URL` with a `next` parameter.

| To | The user needs | Notes |
|---|---|---|
| Create a vocabulary | `controlled_vocabularies.add_conceptscheme` | |
| Edit a vocabulary | `controlled_vocabularies.change_conceptscheme` | Not offered for an imported vocabulary. |
| Delete a vocabulary | `controlled_vocabularies.delete_conceptscheme` | |

The list of vocabularies and a vocabulary's own page show a link only to a user who may follow it.
Hiding a link is a convenience; the page behind it checks the permission itself.

## Mounting the pages

The three pages are part of the browsing routes, so a project that already mounts
`controlled_vocabularies.ui.urls` has them. Given a mount at `browse/`:

| Page | Address |
|---|---|
| Create | `browse/-/new/` |
| Edit | `browse/<slug>/-/edit/` |
| Delete | `browse/<slug>/-/delete/` |

No slug the package derives can be `-`, so these addresses never take the place of a
vocabulary or concept whose slug is `new`, `edit` or `delete`.

The package provides no sign-in page. A project needs a working `LOGIN_URL`, for example
Django's own `django.contrib.auth.urls`. The demo project mounts them under `accounts/`.

## Creating a vocabulary

1. Sign in as a user holding `add_conceptscheme`.
2. On the list of vocabularies, choose **New vocabulary**.
3. Enter a name. It is the only required field.
4. Optionally add a description, a default language and the publication details: publisher,
   creator, licence, version and when the content last changed.
5. Choose **Create vocabulary**.

You land on the new vocabulary's page, with a message confirming it. The vocabulary holds no
concepts yet; add them by [importing a file](importing.md) or through your own code.

A few things the form decides for you:

- **The address is made from the name.** Entering "Rock Types" gives the address segment
  `rock-types`. A name with no letter or number in it is refused, because it would leave the
  vocabulary with no address, and so is a name whose address another vocabulary already holds.
  The form says which vocabulary holds it, and keeps everything else you typed.
- **The identifier is not asked for.** A vocabulary created here is identified by the address
  your project's `CONTROLLED_VOCABULARIES_BASE_URI` composes from its slug. Fixing an identifier
  by hand is what a publisher does, so it is left to [importing](importing.md).
- **The default language** is offered from the languages your project configures in `LANGUAGES`.
  Leave it blank to use the site's own default.

## Editing a vocabulary

1. Sign in as a user holding `change_conceptscheme`.
2. Open the vocabulary's page and choose **Edit**.
3. Change what you need and choose **Save changes**, or **Cancel** to leave it as it was.

You land back on the vocabulary's page, with a message confirming the save. The form offers the
same fields as creating, with these differences:

- **Renaming moves the address.** The address segment follows the name, so renaming "Rock Types"
  to "Stone Kinds" moves the vocabulary from `rock-types` to `stone-kinds`. The old address stops
  working: it is not redirected. A name whose address another vocabulary holds is refused, as when
  creating. Identifiers other systems recorded from the old address no longer resolve, so rename a
  vocabulary other people already cite with care.
- **The default language is fixed once the vocabulary holds concepts.** Each concept is identified
  by its label in that language, so changing it would change what the concepts are. The control is
  shown but disabled, and a request that tries to change it is refused with a message saying why.
  Until the first concept exists the language can still change, and choosing the blank "site
  default" option clears it.
- **An imported vocabulary cannot be edited.** A vocabulary that carries an identifier its
  publisher fixed belongs to the publisher, so **Edit** is not offered for it. A request for its
  edit page gets a 403 page, whoever asks and whatever they hold, a superuser included. To change
  one, change the source and [import it again](importing.md), or delete it and create your own.

A vocabulary deleted by someone else while you had its form open is reported as not found when you
save; saving never recreates it.

## Deleting a vocabulary

1. Sign in as a user holding `delete_conceptscheme`.
2. Open the vocabulary's page, or its edit page, and choose **Delete**.
3. Read what will go with it, then choose **Delete vocabulary**, or **Cancel** to keep it.

You land on the list of vocabularies, with a message confirming the delete. Deleting cannot be
undone, and it takes everything the vocabulary holds with it: every concept, with its labels,
notes and relations, and every collection. The confirmation page says how many concepts and
collections that is.

An imported vocabulary can be deleted like any other. Importing the same file again creates it
afresh, without whatever was added to it by hand.

### A vocabulary in use is never deleted

A concept that a record elsewhere on the site points at, through a `ConceptField` or a
`ConceptsField`, is protected. While any concept of the vocabulary is in use, the confirmation page
offers no **Delete vocabulary** button. It lists the models whose records use the vocabulary's
concepts, with how many records of each. A record that holds several of the concepts counts once.
A request sent to delete anyway deletes nothing and shows the same page.

To delete the vocabulary, change those records to use other concepts, or remove them, then try
again. The page lists the models, not the individual records, so look for them through those
models' own pages.

## Trying it in the demo project

The [demo project](browsing.md#try-it-the-demo-project) seeds a set of accounts, all with the
password `password`. `curator.user` holds exactly the three permissions above and nothing else;
`regular.user` holds none. Sign in at `http://127.0.0.1:8000/accounts/login/` as `curator.user`
to see the **New vocabulary** action.
