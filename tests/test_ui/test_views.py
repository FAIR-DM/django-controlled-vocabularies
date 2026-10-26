"""Tests for controlled_vocabularies.ui.views."""

import inspect
import itertools
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from django.db import connection
from django.http import Http404
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation
from django.utils.functional import Promise

from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.models import Record
from controlled_vocabularies.ui import views as views_module
from controlled_vocabularies.ui.rows import PropertyRows, PublicationDetails
from controlled_vocabularies.ui.views import CollectionDetailView, ConceptDetailView
from tests.factories import (
    ConceptSchemeFactory,
    RecordFactory,
    collection_with_members,
    labelled,
)
from tests.i18n_sweep import visit_fields_checks_source

LIST_URL = reverse("controlled_vocabularies_ui:vocabulary-list")

#: The vocabulary page's side panel, and the region holding its list of concepts.
SIDE_PANEL = "#vocabulary-about"
CONCEPT_ROWS = "#mvp-list li.list-row"

serial = itertools.count()


def text(value, language=None):
    """Return a literal entry, tagged with a language when one is given.

    Args:
        value: The literal.
        language: The language tag, or None for an untagged literal.

    Returns:
        The entry.
    """
    entry = {"@value": value}
    if language:
        entry["@language"] = language
    return entry


def link(uri):
    """Return a link entry.

    Args:
        uri: The address linked to.

    Returns:
        The entry.
    """
    return {"@id": uri}


def published(name=None, *, description=None, **details):
    """Create a vocabulary that gives publication details and a description.

    Args:
        name: Its English name; a unique one is made when omitted.
        description: Its English description.
        **details: Publication details by name (``publisher``, ``creator``, ``license``,
            ``version``, ``modified``).

    Returns:
        The saved vocabulary.
    """
    statements = {
        PublicationDetails.CURIES[key]: [text(value)] for key, value in details.items()
    }
    if description:
        statements["dcterms:description"] = [text(description, "en")]
    return ConceptSchemeFactory(
        data=labelled(name or f"Published {next(serial)}", statements=statements)
    )


def concept_with(scheme, label, **statements):
    """Create a concept with further statements.

    Args:
        scheme: The vocabulary.
        label: Its English preferred label.
        **statements: Further predicates, keyed by CURIE with ``:`` written as ``__``.

    Returns:
        The saved concept.
    """
    document = labelled(
        label,
        statements={key.replace("__", ":"): value for key, value in statements.items()},
    )
    return RecordFactory(scheme=scheme, data=document)


def gather(collection, *members):
    """Make a collection list further concepts as members.

    Args:
        collection: The collection.
        *members: The concepts to add.
    """
    collection.data.setdefault("skos:member", []).extend(
        link(member.uri) for member in members
    )
    collection.save()


def vocabulary_page(scheme):
    """Return the address of a vocabulary's page.

    Args:
        scheme: The vocabulary.

    Returns:
        The address.
    """
    return reverse(
        "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
    )


def concept_page(concept):
    """Return the address of a concept's page.

    Args:
        concept: The concept.

    Returns:
        The address.
    """
    return reverse(
        "controlled_vocabularies_ui:concept-detail",
        kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
    )


def collection_page(collection):
    """Return the address of a collection's page.

    Args:
        collection: The collection.

    Returns:
        The address.
    """
    return reverse(
        "controlled_vocabularies_ui:collection-detail",
        kwargs={"slug": collection.scheme.slug, "collection_slug": collection.slug},
    )


def visible_text(element) -> str:
    """Join an element's text, leaving out any ``.sr-only`` descendant.

    A disclosed identifier is a real DOM node inside a visually hidden span, so
    ``get_text()`` alone cannot tell text printed for every reader from text reachable only
    through a tooltip and an accessible description.

    Args:
        element: The parsed element to read.

    Returns:
        The element's text nodes concatenated.
    """
    return "".join(
        node
        for node in element.find_all(string=True)
        if node.find_parent(attrs={"class": "sr-only"}) is None
    )


def term_text(dt) -> str:
    """Read a ``<dt>``'s visible term, leaving out its hidden URI span.

    Args:
        dt: The parsed ``<dt>`` element.

    Returns:
        The term as a sighted reader sees it.
    """
    return visible_text(dt).strip()


def soup_of(response):
    """Parse a response.

    Args:
        response: The test client's response.

    Returns:
        The parsed page.
    """
    return BeautifulSoup(response.content, "html.parser")


def pairs_of(response):
    """Pair each term on a record's page with the text of its value.

    Args:
        response: The record page's response.

    Returns:
        ``(term, value)`` tuples in page order.
    """
    return [
        (term_text(dt), dt.find_next_sibling("dd").get_text(strip=True))
        for dt in soup_of(response)("dt")
    ]


def terms_of(response):
    """List the terms on a record's page.

    Args:
        response: The record page's response.

    Returns:
        The terms in page order.
    """
    return [term_text(dt) for dt in soup_of(response)("dt")]


def dd_after(soup, term):
    """Find the ``<dd>`` following a term's ``<dt>``.

    Args:
        soup: The parsed page.
        term: The term as a sighted reader sees it.

    Returns:
        The ``<dd>`` element paired with the term.
    """
    dt = next(dt for dt in soup("dt") if term_text(dt) == term)
    return dt.find_next_sibling("dd")


def listed_pks(response):
    """Return the primary keys of the objects a list response shows, in order.

    Args:
        response: The list page's response.

    Returns:
        The primary keys.
    """
    return [obj.pk for obj in response.context["object_list"]]


def submits_to(soup, name) -> str | None:
    """Return the id of the form an input submits with.

    An input belongs to the form named by its ``form`` attribute, else to the form it sits in.
    django-mvp draws the search box inside the filter form and the sort's input outside it, so
    a check reading only one of the two would miss the other.

    Args:
        soup: The parsed page.
        name: The input's ``name``.

    Returns:
        The form's id, or ``None`` when the input belongs to no form.
    """
    field = soup.find("input", attrs={"name": name})
    if field is None:
        return None
    if field.get("form"):
        return field["form"]
    form = field.find_parent("form")
    return form.get("id") if form else None


def facet_options(response, name) -> dict[str, str]:
    """Return a facet's options as the filter panel draws them, by value.

    Args:
        response: The list page's response.
        name: The facet.

    Returns:
        Each option's drawn label, count included, keyed by its value.
    """
    soup = soup_of(response)
    return {
        box["value"]: soup.find("label", attrs={"for": box["id"]}).get_text(
            " ", strip=True
        )
        for box in soup.find_all("input", attrs={"type": "checkbox", "name": name})
    }


def hrefs(response):
    """Return every address a page links to.

    Args:
        response: The test client's response.

    Returns:
        The ``href`` of every anchor on the page.
    """
    return {anchor["href"] for anchor in soup_of(response)("a", href=True)}


def query_count(client, url):
    """Count the queries a request runs.

    Args:
        client: The test client.
        url: The address to request.

    Returns:
        The number of queries.
    """
    with CaptureQueriesContext(connection) as captured:
        client.get(url)
    return len(captured.captured_queries)


@pytest.mark.django_db
class TestVocabularyList:
    def test_every_vocabulary_appears_exactly_once(self, client):
        schemes = ConceptSchemeFactory.create_batch(3)

        response = client.get(LIST_URL)

        assert response.status_code == 200
        assert sorted(listed_pks(response)) == sorted(scheme.pk for scheme in schemes)

    def test_a_vocabulary_added_after_the_first_request_appears_on_the_next(
        self, client
    ):
        client.get(LIST_URL)

        added = ConceptSchemeFactory()

        assert added.pk in listed_pks(client.get(LIST_URL))

    def test_an_empty_site_returns_200_with_no_vocabularies_listed(self, client):
        response = client.get(LIST_URL)

        assert response.status_code == 200
        assert listed_pks(response) == []


