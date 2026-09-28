# Research — 008 Run an import from the command line

Unknowns resolved before planning. Each entry states the question, what was measured or read, and
what the plan takes from it. Findings that changed the spec are marked.

## R1 — What the existing entry point needs from a source

`import_skos(file, *, serialization=None, scheme=None)` delegates to `SkosImporter`, whose
`run()` calls `SkosGraph.from_file(file, serialization=...)` (`skos.py:1922`). `from_file` takes a
path, requires `Path(file).is_file()`, guesses the serialization from the file extension when the
caller does not state it, scans RDF/XML and JSON-LD bytes for unsafe constructs, and only then
lets `rdflib` parse the file.

The scan runs on bytes read from the path, and `rdflib` then reads the file a second time from the
path itself. `from_file`'s own docstring records why that second read is deliberate: a file-based
parse establishes the base URI from the file's location, which pre-read `data=` bytes would
silently change (#50, D13).

**Taken into the plan:** a fetched source must reach this same function. Handing a URL to
`rdflib`'s own remote parsing would skip the safety scan entirely, which is the one thing
`UnsafeRdfXmlError` and `UnsafeJsonLdError` exist to prevent.

## R2 — Base URI, and why a temporary file is not sufficient on its own

**This finding changed the spec.** Measured against `rdflib` 7.6 in the project environment.

A published vocabulary may state its identifiers relative to the document that carries them, which
is ordinary SKOS: `<>` for the scheme, `<concept-a>` for a concept. Parsing resolves those against
the base URI, and the base URI comes from where the document was read.

| Source of the same bytes | Resulting concept identity |
|---|---|
| Parsed from `/tmp/tmpXXXX/vocab.ttl` | `file:///tmp/tmpXXXX/concept-a` |
| Parsed with the publisher's address as base | `https://example.org/concept-a` |

So downloading to a temporary file and importing that path gives a relative-URI vocabulary
identities derived from a temporary directory name — different on every run, and meaningless to
every other system. Article IX makes a concept's URI its identity, and #49 built the whole matching
path on the identifier a publisher assigned. A `file:///tmp/...` identity fails both.

Two consequences:

1. **The plan must carry the fetched document's address into the parse as its base URI.** A
   temporary file alone is not enough. `rdflib.Graph.parse` accepts `publicID` for exactly this,
   and it was confirmed to produce the publisher's identities from the same bytes.
2. **SC-002 as gated was wrong.** It said importing by URL and importing the identical bytes from
   disk produce the same records. For a document using relative URIs that is false, and it is
   false in the direction where the URL form is the correct one. The criterion has been amended to
   require sameness for absolute-URI documents and to require the publisher's address to be the
   base for a fetched one. This is a correction to a criterion drafted here, not a change to what
   the maintainer approved, and it is reported at the plan notification.

**Taken into the plan:** `SkosGraph.from_file` gains an optional base-URI argument threaded through
`SkosImporter` and `import_skos`, defaulting to today's behaviour so no existing caller changes. The
command supplies the URL when it fetched one and nothing when it read a path.

## R3 — Fetching with the standard library

`urllib.request.urlopen(url, timeout=...)` covers the whole requirement: HTTPS, redirects, a
timeout, and a status that raises `HTTPError` on a non-2xx answer. No new runtime dependency is
needed, which is what the spec assumed and what Article VII prefers.

Two measured behaviours shape the plan.

**`urlopen` opens `file://` URLs.** Passing `file:///tmp/secret.txt` returned the file's contents.
An operator can already read any local file by passing its path, so this is not an escalation of
what they can do. It matters for a different reason: with redirects followed automatically, the
scheme of the *final* request is chosen by the remote server rather than by the operator. Python's
own `HTTPRedirectHandler` restricts redirect targets to `http`, `https` and `ftp`, so `file://` is
already closed, but `ftp://` is not.

Checking the final URL on the response object does not close that: the response only exists once
`urlopen` has followed the redirect and completed the transfer, so the FTP connection has already
been made and the body already pulled. The fetch therefore uses an opener carrying the
`http`/`https` handlers alone, which has no handler for any other scheme and so raises before a
connection is attempted. Removing a handler, rather than adding a check.

**`build_opener` cannot build that opener** (corrected during T008, `decisions.md` D15). It merges
its own default handlers for every protocol not overridden by an instance of the same default
class, so `build_opener(HTTPHandler, HTTPSHandler, HTTPRedirectHandler, HTTPErrorProcessor)` still
carries a live `FTPHandler`, `FileHandler` and `DataHandler`. The opener is an `OpenerDirector()`
with six handlers added by hand instead: `HTTPHandler`, `HTTPSHandler`, `HTTPRedirectHandler`,
`HTTPErrorProcessor`, `UnknownHandler`, `HTTPDefaultErrorHandler`. The last two are what make an
unhandled scheme and a non-2xx status raise, rather than `open()` returning `None`.

**`urlopen`'s timeout is per socket operation, not per transfer.** It bounds each individual read,
so a server that answers slowly but continuously never trips it, and nothing bounds the number of
bytes written to the temporary file and then read again by the safety scan — whose own module
docstring names document size as the denial-of-service route it exists for. The copy is therefore
read in chunks against a byte ceiling and abandoned when it is passed.

**A Windows drive letter parses as a URL scheme.** `urlsplit("C:/vocab/skos.ttl").scheme` is
`"c"`. A rule of "has a scheme, therefore a URL" would send a Windows path down the network path.

**Taken into the plan:** the source is classified by an explicit `http://` / `https://` prefix test,
case-insensitive. Anything else is a filesystem path, except a value whose parsed scheme is longer
than one character, which is refused as an unsupported source. The single-character exemption is
what keeps `C:\` a path.

## R4 — Choosing the serialization for a fetched document

`rdflib.util.guess_format` maps file extensions only: `.ttl` → `turtle`, `.rdf` → `xml`, `.jsonld`
→ `json-ld`, and `None` for a name with no recognised extension. It knows nothing about media
types.

A URL frequently ends in a recognisable extension, so `guess_format` can be called on the URL's own
path. When it cannot answer, the response's `Content-Type` is the only other evidence, and after
that the operator has to say. The temporary file needs no matching suffix either way: a fetched
source always reaches `import_skos` with the serialization stated explicitly, or is refused before
it gets there, so `from_file`'s own guess is never consulted for one.

**Taken into the plan:** resolution order for a fetched source is the explicit `--format` option,
then the URL path's extension, then the response `Content-Type` mapped to the three supported
serializations, then a refusal naming what is missing and how to supply it. A local path keeps
today's behaviour untouched.

## R5 — Previewing inside a transaction

`SkosImporter.run` already wraps its work in `transaction.atomic()` (`skos.py:1925`), and raises
`SkosImportFailed` on a fatal finding, which is what rolls a refused run back today.

A dry run needs the opposite: roll back a run that *succeeded*. The Django pattern is an outer
`atomic()` block exited by raising a sentinel exception caught immediately outside it. The inner
`atomic()` becomes a savepoint, and the outer rollback discards everything including the savepoint.

**Taken into the plan:** the command wraps its call in an outer `atomic()` and raises a private
sentinel after capturing the report. The importer is not modified and knows nothing about
dry run, which is what keeps the dry run's report identical to a live one by construction
rather than by agreement.

## R6 — What the report already offers a renderer

`ImportReport` carries `created`, `updated`, `set_aside`, `absent_from_source`, `normalized` and
`fatal`, with `set_aside_by_reason()` grouping entries by reason and `language_account()` returning
counts per language. Every entry renders its own message through `render()`, in the caller's active
language at display time.

**Taken into the plan:** the renderer reads these directly and parses no rendered message, which is
the constraint `report.py`'s module docstring states for this feature. Nothing is added to
`ImportReport`.

## R7 — Where the code and its tests belong

Django resolves management commands from `<app>/management/commands/<name>.py`, so the path is
fixed by the framework. testing standard §4 mirrors the source tree, giving
`tests/test_management/test_commands/test_<name>.py` with `__init__.py` at each level.

Article XIV exempts management-command entry points from its cohesion rule, so `Command` stays the
framework's shape. The rendering and the source resolution are not entry points and do carry
subjects of their own, so each is a class.

**Taken into the plan:** the command module holds `Command`; source resolution and report rendering
are classes in sibling modules under the command package's own namespace, not in `exchange/`, since
neither has a second caller today (Article III).

## R8 — Serving a fixture over HTTP in tests

The suite uses `pytest-django` and `factory_boy` from the `mvp-shared[test]` bundle. Nothing in it
serves HTTP today, and `tests/fixtures/skos/` already holds the SKOS documents #50 and #51 use.

`http.server.ThreadingHTTPServer` on an ephemeral port, started in a fixture and torn down after,
serves a fixture file with a chosen status and `Content-Type` using only the standard library. That
covers every URL scenario the spec names: success, a non-2xx status, HTML content, and a redirect.
A connection that never answers is tested against a socket that accepts and never responds, so the
timeout is exercised without a real wait.

**Taken into the plan:** one HTTP stub fixture in `tests/conftest.py` or a sibling, reusable and
parameterised by status, body and content type. No new test dependency.
