# Import a single file from the command line

The `import_skos` management command loads one source by hand, without declaring it:

```bash
python manage.py import_skos rocks.ttl
```

The vocabulary takes the slug derived from its URI (see
[Slugs and addresses](../explanation/slugs-and-addresses.md)). To manage it with `sync_vocabularies` afterwards,
declare it under that slug.

The source can be a local filesystem path or an `http://`/`https://` URL, told apart by the value
itself rather than by a flag. A URL is fetched under a fixed 30-second read timeout, a fixed 50 MiB
response ceiling and a fixed ten-minute deadline for the whole transfer, over a connection that
only ever speaks http and https. The fetched document's identifiers resolve against the address it
was served from, following any redirect — so a vocabulary published behind a PURL or a `/latest`
alias is stored under the URIs its publisher assigned, and a re-import updates the same concepts
the first import created rather than making a second copy.

- `--format` names the source's serialization (`turtle`, `xml`, or `json-ld`), for a source whose
  extension or `Content-Type` does not.
- `--dry-run` performs the entire import and reports the outcome exactly as a live run would,
  then leaves the database exactly as it was beforehand — useful for seeing what a file would
  create and update before running it for real.
- `--verbosity`, Django's own option, prints how many records were created, updated, and absent
  from the source, then names each absent record, then how many belong to another vocabulary and
  were left untouched, naming each. A dry run adds a line saying nothing was kept. At
  `0` nothing prints at all, as with any Django command.

A refusal exits non-zero and prints every reason the run was refused.