@pytest.mark.django_db
class TestVocabularyListEntry:
    @staticmethod
    def row_for(client, scheme):
        """Return the list row naming ``scheme``.

        Args:
            client: The test client.
            scheme: The vocabulary whose row to find.

        Returns:
            The row element.
        """
        soup = soup_of(client.get(LIST_URL))
        return next(
            row
            for row in soup.select("li.list-row")
            if row.find("a", href=vocabulary_page(scheme))
        )

    def test_the_counts_are_those_of_the_concepts_and_collections_it_holds(
        self, client
    ):
        populated = ConceptSchemeFactory()
        RecordFactory.create_batch(3, scheme=populated)
        RecordFactory(scheme=populated, type=Record.Type.COLLECTION)
        RecordFactory(scheme=populated, type=Record.Type.ORDERED_COLLECTION)
        empty = ConceptSchemeFactory()

        response = client.get(LIST_URL)

        counts = {
            scheme.pk: (scheme.concept_count, scheme.collection_count)
            for scheme in response.context["object_list"]
        }
        assert counts[populated.pk] == (3, 2)
        assert counts[empty.pk] == (0, 0)

    def test_an_entry_names_and_describes_its_vocabulary(self, client):
        scheme = published(
            "Geological Time Scale",
            description="Periods, epochs and ages of the geological record.",
        )

        row = self.row_for(client, scheme)

        assert row.find("a", href=vocabulary_page(scheme)).get_text(strip=True) == (
            "Geological Time Scale"
        )
        assert "Periods, epochs and ages" in row.get_text()

    def test_a_description_running_to_several_paragraphs_is_shortened(self, client):
        description = " ".join(f"word{index}" for index in range(400))
        scheme = published("Verbose", description=description)

        row = self.row_for(client, scheme)

        assert "word0" in row.get_text()
        assert "word399" not in row.get_text()

    def test_an_entry_shows_the_identifier_of_its_vocabulary_as_a_link(self, client):
        scheme = ConceptSchemeFactory(uri="http://publisher.example.org/vocab-1")

        anchor = self.row_for(client, scheme).find("a", href=scheme.uri)

        assert anchor.get_text(strip=True) == scheme.uri
        assert anchor.get("rel") == ["noopener"]

    def test_an_identifier_that_is_not_a_web_address_is_shown_but_not_linked(
        self, client
    ):
        scheme = ConceptSchemeFactory(uri="urn:nbn:example:vocab-1")

        row = self.row_for(client, scheme)

        assert row.find("a", href="urn:nbn:example:vocab-1") is None
        assert "urn:nbn:example:vocab-1" in row.get_text()

    def test_an_entry_names_its_publisher_when_it_gives_one(self, client):
        scheme = published(publisher="Dublin Core Metadata Initiative")

        row = self.row_for(client, scheme)

        assert "Dublin Core Metadata Initiative" in row.get_text()

    def test_an_entry_reports_the_number_of_concepts_it_holds(self, client):
        scheme = ConceptSchemeFactory()
        RecordFactory.create_batch(3, scheme=scheme)

        assert "3 concepts" in self.row_for(client, scheme).get_text()

    def test_a_vocabulary_with_no_concepts_reports_none_rather_than_blank(self, client):
        scheme = ConceptSchemeFactory()

        assert "0 concepts" in self.row_for(client, scheme).get_text()

    def test_an_entry_reports_its_collections_and_when_it_was_last_updated(
        self, client
    ):
        scheme = published(modified="2024-03-02")
        RecordFactory.create_batch(2, scheme=scheme, type=Record.Type.COLLECTION)

        with translation.override("en"):
            row_text = self.row_for(client, scheme).get_text()

        assert "2 collections" in row_text
        assert "2 March 2024" in row_text or "March 2, 2024" in row_text

    def test_a_vocabulary_with_no_collections_and_no_date_says_nothing_about_either(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        RecordFactory(scheme=scheme)

        row_text = self.row_for(client, scheme).get_text()

        assert "collection" not in row_text
        assert "·" not in row_text

    def test_a_vocabulary_with_no_description_renders_no_paragraph(self, client):
        scheme = ConceptSchemeFactory()

        assert self.row_for(client, scheme).find("p") is None


@pytest.mark.django_db
class TestVocabularyListOrdering:
    # Each test gives the vocabulary whose name sorts last a slug that sorts first, so a
    # slug-ordered page and a name-ordered one cannot agree by accident.

    def test_a_name_beginning_with_a_lowercase_letter_sorts_before_an_uppercase_one_later_in_the_alphabet(
        self, client
    ):
        zebra = ConceptSchemeFactory(name="Zebra", slug="aaa-sorts-first-by-slug")
        antelope = ConceptSchemeFactory(name="antelope")

        response = client.get(LIST_URL)

        # Byte order (capital Z = 0x5A, lowercase a = 0x61) would sort "Zebra" first.
        assert listed_pks(response) == [antelope.pk, zebra.pk]

    def test_two_requests_return_the_same_sequence(self, client):
        ConceptSchemeFactory.create_batch(5)

        assert listed_pks(client.get(LIST_URL)) == listed_pks(client.get(LIST_URL))

    def test_two_vocabularies_sharing_a_name_are_ordered_by_creation(self, client):
        # The first sorts last by slug, so only a real primary key tiebreak gives this order.
        first = ConceptSchemeFactory(name="Duplicate", slug="zzz-sorts-last-by-slug")
        second = ConceptSchemeFactory(name="Duplicate")

        assert listed_pks(client.get(LIST_URL)) == [first.pk, second.pk]

    def test_query_count_is_flat_regardless_of_how_many_vocabularies_the_site_holds(
        self, client, django_assert_num_queries
    ):
        ConceptSchemeFactory.create_batch(3)
        baseline = query_count(client, LIST_URL)
        ConceptSchemeFactory.create_batch(27)

        with django_assert_num_queries(baseline):
            client.get(LIST_URL)


@pytest.mark.django_db
class TestVocabularyListChosenOrdering:
    # ?o= does nothing unless the view's filterset declares a sort, and the sort control is drawn
    # only for one, so a view declaring none ignores it in silence.

    def test_the_page_offers_name_both_ways_size_and_recency(self, client):
        ConceptSchemeFactory()

        response = client.get(LIST_URL)

        options = response.context["filter"].filters["o"].options
        assert [key for key, _label, _columns in options] == [
            "name_asc",
            "name_desc",
            "concepts_desc",
            "modified_desc",
        ]

    def test_most_concepts_puts_the_largest_vocabulary_first(self, client):
        small = ConceptSchemeFactory(name="Alpha")
        RecordFactory.create_batch(1, scheme=small)
        large = ConceptSchemeFactory(name="Beta")
        RecordFactory.create_batch(3, scheme=large)

        response = client.get(LIST_URL, {"o": "concepts_desc"})

        assert listed_pks(response) == [large.pk, small.pk]

    def test_recently_updated_puts_the_newest_first_and_undated_ones_last(self, client):
        undated = published("Alpha")
        older = published("Beta", modified="2020-01-01")
        newer = published("Gamma", modified="2025-01-01")

        response = client.get(LIST_URL, {"o": "modified_desc"})

        assert listed_pks(response) == [newer.pk, older.pk, undated.pk]

    def test_choosing_z_to_a_reverses_the_page(self, client):
        zebra = ConceptSchemeFactory(name="Zebra", slug="aaa-sorts-first-by-slug")
        antelope = ConceptSchemeFactory(name="antelope")

        ascending = listed_pks(client.get(LIST_URL, {"o": "name_asc"}))
        descending = listed_pks(client.get(LIST_URL, {"o": "name_desc"}))

        assert ascending == [antelope.pk, zebra.pk]
        assert descending == [zebra.pk, antelope.pk]

    def test_the_chosen_order_is_marked_as_the_current_one(self, client):
        ConceptSchemeFactory()

        response = client.get(LIST_URL, {"o": "name_desc"})

        options = response.context["filter"].filters["o"].options
        label = next(label for key, label, _columns in options if key == "name_desc")
        assert response.context["sort_label"] == str(label)

    def test_an_ordering_nobody_offered_is_ignored_rather_than_obeyed(self, client):
        # `?o=` is matched against declared keys, so a field name or SQL fragment is neither
        # honoured nor an error.
        zebra = ConceptSchemeFactory(name="Zebra", slug="aaa-sorts-first-by-slug")
        antelope = ConceptSchemeFactory(name="antelope")

        response = client.get(LIST_URL, {"o": "-slug"})

        assert response.status_code == 200
        assert listed_pks(response) == [antelope.pk, zebra.pk]
        assert response.context["sort_label"] == ""

    def test_a_search_and_a_chosen_order_apply_together(self, client):
        ConceptSchemeFactory(name="Soil Zebra")
        ConceptSchemeFactory(name="Soil Antelope")
        ConceptSchemeFactory(name="Rock Badger")

        response = client.get(LIST_URL, {"q": "Soil", "o": "name_desc"})

        assert [v.pref_label for v in response.context["object_list"]] == [
            "Soil Zebra",
            "Soil Antelope",
        ]

    def test_the_sort_control_submits_to_the_same_form_as_the_search_box(self, client):
        ConceptSchemeFactory()

        soup = soup_of(client.get(LIST_URL))

        assert soup.find("form", id="filterForm") is not None
        assert submits_to(soup, "o") == "filterForm"


@pytest.mark.django_db
class TestVocabularyListFacets:
    def test_choosing_a_publisher_keeps_only_its_vocabularies(self, client):
        first = published(publisher="ODM2 Project")
        published(publisher="NASA")

        response = client.get(LIST_URL, {"publisher": "ODM2 Project"})

        assert listed_pks(response) == [first.pk]

    def test_choosing_two_publishers_keeps_the_vocabularies_of_either(self, client):
        first = published(publisher="ODM2 Project")
        second = published(publisher="NASA")
        published(publisher="BODC")

        response = client.get(LIST_URL, {"publisher": ["ODM2 Project", "NASA"]})

        assert sorted(listed_pks(response)) == sorted([first.pk, second.pk])

    def test_choosing_a_licence_keeps_only_its_vocabularies(self, client):
        licence = "https://creativecommons.org/licenses/by/4.0/"
        match = published(license=licence)
        published(license="https://creativecommons.org/publicdomain/zero/1.0/")

        response = client.get(LIST_URL, {"license": licence})

        assert listed_pks(response) == [match.pk]

    def test_a_known_licence_is_offered_by_its_short_name(self, client):
        published(license="http://creativecommons.org/licenses/by/4.0")
        published(license="Open Government Licence")

        options = facet_options(client.get(LIST_URL), "license")

        assert options["http://creativecommons.org/licenses/by/4.0"].startswith(
            "CC BY 4.0"
        )
        assert options["Open Government Licence"].startswith("Open Government Licence")

    def test_choosing_a_language_keeps_only_the_vocabularies_in_it(self, client):
        german = ConceptSchemeFactory(default_language="de")
        ConceptSchemeFactory(default_language="en")

        response = client.get(LIST_URL, {"language": "de"})

        assert listed_pks(response) == [german.pk]

    def test_a_facet_on_which_no_two_vocabularies_differ_is_not_offered(self, client):
        published(publisher="ODM2 Project")
        published(publisher="ODM2 Project")

        response = client.get(LIST_URL)

        assert "publisher" not in response.context["filter"].filters
        assert "license" not in response.context["filter"].filters

    def test_each_option_counts_the_vocabularies_it_would_leave(self, client):
        published(publisher="ODM2 Project")
        published(publisher="ODM2 Project")
        published(publisher="NASA")

        options = facet_options(client.get(LIST_URL), "publisher")

        assert options["ODM2 Project"].endswith("(2)")
        assert options["NASA"].endswith("(1)")

    def test_the_counts_follow_the_search(self, client):
        published("Soil one", publisher="ODM2 Project")
        published("Rock one", publisher="ODM2 Project")
        published("Rock two", publisher="NASA")

        options = facet_options(client.get(LIST_URL, {"q": "Soil"}), "publisher")

        assert options["ODM2 Project"].endswith("(1)")
        assert options["NASA"].endswith("(0)")

    def test_a_choice_narrows_the_other_facets_counts_and_not_its_own(self, client):
        cc_by = "https://creativecommons.org/licenses/by/4.0/"
        cc_zero = "https://creativecommons.org/publicdomain/zero/1.0/"
        published(publisher="ODM2 Project", license=cc_by)
        published(publisher="NASA", license=cc_zero)

        response = client.get(LIST_URL, {"publisher": "ODM2 Project"})

        assert facet_options(response, "publisher")["NASA"].endswith("(1)")
        assert facet_options(response, "license")[cc_zero].endswith("(0)")

    def test_an_applied_filter_is_named_without_its_count(self, client):
        published(publisher="ODM2 Project")
        published(publisher="NASA")

        response = client.get(LIST_URL, {"publisher": "ODM2 Project"})

        assert [
            refinement["value"] for refinement in response.context["refinements"]
        ] == ["ODM2 Project"]


@pytest.mark.django_db
class TestVocabularySearch:
    def test_a_word_from_the_name_narrows_to_that_vocabulary(self, client):
        match = ConceptSchemeFactory(name="Geological Time Scale")
        ConceptSchemeFactory(name="Soil Classification")

        response = client.get(LIST_URL, {"q": "Geological"})

        assert listed_pks(response) == [match.pk]

    def test_a_word_appearing_only_in_the_description_narrows_too(self, client):
        match = published("Alpha", description="Covers stratigraphy and rock units")
        published("Beta", description="Covers something else entirely")

        response = client.get(LIST_URL, {"q": "stratigraphy"})

        assert listed_pks(response) == [match.pk]

    def test_matching_ignores_case(self, client):
        match = ConceptSchemeFactory(name="Geological Time Scale")
        ConceptSchemeFactory(name="Soil Classification")

        response = client.get(LIST_URL, {"q": "geological"})

        assert listed_pks(response) == [match.pk]

    @pytest.mark.parametrize(
        ("name", "term"),
        [
            ("Ecology", "ECOLOGY"),
            ("Ökologie", "ökologie"),
            ("Гидрология", "ГИДРОЛОГИЯ"),
        ],
    )
    def test_matching_ignores_case_in_any_script(self, client, name, term):
        match = ConceptSchemeFactory(name=name)
        ConceptSchemeFactory(name="Soil Classification")

        response = client.get(LIST_URL, {"q": term})

        assert listed_pks(response) == [match.pk]

    @pytest.mark.parametrize("term", ["%", "_", "'"])
    def test_a_term_containing_a_like_wildcard_or_a_quote_is_looked_for_literally(
        self, client, term
    ):
        ConceptSchemeFactory.create_batch(3)

        assert listed_pks(client.get(LIST_URL, {"q": term})) == []

    def test_a_non_latin_term_matches_its_vocabulary(self, client):
        match = ConceptSchemeFactory(name="地質年代")
        ConceptSchemeFactory(name="Soil Classification")

        response = client.get(LIST_URL, {"q": "地質"})

        assert listed_pks(response) == [match.pk]

    def test_a_search_far_longer_than_any_real_one_still_answers(self, client):
        ConceptSchemeFactory(name="Geology")
        term = " ".join(f"word{index}" for index in range(600))

        assert client.get(LIST_URL, {"q": term}).status_code == 200

    def test_a_search_past_the_bound_keeps_its_first_words_and_drops_the_rest(
        self, client
    ):
        # Matching is OR, so a truncated term is answered on its first 100 words alone.
        # Zero-padded so no word is a substring of another.
        early = ConceptSchemeFactory(name="word003 vocabulary")
        late = ConceptSchemeFactory(name="word500 vocabulary")
        term = " ".join(f"word{index:03d}" for index in range(600))

        response = client.get(LIST_URL, {"q": term})

        assert early.pk in listed_pks(response)
        assert late.pk not in listed_pks(response)

    def test_a_search_of_nothing_but_whitespace_is_not_a_search(self, client):
        ConceptSchemeFactory.create_batch(2)

        assert len(listed_pks(client.get(LIST_URL, {"q": "   "}))) == 2

    def test_a_whitespace_only_search_does_not_come_back_in_the_box(self, client):
        ConceptSchemeFactory.create_batch(2)

        soup = soup_of(client.get(LIST_URL, {"q": "   "}))

        assert soup.find("input", attrs={"name": "q"}).get("value", "") == ""

    def test_the_search_input_belongs_to_a_get_form_that_actually_exists(self, client):
        ConceptSchemeFactory()

        soup = soup_of(client.get(LIST_URL))

        form = soup.find("form", id="filterForm")
        assert form is not None
        assert form.get("method", "").lower() == "get"
        assert submits_to(soup, "q") == "filterForm"
        assert form.find(attrs={"type": "submit"}) is not None


@pytest.mark.django_db
class TestVocabularySearchAcrossRequestsAndPages:
    def test_requesting_the_same_search_address_twice_returns_the_same_set_in_the_same_order(
        self, client
    ):
        ConceptSchemeFactory(name="Stratigraphy Unit A")
        ConceptSchemeFactory(name="Stratigraphy Unit B")
        ConceptSchemeFactory(name="Soil Classification")

        first = listed_pks(client.get(LIST_URL, {"q": "Stratigraphy"}))
        second = listed_pks(client.get(LIST_URL, {"q": "Stratigraphy"}))

        assert first == second
        assert len(first) == 2

    def test_following_the_rendered_link_to_page_two_keeps_the_search_applied(
        self, client
    ):
        matching = [
            ConceptSchemeFactory(name=f"Stratigraphy Unit {i:02d}") for i in range(30)
        ]
        ConceptSchemeFactory.create_batch(5)

        first_page = client.get(LIST_URL, {"q": "Stratigraphy"})
        first_page_pks = set(listed_pks(first_page))
        assert len(first_page_pks) == first_page.context["paginator"].per_page

        # Read the link from the markup: a hand-built ?page=2 would hide a broken
        # query-string tag.
        page_two_href = next(
            href for href in hrefs(first_page) if "page=2" in href and "q=" in href
        )

        second_page = client.get(LIST_URL + page_two_href)

        assert second_page.status_code == 200
        second_page_pks = set(listed_pks(second_page))
        matching_pks = {scheme.pk for scheme in matching}
        assert second_page_pks.isdisjoint(first_page_pks)
        assert first_page_pks | second_page_pks == matching_pks


@pytest.mark.django_db
class TestVocabularySearchEmptyState:
    def test_a_search_matching_nothing_returns_200_and_echoes_the_term(self, client):
        ConceptSchemeFactory(name="Soil Classification")

        response = client.get(LIST_URL, {"q": "Stratigraphy"})

        assert response.status_code == 200
        assert "Stratigraphy" in response.content.decode()

    def test_a_search_matching_nothing_offers_a_link_back_to_the_unsearched_list(
        self, client
    ):
        ConceptSchemeFactory(name="Soil Classification")

        assert LIST_URL in hrefs(client.get(LIST_URL, {"q": "Stratigraphy"}))

    def test_an_empty_site_with_no_search_shows_no_link_back_to_the_unsearched_list(
        self, client
    ):
        assert LIST_URL not in hrefs(client.get(LIST_URL))

    def test_a_term_containing_markup_is_escaped_in_the_response(self, client):
        # Scoped to the applied-search chip, where the term is repeated, because the page's own
        # theme-toggle script is a <script>. An unescaped term parses as a real <script> inside
        # the chip.
        ConceptSchemeFactory(name="Soil Classification")

        response = client.get(LIST_URL, {"q": "<script>alert(1)</script>"})
        refinements = soup_of(response).find(class_="mvp-list-refinements")

        assert refinements.find("script") is None
        assert "<script>alert(1)</script>" in refinements.get_text()


@pytest.mark.django_db
class TestVocabularyDetail:
    def test_a_known_vocabulary_serves_its_page_anonymously(self, client):
        scheme = ConceptSchemeFactory()

        assert client.get(vocabulary_page(scheme)).status_code == 200

    def test_a_slug_nothing_has_returns_404(self, client):
        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": "no-such-vocabulary"},
            )
        )

        assert response.status_code == 404

    def test_the_page_title_is_the_vocabularys_name(self, client):
        scheme = ConceptSchemeFactory(name="Geological Time Scale")

        response = client.get(vocabulary_page(scheme))

        assert response.context["page"]["title"] == "Geological Time Scale"

    def test_a_vocabulary_named_in_a_non_latin_script_still_serves_its_own_page(
        self, client
    ):
        # <str:slug>, not <slug:slug>: Django's slug converter matches ASCII only.
        scheme = ConceptSchemeFactory(name="地質年代")

        assert client.get(vocabulary_page(scheme)).status_code == 200


