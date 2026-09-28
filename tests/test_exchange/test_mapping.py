"""``controlled_vocabularies.exchange.mapping`` — the SKOS predicate/model correspondence,
and, from 015-read-single-record T001, the opposite direction: a stored kind's CURIE.

Mirrors the module (testing standard §4). New module, so it carries no conformance declaration
of its own (tasks.md T001).
"""

import pytest
import rdflib

from controlled_vocabularies.exchange.mapping import (
    LABEL_CURIES,
    LABEL_PREDICATES,
    NOTE_CURIES,
    NOTE_PREDICATES,
    SKOS,
    skos_curie,
)
from controlled_vocabularies.models import ConceptLabel, ConceptNote

# Hand-written, restating the expectation rather than recomputing it (tasks.md T001) —
# the shape decisions.md D48 already established for these exact predicates in
# tests/test_exchange/test_skos.py's own `_COVERAGE_LABEL_NOTE_CURIE`.
_EXPECTED_LABEL_CURIES = {
    ConceptLabel.Kind.PREFERRED: "skos:prefLabel",
    ConceptLabel.Kind.ALTERNATIVE: "skos:altLabel",
    ConceptLabel.Kind.HIDDEN: "skos:hiddenLabel",
}
_EXPECTED_NOTE_CURIES = {
    ConceptNote.Kind.DEFINITION: "skos:definition",
    ConceptNote.Kind.SCOPE: "skos:scopeNote",
    ConceptNote.Kind.EXAMPLE: "skos:example",
    ConceptNote.Kind.EDITORIAL: "skos:editorialNote",
    ConceptNote.Kind.HISTORY: "skos:historyNote",
    ConceptNote.Kind.CHANGE: "skos:changeNote",
    ConceptNote.Kind.NOTE: "skos:note",
}


class TestSkosCurie:
    """The module-level CURIE formatter (moved here from ``exchange/skos.py``'s
    ``SkosGraph``, T001) — a namespace concern now living beside the namespace it
    depends on.
    """

    def test_formats_a_skos_predicate_as_a_curie(self):
        assert skos_curie(SKOS.prefLabel) == "skos:prefLabel"

    def test_raises_rather_than_mangling_a_predicate_outside_the_skos_namespace(self):
        # Slicing the namespace off by length with no check used to turn this into the
        # nonsensical "skos:tax-ns#type" — refusing it is the point of the guard.
        with pytest.raises(ValueError):
            skos_curie(rdflib.RDF.type)


class TestLabelCuries:
    """``LABEL_CURIES`` — the inverse of ``LABEL_PREDICATES``, derived rather than
    hand-written (T001, FR-003).
    """

    def test_matches_the_hand_written_expectation(self):
        assert LABEL_CURIES == _EXPECTED_LABEL_CURIES

    def test_every_label_predicates_kind_appears_in_the_inverse(self):
        # The no-second-edit property: adding a predicate to LABEL_PREDICATES is enough
        # for its kind to reach LABEL_CURIES. Compares two different structures (a
        # predicate->kind table against a kind->curie table's keys), so this is not
        # the same assertion as the hand-written comparison above and does not borrow
        # the implementation that builds LABEL_CURIES.
        assert set(LABEL_PREDICATES.values()) == set(LABEL_CURIES.keys())


class TestNoteCuries:
    """``NOTE_CURIES`` — the inverse of ``NOTE_PREDICATES``, same guarantee as
    ``LABEL_CURIES`` (T001, FR-003).
    """

    def test_matches_the_hand_written_expectation(self):
        assert NOTE_CURIES == _EXPECTED_NOTE_CURIES

    def test_every_note_predicates_kind_appears_in_the_inverse(self):
        assert set(NOTE_PREDICATES.values()) == set(NOTE_CURIES.keys())
