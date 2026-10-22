# Implementation Plan — 008 Run an import from the command line

**Branch**: `008-import-from-command-line` · **Spec**: [`spec.md`](spec.md) · **Research**: [`research.md`](research.md) · **Decisions**: [`decisions.md`](decisions.md)

## Summary

A Django management command wraps the import #50 and #51 built, so a deployment can load a
vocabulary from a terminal or a script. It takes one source, either a filesystem path or an
`http`/`https` URL, and offers a dry run that performs the whole import and then abandons the
transaction.

Almost all of the work is at the edges: classifying the source, fetching bytes and handing them to
the parser with the right base URI and serialization, wrapping a run so it can be discarded, and
turning `ImportReport` into something a person reads. The import itself is untouched.

One change reaches into the exchange layer. A fetched document's relative identifiers must resolve
against the address it came from, not against the temporary file it landed in, so `from_file` gains
an optional base URI threaded through `SkosImporter` and `import_skos` (`research.md` R2,
`decisions.md` D10). It defaults to today's behaviour and no existing caller changes.

## Technical Context

**Language/Version**: Python 3.11+ · **Framework**: Django 5.2 LTS and 6.0
**Runtime dependencies**: unchanged — `django`, `rdflib`, `defusedxml`. Fetching uses
`urllib.request` from the standard library (`research.md` R3), so Article VII needs no new
justification.
**Testing**: pytest + pytest-django + factory_boy from `mvp-shared[test]`. The HTTP stub is
`http.server.ThreadingHTTPServer` on an ephemeral port, standard library only (`research.md` R8).
**Storage**: no model changes, no migrations.
**Target**: any deployment installing this package.

**What exists and is being used, not rebuilt:**

| Surface | Where | Used for |
|---|---|---|
| `import_skos(file, *, serialization, scheme)` | `exchange/skos.py:1981` | the entire import |
| `SkosGraph.from_file` | `exchange/skos.py:195` | path check, format guess, safety scan, parse |
| `ImportReport` + `set_aside_by_reason()` + `language_account()` | `exchange/report.py` | everything the renderer prints |
| `SkosImportError` / `SkosImportFailed` | `exchange/exceptions.py` | the two refusals the command catches |
| `transaction.atomic()` inside `SkosImporter.run` | `exchange/skos.py:1925` | becomes a savepoint under the dry run's outer block |

## Constitution Check

| Article | Bearing on this feature |
|---|---|
| I — Test-First | Every task writes its failing test first. No pre-existing test is touched; the exchange change is additive with a default, so #50's and #51's suites must stay green unmodified — that is the regression proof for D10. |
| II — Simplicity | The command delegates and renders. No caching, no retry policy, no progress bar, no strictness flag. |
| III — Anti-Abstraction | The renderer and the source resolver are classes because each has a subject, not because a second implementation is coming. Neither goes in `exchange/`, which would imply a reuse that does not exist. |
| IV — Integration-First | The acceptance scenarios are the tests: `call_command` against real fixtures and a real HTTP stub, asserting on stored records and printed output. |
| V — Security & data-safety | Fetched content is untrusted and reaches the existing safety scan unchanged. The fetcher is built from an opener carrying only the `http`/`https` handlers, so a redirect onto another protocol fails before a connection is opened rather than after the transfer (`research.md` R3). The copy is bounded by a byte ceiling, since the operator cannot see how much a remote server intends to send (FR-014). |
| VI — Documentation | README documents the command, both source forms and the dry run. CHANGELOG records it. `CONTEXT.md` defines *dry run*. |
| VII — Dependency discipline | No new dependency. `deptry` must stay green. |
| XII — i18n | Every printed string and every help string is `gettext_lazy` with named placeholders. |
| XIII — Data-model conventions | No models, no migrations. Nothing to index. |
| XIV — Test structure | `tests/test_management/test_commands/test_import_skos.py`, with `__init__.py` at each level. The HTTP stub is a `conftest.py` fixture, not inlined. |
| XV — Cohesion | `Command` is a framework entry point and exempt. `SourceResolver` and `ReportRenderer` are classes. |

No violation requiring Complexity Tracking.

## Project Structure

### Documentation (this feature)

```
specs/008-import-from-command-line/
├── spec.md
├── research.md
├── decisions.md
├── plan.md
└── tasks.md
```

### Source code

```
controlled_vocabularies/
├── exchange/
│   └── skos.py                          # MODIFIED: optional base_uri through from_file/SkosImporter/import_skos
└── management/                          # NEW
    ├── __init__.py
    ├── sources.py                       # NEW: SourceResolver — classify, fetch, hand back a parsable local path + base URI
    ├── rendering.py                      # NEW: ReportRenderer — ImportReport to lines, at a verbosity
    └── commands/
        ├── __init__.py
        └── import_skos.py               # NEW: Command

tests/
├── conftest.py                          # MODIFIED: http_stub fixture
├── fixtures/skos/                       # MODIFIED: relative-URI fixtures added, one per serialization
└── test_management/                     # NEW
    ├── __init__.py
    ├── test_sources.py
    ├── test_rendering.py
    └── test_commands/
        ├── __init__.py
        └── test_import_skos.py
```

The command is named `import_skos`, matching the public function it wraps, so an operator reading
the README meets one name rather than two.

## Design

### The base URI thread (the only change to existing code)

`SkosGraph.from_file(file, *, serialization=None, base_uri=None)`. When `base_uri` is given it is
passed to `rdflib`'s parse as `publicID`; when it is not, nothing changes and the parse takes its
base from the file's own location, which is #50's D13 and stays correct for a local path.
`SkosImporter.__init__` and `import_skos` each gain the same keyword and pass it straight through.