@pytest.mark.django_db
class TestVocabularyDetailDescriptionAndIdentifier:
    def test_a_vocabulary_with_a_description_leads_with_it(self, client):
        scheme = published(
            description="Periods, epochs and ages of the geological record."
        )

        response = client.get(vocabulary_page(scheme))

        assert response.context["page"]["subtitle"] == (
            "Periods, epochs and ages of the geological record."
        )

    def test_a_vocabulary_with_no_description_has_no_lead(self, client):
        scheme = ConceptSchemeFactory()

        response = client.get(vocabulary_page(scheme))

        assert not response.context["page"]["subtitle"]

    def test_the_lead_is_read_in_the_active_language(self, client):
        scheme = ConceptSchemeFactory(
            data=labelled(
                "Rocks",
                statements={
                    "dcterms:description": [
                        text("About rocks.", "en"),
                        text("Über Gesteine.", "de"),
                    ]
                },
            )
        )

        with translation.override("de"):
            response = client.get(vocabulary_page(scheme))

        assert response.context["page"]["subtitle"] == "Über Gesteine."

    def test_a_description_running_to_several_paragraphs_is_shortened(self, client):
        description = " ".join(f"word{index}" for index in range(400))
        scheme = published(description=description)

        content = client.get(vocabulary_page(scheme)).content.decode()

        assert "word0" in content
        assert "word399" not in content

    def test_a_vocabulary_links_to_the_identifier_it_has(self, client):
        scheme = ConceptSchemeFactory(uri="http://publisher.example.org/vocab-1")

        panel = soup_of(client.get(vocabulary_page(scheme))).select_one(SIDE_PANEL)
        anchor = panel.find("a", href=scheme.uri)

        assert anchor.get_text(strip=True) == scheme.uri
        assert anchor.get("rel") == ["noopener"]

    def test_a_vocabulary_held_here_links_to_the_address_this_site_composes(
        self, client
    ):
        scheme = ConceptSchemeFactory()

        panel = soup_of(client.get(vocabulary_page(scheme))).select_one(SIDE_PANEL)

        assert panel.find("a", href=scheme.uri) is not None

    def test_an_identifier_that_is_not_a_web_address_is_shown_but_not_linked(
        self, client
    ):
        scheme = ConceptSchemeFactory(uri="urn:nbn:example:vocab-1")

        panel = soup_of(client.get(vocabulary_page(scheme))).select_one(SIDE_PANEL)

        assert panel.find("a", href="urn:nbn:example:vocab-1") is None
        assert "urn:nbn:example:vocab-1" in panel.get_text()

    def test_the_default_language_is_named_in_the_side_panel(self, client):
        scheme = ConceptSchemeFactory(default_language="de")

        response = client.get(vocabulary_page(scheme))

        language_name = str(response.context["language_name"])
        assert language_name != "de"
        assert language_name in response.content.decode()

    def test_a_language_django_does_not_know_is_shown_by_its_code(self, client):
        scheme = ConceptSchemeFactory(default_language="xx-unknown")

        response = client.get(vocabulary_page(scheme))

        assert response.context["language_name"] == "xx-unknown"


@pytest.mark.django_db
class TestVocabularyDetailPublicationDetails:
    @staticmethod
    def details(client, scheme):
        return soup_of(client.get(vocabulary_page(scheme))).find(
            id="vocabulary-publication"
        )

    def test_each_publication_detail_is_shown(self, client):
        scheme = published(
            publisher="Gem Survey",
            creator="A. Lapidary",
            license="CC BY 4.0",
            version="2.1",
            modified="2026-03-14",
        )

        values = [dd.get_text(strip=True) for dd in self.details(client, scheme)("dd")]

        assert values[:4] == ["Gem Survey", "A. Lapidary", "CC BY 4.0", "2.1"]
        assert "2026" in values[4]

    def test_a_detail_given_as_an_address_links_to_it(self, client):
        licence = "https://creativecommons.org/licenses/by/4.0/"
        scheme = published(license=licence)

        anchor = self.details(client, scheme).find("a", href=licence)

        assert anchor is not None
        assert anchor.get("rel") == ["noopener"]

    def test_a_detail_given_as_a_name_is_not_a_link(self, client):
        scheme = published(publisher="Gem Survey")

        assert self.details(client, scheme).find("a") is None

    def test_a_licence_stated_as_a_link_entry_is_shown_as_its_address(self, client):
        licence = "https://creativecommons.org/licenses/by/4.0/"
        scheme = ConceptSchemeFactory(
            data=labelled("Rocks", statements={"dcterms:license": [link(licence)]})
        )

        assert self.details(client, scheme).find("a", href=licence) is not None

    def test_an_imported_value_is_escaped_and_only_a_web_address_is_linked(
        self, client
    ):
        scheme = published(publisher="<b>Gem Survey</b>", license="javascript:alert(1)")

        details = self.details(client, scheme)

        assert details.find("b") is None
        assert details.find("a") is None

    def test_a_vocabulary_without_details_shows_a_dash_for_each(self, client):
        scheme = ConceptSchemeFactory()

        values = [dd.get_text(strip=True) for dd in self.details(client, scheme)("dd")]

        assert values == ["—"] * 5


