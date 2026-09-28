# Tasks — 008 Run an import from the command line

Every task is test-first (Article I): the failing test comes before the code that satisfies it, in
the same task. Task ids are stable and never reused.

**No pre-existing test is modified.** The one change to existing code (T001) is a keyword argument
with a default, so #50's and #51's suites must pass unmodified — that is the regression proof, and
a task that needs to edit one of them has got the change wrong.

**Tasks have no issues** — this file and `feature-state.json` are the whole task record.

**US-2, US-3 and US-5 are sequenced, not parallel.** Each edits `handle()` in
`commands/import_skos.py` and two edit its argument parsing, so they run one at a time in any order,
each rebasing on the last. US-4 touches only `rendering.py` and runs alongside them.

## Phase 0 — Foundational (blocks every story)

- **T001** — The base URI thread through the exchange layer (FR-003, `research.md` R2,
  `decisions.md` D10).

  `SkosGraph.from_file` gains `base_uri: str | None = None`. When given, it is passed to
  `rdflib`'s parse as `publicID`; when omitted, the call is byte-for-byte what it is today and the
  parse takes its base from the file's own location. `SkosImporter.__init__` and `import_skos` gain
  the same keyword and pass it through untouched.

  The parameter changes **only** the base URI. It does not affect the `is_file()` check, the format
  guess, the safety scan, or which bytes are scanned — all of which continue to work from the path.

  The same keyword also decides what a refusal calls the source, in two places and two lines. In
  `from_file`, the three `SkosImportError`s built at `skos.py:216-248` take `base_uri or path` for
  their `file` param instead of `str(path)`. In `SkosImporter.run`, `source_label` (`skos.py:1923`)
  becomes `str(self.base_uri or self.file)`, which is what `VOCABULARY_AMBIGUOUS` and
  `VOCABULARY_UNDETERMINED` name. Without this a fetched document's every refusal names a temporary
  file that no longer exists by the time the operator reads it, and no later task delivers FR-014's
  "naming the source" for a URL. Both are no-ops when no base URI is given, so this stays additive.

  Add relative-identifier fixtures under `tests/fixtures/skos/`, **one per supported serialization**
  — `relative-uris.ttl`, `relative-uris.rdf`, `relative-uris.jsonld`. Each declares its scheme as an
  empty relative reference and two concepts declared relative (`concept-a`, `concept-b`), with
  `skos:prefLabel` in `en` and one `skos:broader` between them, so relative resolution is exercised
  on a subject, an object, and the scheme. FR-003 and SC-002 name no serialization, and rdflib's
  three parsers take their base from `publicID` by different routes, so Turtle's result does not
  carry over by inspection.

  Tests, parameterised over all three fixtures: parsed with
  `base_uri="https://example.org/vocab.ttl"` each yields `https://example.org/concept-a`; parsed
  without one each yields a `file://` identity derived from the fixture's own path; a document whose
  identifiers are absolute is unaffected by either. Add one test per message that a base URI is
  given and the raised message names the URL rather than the path. If a serialization turns out not
  to honour the base URI, stop and report it rather than working around it. Then run the full
  existing suite and confirm it is green **without edits** — record that in the task's report.

- **T002** — The package skeleton. `controlled_vocabularies/management/__init__.py`,
  `management/commands/__init__.py`, and the mirrored test packages
  `tests/test_management/__init__.py` and `tests/test_management/test_commands/__init__.py`
  (testing standard §4). No behaviour. Its test is `tests/test_standards.py` staying green, plus a smoke
  assertion that `call_command("import_skos", ...)` resolves the command rather than raising
  `CommandError: Unknown command` once T003 lands.