The safety scan still runs on bytes read from the path, before any parse. The temporary file is
still a real file on disk, so `from_file`'s `is_file()` check, its format guess and its scan are all
reached exactly as they are today.

The same keyword also settles what a refusal calls the source. Every `SkosImportError` raised in
`from_file` names `str(path)`, and `SkosImporter.run` sets `source_label` from the same value, so a
fetched document's refusals would otherwise name a temporary file that no longer exists by the time
the operator reads the message. Both take `base_uri or file`, which is today's value whenever no
base URI is given. That is what delivers FR-014's "naming the source" for a URL.

**Test-first proof this is additive:** #50's and #51's suites run unmodified and stay green. A new
test asserts a relative-URI document parsed with a base URI yields the publisher's identities, and
the same document parsed without one yields the file's.

### Source resolution

`SourceResolver` takes the raw argument and yields what the importer needs: a path on disk and an
optional base URI. It has two paths and one refusal.

- **A path** — the value does not begin `http://` or `https://` (case-insensitive), and its parsed
  scheme is at most one character. Returned as-is, no base URI. A single-character scheme is a
  Windows drive letter, per `research.md` R3.
- **A URL** — fetched under a timeout through an opener built from the `http`/`https` handlers
  alone, written to a temporary file, returned with the URL as base URI. Because that opener carries
  no handler for any other protocol, a redirect onto one fails before a connection is opened —
  Python's default opener would have followed an `ftp://` redirect and only then let a post-hoc
  check reject the body. The copy stops at a byte ceiling, so an endless response fails instead of
  filling the disk. The temporary file needs no serialization-carrying suffix: the serialization is
  always resolved before the import and passed explicitly, so the extension guess is never
  consulted.
- **Anything else** — a parsed scheme longer than one character that is not `http`/`https` is
  refused as an unsupported source, naming the scheme.

Serialization for a fetched document resolves in order: the explicit `--format` option, the URL
path's extension, the response `Content-Type` mapped to the three supported serializations, then a
refusal saying what could not be determined and that `--format` supplies it (`research.md` R4).

The temporary file is removed when the command finishes, whether or not the import succeeded.

### Dry run

```
try:
    with transaction.atomic():
        report = import_skos(...)
        raise _DryRun(report)
except _DryRun as done:
    report = done.report
```

`SkosImporter.run`'s own `atomic()` becomes a savepoint inside this block, and the outer rollback
discards it along with everything else (`research.md` R5). The importer is not modified and knows
nothing about dry run, which is what makes the dry run's report identical to a live one by
construction. A refused run raises `SkosImportFailed` out of the block and rolls back for the same
reason it does today, so a dry-run refusal needs no separate path.

### Rendering

`ReportRenderer` takes an `ImportReport` and a verbosity and yields translated lines. Default
verbosity prints counts per bucket, then set-asides grouped by reason with a count each, then the
per-language account, then the records absent from the source. Raised verbosity adds one line per
set-aside entry, each rendered by the entry's own `render()`.

Sections that are empty still print, saying so. An absent section and a section reading zero are
the same thing to a reader and different things to a caller, which #51 already settled for the
language account (its spec, FR-008).

A dry run's output carries one extra line saying nothing was kept. That line is the only
difference between the two renderings, which is why it is a deliberate flag on the renderer and not
an incidental print in the command.

### Exit status and errors

`SkosImportError` and `SkosImportFailed` are caught and re-raised as `CommandError`, which Django
exits non-zero on and prints without a traceback. `SkosImportFailed` carries every collected fatal
finding, and all of them print. A completed run returns normally and exits zero however much it set
aside.

## Story to task mapping

| Story | Delivers |
|---|---|
| Foundational | package skeleton, `__init__.py` files, the base-URI thread through the exchange layer, `ReportRenderer` with its bucket counts |
| US-1 (P1) | `Command` with a path source, delegation to `import_skos`, the rendered output, missing-path failure |
| US-2 (P1) | `SourceResolver` fetch path, scheme rules, serialization resolution, HTTP stub fixture, relative-URI fixtures |
| US-3 (P1) | the dry run flag, the rollback, the "nothing was kept" line |
| US-4 (P2) | the renderer's account in full — grouping by reason, the language account, absent-from-source, verbosity |
| US-5 (P2) | refusal handling, exit statuses, all-findings printing |
| US-6 (P3) | i18n sweep, README, CHANGELOG, `CONTEXT.md` glossary, test-structure conformance |

US-1 depends on Foundational. US-6 depends on everything.

`ReportRenderer` sits in Foundational rather than in US-4 because US-3's "nothing was kept" line is
a flag on the renderer, and because a US-1 that printed its own minimal output would have to have
that output — and the tests asserting it — replaced by US-4. The renderer exists before anything
prints, US-1 wires it from its first line, and US-4 adds methods to it.

US-2, US-3 and US-5 each depend on US-1 and are **sequenced, not parallel**: all three edit
`handle()` in `commands/import_skos.py`, and two of them edit its argument parsing, so separate
worktrees would collide in one function at convergence. Any order, one at a time, each rebasing on
the last. US-4 touches only `rendering.py` and its own tests, so it runs alongside them.

## Complexity Tracking

No constitution violation requires justification here. Two decisions are worth naming because a
reviewer will otherwise ask:

- **Modifying `exchange/skos.py` in a feature that claims to add no import behaviour.** The change
  is a parameter with a default, and it exists because a fetched document has no other way to tell
  the parser where it came from (`decisions.md` D10). What a source *means* is unchanged.
- **A temporary file rather than parsing from memory.** `from_file`'s safety scan and format guess
  both work from a path, and its docstring records that a `data=` parse changes the base URI
  silently. Writing bytes to a real file keeps the fetched path and the local path identical from
  `from_file` inward, which is what FR-003 asks for.