@pytest.mark.django_db
class TestVocabularyDetailConceptList:
    def test_a_multi_level_hierarchy_renders_flat_with_every_concept_exactly_once(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        top = concept_with(scheme, "Top Concept")
        middle = concept_with(scheme, "Middle Concept", skos__broader=[link(top.uri)])
        bottom = concept_with(
            scheme, "Bottom Concept", skos__broader=[link(middle.uri)]
        )

        response = client.get(vocabulary_page(scheme))

        assert sorted(listed_pks(response)) == sorted([top.pk, middle.pk, bottom.pk])

    def test_a_record_that_is_not_a_concept_is_not_listed_among_them(self, client):
        scheme = ConceptSchemeFactory()
        concept = RecordFactory(scheme=scheme)
        RecordFactory(scheme=scheme, type=Record.Type.COLLECTION)

        assert listed_pks(client.get(vocabulary_page(scheme))) == [concept.pk]

    def test_a_concept_belonging_to_another_vocabulary_does_not_appear(self, client):
        scheme = ConceptSchemeFactory()
        concept = RecordFactory(scheme=scheme, label="Granite")
        RecordFactory(scheme=ConceptSchemeFactory(), label="Basalt")

        assert listed_pks(client.get(vocabulary_page(scheme))) == [concept.pk]

    def test_a_concept_in_the_list_links_to_and_reaches_its_own_page(self, client):
        concept = RecordFactory(label="Granite")

        response = client.get(vocabulary_page(concept.scheme))
        anchor = next(
            a
            for a in soup_of(response)("a", href=True)
            if a.get_text(strip=True) == "Granite"
        )

        assert anchor["href"] == concept_page(concept)
        follow = client.get(anchor["href"])
        assert follow.status_code == 200
        assert follow.context["object"] == concept

    def test_a_search_narrowed_result_links_to_and_reaches_its_own_page(self, client):
        match = RecordFactory(label="Granite")
        RecordFactory(scheme=match.scheme, label="Basalt")

        response = client.get(vocabulary_page(match.scheme), {"q": "Granite"})
        anchor = next(
            a
            for a in soup_of(response)("a", href=True)
            if a.get_text(strip=True) == "Granite"
        )

        assert anchor["href"] == concept_page(match)
        assert client.get(anchor["href"]).context["object"] == match


@pytest.mark.django_db
class TestVocabularyDetailConceptRow:
    @staticmethod
    def row_for(client, concept):
        """Return the list row naming ``concept`` on its vocabulary's page.

        Args:
            client: The test client.
            concept: The concept whose row to find.

        Returns:
            The row element.
        """
        soup = soup_of(client.get(vocabulary_page(concept.scheme)))
        return next(
            row
            for row in soup.select(CONCEPT_ROWS)
            if row.find("a", href=concept_page(concept))
        )

    def test_a_row_shows_the_concepts_definition(self, client):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            skos__definition=[text("A coarse-grained igneous rock.", "en")],
        )

        assert (
            "A coarse-grained igneous rock." in self.row_for(client, concept).get_text()
        )

    def test_a_definition_missing_in_the_active_language_falls_back_to_the_default_one(
        self, client
    ):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            skos__definition=[text("A coarse-grained igneous rock.", "en")],
        )

        with translation.override("de"):
            row = self.row_for(client, concept)

        assert "A coarse-grained igneous rock." in row.get_text()

    def test_a_definition_in_the_active_language_is_preferred_to_the_default_one(
        self, client
    ):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            skos__definition=[
                text("A coarse-grained igneous rock.", "en"),
                text("Ein grobkörniges Tiefengestein.", "de"),
            ],
        )

        with translation.override("de"):
            row_text = self.row_for(client, concept).get_text()

        assert "Ein grobkörniges Tiefengestein." in row_text
        assert "A coarse-grained igneous rock." not in row_text

    def test_a_row_names_the_concepts_broader_concept(self, client):
        scheme = ConceptSchemeFactory()
        parent = RecordFactory(scheme=scheme, label="Plutonic rock")
        concept = concept_with(scheme, "Granite", skos__broader=[link(parent.uri)])

        assert "Plutonic rock" in self.row_for(client, concept).get_text()

    def test_a_row_names_a_broader_concept_that_only_states_it_as_narrower(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        concept = RecordFactory(scheme=scheme, label="Granite")
        concept_with(scheme, "Plutonic rock", skos__narrower=[link(concept.uri)])

        assert "Plutonic rock" in self.row_for(client, concept).get_text()

    def test_the_broader_concept_is_named_in_the_active_language(self, client):
        scheme = ConceptSchemeFactory()
        parent = RecordFactory(
            scheme=scheme,
            data={
                "skos:prefLabel": [
                    text("Plutonic rock", "en"),
                    text("Tiefengestein", "de"),
                ]
            },
        )
        concept = concept_with(scheme, "Granite", skos__broader=[link(parent.uri)])

        with translation.override("de"):
            row_text = self.row_for(client, concept).get_text()

        assert "Tiefengestein" in row_text
        assert "Plutonic rock" not in row_text

    def test_a_row_links_the_concepts_identifier_to_itself(self, client):
        concept = RecordFactory(
            label="Granite", uri="http://publisher.example.org/concept/granite"
        )

        anchor = self.row_for(client, concept).find("a", href=concept.uri)

        assert anchor.get_text(strip=True) == concept.uri
        assert anchor.get("rel") == ["noopener"]

    def test_a_row_links_each_collection_holding_the_concept_to_its_page(self, client):
        scheme = ConceptSchemeFactory()
        igneous, (granite,) = collection_with_members(
            scheme=scheme, labels=("Granite",)
        )
        RecordFactory(scheme=scheme, type=Record.Type.COLLECTION)  # Holds nothing.

        row = self.row_for(client, granite)
        collection_links = [
            anchor["href"] for anchor in row("a") if "/collection/" in anchor["href"]
        ]

        assert collection_links == [collection_page(igneous)]

    def test_alternative_and_hidden_labels_are_not_shown_on_the_row(self, client):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            skos__altLabel=[text("granitic rock", "en")],
            skos__hiddenLabel=[text("granate", "en")],
        )

        row_text = self.row_for(client, concept).get_text()

        assert "granitic rock" not in row_text
        assert "granate" not in row_text

    def test_a_concept_with_no_definition_broader_concept_or_collection_shows_only_its_label_and_identifier(
        self, client
    ):
        concept = RecordFactory(label="Granite")

        row = self.row_for(client, concept)

        assert row.get_text(" ", strip=True) == f"Granite {concept.uri}"


