"""Tests for the CURIE prefixes and the predicate tables."""

import pytest

from controlled_vocabularies.predicates import (
    PREDICATE_ORDER,
    TRANSLATED_PREDICATES,
    Namespaces,
)


class TestNamespaces:
    @pytest.mark.parametrize(
        ("uri", "curie"),
        [
            ("http://www.w3.org/2004/02/skos/core#prefLabel", "skos:prefLabel"),
            ("http://purl.org/dc/terms/license", "dcterms:license"),
            ("http://www.w3.org/2002/07/owl#versionInfo", "owl:versionInfo"),
            ("http://www.w3.org/2001/XMLSchema#date", "xsd:date"),
        ],
    )
    def test_a_uri_in_a_known_namespace_is_compacted(self, uri, curie):
        assert Namespaces.compact(uri) == curie

    def test_a_uri_in_an_unknown_namespace_is_kept_whole(self):
        uri = "https://schema.org/keywords"

        assert Namespaces.compact(uri) == uri

    def test_a_local_name_no_curie_can_carry_is_kept_whole(self):
        uri = "http://www.w3.org/2004/02/skos/core#pref/label"

        assert Namespaces.compact(uri) == uri

    def test_the_namespace_itself_is_kept_whole(self):
        uri = "http://www.w3.org/2004/02/skos/core#"

        assert Namespaces.compact(uri) == uri

    def test_a_curie_expands_to_the_uri_it_abbreviates(self):
        assert Namespaces.expand("skos:broader") == (
            "http://www.w3.org/2004/02/skos/core#broader"
        )

    def test_a_full_uri_expands_to_itself(self):
        uri = "https://schema.org/keywords"

        assert Namespaces.expand(uri) == uri

    @pytest.mark.parametrize("curie", PREDICATE_ORDER)
    def test_every_listed_predicate_survives_a_round_trip(self, curie):
        assert Namespaces.compact(Namespaces.expand(curie)) == curie


class TestPredicateTables:
    def test_every_translated_predicate_is_one_the_pages_order(self):
        assert set(PREDICATE_ORDER) >= TRANSLATED_PREDICATES
