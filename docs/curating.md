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

The `-` segment can never be a vocabulary's slug, so these addresses never take the place of a
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

## Trying it in the demo project

The [demo project](browsing.md#try-it-the-demo-project) seeds a set of accounts, all with the
password `password`. `curator.user` holds exactly the three permissions above and nothing else;
`regular.user` holds none. Sign in at `http://127.0.0.1:8000/accounts/login/` as `curator.user`
to see the **New vocabulary** action.