@pytest.mark.django_db
class TestVocabularyDetailTopConcepts:
    def test_a_hierarchy_lists_the_concepts_with_no_broader_concept(self, client):
        scheme = ConceptSchemeFactory()
        rock = RecordFactory(scheme=scheme, label="Rock")
        mineral = RecordFactory(scheme=scheme, label="Mineral")
        concept_with(scheme, "Granite", skos__broader=[link(rock.uri)])

        response = client.get(vocabulary_page(scheme))

        assert [c.pk for c in response.context["top_concepts"]] == [mineral.pk, rock.pk]
        panel = soup_of(response).select_one(SIDE_PANEL)
        assert panel.find("a", href=concept_page(rock))

    def test_a_hierarchy_stated_only_as_narrower_lists_the_concepts_at_its_top(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        granite = RecordFactory(scheme=scheme, label="Granite")
        rock = concept_with(scheme, "Rock", skos__narrower=[link(granite.uri)])

        response = client.get(vocabulary_page(scheme))

        assert [c.pk for c in response.context["top_concepts"]] == [rock.pk]

    def test_a_flat_vocabulary_lists_no_top_concepts(self, client):
        scheme = ConceptSchemeFactory()
        RecordFactory.create_batch(3, scheme=scheme)

        response = client.get(vocabulary_page(scheme))

        assert list(response.context["top_concepts"]) == []

    def test_a_top_concept_is_named_in_the_active_language(self, client):
        scheme = ConceptSchemeFactory()
        rock = RecordFactory(
            scheme=scheme,
            data={"skos:prefLabel": [text("Rock", "en"), text("Gestein", "de")]},
        )
        concept_with(scheme, "Granite", skos__broader=[link(rock.uri)])

        with translation.override("de"):
            response = client.get(vocabulary_page(scheme))

        panel = soup_of(response).select_one(SIDE_PANEL)
        assert "Gestein" in panel.get_text()


@pytest.mark.django_db
class TestVocabularyDetailConceptLabel:
    def test_a_concept_with_a_preferred_label_in_the_active_language_shows_it(
        self, client
    ):
        # Not a substring of the default label, so truncating "Granite" cannot pass.
        scheme = ConceptSchemeFactory()
        RecordFactory(
            scheme=scheme,
            data={
                "skos:prefLabel": [
                    text("Granite", "en"),
                    text("Kristallgestein", "de"),
                ]
            },
        )

        with translation.override("de"):
            content = client.get(vocabulary_page(scheme)).content.decode()

        assert "Kristallgestein" in content
        assert "Granite" not in content

    def test_a_concept_with_no_label_in_the_active_language_falls_back_to_its_stored_one(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        RecordFactory(scheme=scheme, label="Granite")

        with translation.override("de"):
            content = client.get(vocabulary_page(scheme)).content.decode()

        assert "Granite" in content

    def test_query_count_is_flat_regardless_of_how_many_concepts_the_vocabulary_holds(
        self, client, django_assert_num_queries
    ):
        # Every concept carries what a row shows beside its label: a definition, a broader
        # concept and a collection, so none of those can cost a query per row.
        scheme = ConceptSchemeFactory()
        root = RecordFactory(scheme=scheme)
        collection = RecordFactory(scheme=scheme, type=Record.Type.COLLECTION)

        def decorated_concepts(count):
            """Create ``count`` concepts carrying everything a row shows.

            Args:
                count: How many to create.
            """
            concepts = [
                concept_with(
                    scheme,
                    f"Decorated {next(serial)}",
                    skos__definition=[text("A definition.", "en")],
                    skos__broader=[link(root.uri)],
                )
                for _ in range(count)
            ]
            gather(collection, *concepts)

        decorated_concepts(3)
        baseline = query_count(client, vocabulary_page(scheme))
        decorated_concepts(27)

        with django_assert_num_queries(baseline):
            client.get(vocabulary_page(scheme))


@pytest.mark.django_db
class TestVocabularyDetailConceptOrder:
    def test_concepts_are_ordered_by_their_preferred_label_ignoring_case(self, client):
        scheme = ConceptSchemeFactory()
        zebra = RecordFactory(scheme=scheme, label="Zebra")
        antelope = RecordFactory(scheme=scheme, label="antelope")

        assert listed_pks(client.get(vocabulary_page(scheme))) == [
            antelope.pk,
            zebra.pk,
        ]

    def test_two_identically_labelled_concepts_are_ordered_by_creation(self, client):
        scheme = ConceptSchemeFactory()
        # The first sorts last by slug, so only a real primary key tiebreak gives this order.
        first = RecordFactory(scheme=scheme, label="Duplicate", slug="zzz-sorts-last")
        second = RecordFactory(scheme=scheme, label="Duplicate")

        first_request = listed_pks(client.get(vocabulary_page(scheme)))
        second_request = listed_pks(client.get(vocabulary_page(scheme)))

        assert first_request == second_request == [first.pk, second.pk]


@pytest.mark.django_db
class TestVocabularyDetailChosenConceptOrder:
    def test_the_page_offers_both_directions_by_label(self, client):
        scheme = ConceptSchemeFactory()
        RecordFactory(scheme=scheme)

        response = client.get(vocabulary_page(scheme))

        options = response.context["filter"].filters["o"].options
        assert [key for key, _label, _columns in options] == [
            "label_asc",
            "label_desc",
        ]

    def test_choosing_z_to_a_reverses_the_concepts(self, client):
        scheme = ConceptSchemeFactory()
        zebra = RecordFactory(scheme=scheme, label="Zebra")
        antelope = RecordFactory(scheme=scheme, label="Antelope")
        url = vocabulary_page(scheme)

        ascending = listed_pks(client.get(url, {"o": "label_asc"}))
        descending = listed_pks(client.get(url, {"o": "label_desc"}))

        assert ascending == [antelope.pk, zebra.pk]
        assert descending == [zebra.pk, antelope.pk]

    def test_an_ordering_nobody_offered_is_ignored_rather_than_obeyed(self, client):
        scheme = ConceptSchemeFactory()
        zebra = RecordFactory(scheme=scheme, label="Zebra")
        antelope = RecordFactory(scheme=scheme, label="Antelope")

        response = client.get(vocabulary_page(scheme), {"o": "-label"})

        assert response.status_code == 200
        assert listed_pks(response) == [antelope.pk, zebra.pk]
        assert response.context["sort_label"] == ""

    def test_a_search_and_a_chosen_order_apply_together(self, client):
        scheme = ConceptSchemeFactory()
        RecordFactory(scheme=scheme, label="Basalt Zebra")
        RecordFactory(scheme=scheme, label="Basalt Antelope")
        RecordFactory(scheme=scheme, label="Granite Badger")

        response = client.get(
            vocabulary_page(scheme), {"q": "Basalt", "o": "label_desc"}
        )

        assert [c.pref_label for c in response.context["object_list"]] == [
            "Basalt Zebra",
            "Basalt Antelope",
        ]

    def test_the_search_box_and_the_sort_control_both_submit_to_a_form_that_exists(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        RecordFactory(scheme=scheme)

        soup = soup_of(client.get(vocabulary_page(scheme)))

        form = soup.find("form", id="filterForm")
        assert form is not None
        assert form.get("method", "").lower() == "get"
        assert submits_to(soup, "q") == "filterForm"
        assert submits_to(soup, "o") == "filterForm"


@pytest.mark.django_db
class TestVocabularyDetailConceptPaging:
    def test_a_long_list_is_paged_and_the_second_page_renders(self, client):
        scheme = ConceptSchemeFactory()
        RecordFactory.create_batch(30, scheme=scheme)
        url = vocabulary_page(scheme)

        first_page = client.get(url)
        per_page = first_page.context["paginator"].per_page
        assert len(first_page.context["object_list"]) == per_page

        page_two_href = next(href for href in hrefs(first_page) if "page=2" in href)
        second_page = client.get(url + page_two_href)

        assert second_page.status_code == 200
        assert len(second_page.context["object_list"]) == 30 - per_page

    def test_a_paging_link_carries_forward_an_active_query_parameter(self, client):
        # Uses a parameter the view gives no meaning to, so this is about the paging link
        # carrying it forward. Read the link from the markup: a hand-built one would hide a
        # broken querystring tag.
        scheme = ConceptSchemeFactory()
        RecordFactory.create_batch(30, scheme=scheme)
        url = vocabulary_page(scheme)

        response = client.get(url, {"unrelated": "kept"})

        assert any(
            "page=2" in href and "unrelated=kept" in href for href in hrefs(response)
        )

    def test_a_vocabulary_holding_no_concepts_still_renders_the_rest_of_the_page(
        self, client
    ):
        scheme = published(
            "Geological Time Scale",
            description="Periods, epochs and ages of the geological record.",
        )

        response = client.get(vocabulary_page(scheme))

        assert response.status_code == 200
        assert listed_pks(response) == []
        assert response.context["page"]["title"] == "Geological Time Scale"
        assert response.context["page"]["subtitle"] == (
            "Periods, epochs and ages of the geological record."
        )


@pytest.mark.django_db
class TestVocabularyDetailConceptSearch:
    def test_a_word_only_in_the_preferred_label_finds_it(self, client):
        match = RecordFactory(label="Granite")
        RecordFactory(scheme=match.scheme, label="Basalt")

        response = client.get(vocabulary_page(match.scheme), {"q": "Granite"})

        assert listed_pks(response) == [match.pk]

    def test_a_word_only_in_an_alternative_label_finds_it(self, client):
        scheme = ConceptSchemeFactory()
        match = concept_with(
            scheme, "Granite", skos__altLabel=[text("granitic rock", "en")]
        )
        RecordFactory(scheme=scheme, label="Basalt")

        response = client.get(vocabulary_page(scheme), {"q": "granitic"})

        assert listed_pks(response) == [match.pk]

    def test_a_word_only_in_a_label_of_another_language_finds_it(self, client):
        scheme = ConceptSchemeFactory()
        match = RecordFactory(
            scheme=scheme,
            data={"skos:prefLabel": [text("Granite", "en"), text("Granit", "de")]},
        )
        RecordFactory(scheme=scheme, label="Basalt")

        response = client.get(vocabulary_page(scheme), {"q": "Granit"})

        assert listed_pks(response) == [match.pk]

    def test_a_word_only_in_a_hidden_label_finds_it_and_the_label_is_shown_nowhere(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        match = concept_with(
            scheme, "Granite", skos__hiddenLabel=[text("granate", "en")]
        )
        RecordFactory(scheme=scheme, label="Basalt")

        response = client.get(vocabulary_page(scheme), {"q": "granate"})
        # Read from the result rows: the applied-search chip repeats what the reader typed,
        # which is the term and not the concept's label.
        rows_text = " ".join(
            row.get_text() for row in soup_of(response).select(CONCEPT_ROWS)
        )

        assert listed_pks(response) == [match.pk]
        assert "Granite" in rows_text
        assert "granate" not in rows_text

    def test_a_concept_matching_on_several_labels_at_once_is_listed_once(self, client):
        scheme = ConceptSchemeFactory()
        match = concept_with(
            scheme,
            "Granite",
            skos__altLabel=[text("Granite rock", "en")],
            skos__hiddenLabel=[text("Granite stone", "en")],
        )

        response = client.get(vocabulary_page(scheme), {"q": "Granite"})

        assert listed_pks(response) == [match.pk]

    def test_a_word_only_in_the_definition_does_not_find_the_concept(self, client):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            skos__definition=[text("A coarse-grained igneous rock.", "en")],
        )

        response = client.get(vocabulary_page(concept.scheme), {"q": "igneous"})

        assert listed_pks(response) == []

    def test_a_matching_concept_in_another_vocabulary_is_not_returned(self, client):
        match = RecordFactory(label="Granite")
        RecordFactory(scheme=ConceptSchemeFactory(), label="Granite Boulder")

        response = client.get(vocabulary_page(match.scheme), {"q": "Granite"})

        assert listed_pks(response) == [match.pk]

    def test_a_search_run_directly_from_the_second_page_still_reaches_every_concept(
        self, client
    ):
        # Requested with page=2 up front: a search scoped to the page being viewed would
        # filter only that page and leak the non-matching concepts through.
        scheme = ConceptSchemeFactory()
        matching = [
            RecordFactory(scheme=scheme, label=f"Stratigraphy Unit {i:02d}")
            for i in range(30)
        ]
        non_matching = RecordFactory.create_batch(5, scheme=scheme)

        response = client.get(vocabulary_page(scheme), {"q": "Stratigraphy", "page": 2})

        assert response.status_code == 200
        listed = set(listed_pks(response))
        assert listed <= {c.pk for c in matching}
        assert listed.isdisjoint(c.pk for c in non_matching)
        assert response.context["paginator"].count == 30

    def test_a_narrowed_lists_address_opened_fresh_returns_the_same_concepts(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        match = RecordFactory(scheme=scheme, label="Stratigraphy Unit")
        RecordFactory(scheme=scheme, label="Soil Classification")
        url = vocabulary_page(scheme)

        first = listed_pks(client.get(url, {"q": "Stratigraphy"}))
        second = listed_pks(client.get(url, {"q": "Stratigraphy"}))

        assert first == second == [match.pk]

    def test_matching_ignores_ascii_case(self, client):
        match = RecordFactory(label="Granite")
        RecordFactory(scheme=match.scheme, label="Basalt")

        response = client.get(vocabulary_page(match.scheme), {"q": "granite"})

        assert listed_pks(response) == [match.pk]

    @pytest.mark.parametrize("term", ["%", "_", "'"])
    def test_a_term_containing_a_like_wildcard_or_a_quote_is_looked_for_literally(
        self, client, term
    ):
        scheme = ConceptSchemeFactory()
        RecordFactory.create_batch(3, scheme=scheme)

        assert listed_pks(client.get(vocabulary_page(scheme), {"q": term})) == []

    @pytest.mark.skipif(
        connection.vendor != "sqlite", reason="the limitation under test is SQLite's"
    )
    @pytest.mark.parametrize(
        ("label", "term", "matches"),
        [
            ("Ecology", "ECOLOGY", True),
            ("Ökologie", "ÖKOLOGIE", True),
            ("Ökologie", "ökologie", False),
            ("Гидрология", "гидрология", False),
        ],
    )
    def test_case_insensitive_matching_covers_ascii_letters_only_on_sqlite(
        self, client, label, term, matches
    ):
        # SQLite's LIKE folds ASCII letters only, so Ökologie is found by ÖKOLOGIE and not
        # by ökologie; PostgreSQL matches either way
        # (docs/adr/0014-database-collation-differences-are-disclosed-not-repaired.md).
        concept = RecordFactory(label=label)

        response = client.get(vocabulary_page(concept.scheme), {"q": term})

        assert (listed_pks(response) == [concept.pk]) is matches


@pytest.mark.django_db
class TestVocabularyDetailConceptSearchEmptyState:
    # The term is read stripped, as django-mvp's mixin reads it, so the empty state and the
    # queryset agree on whether a search is in force.

    def test_a_search_matching_nothing_returns_200_and_echoes_the_term(self, client):
        scheme = ConceptSchemeFactory()
        RecordFactory(scheme=scheme, label="Granite")

        response = client.get(vocabulary_page(scheme), {"q": "Basalt"})

        assert response.status_code == 200
        assert "Basalt" in response.content.decode()

    def test_a_search_matching_nothing_offers_a_link_back_to_the_unsearched_vocabulary(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        RecordFactory(scheme=scheme, label="Granite")

        response = client.get(vocabulary_page(scheme), {"q": "Basalt"})

        assert vocabulary_page(scheme) in hrefs(response)

    def test_a_vocabulary_holding_no_concepts_shows_no_link_back_to_the_unsearched_one(
        self, client
    ):
        scheme = ConceptSchemeFactory()

        assert vocabulary_page(scheme) not in hrefs(client.get(vocabulary_page(scheme)))

    def test_a_whitespace_only_search_is_not_a_search(self, client):
        # A raw, unstripped `?q=%20%20` must not half-search: the list stays unfiltered and
        # no link offers to undo a search that never happened.
        scheme = ConceptSchemeFactory()
        RecordFactory.create_batch(2, scheme=scheme)

        response = client.get(vocabulary_page(scheme), {"q": "   "})

        assert len(response.context["object_list"]) == 2
        assert vocabulary_page(scheme) not in hrefs(response)


@pytest.mark.django_db
class TestVocabularyDetailCollections:
    def test_each_collection_is_named(self, client):
        scheme = ConceptSchemeFactory()
        igneous, _ = collection_with_members(scheme=scheme, labels=("Granite",))
        sedimentary, _ = collection_with_members(scheme=scheme, labels=("Sandstone",))

        content = client.get(vocabulary_page(scheme)).content.decode()

        assert igneous.pref_label in content
        assert sedimentary.pref_label in content

    def test_an_ordered_collection_is_distinguishable_from_an_unordered_one(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        unordered, _ = collection_with_members(
            scheme=scheme, labels=("Granite",), ordered=False
        )
        ordered, _ = collection_with_members(
            scheme=scheme, labels=("Basalt",), ordered=True
        )

        panel = soup_of(client.get(vocabulary_page(scheme))).select_one(SIDE_PANEL)
        rows = panel("li")
        unordered_row = next(r for r in rows if unordered.pref_label in r.get_text())
        ordered_row = next(r for r in rows if ordered.pref_label in r.get_text())

        # Both hold one member, so whatever else differs between the two rows is the marking.
        unordered_marking = unordered_row.get_text(strip=True).replace(
            unordered.pref_label, ""
        )
        ordered_marking = ordered_row.get_text(strip=True).replace(
            ordered.pref_label, ""
        )
        assert ordered_marking != unordered_marking

    def test_each_collection_counts_its_members(self, client):
        scheme = ConceptSchemeFactory()
        pair, _ = collection_with_members(scheme=scheme, labels=("Granite", "Basalt"))
        RecordFactory(scheme=scheme, type=Record.Type.COLLECTION)

        response = client.get(vocabulary_page(scheme))

        counts = {c.pk: c.member_count for c in response.context["collections"]}
        assert counts[pair.pk] == 2
        assert sorted(counts.values()) == [0, 2]

    def test_each_collection_links_to_and_reaches_its_own_page(self, client):
        scheme = ConceptSchemeFactory()
        collection, _ = collection_with_members(scheme=scheme)

        response = client.get(vocabulary_page(scheme))
        panel = soup_of(response).select_one(SIDE_PANEL)
        anchor = panel.find("a", href=collection_page(collection))

        assert anchor.get_text(strip=True) == collection.pref_label
        follow = client.get(anchor["href"])
        assert follow.status_code == 200
        assert follow.context["object"] == collection

    def test_a_vocabulary_holding_no_collections_lists_none(self, client):
        scheme = ConceptSchemeFactory()

        response = client.get(vocabulary_page(scheme))

        assert list(response.context["collections"]) == []

    def test_collections_are_separate_from_the_concept_list_not_mixed_into_it(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite", "Basalt")
        )
        other_concept = RecordFactory(scheme=scheme, label="Quartz")

        response = client.get(vocabulary_page(scheme))

        assert list(response.context["collections"]) == [collection]
        # Every concept appears once, whether or not it belongs to a collection.
        assert sorted(listed_pks(response)) == sorted(
            [members[0].pk, members[1].pk, other_concept.pk]
        )


@pytest.mark.django_db
class TestTemplateCommentsDoNotReachThePage:
    # Django's {# #} does not match across a newline, so a multi-line one is served to the
    # reader as text.

    def test_the_list_of_vocabularies_serves_no_comment_text(self, client):
        published(description="A description.")

        content = client.get(LIST_URL).content.decode()

        assert "{#" not in content
        assert "#}" not in content

    def test_a_vocabulary_page_serves_no_comment_text(self, client):
        scheme = published(description="A description.")
        collection_with_members(scheme=scheme)

        content = client.get(vocabulary_page(scheme), {"q": "nothing"}).content.decode()

        assert "{#" not in content
        assert "#}" not in content


@pytest.mark.django_db
class TestConceptDetail:
    def test_a_known_concept_serves_its_page_anonymously(self, client):
        assert client.get(concept_page(RecordFactory())).status_code == 200

    def test_a_concept_slug_naming_nothing_in_a_real_vocabulary_returns_404(
        self, client
    ):
        scheme = ConceptSchemeFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": scheme.slug, "concept_slug": "no-such-concept"},
            )
        )

        assert response.status_code == 404

    def test_a_collections_slug_does_not_serve_a_concept_page(self, client):
        collection = RecordFactory(type=Record.Type.COLLECTION)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "concept_slug": collection.slug,
                },
            )
        )

        assert response.status_code == 404

    def test_a_vocabulary_segment_naming_nothing_also_returns_404(self, client):
        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": "no-such-vocabulary", "concept_slug": "whatever"},
            )
        )

        assert response.status_code == 404

    def test_a_concept_slug_shared_by_two_vocabularies_resolves_to_the_one_named_in_the_address(
        self, client
    ):
        RecordFactory(scheme=ConceptSchemeFactory(), label="Granite")
        concept_in_two = RecordFactory(scheme=ConceptSchemeFactory(), label="Granite")

        response = client.get(concept_page(concept_in_two))

        assert response.status_code == 200
        assert response.context["object"] == concept_in_two

    def test_the_context_carries_the_concepts_property_rows(self, client):
        concept = RecordFactory(label="Granite")

        response = client.get(concept_page(concept))

        assert response.context["rows"] == PropertyRows(concept, "en").build()


