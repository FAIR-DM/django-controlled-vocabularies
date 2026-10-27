# How-to guides

Each guide takes you through one task in a project that already uses the package.

- **[Attach a concept to a model](attach-a-concept-to-a-model.md)** — `ConceptField`, the vocabularies it can name, and shipping a model in a reusable app.
- **[Attach several concepts to a model](attach-several-concepts-to-a-model.md)** — `MultiConceptField` and what it shares with `ConceptField`.
- **[Restrict a field to a collection](restrict-a-field-to-a-collection.md)** — Offer only the members of one collection.
- **[Restrict a field to a branch](restrict-a-field-to-a-branch.md)** — Offer only one branch of a vocabulary’s hierarchy.
- **[Choosing a concept](choosing-a-concept.md)** — The search-as-you-type control in your own forms and on Django admin pages.
- **[Prepare PostgreSQL for concept search](prepare-postgresql-for-concept-search.md)** — The extension and indexes search uses on PostgreSQL.
- **[Load the vocabularies your site uses](load-the-vocabularies-your-site-uses.md)** — Declare vocabularies and load them all with one command.
- **[Import a SKOS file from Python](import-a-skos-file-from-python.md)** — Call `import_skos()` yourself.
- **[Import a single file from the command line](import-a-single-file-from-the-command-line.md)** — Load one source by hand with `import_skos`.
- **[Read a row back as RDF](read-a-row-back-as-rdf.md)** — Turn a stored vocabulary or record into an `rdflib` graph.
- **[Upgrade from 0.1.0](upgrade-from-0-1-0.md)** — What to do on a site that used the earlier tables.
- **[Add the browsing pages to your site](add-the-browsing-pages-to-your-site.md)** — Install the `ui` extra, wire it up and mount the routes.
- **[Ask a page for RDF](ask-a-page-for-rdf.md)** — Fetch a vocabulary, concept or collection as RDF, or download it as a file.

```{toctree}
:hidden:

attach-a-concept-to-a-model
attach-several-concepts-to-a-model
restrict-a-field-to-a-collection
restrict-a-field-to-a-branch
choosing-a-concept
prepare-postgresql-for-concept-search
load-the-vocabularies-your-site-uses
import-a-skos-file-from-python
import-a-single-file-from-the-command-line
read-a-row-back-as-rdf
upgrade-from-0-1-0
add-the-browsing-pages-to-your-site
ask-a-page-for-rdf
```
