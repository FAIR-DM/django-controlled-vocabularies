# Load the vocabularies your site uses

One command loads every vocabulary a site uses, and refreshes them on every deploy:

```bash
python manage.py sync_vocabularies
```

It loads two kinds of vocabulary:

- every vocabulary a concept field on one of the site's models names (see
  [vocabularies your models name](#vocabularies-your-models-name))
- every vocabulary declared in the `CONTROLLED_VOCABULARIES` setting, which covers a vocabulary no
  field names, and lets a site choose where a vocabulary a field names is read from (see
  [declaring vocabularies](#declaring-vocabularies))

```python
# settings.py
CONTROLLED_VOCABULARIES = {
    "rock-type": {"source": BASE_DIR / "vocabularies" / "rock-type.ttl"},
    "sample-status": {"source": "https://vocab.example.org/sample-status.ttl"},
}
```

Run the command on every deploy: each run updates every vocabulary in place and never deletes
anything.

**Ship the file with the project where you can.** A source can be a local path or an
`http://`/`https://` address, but a file checked in beside your code is loaded the same way on
every machine and does not make a deploy depend on a remote server being up. A vocabulary your
project publishes itself works the same way: ship it as a SKOS file and declare it like any other.

## Vocabularies your models name

A concept field names each vocabulary by its URI, and can say where it is published (see
[attaching concepts to your models](attach-a-concept-to-a-model.md)):

```python
ROCK_TYPE = Vocabulary(
    "https://vocab.example.org/rock-type",
    source="https://vocab.example.org/rock-type.ttl",
)
```

`sync_vocabularies` goes through every concrete model the site installs, including the fields a
model inherits from an abstract one, and loads each vocabulary their fields name:

- A vocabulary is read from the field's `source`, or from its URI when the field gives none.
  Fetching a URI asks for Turtle, RDF/XML or JSON-LD, which a publisher serving several formats
  at one address answers with the vocabulary rather than its web page.
- A vocabulary several fields name is loaded once. The first field giving a source is used, and
  the command names any other source it did not read.
- A vocabulary the site declares in `CONTROLLED_VOCABULARIES` is loaded from the declaration
  instead, and no field's source is read for it.
- A source that publishes a vocabulary other than the one the field names is refused, and nothing
  is loaded from it.

A vocabulary loaded this way takes the slug derived from its URI (see
[slugs and addresses](../explanation/slugs-and-addresses.md)).

## Declaring vocabularies

`CONTROLLED_VOCABULARIES` is a dict. Each key is the slug the vocabulary is given on this site,
and each value holds:

- `source` — a local path, as a string or a `Path`, or an `http://`/`https://` address. A URL is
  fetched exactly as [the `import_skos` command](import-a-single-file-from-the-command-line.md)
  fetches one.
- `format`, optional — the serialization (`turtle`, `xml` or `json-ld`), for a source whose name
  or `Content-Type` does not carry one.

Each key must be a valid slug: letters, digits, hyphens and underscores. The key becomes the
vocabulary's slug when the command first loads it, in place of the slug an
import would derive from its URI, and it is how every later run finds the vocabulary again.

- A source that declares a vocabulary other than the one already held under its key is refused,
  and nothing about either changes.
- A source that declares no vocabulary of its own loads into the one already held under its key.
  With nothing held there yet, it is refused, since there is nothing to load it into.
- A vocabulary already loaded under a different slug, by `import_skos` for example, is reported
  and left as it is. It is never renamed, because pages and links may already use its slug.
  Declare it under the slug it has.

`manage.py check` warns about a field naming a vocabulary that is not loaded yet
(`controlled_vocabularies.W001`). See
[attaching concepts to your models](attach-a-concept-to-a-model.md).

## Loading every vocabulary

```bash
python manage.py sync_vocabularies
python manage.py sync_vocabularies rock-type https://vocab.example.org/mineral
python manage.py sync_vocabularies --dry-run
```

The declared vocabularies load first, then the ones fields name. Each is imported in a
transaction of its own, through the same import the
rest of this page describes, and gets its own report: how many records were created, updated and
absent from the source, naming each absent one, as `import_skos` prints. A record the source no
longer lists is reported and left alone, never deleted.

- Naming vocabularies limits the run to them. Name a declared one by its key and one a field
  names by its URI. A name that is neither is refused before anything is loaded.
- `--dry-run` performs every import and prints every report, then leaves the database exactly
  as it was.
- A vocabulary that fails, because its source cannot be fetched or read or the import refuses
  it, is reported with the reason, and nothing of it is kept. The others still load. The command
  exits non-zero if any failed, so a deployment script stops there.