@pytest.mark.django_db
class TestConceptDetailBreadcrumbs:
    def test_the_trail_leads_home_then_to_the_vocabulary_then_the_concept(self, client):
        concept = RecordFactory(label="Granite")

        response = client.get(concept_page(concept))

        trail = response.context["page"]["breadcrumbs"]
        assert [crumb.get("href") for crumb in trail] == [
            "/",
            vocabulary_page(concept.scheme),
            None,
        ]
        assert [crumb["text"] for crumb in trail[1:]] == [
            concept.scheme.display_label(),
            "Granite",
        ]


@pytest.mark.django_db
class TestConceptDetailShowsWhatIsRecorded:
    def test_a_preferred_label_a_definition_and_a_scope_note_each_show_on_their_own_row(
        self, client
    ):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            skos__definition=[text("A coarse-grained igneous rock.", "en")],
            skos__scopeNote=[text("Used for building stone.", "en")],
        )

        pairs = pairs_of(client.get(concept_page(concept)))

        assert ("skos:prefLabel", "Granite") in pairs
        assert ("skos:definition", "A coarse-grained igneous rock.") in pairs
        assert ("skos:scopeNote", "Used for building stone.") in pairs

    def test_alternative_labels_appear_and_no_hidden_label_appears_anywhere(
        self, client
    ):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            skos__altLabel=[text("granitic rock", "en")],
            skos__hiddenLabel=[text("granate", "en")],
        )

        response = client.get(concept_page(concept))

        assert ("skos:altLabel", "granitic rock") in pairs_of(response)
        assert "granate" not in response.content.decode()

    def test_a_predicate_the_pages_have_no_place_for_is_still_shown(self, client):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            dcterms__source=[text("Field survey 1998")],
        )

        assert ("dcterms:source", "Field survey 1998") in pairs_of(
            client.get(concept_page(concept))
        )

    def test_a_notation_without_a_language_is_shown_in_any_reading_language(
        self, client
    ):
        concept = concept_with(
            ConceptSchemeFactory(), "Granite", skos__notation=[text("GR-01")]
        )

        with translation.override("de"):
            response = client.get(concept_page(concept))

        assert ("skos:notation", "GR-01") in pairs_of(response)


@pytest.mark.django_db
class TestConceptDetailValuesInTheReadingLanguage:
    def test_values_present_in_both_languages_show_the_reading_languages_ones(
        self, client
    ):
        concept = RecordFactory(
            data={
                "skos:prefLabel": [
                    text("Granite", "en"),
                    text("Kristallgestein", "de"),
                ],
                "skos:altLabel": [
                    text("granite stone", "en"),
                    text("Granitstein", "de"),
                ],
                "skos:definition": [
                    text("An igneous rock.", "en"),
                    text("Ein Eruptivgestein.", "de"),
                ],
            }
        )

        with translation.override("de"):
            response = client.get(concept_page(concept))

        values = [value for _term, value in pairs_of(response)]
        assert "Kristallgestein" in values
        assert "Granitstein" in values
        assert "Ein Eruptivgestein." in values
        assert "Granite" not in values
        assert "granite stone" not in values
        assert "An igneous rock." not in values

    def test_a_concept_with_no_value_in_the_reading_language_falls_back_to_the_vocabularys_default(
        self, client
    ):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            skos__altLabel=[text("granite stone", "en")],
            skos__definition=[text("An igneous rock.", "en")],
        )

        with translation.override("de"):
            response = client.get(concept_page(concept))

        values = [value for _term, value in pairs_of(response)]
        assert "Granite" in values
        assert "granite stone" in values
        assert "An igneous rock." in values


@pytest.mark.django_db
class TestConceptDetailTypeAndIdentifier:
    def test_the_type_row_names_the_concept_class(self, client):
        concept = RecordFactory(label="Granite")

        pairs = pairs_of(client.get(concept_page(concept)))

        assert ("rdf:type", Record.Type.CONCEPT) in pairs

    def test_the_identifier_appears_as_an_anchor_to_the_records_own_uri(self, client):
        concept = RecordFactory(label="Granite")

        soup = soup_of(client.get(concept_page(concept)))
        identifier_link = soup.find("a", href=concept.uri)

        assert concept.uri in identifier_link.get_text(strip=True)

    def test_an_identifier_in_a_scheme_a_browser_would_hand_off_is_not_linked(
        self, client
    ):
        concept = RecordFactory(label="Granite", uri="search-ms:query=granite")

        soup = soup_of(client.get(concept_page(concept)))

        assert soup.find("a", href=concept.uri) is None
        assert concept.uri in soup.get_text()

    def test_an_imported_concept_shows_its_publishers_identifier(self, client):
        concept = RecordFactory(
            label="Granite", uri="http://publisher.example.org/concept/granite"
        )

        soup = soup_of(client.get(concept_page(concept)))
        identifier_link = soup.find("a", href=concept.uri)

        assert concept.uri in identifier_link.get_text(strip=True)


@pytest.mark.django_db
class TestConceptDetailUnfilledPropertiesProduceNoRow:
    def test_a_bare_concepts_page_names_exactly_type_label_and_vocabulary(self, client):
        concept = RecordFactory(label="Granite")

        response = client.get(concept_page(concept))

        assert terms_of(response) == ["rdf:type", "skos:prefLabel", "skos:inScheme"]
        assert soup_of(response).find("a", href=concept.uri) is not None


@pytest.mark.django_db
class TestConceptDetailQueryCount:
    def test_query_count_is_flat_as_statements_and_relations_grow(
        self, client, django_assert_num_queries
    ):
        scheme = ConceptSchemeFactory()
        concept = concept_with(scheme, "Granite")
        url = concept_page(concept)

        def grow(count):
            """Give the concept ``count`` more of every kind of statement.

            Args:
                count: How many of each to add.
            """
            for number in range(count):
                broader = RecordFactory(scheme=scheme)
                related = RecordFactory(scheme=scheme)
                concept.data.setdefault("skos:altLabel", []).append(
                    text(f"Label {next(serial)}-{number}", "fr")
                )
                concept.data.setdefault("skos:definition", []).append(
                    text(f"Definition {number}", "en")
                )
                concept.data.setdefault("skos:broader", []).append(link(broader.uri))
                concept.data.setdefault("skos:related", []).append(link(related.uri))
                concept_with(
                    scheme, f"Child {next(serial)}", skos__broader=[link(concept.uri)]
                )
                collection = RecordFactory(scheme=scheme, type=Record.Type.COLLECTION)
                gather(collection, concept)
            concept.save()

        grow(1)
        baseline = query_count(client, url)
        grow(5)

        with django_assert_num_queries(baseline):
            client.get(url)


