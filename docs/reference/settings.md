# Settings

## The vocabularies your site uses

`python manage.py sync_vocabularies` loads every vocabulary your models' concept fields name, with
no setting at all. Declare a vocabulary in your Django settings when no field names it, or when
you want it read from somewhere other than the source a field gives. Each is keyed by the slug the
vocabulary is given on this site:

```python
CONTROLLED_VOCABULARIES = {
    "rock-type": {"source": BASE_DIR / "vocabularies" / "rock-type.ttl"},
    "sample-status": {"source": "https://vocab.example.org/sample-status.ttl"},
}
```

Each `source` is a local path or an `http://`/`https://` address, with an optional `format` for a
source whose name does not carry its serialization. Prefer a file shipped with the project: a
deploy then never depends on a remote server being up. The setting is optional. Code of your own reads the
declarations with `controlled_vocabularies.conf.get_declared_vocabularies()`, which returns the
setting, or an empty dict when it is not set.
[Importing a published vocabulary](../how-to/load-the-vocabularies-your-site-uses.md) covers the command and what each run does.

## `CONTROLLED_VOCABULARIES_BASE_URI`

The base address a URI is composed from when a vocabulary or record is created without one. It
defaults to `http://localhost:8000/vocabularies`. How the address is used is explained under
[Identifiers](../explanation/identifiers.md).

```python
CONTROLLED_VOCABULARIES_BASE_URI = "https://vocab.example.org/vocabularies"
```
