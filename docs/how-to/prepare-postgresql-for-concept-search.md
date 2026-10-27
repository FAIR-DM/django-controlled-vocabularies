# Prepare PostgreSQL for concept search

The package runs on any database Django supports. On PostgreSQL, its migrations also enable the
`pg_trgm` extension and add the two trigram indexes concept search uses (see
[searching a large vocabulary](choose-a-concept.md#searching-a-large-vocabulary)). There is
nothing to configure, and `django.contrib.postgres` does not need to be in `INSTALLED_APPS`.

Enabling the extension needs a database user allowed to create one. `pg_trgm` is a trusted
extension, so any user with the `CREATE` privilege on the database can. Where the user that runs
your migrations cannot, have an administrator run `CREATE EXTENSION pg_trgm;` in the database
once, before migrating. Reversing the migration drops the two indexes and leaves the extension in
place, since another application may use it.

On any other database the migration adds neither, and search works without them.
