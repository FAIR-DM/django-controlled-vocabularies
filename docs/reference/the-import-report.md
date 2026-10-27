# The import report

The call returns an `ImportReport`, a plain dataclass rather than rendered text, so a caller can
inspect what happened without parsing anything:

- `created` / `updated` — the URIs of every vocabulary and record the run wrote.
- `absent_from_source` — the URIs of records that exist here but that the file no longer mentions.
- `held_elsewhere` — the URIs of subjects the file describes that belong to another vocabulary, left
  untouched.
- `fatal` — populated only on a failed run: a `FatalFinding` per reason the whole import was
  refused. A failed run raises `SkosImportFailed`, carrying this same report, and leaves the
  database exactly as it was before the run started.

A run is refused for one of these reasons, each a member of `FatalReason`:

- `MISSING_IDENTITY` — a concept, a collection or the vocabulary is a blank node, which cannot be
  identified again on a re-import.
- `REFUSED_IDENTITY` — a concept, a collection or the vocabulary has an identifier that starts with
  `javascript:`, `data:` or `vbscript:`. A stored identifier is rendered as a link, and these can
  carry executable content.
- `IDENTIFIER_TOO_LONG` — an identifier is longer than the 500 characters the `uri` column holds.
- `VOCABULARY_UNDETERMINED` — the file declares no vocabulary of its own and none was named.
- `VOCABULARY_TARGET_MISMATCH` — the file declares a vocabulary other than the one named.
- `VOCABULARY_AMBIGUOUS` — the file declares more than one vocabulary and none was named.

Nothing else in this list refuses a run, and a file that cannot be read as SKOS at all raises
`SkosImportError` (see [Untrusted input](../explanation/untrusted-input.md)). A run either succeeds in full or changes nothing: every problem in a
file is collected before any of it is written, and a fatal one rolls the whole run back. The
`sync_vocabularies` and `import_skos` management commands wrap this for use from a terminal.
There is no web-facing entry point yet.
