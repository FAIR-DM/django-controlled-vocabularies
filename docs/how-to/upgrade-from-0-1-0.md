# Upgrade from 0.1.0

Version 0.2.0 stores a vocabulary in two tables, `ConceptScheme` and `Record`, in place of the seven
earlier ones. The migrations start again at a new `0001_initial`, and no data migration is provided,
because the package is before 1.0. A site on 0.1.0 imports its vocabularies again from their
published files after upgrading. A concept attached to a row of your own models referred to a row of
the earlier tables, so it is attached again once the vocabularies are back.