@pytest.mark.django_db
class TestConceptDetailCollectionMembership:
    def test_a_concept_gathered_by_two_collections_links_to_each_collections_page(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        concept = RecordFactory(scheme=scheme, label="Granite")
        igneous = RecordFactory(
            scheme=scheme,
            type=Record.Type.COLLECTION,
            data=labelled(
                "Igneous rocks", statements={"skos:member": [link(concept.uri)]}
            ),
        )
        hardness = RecordFactory(
            scheme=scheme,
            type=Record.Type.ORDERED_COLLECTION,
            data=labelled(
                "Hardness scale", statements={"skos:memberList": [link(concept.uri)]}
            ),
        )

        soup = soup_of(client.get(concept_page(concept)))

        for collection in (igneous, hardness):
            anchor = soup.find("div", class_="concept-collections").find(
                "a", href=collection_page(collection)
            )
            assert anchor.get_text(strip=True) == collection.pref_label
            follow = client.get(anchor["href"])
            assert follow.status_code == 200
            assert follow.context["object"] == collection

    def test_a_concept_no_collection_gathers_lists_no_collections(self, client):
        concept = RecordFactory(label="Granite")

        response = client.get(concept_page(concept))

        assert list(response.context["concept_collections"]) == []

    def test_a_collection_that_merely_mentions_the_concept_does_not_gather_it(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        concept = RecordFactory(scheme=scheme, label="Granite")
        RecordFactory(
            scheme=scheme,
            type=Record.Type.COLLECTION,
            data=labelled("Notes", statements={"skos:note": [text(concept.uri)]}),
        )

        response = client.get(concept_page(concept))

        assert list(response.context["concept_collections"]) == []

    def test_membership_is_never_a_property_row(self, client):
        scheme = ConceptSchemeFactory()
        collection, (member,) = collection_with_members(
            scheme=scheme, labels=("Granite",)
        )

        response = client.get(concept_page(member))

        assert terms_of(response) == ["rdf:type", "skos:prefLabel", "skos:inScheme"]
        assert list(response.context["concept_collections"]) == [collection]


@pytest.mark.django_db
class TestCollectionDetail:
    def test_a_known_collection_serves_its_page_anonymously(self, client):
        collection = RecordFactory(type=Record.Type.COLLECTION)

        assert client.get(collection_page(collection)).status_code == 200

    def test_a_collection_slug_naming_nothing_in_a_real_vocabulary_returns_404(
        self, client
    ):
        scheme = ConceptSchemeFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={"slug": scheme.slug, "collection_slug": "no-such-collection"},
            )
        )

        assert response.status_code == 404

    def test_a_concepts_slug_does_not_serve_a_collection_page(self, client):
        concept = RecordFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": concept.scheme.slug,
                    "collection_slug": concept.slug,
                },
            )
        )

        assert response.status_code == 404

    def test_a_vocabulary_segment_naming_nothing_also_returns_404(self, client):
        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={"slug": "no-such-vocabulary", "collection_slug": "whatever"},
            )
        )

        assert response.status_code == 404

    def test_the_context_carries_the_collections_property_rows(self, client):
        collection = RecordFactory(label="Rock Types", type=Record.Type.COLLECTION)

        response = client.get(collection_page(collection))

        assert response.context["rows"] == PropertyRows(collection, "en").build()


@pytest.mark.django_db
class TestCollectionDetailBreadcrumbs:
    def test_the_trail_leads_home_then_to_the_vocabulary_then_the_collection(
        self, client
    ):
        collection = RecordFactory(label="Rock Types", type=Record.Type.COLLECTION)

        response = client.get(collection_page(collection))

        trail = response.context["page"]["breadcrumbs"]
        assert [crumb.get("href") for crumb in trail] == [
            "/",
            vocabulary_page(collection.scheme),
            None,
        ]
        assert [crumb["text"] for crumb in trail[1:]] == [
            collection.scheme.display_label(),
            "Rock Types",
        ]


@pytest.mark.django_db
class TestCollectionDetailNameTypeAndMembers:
    def test_an_unordered_collection_shows_its_name_type_and_one_row_carrying_every_member(
        self, client
    ):
        # One row carries every member, rather than one row per member.
        collection, members = collection_with_members(
            labels=("Granite", "Basalt", "Gabbro"), ordered=False
        )

        response = client.get(collection_page(collection))
        soup = soup_of(response)
        pairs = pairs_of(response)

        assert ("skos:prefLabel", collection.pref_label) in pairs
        assert ("rdf:type", Record.Type.COLLECTION) in pairs
        assert terms_of(response).count("skos:member") == 1
        assert "skos:memberList" not in terms_of(response)
        short_forms = {
            a.get_text(strip=True) for a in dd_after(soup, "skos:member")("a")
        }
        assert short_forms == {
            f"{collection.scheme.slug}:{member.slug}" for member in members
        }

    def test_an_ordered_collections_type_differs_and_its_one_member_row_is_in_position_order(
        self, client
    ):
        # A non-alphabetical sequence, so the order assertion cannot pass by accident.
        collection, members = collection_with_members(
            labels=("Granite", "Basalt", "Gabbro"), ordered=True
        )

        response = client.get(collection_page(collection))
        soup = soup_of(response)

        assert ("rdf:type", Record.Type.ORDERED_COLLECTION) in pairs_of(response)
        assert "skos:member" not in terms_of(response)
        assert terms_of(response).count("skos:memberList") == 1
        assert [
            a.get_text(strip=True) for a in dd_after(soup, "skos:memberList")("a")
        ] == [f"{collection.scheme.slug}:{member.slug}" for member in members]

    def test_the_identifier_appears_as_an_anchor_to_the_records_own_uri(self, client):
        collection = RecordFactory(label="Rock Types", type=Record.Type.COLLECTION)

        soup = soup_of(client.get(collection_page(collection)))
        identifier_link = soup.find("a", href=collection.uri)

        assert collection.uri in identifier_link.get_text(strip=True)

    def test_each_members_identifier_is_disclosed_by_a_wrapping_tooltip(self, client):
        collection, members = collection_with_members()

        soup = soup_of(client.get(collection_page(collection)))
        dd = dd_after(soup, "skos:member")
        anchors = dd("a")

        assert len(anchors) == len(members)
        seen_hidden_ids = set()
        for anchor, member in zip(anchors, members, strict=True):
            wrapper = anchor.find_parent("span", class_="tooltip")
            assert wrapper.get("data-tip") == member.uri
            hidden_id = anchor.get("aria-describedby")
            assert hidden_id not in seen_hidden_ids
            seen_hidden_ids.add(hidden_id)
            assert wrapper.find("span", id=hidden_id).get_text() == member.uri
        assert all(member.uri not in visible_text(dd) for member in members)


@pytest.mark.django_db
class TestCollectionDetailEmptyState:
    @pytest.mark.parametrize(
        "kind", [Record.Type.COLLECTION, Record.Type.ORDERED_COLLECTION]
    )
    def test_a_collection_with_no_members_has_no_membership_row(self, client, kind):
        collection = RecordFactory(label="Rock Types", type=kind)

        response = client.get(collection_page(collection))

        assert "skos:member" not in terms_of(response)
        assert "skos:memberList" not in terms_of(response)
        assert response.context["collection_has_members"] is False

    def test_a_collection_with_members_is_flagged_as_having_them(self, client):
        collection, members = collection_with_members(labels=("Granite",))

        response = client.get(collection_page(collection))

        assert response.context["collection_has_members"] is True


@pytest.mark.django_db
class TestCollectionDetailQueryCount:
    def test_query_count_is_flat_as_members_grow(
        self, client, django_assert_num_queries
    ):
        scheme = ConceptSchemeFactory()
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite", "Basalt")
        )
        url = collection_page(collection)
        baseline = query_count(client, url)

        gather(collection, *RecordFactory.create_batch(5, scheme=scheme))

        with django_assert_num_queries(baseline):
            client.get(url)