- **T015** — `ReportRenderer` in `management/rendering.py`. Takes an `ImportReport`, a verbosity and
  the dry run flag, and yields translated lines. This task covers the bucket counts: created,
  updated, set aside, normalized, absent from source.

  **Empty sections still print, saying so** (FR-007 read with #51's own FR-008): an absent section
  and a section reading zero are the same thing to a reader and different things to a caller.

  It is Foundational rather than US-4's opening task because the command prints through it from its
  first line. A US-1 that printed its own output would have that output — and the tests asserting
  it — rewritten by US-4, which is the one thing this task file forbids. US-3's dry run line is a
  flag on this class for the same reason.

  Tests: a report with content renders each count; a report with nothing in it renders every
  section as zero rather than omitting any. The renderer is exercised against a hand-built
  `ImportReport`, so none of this needs an import to run.

## US-1 — A vendored file imports from a terminal (P1)

- **T003** — `Command` in `management/commands/import_skos.py`. One positional `source` argument, a
  `--format` option, and `handle()` calling `import_skos(path, serialization=...)`. Output goes
  through T015's `ReportRenderer` from the first line — the command never prints a report itself, at
  this task or any later one. What the renderer says grows in US-4; where it is called from does
  not change again.

  `Command.help` and every argument's `help` are `gettext_lazy` from the first line written
  (Article XII) — retrofitting translation in US-6 is a sweep for misses, not the first pass.

  Tests: `call_command` against `tests/fixtures/skos/` on an empty database creates the vocabulary
  and its concepts; the output names the created counts; a second run against the same file reports
  updates and creates no duplicate concept.

- **T004** — A missing or unreadable path. `SkosImportError` from `from_file`'s own `is_file()`
  check is caught and re-raised as `CommandError`, which Django exits non-zero on and prints
  without a traceback. A path that exists but cannot be opened for permission reasons is reported
  as unreadable, distinctly from one that is absent (spec Edge Cases).

  Tests: a non-existent path exits non-zero, names the path, and writes nothing; an unreadable file
  gives the distinct message. Assert on the database being untouched in both, not only on the exit
  status.

- **T005** — `--format` reaches `from_file` as `serialization`. Tests: a fixture whose extension
  carries no recognisable format imports when `--format turtle` is given, and is refused with the
  existing unsupported-serialization message when it is not.

## US-2 — A vocabulary imports straight from its publisher (P1)

- **T006** — The HTTP stub fixture, in `tests/conftest.py` (testing standard §4 — reusable, not inlined).
  `http.server.ThreadingHTTPServer` bound to port 0, started in a thread, torn down on teardown,
  yielding a base URL. Parameterised per request by status, body bytes and `Content-Type`, so one
  fixture serves the success case, a 404, a 500, an HTML body, and a redirect. A second, smaller
  fixture opens a listening socket that accepts and never responds, for the timeout case
  (`research.md` R8). Standard library only — no new test dependency, and `deptry` stays green.

  Tests: the fixture itself is tested (`tests/test_conftest.py` is not a thing — assert it inside
  `tests/test_management/test_sources.py`'s first cases rather than testing the fixture in
  isolation).

- **T007** — `SourceResolver` classification, in `management/sources.py` (`research.md` R3,
  `decisions.md` D3). A class taking the raw argument and answering what kind of source it is:

  - begins `http://` or `https://`, case-insensitive → a URL;
  - parsed scheme is empty or exactly one character → a filesystem path (the one-character case is
    a Windows drive letter, and `urlsplit("C:/vocab.ttl").scheme` is `"c"`);
  - any other parsed scheme → refused as an unsupported source, naming the scheme.

  Tests: each rule as its own case, `C:/vocab/skos.ttl` classified as a path, `ftp://host/v.ttl`
  refused naming `ftp`, `HTTPS://host/v.ttl` classified as a URL, and a bare relative filename
  classified as a path.

- **T008** — The fetch. An explicit timeout, the body written to a plain temporary file, returning
  that path together with the URL as base URI. The temporary file is removed when the command
  finishes, on both the success and the failure path. It needs no serialization-carrying suffix:
  T009 either resolves the serialization or refuses the run, and the resolved value is passed to
  `import_skos` explicitly, so `from_file`'s extension guess (`skos.py:223`) is never consulted for
  a fetched document.

  **The fetcher is an opener carrying only the `http`/`https` handlers** — an
  `urllib.request.OpenerDirector()` with `HTTPHandler`, `HTTPSHandler`, `HTTPRedirectHandler`,
  `HTTPErrorProcessor`, `UnknownHandler` and `HTTPDefaultErrorHandler` added by hand
  — rather than `urlopen`'s default opener. **Not `build_opener`**, which merges its own defaults
  and would leave a live `FTPHandler` (`decisions.md` D15). Redirect targets are chosen by the remote server, and
  `HTTPRedirectHandler` permits `ftp` as well as `http` and `https` (`research.md` R3), so the
  default opener would open an FTP connection from the deployment host and only then let a check of
  the final URL reject the body. An opener with no handler for the scheme fails before the
  connection is attempted. This is the one check in the feature that is not about operator error,
  and it is a handler removed rather than a check added.

  **The copy stops at a byte ceiling.** The response is read in chunks and abandoned with a
  `CommandError` naming the URL once the ceiling is passed. `urlopen`'s timeout bounds each socket
  read, not the transfer, so a server answering slowly but continuously never trips it, and nothing
  else in the feature bounds the size of what is written and then read again by the safety scan
  (FR-014). One constant and one branch — no configuration surface. The operator cannot see how
  much a remote server intends to send, so this is not a guard against operator error.

  Tests: a served fixture is fetched and imported; the temporary file does not survive the call;
  a redirect to another `http` URL is followed and imported; a redirect to a non-`http(s)` scheme
  is refused; a response exceeding the ceiling is abandoned with a message naming the URL and
  writes nothing.

- **T009** — Serialization for a fetched document, resolved in order (`research.md` R4): explicit
  `--format`; then the URL path's extension via `rdflib.util.guess_format`; then the response
  `Content-Type` mapped to the three supported serializations; then a refusal naming what could not
  be determined and saying `--format` supplies it.

  Tests: each rung of the ladder reached in turn, including a URL with no extension whose
  `Content-Type` decides it, and a URL with neither, which is refused with the actionable message.

- **T010** — Fetch failures (FR-014). Unreachable host, a non-2xx status, a body that is not RDF,
  and a connection that never answers. Each is a `CommandError` naming the URL and what went wrong,
  exits non-zero, and writes nothing. An HTML body reaches the parser and fails as unreadable
  content, which is what the operator needs to hear, rather than parsing to an empty graph and
  reporting an empty vocabulary.

  The messages name the URL because T001 made `base_uri or file` the label every refusal carries;
  this task asserts that end to end rather than implementing it.

  Tests: one per failure mode, each asserting the exit status, the message naming the URL, and an
  unchanged database. The timeout case uses the non-responding socket fixture and a short timeout,
  so the suite does not wait.

- **T011** — Wire `SourceResolver` into `Command` and prove the parity the spec claims.

  Tests: importing a fixture served over the stub and importing the identical bytes from disk
  produce the same records and the same report, for a document whose identifiers are absolute
  (SC-002); the `relative-uris.ttl` fixture served over the stub is stored under the stub's own
  address rather than under any `file://` path (SC-002, FR-003); nothing anywhere records the URL.

## US-3 — A run can be dry-run before it is kept (P1)

- **T012** — The dry run flag and its rollback (`research.md` R5, `decisions.md` D4). A
  `--dry-run` flag wraps the `import_skos` call in an outer `transaction.atomic()` exited by
  raising a private sentinel carrying the report, caught immediately outside the block. The
  importer is not modified and learns nothing about dry run.

  The tests need a real transaction, so they use `transactional_db` rather than `db` — under the
  default `db` fixture the whole test already runs inside a transaction that is rolled back, which
  would make a broken dry run pass.

  Tests: a dry run against a populated database leaves every table unchanged, asserted by
  comparing row counts and the specific records before and after, not only by counting.

- **T013** — Dry run fidelity. A dry run and a live run against the same starting state produce
  equal reports (SC-003), and a source that would be refused is reported as refused when dry-run
  and still exits non-zero.

  Tests: the equality assertion compares the report's buckets rather than rendered text; the
  refusal case uses a fixture with a fatal finding and asserts both the non-zero exit and the
  unchanged database.

- **T014** — The dry run line. A dry run's output states that nothing was kept
  (FR-010, `decisions.md` D9), and a live run's does not. It is a flag on the renderer rather than
  a print in the command, so the two renderings differ in exactly one deliberate place.

  Tests: the line is present for a dry run and absent for a live run of the same source.

## US-4 — The account of what was set aside is readable at a terminal (P2)

`ReportRenderer` already exists and is already wired (T015, Foundational). Every task here adds a
method to it. Nothing in this story touches `commands/import_skos.py`, which is why it is the one
story that runs alongside the others rather than in sequence with them.

- **T016** — Set-asides grouped by reason with a count each, and the per-language account, both read
  from `report.set_aside_by_reason()` and `report.language_account()`. **No rendered message is
  parsed** — the constraint `report.py`'s module docstring states for this feature.

  Tests: a fixture producing several reasons renders one line per reason with the right counts; a
  fixture producing set-asides in several unconfigured languages renders the per-language counts;
  the renderer is exercised against a hand-built `ImportReport` as well as a real run, so the
  grouping is tested without a full import.

- **T017** — Records absent from the source render as their own section, separate from set-asides
  and not counted among them (FR-008, `decisions.md` D7).

  Tests: a re-import of a file with a concept removed names that concept as absent from the source
  and leaves the set-aside counts alone.

- **T018** — Verbosity (FR-007, `decisions.md` D6). At default verbosity no per-entry line is
  printed. At raised verbosity each set-aside entry prints, rendered by the entry's own `render()`,
  naming its subject and its reason. Django's `--verbosity` carries this; no new flag.

  Tests: an import setting aside several hundred values prints no per-value line at the default and
  one per value at verbosity 2; the count in the summary matches the number of detail lines.

*(T019 was the task that wired the renderer into `Command` and replaced US-1's own output. With
T015 in Foundational there is nothing to replace, so it is deleted rather than renumbered. Task ids
are never reused.)*

## US-5 — A refused run is unmistakable (P2)

- **T020** — Refusal handling in full. `SkosImportError` and `SkosImportFailed` are caught and
  re-raised as `CommandError`. `SkosImportFailed` carries every collected fatal finding and **all
  of them print**, not only the first (FR-011).

  Tests: a source with more than one fatal finding prints all of them; the exit status is non-zero;
  the database is unchanged.

- **T021** — The two refusals that matter most to this feature. A source declaring no concept
  scheme is refused as not being SKOS, which falls out of `VOCABULARY_UNDETERMINED` because the
  command names no target (FR-013, `decisions.md` D2). A source the safety scan refuses is refused
  with that reason and nothing parses it further.

  Tests: a scheme-less fixture exits non-zero with the not-SKOS message; the existing unsafe
  RDF/XML and JSON-LD fixtures under `tests/fixtures/security/` are refused through the command,
  proving the scan is reached from both source forms — the URL case served over the stub. Two
  further spec Edge Cases land here because they reach the same refusal: an empty file, and a file
  that parses to a graph carrying no SKOS content, are refused rather than importing an empty
  vocabulary. A source declaring more than one concept scheme is already refused by the importer,
  and the test asserts the command surfaces that refusal unchanged rather than reinterpreting it.

- **T022** — Exit status on a completed run (FR-012, `decisions.md` D5). A run that stored the
  vocabulary exits zero however much it set aside.

  Tests: an import into a site configured for a subset of the file's languages sets values aside and
  exits zero; the assertion is on the exit status specifically, since this is the bit a deployment
  script reads.

## US-6 — Translatable messages, documentation, and reusable test material (P3)

- **T023** — The i18n sweep (Article XII, FR-015). Every printed string and every help string is
  `gettext_lazy` with named placeholders so message identifiers stay static. This is a sweep for
  misses, not the first pass — earlier tasks wrap as they write.

  Tests: a check over the command package asserting no bare user-visible literal reaches output.
  Follow `tests/test_standards.py`'s existing approach rather than inventing a second mechanism.

- **T024** — Documentation (Article VI, FR-016). README documents the command, both source forms,
  the dry run flag and the verbosity behaviour, alongside the programmatic entry point.
  `CONTEXT.md` gains **dry run** in the "Importing published vocabularies" table. CHANGELOG
  records the addition.

  All three are public markdown: humanize before commit, and no internal handles.

- **T025** — Conformance and the whole-feature verification. Test modules mirror the source tree
  with `__init__.py` at each level (testing standard §4), fixtures are reusable rather than inlined, the
  full suite is green, coverage floors hold (project ≥ 90%, patch ≥ 85%), and `ruff`, `mypy` and
  `deptry` pass.

  This is the story-level full-suite run; earlier tasks run their own class or module only.
