"""Tests for controlled_vocabularies.exchange.mapping."""

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

# Hand-written, so the expectation is not recomputed from the code under test.
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
    def test_formats_a_skos_predicate_as_a_curie(self):
        assert skos_curie(SKOS.prefLabel) == "skos:prefLabel"

    def test_raises_rather_than_mangling_a_predicate_outside_the_skos_namespace(self):
        # Without the guard this would slice into the nonsense "skos:tax-ns#type".
        with pytest.raises(ValueError):
            skos_curie(rdflib.RDF.type)


class TestLabelCuries:
    def test_matches_the_hand_written_expectation(self):
        assert LABEL_CURIES == _EXPECTED_LABEL_CURIES

    def test_every_label_predicates_kind_appears_in_the_inverse(self):
        # Adding a predicate to LABEL_PREDICATES must reach LABEL_CURIES without a
        # second edit.
        assert set(LABEL_PREDICATES.values()) == set(LABEL_CURIES.keys())


class TestNoteCuries:
    def test_matches_the_hand_written_expectation(self):
        assert NOTE_CURIES == _EXPECTED_NOTE_CURIES

    def test_every_note_predicates_kind_appears_in_the_inverse(self):
        assert set(NOTE_PREDICATES.values()) == set(NOTE_CURIES.keys())