@pytest.mark.django_db
class TestConceptDetailRelatedRecordIdentifiers:
    def test_a_related_records_identifier_is_disclosed_by_a_wrapping_tooltip(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        parent = RecordFactory(scheme=scheme, label="Igneous Rock")
        concept = concept_with(scheme, "Granite", skos__broader=[link(parent.uri)])

        soup = soup_of(client.get(concept_page(concept)))
        broader_dd = dd_after(soup, "skos:broader")
        anchor = broader_dd.find("a")
        wrapper = anchor.find_parent("span", class_="tooltip")

        assert wrapper.get("data-tip") == parent.uri
        hidden_span = wrapper.find("span", id=anchor.get("aria-describedby"))
        assert "sr-only" in hidden_span.get("class", [])
        assert hidden_span.get_text() == parent.uri
        assert parent.uri not in visible_text(broader_dd)
        assert anchor["href"] == concept_page(parent)

    def test_an_imported_related_concept_shows_the_publishers_identifier_and_links_here(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        parent = RecordFactory(
            scheme=scheme,
            label="Igneous Rock",
            uri="http://publisher.example.org/concept/igneous-rock",
        )
        concept = concept_with(scheme, "Granite", skos__broader=[link(parent.uri)])

        soup = soup_of(client.get(concept_page(concept)))
        broader_dd = dd_after(soup, "skos:broader")
        anchor = broader_dd.find("a")
        wrapper = anchor.find_parent("span", class_="tooltip")

        assert wrapper.get("data-tip") == parent.uri
        assert parent.uri not in visible_text(broader_dd)
        assert anchor["href"] == concept_page(parent)
        follow = client.get(anchor["href"])
        assert follow.status_code == 200
        assert follow.context["object"] == parent

    def test_two_related_records_hidden_identifier_spans_have_distinct_ids(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        broader = RecordFactory(scheme=scheme, label="Igneous Rock")
        related = RecordFactory(scheme=scheme, label="Basalt")
        concept = concept_with(
            scheme,
            "Granite",
            skos__broader=[link(broader.uri)],
            skos__related=[link(related.uri)],
        )

        soup = soup_of(client.get(concept_page(concept)))
        broader_id = dd_after(soup, "skos:broader").find("a").get("aria-describedby")
        related_id = dd_after(soup, "skos:related").find("a").get("aria-describedby")

        assert broader_id and related_id
        assert broader_id != related_id
        assert soup.find(id=broader_id).get_text() == broader.uri
        assert soup.find(id=related_id).get_text() == related.uri


@pytest.mark.django_db
class TestConceptDetailBroaderNarrowerAndRelated:
    @staticmethod
    def links_for(soup, term):
        """Find the anchors in the ``<dd>`` following a term's ``<dt>``.

        Args:
            soup: The parsed page.
            term: The term as a sighted reader sees it.

        Returns:
            The anchors of the row.
        """
        return dd_after(soup, term)("a")

    def test_a_broader_concept_appears_and_following_it_opens_its_page(self, client):
        scheme = ConceptSchemeFactory()
        parent = RecordFactory(scheme=scheme, label="Igneous Rock")
        concept = concept_with(scheme, "Granite", skos__broader=[link(parent.uri)])

        soup = soup_of(client.get(concept_page(concept)))
        (anchor,) = self.links_for(soup, "skos:broader")

        assert anchor.get_text(strip=True) == f"{scheme.slug}:{parent.slug}"
        follow = client.get(anchor["href"])
        assert follow.status_code == 200
        assert follow.context["object"] == parent

    def test_a_concept_broader_of_two_others_shows_both_as_narrower_though_only_broader_is_stored(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        parent = RecordFactory(scheme=scheme, label="Igneous Rock")
        child_one = concept_with(scheme, "Granite", skos__broader=[link(parent.uri)])
        child_two = concept_with(scheme, "Basalt", skos__broader=[link(parent.uri)])

        soup = soup_of(client.get(concept_page(parent)))
        anchors = self.links_for(soup, "skos:narrower")

        assert {a.get_text(strip=True) for a in anchors} == {
            f"{scheme.slug}:{child_one.slug}",
            f"{scheme.slug}:{child_two.slug}",
        }
        follow = client.get(anchors[0]["href"])
        assert follow.status_code == 200
        assert follow.context["object"] in (child_one, child_two)

    def test_a_concept_narrower_of_another_shows_it_as_broader_though_only_narrower_is_stored(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        child = RecordFactory(scheme=scheme, label="Granite")
        parent = concept_with(scheme, "Igneous Rock", skos__narrower=[link(child.uri)])

        soup = soup_of(client.get(concept_page(child)))
        (anchor,) = self.links_for(soup, "skos:broader")

        assert anchor["href"] == concept_page(parent)

    def test_a_related_concept_appears_and_following_it_opens_its_page(self, client):
        scheme = ConceptSchemeFactory()
        other = RecordFactory(scheme=scheme, label="Basalt")
        concept = concept_with(scheme, "Granite", skos__related=[link(other.uri)])

        soup = soup_of(client.get(concept_page(concept)))
        (anchor,) = self.links_for(soup, "skos:related")

        assert anchor.get_text(strip=True) == f"{scheme.slug}:{other.slug}"
        follow = client.get(anchor["href"])
        assert follow.status_code == 200
        assert follow.context["object"] == other

    def test_a_concept_another_calls_related_shows_it_as_related_too(self, client):
        scheme = ConceptSchemeFactory()
        other = RecordFactory(scheme=scheme, label="Basalt")
        concept_with(scheme, "Granite", skos__related=[link(other.uri)])

        soup = soup_of(client.get(concept_page(other)))

        assert len(self.links_for(soup, "skos:related")) == 1

    def test_a_link_to_a_concept_not_held_here_is_a_link_to_its_own_address(
        self, client
    ):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            skos__exactMatch=[link("https://other.example.org/granite")],
        )

        soup = soup_of(client.get(concept_page(concept)))
        (anchor,) = self.links_for(soup, "skos:exactMatch")

        assert anchor["href"] == "https://other.example.org/granite"


@pytest.mark.django_db
class TestConceptDetailVocabularyRowAndNoAncestorChain:
    def test_the_vocabulary_row_appears_and_following_it_opens_the_vocabularys_page(
        self, client
    ):
        concept = RecordFactory(label="Granite")

        soup = soup_of(client.get(concept_page(concept)))
        anchor = dd_after(soup, "skos:inScheme").find("a")

        assert anchor.get_text(strip=True) == concept.scheme.display_label()
        follow = client.get(anchor["href"])
        assert follow.status_code == 200
        assert follow.context["vocabulary"] == concept.scheme

    def test_a_five_level_chain_names_only_the_middle_concepts_immediate_neighbours(
        self, client
    ):
        # Five levels: the concept needs a neighbour beyond each of its own, or a page that
        # walked two steps would find nothing more to show and still pass.
        scheme = ConceptSchemeFactory()
        great_grandparent = RecordFactory(scheme=scheme, label="Material")
        grandparent = concept_with(
            scheme, "Rock", skos__broader=[link(great_grandparent.uri)]
        )
        parent = concept_with(
            scheme, "Igneous Rock", skos__broader=[link(grandparent.uri)]
        )
        child = concept_with(scheme, "Granite", skos__broader=[link(parent.uri)])
        concept_with(scheme, "Pink Granite", skos__broader=[link(child.uri)])

        soup = soup_of(client.get(concept_page(parent)))
        relation_pairs = [
            (term_text(dt), dt.find_next_sibling("dd").find("a").get_text(strip=True))
            for dt in soup("dt")
            if term_text(dt) in ("skos:broader", "skos:narrower")
        ]

        assert relation_pairs == [
            ("skos:broader", f"{scheme.slug}:{grandparent.slug}"),
            ("skos:narrower", f"{scheme.slug}:{child.slug}"),
        ]


@pytest.mark.django_db
class TestTranslatableStrings:
    @pytest.mark.parametrize(
        ("view_class", "slug_kwarg"),
        [
            (ConceptDetailView, "concept_slug"),
            (CollectionDetailView, "collection_slug"),
        ],
    )
    def test_the_unknown_vocabulary_404_message_is_lazily_translatable(
        self, rf, view_class, slug_kwarg
    ):
        view = view_class()

        with pytest.raises(Http404) as exc_info:
            view.setup(
                rf.get("/"), slug="no-such-vocabulary", **{slug_kwarg: "whatever"}
            )

        assert isinstance(exc_info.value.args[0], Promise)

    def test_module_carries_no_bare_user_visible_literal(self):
        source = Path(inspect.getfile(views_module)).read_text()
        visitor = visit_fields_checks_source(source)

        assert visitor.bare_literals == []
        assert visitor.positional_placeholders == []


@pytest.mark.django_db
class TestRecordValuesReachTheReaderEscaped:
    # Each test parses the response: a raw substring check passes for an unescaped payload
    # too, since it is a substring of the escaped one.

    # Matches the injected payload only, never the shell's own theme-toggle script.
    INJECTED_SCRIPT = re.compile(r"alert\(1\)")
    PAYLOAD = "<script>alert(1)</script>"

    def test_a_preferred_label_containing_markup_is_escaped_on_the_concept_page(
        self, client
    ):
        concept = RecordFactory(label=self.PAYLOAD)

        soup = soup_of(client.get(concept_page(concept)))

        assert soup.find("script", string=self.INJECTED_SCRIPT) is None
        assert self.PAYLOAD in soup.find("dl").get_text()

    def test_a_definition_containing_markup_is_escaped_on_the_concept_page(
        self, client
    ):
        concept = concept_with(
            ConceptSchemeFactory(),
            "Granite",
            skos__definition=[text(self.PAYLOAD, "en")],
        )

        soup = soup_of(client.get(concept_page(concept)))

        assert soup.find("script", string=self.INJECTED_SCRIPT) is None
        assert self.PAYLOAD in soup.find("dl").get_text()

    def test_a_publisher_supplied_identifier_reaches_an_attribute_only_as_a_links_destination(
        self, client
    ):
        # A quote inside the identifier would break out of the href if auto-escaping stopped.
        concept = RecordFactory(
            label="Granite",
            uri='http://publisher.example.org/x"><script>alert(1)</script>',
        )

        soup = soup_of(client.get(concept_page(concept)))

        assert soup.find("script", string=self.INJECTED_SCRIPT) is None
        identifier_link = soup.find("a", href=concept.uri)
        assert concept.uri in identifier_link.get_text(strip=True)

    def test_a_vocabularys_name_containing_markup_is_escaped_on_the_concept_page(
        self, client
    ):
        scheme = ConceptSchemeFactory(name=self.PAYLOAD)
        concept = RecordFactory(scheme=scheme, label="Granite")

        soup = soup_of(client.get(concept_page(concept)))

        assert soup.find("script", string=self.INJECTED_SCRIPT) is None
        assert self.PAYLOAD in soup.find("dl").get_text()

    def test_a_related_records_publisher_supplied_identifier_is_escaped_in_its_tooltip_and_hidden_span(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        parent = RecordFactory(
            scheme=scheme,
            label="Igneous Rock",
            uri='http://publisher.example.org/x"><script>alert(1)</script>',
        )
        concept = concept_with(scheme, "Granite", skos__broader=[link(parent.uri)])

        soup = soup_of(client.get(concept_page(concept)))

        assert soup.find("script", string=self.INJECTED_SCRIPT) is None
        wrapper = soup.find("span", attrs={"data-tip": parent.uri})
        hidden_span = wrapper.find("span", id=wrapper.find("a").get("aria-describedby"))
        assert hidden_span.get_text() == parent.uri

    def test_a_collections_name_containing_markup_is_escaped_on_the_collection_page(
        self, client
    ):
        collection = RecordFactory(label=self.PAYLOAD, type=Record.Type.COLLECTION)

        soup = soup_of(client.get(collection_page(collection)))

        assert soup.find("script", string=self.INJECTED_SCRIPT) is None
        assert self.PAYLOAD in soup.find("dl").get_text()


@pytest.mark.django_db
class TestConceptDetailOfAnImportedConcept:
    MAPPING_TURTLE = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

<http://example.org/rocks/> a skos:ConceptScheme ;
    skos:prefLabel "Rocks"@en .

<http://example.org/rocks/granite> a skos:Concept ;
    skos:inScheme <http://example.org/rocks/> ;
    skos:prefLabel "Granite"@en ;
    skos:exactMatch <http://external.example.org/rocks/granite> ;
    skos:closeMatch <http://external.example.org/rocks/granitic-rock> .
"""

    def test_a_concept_imported_with_exact_and_close_matches_links_to_each(
        self, client, tmp_path
    ):
        source = tmp_path / "rocks.ttl"
        source.write_text(self.MAPPING_TURTLE)
        import_skos(source)
        concept = Record.objects.get(uri="http://example.org/rocks/granite")

        soup = soup_of(client.get(concept_page(concept)))

        assert [a["href"] for a in dd_after(soup, "skos:exactMatch")("a")] == [
            "http://external.example.org/rocks/granite"
        ]
        assert [a["href"] for a in dd_after(soup, "skos:closeMatch")("a")] == [
            "http://external.example.org/rocks/granitic-rock"
        ]


@pytest.mark.django_db
class TestPropertyTermDisclosesItsOwnURI:
    @staticmethod
    def term_disclosures(soup):
        """Map each term to the tooltip span wrapping it.

        Args:
            soup: The parsed page.

        Returns:
            ``{term: span or None}`` for every ``<dt>``.
        """
        return {term_text(dt): dt.find("span", class_="tooltip") for dt in soup("dt")}

    def test_a_concept_pages_terms_each_disclose_the_uri_they_abbreviate(self, client):
        concept = RecordFactory(label="Granite")

        soup = soup_of(client.get(concept_page(concept)))
        terms = self.term_disclosures(soup)

        assert terms["rdf:type"].get("data-tip") == (
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        )
        assert terms["skos:prefLabel"].get("data-tip") == (
            "http://www.w3.org/2004/02/skos/core#prefLabel"
        )
        for curie, wrapper in terms.items():
            assert wrapper is not None, f"{curie} discloses nothing"
            hidden_span = wrapper.find_next_sibling("span", class_="sr-only")
            assert hidden_span.get_text() == wrapper.get("data-tip")
            assert wrapper["data-tip"] not in visible_text(soup.find("dl"))

    def test_a_collection_pages_terms_do_too(self, client):
        collection, members = collection_with_members(labels=("Granite",))

        soup = soup_of(client.get(collection_page(collection)))
        terms = self.term_disclosures(soup)

        assert terms["skos:member"].get("data-tip") == (
            "http://www.w3.org/2004/02/skos/core#member"
        )
        assert all(wrapper is not None for wrapper in terms.values())
