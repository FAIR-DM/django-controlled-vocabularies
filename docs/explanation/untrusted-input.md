# Untrusted input

An imported file is treated as untrusted input. RDF/XML is scanned for entity expansion and
external references before a parser sees it. A JSON-LD document is refused rather than fetched if
its `@context` names a remote location, whether that is a plain string reference or an `@import`
reference tucked inside an inline object context. `import_skos()` itself never makes a network
request when reading a file — the command's own URL fetch (see below) happens first, and only the
fetched or local bytes ever reach this scan. An ordinary inline JSON-LD context, carrying no such
reference, imports normally.

`import_skos()` raises one of two exceptions, both `ValidationError` subclasses carrying a
translatable message. `SkosImportError` covers every reason a file cannot be turned into usable SKOS
at all: not found, not in a supported serialization, unparseable, a `skos:memberList` whose
`rdf:rest` chain loops back on itself, or refused by the safety scan above. `SkosImportFailed` covers the case where the file parses but the run collects one or more
fatal problems, and carries the same `ImportReport` its `fatal` bucket names them in.
`UnsafeRdfXmlError` and `UnsafeJsonLdError`, the two exceptions the safety scan itself raises, are
exported `SkosImportError` subclasses, so code that only catches `(SkosImportError,
SkosImportFailed)` already catches a file the safety scan refuses too.
