# 28. A row's RDF is its own document, plus its class when the document omits it

Date: 2026-10-27

## Status

Accepted.

## Context

A vocabulary's or record's page can return the row as RDF (#231), and the export of a whole
vocabulary will need the same graph for every row. Each row keeps every statement it was imported
with in its document (ADR 0024), so the graph can be built from the document alone.

Two things are not in a document. Statements other rows make about this one, such as the
`skos:narrower` a concept's page shows from the broader links other concepts state, or the
collections that list a concept as a member. And, for a row created on this site rather than
imported, its class: such a row's document may hold only a label and a description, while its
class is recorded by its model and, for a record, by its `type` column.

## Decision

A row's graph holds exactly the statements of its own document, with the row's identifier as the
subject, unchanged. Nothing is gathered from other rows and nothing is inferred. The one addition is
the row's class (`skos:ConceptScheme`, or the record's type) when the document states no `rdf:type`.
A document that states a type keeps exactly the types it states.

The graph is built in the core package (`document_graph()` and `to_graph()`), not in the browsing
pages, so the export and any consumer holding a row reach the same graph.

## Consequences

- An imported row comes out exactly as it was published, and reading it back gives the same
  statements, which the tests check for every row of the demo data in every offered format.
- A row created here says what it is, so the importer, which finds a vocabulary by its type, can
  read it back.
- A client wanting a concept's narrower concepts or its collections reads the rows that state them.
  A later export of a whole vocabulary holds those statements because it holds those rows.
