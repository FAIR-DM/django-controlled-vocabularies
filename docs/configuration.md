# Configuration

## The vocabularies your site uses

Declare every vocabulary your site uses in your Django settings, keyed by the slug your fields
name it by, and load them all with `python manage.py sync_vocabularies`:

```python
CONTROLLED_VOCABULARIES = {
    "rock-type": {"source": BASE_DIR / "vocabularies" / "rock-type.ttl"},
    "sample-status": {"source": "https://vocab.example.org/sample-status.ttl"},
}
```

Each `source` is a local path or an `http://`/`https://` address, with an optional `format` for a
source whose name does not carry its serialization. Prefer a file shipped with the project: a
deploy then never depends on a remote server being up. The setting is optional, and a site that
loads its vocabularies with `import_skos` alone can leave it out. Code of your own reads the
declarations with `controlled_vocabularies.conf.get_declared_vocabularies()`, which returns the
setting, or an empty dict when it is not set.
[Importing a published vocabulary](importing.md) covers the command and what each run does.

## Identifiers

Every vocabulary, concept and collection has a URI, which is its identity. A vocabulary imported
from a publisher keeps the URI its publisher gave it, held exactly as given and never rewritten. A
vocabulary or record created without a URI, in your own code, is given one once, when it is first
saved. That URI is composed from a base address and the row's slugs, and stays as it was made.

Set the base address in your Django settings:

```python
CONTROLLED_VOCABULARIES_BASE_URI = "https://vocab.example.org/vocabularies"
```

If you leave it unset, the app falls back to `http://localhost:8000/vocabularies` so it still
runs out of the box. Set a real address before you rely on it anywhere it is seen. A vocabulary's
composed URI is `{base}/{vocabulary-slug}`, a concept's is `{base}/{vocabulary-slug}/{record-slug}`,
and a collection's is `{base}/{vocabulary-slug}/collection/{record-slug}`, matching the addresses
their pages are served at.

A row's slug is made once, when the row is first saved, and is never changed afterwards. For a row
that arrives with a URI, the slug comes from the last part of that URI: its fragment where it has
one, otherwise its last path segment. For a row created without one, it comes from the row's
preferred label. Where another row already holds the slug, a number is added (`granite-2`).

A row's place in its vocabulary is what keeps its slug distinct, and the database enforces that. A
vocabulary's slug is unique across the site, and a record's slug is unique within its vocabulary.
A URI is unique across the site as well.

Nothing stops you changing a stored `uri` or `slug` by writing around the model, for example with
`QuerySet.update()`. That is deliberate. A published identifier is not supposed to move, but
keeping it still is a matter of not editing it, rather than of the model refusing every write
path. Treat a value that differs between two imports of the same vocabulary as a problem with the
source file.

### Where the base address matters

The base address only decides the URI of a row created without one. An imported row keeps its
publisher's URI whatever this setting says. The address a row is viewed at on your own site comes
from where you mount the browsing pages, and a system check warns when that disagrees with the
path of this setting (see [browsing vocabularies](browsing.md#a-vocabularys-own-page)).

## Database

The package runs on any database Django supports. On PostgreSQL, its migrations also enable the
`pg_trgm` extension and add the two trigram indexes concept search uses (see
[searching a large vocabulary](search.md#searching-a-large-vocabulary)). There is nothing to
configure, and `django.contrib.postgres` does not need to be in `INSTALLED_APPS`.

Enabling the extension needs a database user allowed to create one. `pg_trgm` is a trusted
extension, so any user with the `CREATE` privilege on the database can. Where the user that runs
your migrations cannot, have an administrator run `CREATE EXTENSION pg_trgm;` in the database
once, before migrating. Reversing the migration drops the two indexes and leaves the extension in
place, since another application may use it.

On any other database the migration adds neither, and search works without them.

---

Next: [attaching concepts to your models](fields.md).
