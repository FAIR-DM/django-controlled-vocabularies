# Importing a published vocabulary

`import_skos()` reads a SKOS file — Turtle, RDF/XML, or JSON-LD — and creates or updates the
vocabulary it declares, along with every concept it contains: identity, labels, documentary notes,
broader/narrower and related relationships, and collection membership. Every record is matched by
its static URI, never by name, so importing the same file twice updates the same rows rather than
duplicating them.

```python
from controlled_vocabularies.exchange import import_skos

report = import_skos("rocks.ttl")
```

The caller may name a target `ConceptScheme` for a file that declares no vocabulary of its own, or
have it checked against one the file does declare:

```python
report = import_skos("rocks.ttl", scheme=my_scheme)
```

Re-running an import upserts rather than deleting and recreating. For a record the file still
contains, the file is authoritative for that record's own content — labels, notes, relationships,
and collection membership end up matching the file exactly, including the removal of a value the
file no longer carries. A record the file does not mention at all is left completely untouched and
named in the report instead, never deleted.

## The vocabulary's own details

Besides its concepts, a file usually describes the vocabulary itself. Its name comes from the
scheme's `skos:prefLabel` and its description from `dcterms:description`. Five publication details
are kept as well, each in a field on `ConceptScheme`:

| Published as | Kept in |
|---|---|
| `dcterms:publisher` | `ConceptScheme.publisher` |
| `dcterms:creator` | `ConceptScheme.creator` |
| `dcterms:license` | `ConceptScheme.license` |
| `owl:versionInfo` | `ConceptScheme.version` |
| `dcterms:modified` | `ConceptScheme.modified` |

A detail published as text keeps the text, and one published as an address keeps the address, so a
licence given as `<https://creativecommons.org/licenses/by/4.0/>` is stored as that address. Each
field holds one value. Where a file gives several, such as two creators, the first in alphabetical
order is kept and each of the others is named in the report. `ConceptScheme.modified` is a date: a
typed `xsd:date`, a typed `xsd:dateTime` or untyped ISO 8601 text is read, a date and time keeps
only its date and says so in the report, and anything else is set aside.

The file is authoritative for these as for the description: a detail a later file no longer gives
is cleared.

## Languages

Labels and notes are matched by language, not only by predicate. A file's `en` value fills a site
configured for `en-gb`, and a file's `en-gb` value fills a site configured for `en`. Matching runs
on the base language, the first subtag of the tag, case-insensitively and in both directions, and
an exact tag match always wins over a variant.

Where a file offers several variants of one configured language, what happens next depends on how
many values that kind of label or note can hold:

- A preferred label holds one per language, so the variant the vocabulary predominantly publishes
  in is the one kept, with ties broken by language code. Each variant that lost is named in the
  report under its own published language.
- Alternative labels, hidden labels, and notes have no such limit, so every variant the file offers
  is stored.

A value stored under a variant match is named in the report as a substitution rather than applied
silently. That matters most where two variants differ by script. A site configured for `zh-Hans`
importing a vocabulary published only as `zh-Hant` receives that content, in a script its readers
may not be able to read. The report is what makes that visible, so a curator can decide what to do
about it.

The package stores content for every language code in `settings.LANGUAGES`. A project that declares
none inherits Django's own default list of 99 languages, so a vocabulary published in sixty
languages imports into all sixty. Narrowing `LANGUAGES` is how a site limits what an import stores.

## Slugs and addresses

A vocabulary's slug and a concept's slug are both derived from their own published identifier —
its fragment where it has one, otherwise the last segment of its path — assigned once, on first
import, and never recomputed by a later one. Renaming a record, or a vocabulary's name arriving in
a different language on a later import, never moves that record's local address; only the
publisher reassigning the identifier itself does. A record authored on this site rather than
imported has no published identifier to derive from, and keeps deriving its slug from its label,
as it always has.

That permanence has a cost worth naming: a vocabulary published under opaque codes gets an opaque
local address — `/v-113/00123` rather than `/soil-types/clay`. It is accepted because the address
is correct and stays correct, which is what every consumer of a URL needs from it, and because a
readable address that can move under data already pointing at it is worse than a stable one that
cannot.

## The report

The call returns an `ImportReport`, a plain dataclass rather than rendered text, so a caller can
inspect what happened without parsing anything:

- `created` / `updated` — the URIs of every vocabulary, concept, and collection the run wrote.
- `set_aside` — a `SetAsideEntry` per value the run could not store, each carrying a closed,
  translatable reason (an unconfigured language, a notation, a mapping to another vocabulary, a
  predicate the models have no place for, a missing relationship or collection member, and so on)
  and the data needed to render a message about it. Nothing a file contains is ever dropped in
  silence — a value the app cannot store is always named here.

  Published files are often not well-behaved, and the reasons cover that too. Where a pair of
  concepts is stated as both broader and related, the hierarchical statement wins, because SKOS
  declares the two disjoint, and the related one is set aside. A second preferred label in one
  language is set aside rather than refused at the database. An identifier whose own segment
  yields no usable slug is set aside naming the slug as the problem, not the identifier. A second
  value of one of the vocabulary's publication details is set aside as `SURPLUS_VALUE`, and a
  last-modified value that is not a date as `NOT_A_DATE`. None of these stops the rest of the
  vocabulary from importing.
- `absent_from_source` — the URIs of records that exist here but that the file no longer mentions.
- `normalized` — a `NormalizedEntry` per value the run stored, but under a different predicate than
  the one the file asserted (a foreign `dcterms:description` read as a concept's definition, for
  example), or in a different form (`DATE_FROM_DATE_TIME`, a last-modified date and time kept as
  its date).
- `fatal` — populated only on a failed run: a `FatalFinding` per reason the whole import was
  refused (a missing or blank-node identity, or a vocabulary that could not be resolved). A failed
  run raises `SkosImportFailed`, carrying this same report, and leaves the database exactly as it
  was before the run started.

A run either succeeds in full or changes nothing: every problem in a file is collected before any
of it is written, and a fatal one rolls the whole run back. The `import_skos` management command
wraps this for use from a terminal (see below). There is no web-facing entry point yet.

Reading a file never reassigns identity. A concept or collection whose URI is already held by a
different vocabulary stays where it is. So does one whose URI is held by a record of another kind,
such as a collection in one file and a concept in another. Both are set aside and reported. Moving
a record between vocabularies is a curatorial decision, not a side effect of reading a file.

## Untrusted input

An imported file is treated as untrusted input. RDF/XML is scanned for entity expansion and
external references before a parser sees it. A JSON-LD document is refused rather than fetched if
its `@context` names a remote location, whether that is a plain string reference or an `@import`
reference tucked inside an inline object context. `import_skos()` itself never makes a network
request when reading a file — the command's own URL fetch (see below) happens first, and only the
fetched or local bytes ever reach this scan. An ordinary inline JSON-LD context, carrying no such
reference, imports normally.

`import_skos()` raises one of two exceptions, both `ValidationError` subclasses carrying a
translatable message. `SkosImportError` covers every reason a file cannot be turned into usable SKOS
at all: not found, not in a supported serialization, unparseable, or refused by the safety scan
above. `SkosImportFailed` covers the case where the file parses but the run collects one or more
fatal problems (a missing or blank-node identity, or a vocabulary that cannot be resolved), and
carries the same `ImportReport` its `fatal` bucket names them in. `UnsafeRdfXmlError` and
`UnsafeJsonLdError`, the two exceptions the safety scan itself raises, are exported
`SkosImportError` subclasses, so code that only catches `(SkosImportError, SkosImportFailed)`
already catches a file the safety scan refuses too.

## Importing from the command line

The `import_skos` management command wraps `import_skos()` for use from a terminal or a
deployment script:

```bash
python manage.py import_skos rocks.ttl
```

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
  then leaves the database exactly as it was beforehand — useful for seeing what a file would set
  aside before deciding whether to configure a language for it.
- `--verbosity`, Django's own option, prints bucket counts by default — how many records were
  created, updated, set aside, normalized, or absent from the source, plus the set-aside account
  grouped by reason and by language. At `2` or above, every individual set-aside entry prints too.
  At `0` nothing prints at all, as with any Django command.

A refusal exits non-zero and prints every reason the run was refused. A run that sets values aside
still exits zero: importing a vocabulary published in more languages than a site is configured for
always sets some aside, so that outcome is treated as normal rather than as a failure a deployment
script should stop on.
