"""Tests for controlled_vocabularies.ui.views."""

import re

import pytest
from bs4 import BeautifulSoup
from django.db import connection
from django.http import Http404
from django.template.loader import render_to_string
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation
from django.utils.functional import Promise

from controlled_vocabularies.exchange.mapping import (
    BROADER_CURIE,
    COLLECTION_TYPE_CURIE,
    CONCEPT_TYPE_CURIE,
    IN_SCHEME_CURIE,
    LABEL_CURIES,
    MEMBER_CURIE,
    MEMBER_LIST_CURIE,
    NARROWER_CURIE,
    NOTE_CURIES,
    ORDERED_COLLECTION_TYPE_CURIE,
    RELATED_CURIE,
    TYPE_CURIE,
)
from controlled_vocabularies.exchange.skos import import_skos
from controlled_vocabularies.models import (
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptRelation,
)
from controlled_vocabularies.ui.views import (
    CollectionDetailView,
    ConceptDetailView,
    VocabularyDetailView,
    VocabularyListView,
    collection_property_rows,
    concept_property_rows,
)
from tests.factories import (
    CollectionFactory,
    ConceptFactory,
    ConceptNoteFactory,
    ConceptRelationFactory,
    ConceptSchemeFactory,
    collection_with_members,
)

ROW_TEMPLATE = "controlled_vocabularies/ui/conceptscheme_list_item.html"
CONCEPT_ROW_TEMPLATE = "controlled_vocabularies/ui/concept_list_item.html"


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

    The URI sits in a ``.sr-only`` span inside the ``<dt>``, so ``dt.get_text()`` glues the
    CURIE to the URI it abbreviates.

    Args:
        dt: The parsed ``<dt>`` element.

    Returns:
        The term as a sighted reader sees it.
    """
    return visible_text(dt).strip()


class TestVocabularyList:
    @pytest.mark.django_db
    def test_every_vocabulary_appears_exactly_once(self, client):
        schemes = ConceptSchemeFactory.create_batch(3)

        response = client.get(reverse("controlled_vocabularies_ui:vocabulary-list"))

        assert response.status_code == 200
        listed = list(response.context["object_list"])
        assert len(listed) == len(schemes)
        assert {vocabulary.pk for vocabulary in listed} == {
            scheme.pk for scheme in schemes
        }

    @pytest.mark.django_db
    def test_a_vocabulary_added_after_the_first_request_appears_on_the_next(
        self, client
    ):
        url = reverse("controlled_vocabularies_ui:vocabulary-list")
        client.get(url)

        added = ConceptSchemeFactory()

        response = client.get(url)

        assert added.pk in {
            vocabulary.pk for vocabulary in response.context["object_list"]
        }


class TestVocabularyListEntry:
    # The row partial is rendered directly, so a row's assertions are not confused by the
    # page's own chrome (the pagination summary and empty state also render <p> output).

    def test_an_entry_names_and_describes_its_vocabulary(self):
        # Every other case builds a scheme with a blank description, so only this one would
        # fail if the partial dropped the name or the description.
        scheme = ConceptSchemeFactory.build(
            name="Geological Time Scale",
            description="Periods, epochs and ages of the geological record.",
        )
        scheme.concept_count = 0

        html = render_to_string(ROW_TEMPLATE, {"object": scheme})

        assert scheme.name in html
        assert scheme.description in html

    def test_an_entry_leads_to_the_vocabularys_own_page(self):
        scheme = ConceptSchemeFactory.build(name="Geological Time Scale")
        scheme.concept_count = 0
        detail_url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        html = render_to_string(ROW_TEMPLATE, {"object": scheme})
        anchor = BeautifulSoup(html, "html.parser").find("a", href=detail_url)

        assert anchor is not None
        assert anchor.text.strip() == scheme.name

    def test_a_description_running_to_several_paragraphs_is_shortened(self):
        # Asserts on the rendered text, not a CSS clamp class: the entry must not carry the
        # whole description, however it avoids doing so.
        description = " ".join(f"word{index}" for index in range(400))
        scheme = ConceptSchemeFactory.build(name="Verbose", description=description)
        scheme.concept_count = 0

        html = render_to_string(ROW_TEMPLATE, {"object": scheme})

        assert "word0" in html
        assert "word399" not in html
        assert len(BeautifulSoup(html, "html.parser").get_text()) < len(description)

    @pytest.mark.django_db
    def test_get_queryset_annotates_the_real_concept_count(self, client):
        populated = ConceptSchemeFactory()
        ConceptFactory.create_batch(3, scheme=populated)
        empty = ConceptSchemeFactory()

        response = client.get(reverse("controlled_vocabularies_ui:vocabulary-list"))

        counts = {
            vocabulary.pk: vocabulary.concept_count
            for vocabulary in response.context["object_list"]
        }
        assert counts[populated.pk] == 3
        assert counts[empty.pk] == 0

    def test_imported_vocabulary_shows_its_publisher_identifier_as_a_link_and_reads_as_imported(
        self,
    ):
        # The anchor's href and text are the publisher's identifier, unrewritten, and it
        # carries rel="noopener" because the address is not this site's.
        scheme = ConceptSchemeFactory.build(external=True)
        scheme.concept_count = 0

        html = render_to_string(ROW_TEMPLATE, {"object": scheme})
        soup = BeautifulSoup(html, "html.parser")
        anchor = soup.find("a", href=scheme.static_uri)

        assert anchor is not None
        assert anchor.text == scheme.static_uri
        assert anchor.get("rel") == ["noopener"]
        assert "Imported" in html
        assert "Held here" not in html

    def test_a_locally_authored_vocabulary_is_marked_as_held_here(self):
        scheme = ConceptSchemeFactory.build()
        scheme.concept_count = 0

        html = render_to_string(ROW_TEMPLATE, {"object": scheme})

        assert "Held here" in html
        assert "Imported" not in html

    def test_a_locally_authored_vocabulary_still_shows_no_identifier(self):
        # A vocabulary held here gains an identifier link only on its own page.
        scheme = ConceptSchemeFactory.build()
        scheme.concept_count = 0

        html = render_to_string(ROW_TEMPLATE, {"object": scheme})
        soup = BeautifulSoup(html, "html.parser")

        assert soup.find("a", href=scheme.local_url) is None

    def test_a_urn_identifier_is_still_rendered_as_a_link_unrewritten(self):
        scheme = ConceptSchemeFactory.build(static_uri="urn:nbn:example:vocab-1")
        scheme.concept_count = 0

        html = render_to_string(ROW_TEMPLATE, {"object": scheme})
        soup = BeautifulSoup(html, "html.parser")
        anchor = soup.find("a", href="urn:nbn:example:vocab-1")

        assert anchor is not None
        assert anchor.text == "urn:nbn:example:vocab-1"

    def test_reports_the_number_of_concepts_it_holds(self):
        scheme = ConceptSchemeFactory.build()
        scheme.concept_count = 3

        html = render_to_string(ROW_TEMPLATE, {"object": scheme})

        assert "3 concepts" in html

    def test_a_vocabulary_with_no_concepts_reports_none_rather_than_blank(self):
        scheme = ConceptSchemeFactory.build()
        scheme.concept_count = 0

        html = render_to_string(ROW_TEMPLATE, {"object": scheme})

        assert "0 concepts" in html

    def test_a_vocabulary_with_no_description_renders_without_a_stray_label_or_punctuation(
        self,
    ):
        scheme = ConceptSchemeFactory.build(description="")
        scheme.concept_count = 0

        html = render_to_string(ROW_TEMPLATE, {"object": scheme})

        # Only the concept-count line renders as a <p>; nothing stands in for the description.
        assert html.count("<p") == 1


class TestVocabularyListOrdering:
    # Each test gives the vocabulary whose name sorts last a slug that sorts first. Count()
    # groups by every selected column including the unique slug, so without the mismatch a
    # slug-ordered page and a name-ordered one agree and the test proves nothing.

    @pytest.mark.django_db
    def test_a_name_beginning_with_a_lowercase_letter_still_sorts_before_an_uppercase_one_later_in_the_alphabet(
        self, client
    ):
        zebra = ConceptSchemeFactory(name="Zebra")
        zebra.set_slug("aaa-sorts-first-by-slug")
        ConceptSchemeFactory(name="antelope")

        response = client.get(reverse("controlled_vocabularies_ui:vocabulary-list"))

        names = [vocabulary.name for vocabulary in response.context["object_list"]]
        # Byte order (capital Z = 0x5A, lowercase a = 0x61) would sort "Zebra" first, and
        # so would zebra's own (deliberately mis-set) slug; case-insensitive order by name
        # puts "antelope" first, as a reader expects.
        assert names == ["antelope", "Zebra"]

    @pytest.mark.django_db
    def test_two_requests_return_the_same_sequence(self, client):
        ConceptSchemeFactory.create_batch(5)
        url = reverse("controlled_vocabularies_ui:vocabulary-list")

        first = [vocabulary.pk for vocabulary in client.get(url).context["object_list"]]
        second = [
            vocabulary.pk for vocabulary in client.get(url).context["object_list"]
        ]

        assert first == second

    @pytest.mark.django_db
    def test_two_vocabularies_sharing_a_name_still_produce_a_deterministic_order(
        self, client
    ):
        first = ConceptSchemeFactory(name="Duplicate")
        # The slug is derived from the name and is unique app-wide, so a second same-named
        # scheme needs its own explicit slug to save at all. It sorts first by slug but
        # second by pk, so only a real pk tiebreak produces [first.pk, second.pk].
        second = ConceptSchemeFactory.build(name="Duplicate")
        second.set_slug("aaa-sorts-first-by-slug")
        url = reverse("controlled_vocabularies_ui:vocabulary-list")

        first_request = [
            vocabulary.pk for vocabulary in client.get(url).context["object_list"]
        ]
        second_request = [
            vocabulary.pk for vocabulary in client.get(url).context["object_list"]
        ]

        assert first_request == second_request == [first.pk, second.pk]

    @pytest.mark.django_db
    def test_query_count_is_flat_regardless_of_how_many_vocabularies_the_site_holds(
        self, client, django_assert_num_queries
    ):
        # Proves the annotation costs a flat number of queries as the table grows, not that
        # thirty rows render on one page (the page size is django-mvp's default).
        ConceptSchemeFactory.create_batch(3)
        url = reverse("controlled_vocabularies_ui:vocabulary-list")

        with CaptureQueriesContext(connection) as captured:
            client.get(url)
        baseline = len(captured.captured_queries)

        ConceptSchemeFactory.create_batch(27)

        with django_assert_num_queries(baseline):
            client.get(url)


class TestVocabularyListChosenOrdering:
    # ?o= does nothing unless the view declares order_by, and the sort control is wrapped in
    # {% if order_by_choices %} upstream, so a view declaring none ignores it in silence.

    @pytest.mark.django_db
    def test_the_page_offers_both_directions_by_name(self, client):
        ConceptSchemeFactory()

        response = client.get(reverse("controlled_vocabularies_ui:vocabulary-list"))

        assert [
            key for key, _label, _expression in response.context["order_by_choices"]
        ] == [
            "name_asc",
            "name_desc",
        ]

    @pytest.mark.django_db
    def test_choosing_z_to_a_reverses_the_page(self, client):
        # The slug is set against the name so slug order and name order differ.
        zebra = ConceptSchemeFactory(name="Zebra")
        zebra.set_slug("aaa-sorts-first-by-slug")
        ConceptSchemeFactory(name="antelope")
        url = reverse("controlled_vocabularies_ui:vocabulary-list")

        ascending = [
            v.name for v in client.get(url, {"o": "name_asc"}).context["object_list"]
        ]
        descending = [
            v.name for v in client.get(url, {"o": "name_desc"}).context["object_list"]
        ]

        assert ascending == ["antelope", "Zebra"]
        assert descending == ["Zebra", "antelope"]

    @pytest.mark.django_db
    def test_the_chosen_order_is_marked_as_the_current_one(self, client):
        ConceptSchemeFactory()

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"o": "name_desc"}
        )

        assert response.context["current_ordering"] == "name_desc"

    @pytest.mark.django_db
    def test_an_ordering_nobody_offered_is_ignored_rather_than_obeyed(self, client):
        # `?o=` is matched against declared keys, so a field name or SQL fragment is neither
        # honoured nor an error.
        zebra = ConceptSchemeFactory(name="Zebra")
        zebra.set_slug("aaa-sorts-first-by-slug")
        ConceptSchemeFactory(name="antelope")
        url = reverse("controlled_vocabularies_ui:vocabulary-list")

        response = client.get(url, {"o": "-slug"})

        assert response.status_code == 200
        assert [v.name for v in response.context["object_list"]] == [
            "antelope",
            "Zebra",
        ]
        assert response.context["current_ordering"] == ""

    @pytest.mark.django_db
    def test_a_search_and_a_chosen_order_apply_together(self, client):
        ConceptSchemeFactory(name="Soil Zebra")
        ConceptSchemeFactory(name="Soil Antelope")
        ConceptSchemeFactory(name="Rock Badger")
        url = reverse("controlled_vocabularies_ui:vocabulary-list")

        response = client.get(url, {"q": "Soil", "o": "name_desc"})

        assert [v.name for v in response.context["object_list"]] == [
            "Soil Zebra",
            "Soil Antelope",
        ]

    @pytest.mark.django_db
    def test_the_sort_control_submits_to_the_same_form_as_the_search_box(self, client):
        # Before django-mvp 0.19.2 no element with this id existed on a page showing neither
        # a filter nor a create button, so choosing an order submitted nothing.
        ConceptSchemeFactory()

        response = client.get(reverse("controlled_vocabularies_ui:vocabulary-list"))
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find("form", id="filterForm") is not None
        assert soup.find("input", attrs={"name": "o"}).get("form") == "filterForm"


class TestVocabularyListEmptyState:
    @pytest.mark.django_db
    def test_an_empty_site_returns_200_with_no_vocabularies_listed(self, client):
        response = client.get(reverse("controlled_vocabularies_ui:vocabulary-list"))

        assert response.status_code == 200
        assert list(response.context["object_list"]) == []


class TestVocabularySearch:
    @pytest.mark.django_db
    def test_a_word_from_the_name_narrows_to_that_vocabulary(self, client):
        match = ConceptSchemeFactory(name="Geological Time Scale")
        ConceptSchemeFactory(name="Soil Classification")

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": "Geological"}
        )

        listed = {vocabulary.pk for vocabulary in response.context["object_list"]}
        assert listed == {match.pk}

    @pytest.mark.django_db
    def test_a_word_appearing_only_in_the_description_narrows_too(self, client):
        match = ConceptSchemeFactory(
            name="Alpha", description="Covers stratigraphy and rock units"
        )
        ConceptSchemeFactory(name="Beta", description="Covers something else entirely")

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": "stratigraphy"}
        )

        listed = {vocabulary.pk for vocabulary in response.context["object_list"]}
        assert listed == {match.pk}

    @pytest.mark.django_db
    def test_matching_ignores_case(self, client):
        match = ConceptSchemeFactory(name="Geological Time Scale")
        ConceptSchemeFactory(name="Soil Classification")

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": "geological"}
        )

        listed = {vocabulary.pk for vocabulary in response.context["object_list"]}
        assert listed == {match.pk}

    @pytest.mark.django_db
    @pytest.mark.parametrize("term", ["%", "_", "'"])
    def test_a_term_containing_a_like_wildcard_or_a_quote_is_looked_for_literally(
        self, client, term
    ):
        # icontains escapes %, _ and the backslash, and no seeded value contains the literal
        # character, so a correct implementation matches nothing.
        ConceptSchemeFactory.create_batch(3)

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": term}
        )

        assert list(response.context["object_list"]) == []

    @pytest.mark.django_db
    def test_a_non_latin_term_matches_its_vocabulary(self, client):
        match = ConceptSchemeFactory(name="地質年代")
        ConceptSchemeFactory(name="Soil Classification")

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": "地質"}
        )

        listed = {vocabulary.pk for vocabulary in response.context["object_list"]}
        assert listed == {match.pk}

    @pytest.mark.django_db
    @pytest.mark.skipif(
        connection.vendor != "sqlite", reason="the limitation under test is SQLite's"
    )
    @pytest.mark.parametrize(
        ("name", "term", "matches"),
        [
            ("Ecology", "ECOLOGY", True),
            ("Ökologie", "ÖKOLOGIE", True),
            ("Ökologie", "ökologie", False),
            ("Гидрология", "гидрология", False),
        ],
    )
    def test_case_insensitive_matching_covers_ascii_letters_only_on_sqlite(
        self, client, name, term, matches
    ):
        # SQLite `LIKE` folds ASCII letters only, so `ökologie` does not find `Ökologie`, and
        # `Lower()` compiles to the same ASCII-only `LOWER()`. PostgreSQL folds all of
        # Unicode. Pinned so a change shows as a failing test; the README discloses it.
        scheme = ConceptSchemeFactory(name=name)

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": term}
        )

        listed = {vocabulary.pk for vocabulary in response.context["object_list"]}
        assert (listed == {scheme.pk}) is matches

    @pytest.mark.django_db
    def test_a_search_far_longer_than_any_real_one_still_answers(self, client):
        # Unbounded, the upstream mixin ORs one condition per word per field, and past about
        # 400 words the query exceeds SQLite's parser depth limit (django-mvp#281).
        ConceptSchemeFactory(name="Geology")
        term = " ".join(f"word{index}" for index in range(600))

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": term}
        )

        assert response.status_code == 200

    @pytest.mark.django_db
    def test_a_search_past_the_bound_keeps_its_first_words_and_drops_the_rest(
        self, client
    ):
        # Matching is OR, so a truncated term is answered on its first 100 words alone.
        # Zero-padded so no word is a substring of another: unpadded, `word5` would match
        # `word500` and the late vocabulary would be found for the wrong reason.
        early = ConceptSchemeFactory(name="word003 vocabulary")
        late = ConceptSchemeFactory(name="word500 vocabulary")
        term = " ".join(f"word{index:03d}" for index in range(600))

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": term}
        )

        listed = {vocabulary.pk for vocabulary in response.context["object_list"]}
        assert early.pk in listed
        assert late.pk not in listed

    @pytest.mark.django_db
    def test_a_search_of_nothing_but_whitespace_is_not_a_search(self, client):
        # The search mixin strips before testing for a term, so this filters nothing.
        ConceptSchemeFactory.create_batch(2)

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": "   "}
        )

        assert len(response.context["object_list"]) == 2

    @pytest.mark.django_db
    def test_a_whitespace_only_search_does_not_come_back_in_the_box(self, client):
        ConceptSchemeFactory.create_batch(2)

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": "   "}
        )
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find("input", attrs={"name": "q"}).get("value", "") == ""

    @pytest.mark.django_db
    def test_the_rendered_page_carries_a_search_input_and_nothing_else(self, client):
        # The toolbar django-mvp renders by default also offers filter and create, and this
        # page uses neither. Sort renders only because the view declares order_by.
        ConceptSchemeFactory()

        response = client.get(reverse("controlled_vocabularies_ui:vocabulary-list"))
        content = response.content.decode()

        assert 'name="q"' in content
        assert 'name="o"' in content
        assert "filterModal" not in content

    @pytest.mark.django_db
    def test_the_search_input_belongs_to_a_get_form_that_actually_exists(self, client):
        # The search input and button carry a hard-coded form="filterForm". Before django-mvp
        # 0.19.2 that id existed only inside the filter action, so search alone was wired to
        # nothing. A query-string test never touches the box's own wiring.
        ConceptSchemeFactory()

        response = client.get(reverse("controlled_vocabularies_ui:vocabulary-list"))
        soup = BeautifulSoup(response.content, "html.parser")

        form = soup.find("form", id="filterForm")
        assert form is not None
        assert form.get("method", "").lower() == "get"

        search_input = soup.find("input", attrs={"name": "q"})
        assert search_input is not None
        assert search_input.get("form") == "filterForm"

        submit = soup.find(attrs={"type": "submit", "form": "filterForm"})
        assert submit is not None

        sort_input = soup.find("input", attrs={"name": "o"})
        assert sort_input is not None
        assert sort_input.get("form") == "filterForm"


class TestVocabularySearchAcrossRequestsAndPages:
    @pytest.mark.django_db
    def test_requesting_the_same_search_address_twice_returns_the_same_set_in_the_same_order(
        self, client
    ):
        ConceptSchemeFactory(name="Stratigraphy Unit A")
        ConceptSchemeFactory(name="Stratigraphy Unit B")
        ConceptSchemeFactory(name="Soil Classification")
        url = reverse("controlled_vocabularies_ui:vocabulary-list")

        first = [
            vocabulary.pk
            for vocabulary in client.get(url, {"q": "Stratigraphy"}).context[
                "object_list"
            ]
        ]
        second = [
            vocabulary.pk
            for vocabulary in client.get(url, {"q": "Stratigraphy"}).context[
                "object_list"
            ]
        ]

        assert first == second
        assert len(first) == 2

    @pytest.mark.django_db
    def test_following_the_rendered_link_to_page_two_keeps_the_search_applied(
        self, client
    ):
        matching = [
            ConceptSchemeFactory(name=f"Stratigraphy Unit {i:02d}") for i in range(30)
        ]
        ConceptSchemeFactory.create_batch(5)
        url = reverse("controlled_vocabularies_ui:vocabulary-list")

        first_page = client.get(url, {"q": "Stratigraphy"})
        first_page_pks = {
            vocabulary.pk for vocabulary in first_page.context["object_list"]
        }
        assert len(first_page_pks) == first_page.context["paginator"].per_page

        # Read the link from the markup: a hand-built ?page=2 would hide a broken
        # query-string tag.
        soup = BeautifulSoup(first_page.content, "html.parser")
        page_two_href = next(
            a["href"]
            for a in soup.find_all("a", href=True)
            if "page=2" in a["href"] and "q=" in a["href"]
        )

        second_page = client.get(url + page_two_href)

        assert second_page.status_code == 200
        second_page_pks = {
            vocabulary.pk for vocabulary in second_page.context["object_list"]
        }
        matching_pks = {vocabulary.pk for vocabulary in matching}
        # The second page continues the narrowed set: no overlap, all matched, none missing.
        assert second_page_pks.isdisjoint(first_page_pks)
        assert second_page_pks <= matching_pks
        assert first_page_pks | second_page_pks == matching_pks


class TestVocabularySearchEmptyState:
    @pytest.mark.django_db
    def test_a_search_matching_nothing_returns_200_and_echoes_the_term(self, client):
        ConceptSchemeFactory(name="Soil Classification")

        response = client.get(
            reverse("controlled_vocabularies_ui:vocabulary-list"), {"q": "Stratigraphy"}
        )
        content = response.content.decode()

        assert response.status_code == 200
        assert "Stratigraphy" in content

    @pytest.mark.skip(
        reason=(
            "django-mvp 0.19.2 fixed the search box itself (django-mvp#282) but not this. A "
            "reader whose search matched nothing can clear the box and press the button to get "
            "back, so the page is usable; what is missing is a plain link that says so. It has "
            "to go in the page's actions area, because django-mvp renders the empty-state "
            "heading and message as autoescaped strings with no slot — an anchor inside the "
            "message would show as literal text, and mark_safe over a string that also carries "
            "the search term would emit that term unescaped. The actions area has no slot "
            "either, so placing it needs a page-template override, and this package no longer "
            "carries one. Raised upstream as django-mvp#291. The no-match message still names "
            "the term (test above); the vocabulary's own page has the link (it has its own "
            "template) and is not skipped."
        )
    )
    @pytest.mark.django_db
    def test_a_search_matching_nothing_offers_a_link_back_to_the_unsearched_list(
        self, client
    ):
        ConceptSchemeFactory(name="Soil Classification")
        list_url = reverse("controlled_vocabularies_ui:vocabulary-list")

        response = client.get(list_url, {"q": "Stratigraphy"})
        soup = BeautifulSoup(response.content, "html.parser")

        hrefs = {a["href"] for a in soup.find_all("a", href=True)}
        assert list_url in hrefs

    @pytest.mark.django_db
    def test_an_empty_site_with_no_search_shows_no_link_back_to_the_unsearched_list(
        self, client
    ):
        list_url = reverse("controlled_vocabularies_ui:vocabulary-list")

        response = client.get(list_url)
        soup = BeautifulSoup(response.content, "html.parser")

        hrefs = {a["href"] for a in soup.find_all("a", href=True)}
        assert list_url not in hrefs

    def test_the_no_match_and_site_empty_headings_are_different_strings(self, rf):
        no_match_view = VocabularyListView()
        no_match_view.request = rf.get("/", {"q": "Stratigraphy"})

        site_empty_view = VocabularyListView()
        site_empty_view.request = rf.get("/")

        assert str(no_match_view.get_empty_state_heading()) != str(
            site_empty_view.get_empty_state_heading()
        )

    @pytest.mark.django_db
    def test_a_term_containing_markup_is_escaped_in_the_response(self, client):
        # Scoped to the heading because the page's own theme-toggle script is a <script>. An
        # unescaped term parses as a real <script> inside it; a substring check on the raw
        # response cannot tell the two apart.
        ConceptSchemeFactory(name="Soil Classification")
        list_url = reverse("controlled_vocabularies_ui:vocabulary-list")

        response = client.get(list_url, {"q": "<script>alert(1)</script>"})
        soup = BeautifulSoup(response.content, "html.parser")
        heading = soup.find("h3")

        assert heading.find("script") is None
        assert "<script>alert(1)</script>" in heading.get_text()


class TestVocabularyDetail:
    @pytest.mark.django_db
    def test_a_known_vocabulary_serves_its_page_anonymously(self, client):
        scheme = ConceptSchemeFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )

        assert response.status_code == 200

    @pytest.mark.django_db
    def test_a_slug_nothing_has_returns_404(self, client):
        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": "no-such-vocabulary"},
            )
        )

        assert response.status_code == 404

    @pytest.mark.django_db
    def test_the_page_title_is_the_vocabularys_name(self, client):
        scheme = ConceptSchemeFactory(name="Geological Time Scale")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )

        assert response.context["page"]["title"] == scheme.name

    @pytest.mark.django_db
    def test_a_vocabulary_named_in_a_non_latin_script_still_serves_its_own_page(
        self, client
    ):
        # <str:slug>, not <slug:slug>: the model slugifies with allow_unicode=True, and
        # Django's slug converter matches ASCII only. A vocabulary named this way would
        # 404 on its own page under the obvious converter.
        scheme = ConceptSchemeFactory(name="地質年代")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )

        assert response.status_code == 200


class TestVocabularyDetailDescriptionAndProvenance:
    @pytest.mark.django_db
    def test_a_vocabulary_with_a_description_shows_it_and_reads_as_held_here(
        self, client
    ):
        scheme = ConceptSchemeFactory(
            description="Periods, epochs and ages of the geological record."
        )

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        content = response.content.decode()

        assert scheme.description in content
        assert "Held here" in content
        assert "Imported" not in content

    @pytest.mark.django_db
    def test_a_vocabulary_with_no_description_renders_no_heading_or_empty_element(
        self, client
    ):
        scheme = ConceptSchemeFactory(description="")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find(class_="vocabulary-description") is None

    @pytest.mark.django_db
    def test_a_vocabulary_published_elsewhere_shows_its_publisher_identifier(
        self, client
    ):
        scheme = ConceptSchemeFactory(external=True)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        content = response.content.decode()

        assert scheme.static_uri in content
        assert "Imported" in content
        assert "Held here" not in content

    @pytest.mark.django_db
    def test_a_description_running_to_several_paragraphs_is_shortened(self, client):
        description = " ".join(f"word{index}" for index in range(400))
        scheme = ConceptSchemeFactory(description=description)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        content = response.content.decode()

        assert "word0" in content
        assert "word399" not in content


class TestVocabularyDetailIdentifierLink:
    @pytest.mark.django_db
    def test_a_vocabulary_published_elsewhere_links_to_its_publisher_address(
        self, client
    ):
        scheme = ConceptSchemeFactory(external=True)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        anchor = soup.find("a", href=scheme.static_uri)

        assert anchor is not None
        assert anchor.text == scheme.static_uri
        assert anchor.get("rel") == ["noopener"]

    @pytest.mark.django_db
    def test_a_vocabulary_held_here_links_to_the_address_this_site_composes(
        self, client
    ):
        scheme = ConceptSchemeFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        anchor = soup.find("a", href=scheme.uri)

        assert anchor is not None
        assert anchor.text == scheme.uri
        assert anchor.get("rel") == ["noopener"]

    @pytest.mark.django_db
    def test_a_urn_identifier_is_still_rendered_as_a_link_unrewritten(self, client):
        scheme = ConceptSchemeFactory(static_uri="urn:nbn:example:vocab-1")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        anchor = soup.find("a", href="urn:nbn:example:vocab-1")

        assert anchor is not None
        assert anchor.text == "urn:nbn:example:vocab-1"


class TestVocabularyDetailConceptList:
    @pytest.mark.django_db
    def test_a_multi_level_hierarchy_renders_flat_with_every_concept_exactly_once(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        top = ConceptFactory(scheme=scheme, label="Top Concept")
        middle = ConceptFactory(scheme=scheme, label="Middle Concept")
        bottom = ConceptFactory(scheme=scheme, label="Bottom Concept")
        middle.add_broader(top)
        bottom.add_broader(middle)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )

        listed = list(response.context["object_list"])
        assert len(listed) == 3
        assert {concept.pk for concept in listed} == {top.pk, middle.pk, bottom.pk}

    @pytest.mark.django_db
    def test_a_concepts_row_carries_only_its_label_and_a_link_to_its_own_page(self):
        # A fully decorated concept rendered through the row partial alone: none of the
        # alternative label, note, identifier or relation belongs on the row.
        concept = ConceptFactory(label="Granite", external=True)
        concept.resolved_label = concept.label  # set by the list view's annotation
        ConceptNoteFactory(concept=concept, value="A coarse-grained igneous rock.")
        concept.add_label(language="en", kind="alternative", text="granitic rock")
        other = ConceptFactory(scheme=concept.scheme, label="Basalt")
        concept.add_broader(other)

        html = render_to_string(CONCEPT_ROW_TEMPLATE, {"object": concept})
        soup = BeautifulSoup(html, "html.parser")

        assert concept.label in html
        assert "A coarse-grained igneous rock." not in html
        assert "granitic rock" not in html
        assert concept.static_uri not in html
        assert "Basalt" not in html
        # The row leads to the concept's own page and nowhere else.
        anchors = soup.find_all("a")
        assert len(anchors) == 1
        assert anchors[0]["href"] == reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

    @pytest.mark.django_db
    def test_a_concept_belonging_to_another_vocabulary_does_not_appear(self, client):
        scheme = ConceptSchemeFactory()
        other_scheme = ConceptSchemeFactory()
        concept = ConceptFactory(scheme=scheme, label="Granite")
        foreign = ConceptFactory(scheme=other_scheme, label="Basalt")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )

        listed = {c.pk for c in response.context["object_list"]}
        assert listed == {concept.pk}
        assert foreign.pk not in listed


class TestVocabularyDetailConceptListLinksToConceptPages:
    @pytest.mark.django_db
    def test_a_concept_in_the_full_list_links_to_and_reaches_its_own_page(self, client):
        concept = ConceptFactory(label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": concept.scheme.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        anchor = next(
            a
            for a in soup.find_all("a", href=True)
            if a.get_text(strip=True) == concept.label
        )

        assert anchor["href"] == reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

        follow = client.get(anchor["href"])

        assert follow.status_code == 200
        assert follow.context["object"] == concept

    @pytest.mark.django_db
    def test_a_search_narrowed_result_links_to_and_reaches_its_own_page(self, client):
        match = ConceptFactory(label="Granite")
        ConceptFactory(scheme=match.scheme, label="Basalt")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": match.scheme.slug},
            ),
            {"q": "Granite"},
        )
        soup = BeautifulSoup(response.content, "html.parser")
        anchor = next(
            a
            for a in soup.find_all("a", href=True)
            if a.get_text(strip=True) == match.label
        )

        assert anchor["href"] == reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": match.scheme.slug, "concept_slug": match.slug},
        )

        follow = client.get(anchor["href"])

        assert follow.status_code == 200
        assert follow.context["object"] == match


class TestVocabularyDetailConceptLabel:
    @pytest.mark.django_db
    def test_a_concept_with_a_preferred_label_in_the_active_language_shows_it(
        self, client
    ):
        # Not a substring of the default label, so truncating "Granite" cannot pass.
        scheme = ConceptSchemeFactory()
        concept = ConceptFactory(scheme=scheme, label="Granite")
        concept.add_label(language="de", kind="preferred", text="Kristallgestein")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        with translation.override("de"):
            response = client.get(url)

        content = response.content.decode()
        assert "Kristallgestein" in content
        assert concept.label not in content

    @pytest.mark.django_db
    def test_a_concept_with_no_label_in_the_active_language_falls_back_to_its_default_one(
        self, client
    ):
        # Concept.label is the preferred label in the vocabulary's default language, so the
        # fallback needs no ConceptLabel row.
        scheme = ConceptSchemeFactory()
        ConceptFactory(scheme=scheme, label="Granite")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        with translation.override("de"):
            response = client.get(url)

        assert "Granite" in response.content.decode()

    @pytest.mark.django_db
    def test_query_count_is_flat_regardless_of_how_many_concepts_the_vocabulary_holds(
        self, client, django_assert_num_queries
    ):
        scheme = ConceptSchemeFactory()
        ConceptFactory.create_batch(3, scheme=scheme)
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        with CaptureQueriesContext(connection) as captured:
            client.get(url)
        baseline = len(captured.captured_queries)

        ConceptFactory.create_batch(27, scheme=scheme)

        with django_assert_num_queries(baseline):
            client.get(url)


class TestVocabularyDetailConceptOrder:
    @pytest.mark.django_db
    def test_order_follows_the_label_shown_under_the_active_language_not_the_stored_one(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        # zebra's default label sorts last and its German label first; antelope has no
        # German label and falls back. Order must follow the resolved label.
        zebra = ConceptFactory(scheme=scheme, label="Zebra")
        zebra.add_label(language="de", kind="preferred", text="Aardvark")
        antelope = ConceptFactory(scheme=scheme, label="Antelope")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        with translation.override("de"):
            german_order = [c.pk for c in client.get(url).context["object_list"]]
        default_order = [c.pk for c in client.get(url).context["object_list"]]

        assert german_order == [zebra.pk, antelope.pk]
        assert default_order == [antelope.pk, zebra.pk]

    @pytest.mark.django_db
    def test_two_identically_labelled_concepts_produce_a_deterministic_order(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        first = ConceptFactory(scheme=scheme, label="Duplicate")
        # Same-label concepts collide on the derived slug, so give the second its own.
        second = ConceptFactory.build(scheme=scheme, label="Duplicate")
        second.set_slug("aaa-sorts-first-by-slug")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        first_request = [c.pk for c in client.get(url).context["object_list"]]
        second_request = [c.pk for c in client.get(url).context["object_list"]]

        assert first_request == second_request == [first.pk, second.pk]

    @pytest.mark.django_db
    def test_two_requests_return_the_same_order(self, client):
        scheme = ConceptSchemeFactory()
        ConceptFactory.create_batch(5, scheme=scheme)
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        first = [c.pk for c in client.get(url).context["object_list"]]
        second = [c.pk for c in client.get(url).context["object_list"]]

        assert first == second


class TestVocabularyDetailChosenConceptOrder:
    # The page renders django-mvp's actions block as the vocabulary list does, so both the
    # control and the ?o= behind it are asserted.

    @pytest.mark.django_db
    def test_the_page_offers_both_directions_by_label(self, client):
        scheme = ConceptSchemeFactory()
        ConceptFactory(scheme=scheme)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )

        assert [
            key for key, _label, _expression in response.context["order_by_choices"]
        ] == [
            "label_asc",
            "label_desc",
        ]

    @pytest.mark.django_db
    def test_choosing_z_to_a_reverses_the_concepts(self, client):
        scheme = ConceptSchemeFactory()
        zebra = ConceptFactory(scheme=scheme, label="Zebra")
        antelope = ConceptFactory(scheme=scheme, label="Antelope")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        ascending = [
            c.pk for c in client.get(url, {"o": "label_asc"}).context["object_list"]
        ]
        descending = [
            c.pk for c in client.get(url, {"o": "label_desc"}).context["object_list"]
        ]

        assert ascending == [antelope.pk, zebra.pk]
        assert descending == [zebra.pk, antelope.pk]

    @pytest.mark.django_db
    def test_the_chosen_order_follows_the_label_shown_not_the_one_stored(self, client):
        # Sorting on the stored `label` column would put these the other way round.
        scheme = ConceptSchemeFactory()
        zebra = ConceptFactory(scheme=scheme, label="Zebra")
        zebra.add_label(language="de", kind="preferred", text="Aardvark")
        antelope = ConceptFactory(scheme=scheme, label="Antelope")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        with translation.override("de"):
            german = [
                c.pk
                for c in client.get(url, {"o": "label_desc"}).context["object_list"]
            ]

        assert german == [antelope.pk, zebra.pk]

    @pytest.mark.django_db
    def test_an_ordering_nobody_offered_is_ignored_rather_than_obeyed(self, client):
        scheme = ConceptSchemeFactory()
        zebra = ConceptFactory(scheme=scheme, label="Zebra")
        antelope = ConceptFactory(scheme=scheme, label="Antelope")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        response = client.get(url, {"o": "-label"})

        assert response.status_code == 200
        assert [c.pk for c in response.context["object_list"]] == [
            antelope.pk,
            zebra.pk,
        ]
        assert response.context["current_ordering"] == ""

    @pytest.mark.django_db
    def test_a_search_and_a_chosen_order_apply_together(self, client):
        scheme = ConceptSchemeFactory()
        ConceptFactory(scheme=scheme, label="Basalt Zebra")
        ConceptFactory(scheme=scheme, label="Basalt Antelope")
        ConceptFactory(scheme=scheme, label="Granite Badger")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        response = client.get(url, {"q": "Basalt", "o": "label_desc"})

        labels = [c.label for c in response.context["object_list"]]
        assert labels == ["Basalt Zebra", "Basalt Antelope"]

    @pytest.mark.django_db
    def test_the_search_box_and_the_sort_control_both_submit_to_a_form_that_exists(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        ConceptFactory(scheme=scheme)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        form = soup.find("form", id="filterForm")
        assert form is not None
        assert form.get("method", "").lower() == "get"
        assert soup.find("input", attrs={"name": "q"}).get("form") == "filterForm"
        assert soup.find("input", attrs={"name": "o"}).get("form") == "filterForm"


class TestVocabularyDetailConceptPaging:
    @pytest.mark.django_db
    def test_a_long_list_is_paged_and_the_second_page_renders(self, client):
        scheme = ConceptSchemeFactory()
        ConceptFactory.create_batch(30, scheme=scheme)
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        first_page = client.get(url)
        per_page = first_page.context["paginator"].per_page
        assert len(first_page.context["object_list"]) == per_page

        soup = BeautifulSoup(first_page.content, "html.parser")
        page_two_href = next(
            a["href"] for a in soup.find_all("a", href=True) if "page=2" in a["href"]
        )

        second_page = client.get(url + page_two_href)

        assert second_page.status_code == 200
        assert len(second_page.context["object_list"]) == 30 - per_page

    @pytest.mark.django_db
    def test_a_paging_link_carries_forward_an_active_query_parameter(self, client):
        # Uses a parameter the view gives no meaning to, so this is about the paging link
        # carrying it forward. Read the link from the markup: a hand-built one would hide a
        # broken querystring tag.
        scheme = ConceptSchemeFactory()
        ConceptFactory.create_batch(30, scheme=scheme)
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        response = client.get(url, {"unrelated": "kept"})
        soup = BeautifulSoup(response.content, "html.parser")

        page_two_href = next(
            a["href"]
            for a in soup.find_all("a", href=True)
            if "page=2" in a["href"] and "unrelated=kept" in a["href"]
        )

        second_page = client.get(url + page_two_href)
        assert second_page.status_code == 200

    @pytest.mark.django_db
    def test_a_vocabulary_holding_no_concepts_still_renders_the_rest_of_the_page(
        self, client
    ):
        scheme = ConceptSchemeFactory(
            description="Periods, epochs and ages of the geological record."
        )

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        content = response.content.decode()

        assert response.status_code == 200
        assert list(response.context["object_list"]) == []
        assert scheme.name in content
        assert scheme.description in content


class TestVocabularyDetailConceptSearch:
    @pytest.mark.django_db
    def test_a_word_only_in_the_preferred_label_finds_it(self, client):
        match = ConceptFactory(label="Granite")
        ConceptFactory(scheme=match.scheme, label="Basalt")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail",
            kwargs={"slug": match.scheme.slug},
        )

        response = client.get(url, {"q": "Granite"})

        listed = {c.pk for c in response.context["object_list"]}
        assert listed == {match.pk}

    @pytest.mark.django_db
    def test_a_word_only_in_an_alternative_label_finds_it(self, client):
        match = ConceptFactory(label="Granite")
        match.add_label(
            language="en", kind=ConceptLabel.Kind.ALTERNATIVE, text="granitic rock"
        )
        ConceptFactory(scheme=match.scheme, label="Basalt")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail",
            kwargs={"slug": match.scheme.slug},
        )

        response = client.get(url, {"q": "granitic"})

        listed = {c.pk for c in response.context["object_list"]}
        assert listed == {match.pk}

    @pytest.mark.django_db
    def test_a_word_only_in_a_hidden_label_finds_it_and_the_label_is_shown_nowhere(
        self, client
    ):
        match = ConceptFactory(label="Granite")
        match.add_label(language="en", kind=ConceptLabel.Kind.HIDDEN, text="granate")
        ConceptFactory(scheme=match.scheme, label="Basalt")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail",
            kwargs={"slug": match.scheme.slug},
        )

        response = client.get(url, {"q": "granate"})
        # The search box echoes ?q= as an <input value> attribute, which get_text() skips.
        rendered_text = BeautifulSoup(response.content, "html.parser").get_text()

        listed = {c.pk for c in response.context["object_list"]}
        assert listed == {match.pk}
        assert "granate" not in rendered_text

    @pytest.mark.django_db
    def test_a_concept_matching_on_several_labels_at_once_is_listed_once(self, client):
        # Searching a reverse relation joins one row per matching label. Asserted as a list
        # because a set cannot see a repeat.
        match = ConceptFactory(label="Granite")
        match.add_label(
            language="en", kind=ConceptLabel.Kind.ALTERNATIVE, text="Granite rock"
        )
        match.add_label(
            language="en", kind=ConceptLabel.Kind.HIDDEN, text="Granite stone"
        )
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail",
            kwargs={"slug": match.scheme.slug},
        )

        response = client.get(url, {"q": "Granite"})

        assert [concept.pk for concept in response.context["object_list"]] == [match.pk]

    @pytest.mark.django_db
    def test_a_word_only_in_the_definition_does_not_find_the_concept(self, client):
        concept = ConceptFactory(label="Granite")
        ConceptNoteFactory(concept=concept, value="A coarse-grained igneous rock.")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail",
            kwargs={"slug": concept.scheme.slug},
        )

        response = client.get(url, {"q": "igneous"})

        assert list(response.context["object_list"]) == []

    @pytest.mark.django_db
    def test_a_matching_concept_in_another_vocabulary_is_not_returned(self, client):
        match = ConceptFactory(label="Granite")
        other_scheme = ConceptSchemeFactory()
        foreign = ConceptFactory(scheme=other_scheme, label="Granite Boulder")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail",
            kwargs={"slug": match.scheme.slug},
        )

        response = client.get(url, {"q": "Granite"})

        listed = {c.pk for c in response.context["object_list"]}
        assert listed == {match.pk}
        assert foreign.pk not in listed

    @pytest.mark.django_db
    def test_a_search_run_directly_from_the_second_page_still_reaches_every_concept(
        self, client
    ):
        # Requested with page=2 up front: a search scoped to the page being viewed would
        # filter only that page and leak the non-matching concepts through.
        scheme = ConceptSchemeFactory()
        matching = [
            ConceptFactory(scheme=scheme, label=f"Stratigraphy Unit {i:02d}")
            for i in range(30)
        ]
        non_matching = ConceptFactory.create_batch(5, scheme=scheme)
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        response = client.get(url, {"q": "Stratigraphy", "page": 2})

        assert response.status_code == 200
        listed = {c.pk for c in response.context["object_list"]}
        matching_pks = {c.pk for c in matching}
        non_matching_pks = {c.pk for c in non_matching}
        assert listed <= matching_pks
        assert listed.isdisjoint(non_matching_pks)
        assert response.context["paginator"].count == 30


class TestVocabularyDetailConceptSearchAddressAndCase:
    # The letter-case limit outside ASCII is disclosed in
    # docs/adr/0014-database-collation-differences-are-disclosed-not-repaired.md.

    @pytest.mark.django_db
    def test_a_narrowed_lists_address_opened_fresh_returns_the_same_concepts(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        match = ConceptFactory(scheme=scheme, label="Stratigraphy Unit")
        ConceptFactory(scheme=scheme, label="Soil Classification")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        first = {
            c.pk for c in client.get(url, {"q": "Stratigraphy"}).context["object_list"]
        }
        second = {
            c.pk for c in client.get(url, {"q": "Stratigraphy"}).context["object_list"]
        }

        assert first == second == {match.pk}

    @pytest.mark.django_db
    def test_matching_ignores_ascii_case(self, client):
        match = ConceptFactory(label="Granite")
        ConceptFactory(scheme=match.scheme, label="Basalt")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail",
            kwargs={"slug": match.scheme.slug},
        )

        response = client.get(url, {"q": "granite"})

        listed = {c.pk for c in response.context["object_list"]}
        assert listed == {match.pk}

    @pytest.mark.django_db
    @pytest.mark.parametrize("term", ["%", "_", "'"])
    def test_a_term_containing_a_like_wildcard_or_a_quote_is_looked_for_literally(
        self, client, term
    ):
        # icontains escapes %, _ and the backslash, and no seeded label contains the literal
        # character, so a correct implementation matches nothing.
        scheme = ConceptSchemeFactory()
        ConceptFactory.create_batch(3, scheme=scheme)
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        response = client.get(url, {"q": term})

        assert list(response.context["object_list"]) == []

    @pytest.mark.django_db
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
        # by ökologie; PostgreSQL matches either way (docs/adr/0014-...).
        concept = ConceptFactory(label=label)
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail",
            kwargs={"slug": concept.scheme.slug},
        )

        response = client.get(url, {"q": term})

        listed = {c.pk for c in response.context["object_list"]}
        assert (listed == {concept.pk}) is matches


class TestVocabularyDetailConceptSearchEmptyState:
    # The term is read stripped, as django-mvp's mixin reads it, so the empty state and the
    # queryset agree on whether a search is in force.

    @pytest.mark.django_db
    def test_a_search_matching_nothing_returns_200_and_echoes_the_term(self, client):
        scheme = ConceptSchemeFactory()
        ConceptFactory(scheme=scheme, label="Granite")
        url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        response = client.get(url, {"q": "Basalt"})
        content = response.content.decode()

        assert response.status_code == 200
        assert "Basalt" in content

    @pytest.mark.django_db
    def test_a_search_matching_nothing_offers_a_link_back_to_the_unsearched_vocabulary(
        self, client
    ):
        # Unlike the vocabulary list, this page has its own template and renders the link
        # itself, so it does not wait on django-mvp.
        scheme = ConceptSchemeFactory()
        ConceptFactory(scheme=scheme, label="Granite")
        detail_url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        response = client.get(detail_url, {"q": "Basalt"})
        soup = BeautifulSoup(response.content, "html.parser")

        hrefs = {a["href"] for a in soup.find_all("a", href=True)}
        assert detail_url in hrefs

    @pytest.mark.django_db
    def test_a_vocabulary_holding_no_concepts_shows_no_link_back_to_the_unsearched_one(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        detail_url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        response = client.get(detail_url)
        soup = BeautifulSoup(response.content, "html.parser")

        hrefs = {a["href"] for a in soup.find_all("a", href=True)}
        assert detail_url not in hrefs

    def test_the_no_match_and_no_concepts_headings_are_different_strings(self, rf):
        scheme = ConceptSchemeFactory.build()

        no_match_view = VocabularyDetailView()
        no_match_view.vocabulary = scheme
        no_match_view.request = rf.get("/", {"q": "Basalt"})

        empty_view = VocabularyDetailView()
        empty_view.vocabulary = scheme
        empty_view.request = rf.get("/")

        assert str(no_match_view.get_empty_state_heading()) != str(
            empty_view.get_empty_state_heading()
        )

    @pytest.mark.django_db
    def test_a_whitespace_only_search_is_not_a_search(self, client):
        # A raw, unstripped `?q=%20%20` must not half-search: the list stays unfiltered and
        # no link offers to undo a search that never happened.
        scheme = ConceptSchemeFactory()
        ConceptFactory.create_batch(2, scheme=scheme)
        detail_url = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", kwargs={"slug": scheme.slug}
        )

        response = client.get(detail_url, {"q": "   "})
        soup = BeautifulSoup(response.content, "html.parser")

        assert len(response.context["object_list"]) == 2
        hrefs = {a["href"] for a in soup.find_all("a", href=True)}
        assert detail_url not in hrefs


class TestVocabularyDetailCollections:
    @pytest.mark.django_db
    def test_each_collection_is_named(self, client):
        scheme = ConceptSchemeFactory()
        igneous, _ = collection_with_members(scheme=scheme, labels=("Granite",))
        sedimentary, _ = collection_with_members(scheme=scheme, labels=("Sandstone",))

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        content = response.content.decode()

        assert igneous.name in content
        assert sedimentary.name in content

    @pytest.mark.django_db
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

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        rows = soup.find_all("li")
        unordered_row = next(row for row in rows if unordered.name in row.get_text())
        ordered_row = next(row for row in rows if ordered.name in row.get_text())

        unordered_marking = unordered_row.get_text(strip=True).replace(
            unordered.name, ""
        )
        ordered_marking = ordered_row.get_text(strip=True).replace(ordered.name, "")
        assert unordered_marking == ""
        assert ordered_marking != ""

    @pytest.mark.django_db
    def test_a_vocabulary_holding_no_collections_shows_no_collections_section(
        self, client
    ):
        scheme = ConceptSchemeFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )

        assert list(response.context["collections"]) == []

    @pytest.mark.django_db
    def test_collections_are_separate_from_the_concept_list_not_mixed_into_it(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite", "Basalt")
        )
        other_concept = ConceptFactory(scheme=scheme, label="Quartz")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )

        assert list(response.context["collections"]) == [collection]
        # Every concept appears once, whether or not it belongs to a collection.
        listed = {c.pk for c in response.context["object_list"]}
        assert listed == {members[0].pk, members[1].pk, other_concept.pk}

    @pytest.mark.django_db
    def test_each_collection_links_to_and_reaches_its_own_page(self, client):
        scheme = ConceptSchemeFactory()
        collection, _ = collection_with_members(scheme=scheme)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        expected_href = reverse(
            "controlled_vocabularies_ui:collection-detail",
            kwargs={"slug": scheme.slug, "collection_slug": collection.slug},
        )
        anchor = next(
            a
            for a in soup.find_all("a", href=True)
            if a.get_text(strip=True) == collection.name
        )
        assert anchor["href"] == expected_href

        follow = client.get(anchor["href"])

        assert follow.status_code == 200
        assert follow.context["object"] == collection


class TestTemplateCommentsDoNotReachThePage:
    # Django's {# #} does not match across a newline, so a multi-line one is served to the
    # reader as text.

    @pytest.mark.django_db
    def test_the_list_of_vocabularies_serves_no_comment_text(self, client):
        ConceptSchemeFactory(external=True, description="A description.")

        response = client.get(reverse("controlled_vocabularies_ui:vocabulary-list"))
        content = response.content.decode()

        assert "{#" not in content
        assert "#}" not in content

    @pytest.mark.django_db
    def test_a_vocabulary_page_serves_no_comment_text(self, client):
        scheme = ConceptSchemeFactory(external=True, description="A description.")
        collection_with_members(scheme=scheme)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": scheme.slug},
            ),
            {"q": "nothing"},
        )
        content = response.content.decode()

        assert "{#" not in content
        assert "#}" not in content


class TestConceptPropertyRowsForABareConcept:
    # Membership is a statement other records make about a concept, so it is not a row.

    @pytest.mark.django_db
    def test_a_bare_concept_yields_exactly_type_preferred_label_and_vocabulary(self):
        concept = ConceptFactory(label="Granite")

        rows = concept_property_rows(concept, "en")

        assert [row["term"] for row in rows] == [
            TYPE_CURIE,
            LABEL_CURIES[ConceptLabel.Kind.PREFERRED],
            IN_SCHEME_CURIE,
        ]

    @pytest.mark.django_db
    def test_the_type_row_carries_the_concept_type_curie_as_a_plain_value(self):
        concept = ConceptFactory()

        rows = concept_property_rows(concept, "en")

        type_row = rows[0]
        assert type_row["term"] == TYPE_CURIE
        assert type_row["value"] == CONCEPT_TYPE_CURIE
        assert type_row["short_form"] is None


class TestConceptPropertyRowsOrderForARichlyPopulatedConcept:
    @pytest.mark.django_db
    def test_every_section_appears_in_the_fixed_order(self):
        concept = ConceptFactory(label="Granite")
        concept.add_label(
            language="en", kind=ConceptLabel.Kind.ALTERNATIVE, text="granitic rock"
        )
        for kind in ConceptNote.Kind:
            ConceptNoteFactory(concept=concept, kind=kind, value=f"A {kind} note.")
        parent = ConceptFactory(scheme=concept.scheme, label="Igneous Rock")
        concept.add_broader(parent)
        child = ConceptFactory(scheme=concept.scheme, label="Pink Granite")
        child.add_broader(concept)
        other = ConceptFactory(scheme=concept.scheme, label="Basalt")
        concept.add_related(other)

        rows = concept_property_rows(concept, "en")

        assert [row["term"] for row in rows] == [
            TYPE_CURIE,
            LABEL_CURIES[ConceptLabel.Kind.PREFERRED],
            LABEL_CURIES[ConceptLabel.Kind.ALTERNATIVE],
            NOTE_CURIES[ConceptNote.Kind.DEFINITION],
            NOTE_CURIES[ConceptNote.Kind.SCOPE],
            NOTE_CURIES[ConceptNote.Kind.EXAMPLE],
            NOTE_CURIES[ConceptNote.Kind.EDITORIAL],
            NOTE_CURIES[ConceptNote.Kind.HISTORY],
            NOTE_CURIES[ConceptNote.Kind.CHANGE],
            NOTE_CURIES[ConceptNote.Kind.NOTE],
            BROADER_CURIE,
            NARROWER_CURIE,
            RELATED_CURIE,
            IN_SCHEME_CURIE,
        ]


class TestConceptPropertyRowsHiddenLabel:
    @pytest.mark.django_db
    def test_a_hidden_label_contributes_no_row_and_no_hidden_curie_appears(self):
        concept = ConceptFactory(label="Granite")
        concept.add_label(language="en", kind=ConceptLabel.Kind.HIDDEN, text="granate")

        rows = concept_property_rows(concept, "en")

        assert "granate" not in [row["value"] for row in rows]
        assert not any(row["term"] == "skos:hiddenLabel" for row in rows)


class TestConceptPropertyRowsRecordValuedRows:
    @pytest.mark.django_db
    def test_a_broader_row_carries_the_related_concepts_short_form_uri_and_link(self):
        concept = ConceptFactory(label="Granite")
        parent = ConceptFactory(scheme=concept.scheme, label="Igneous Rock")
        concept.add_broader(parent)

        rows = concept_property_rows(concept, "en")

        broader_row = next(row for row in rows if row["term"] == BROADER_CURIE)
        assert broader_row["value"] is None
        assert broader_row["short_form"] == f"{parent.scheme.slug}:{parent.slug}"
        assert broader_row["uri"] == parent.uri
        assert broader_row["href"] == reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": parent.scheme.slug, "concept_slug": parent.slug},
        )

    @pytest.mark.django_db
    def test_the_vocabulary_row_links_to_the_vocabularys_own_page(self):
        concept = ConceptFactory(label="Granite")

        rows = concept_property_rows(concept, "en")

        vocabulary_row = next(row for row in rows if row["term"] == IN_SCHEME_CURIE)
        assert vocabulary_row["value"] is None
        # A vocabulary has no short prefix, so its row uses the display name.
        assert vocabulary_row["short_form"] == concept.scheme.name
        assert vocabulary_row["uri"] == concept.scheme.uri
        assert vocabulary_row["href"] == reverse(
            "controlled_vocabularies_ui:vocabulary-detail",
            kwargs={"slug": concept.scheme.slug},
        )


class TestConceptPropertyRowsLanguageScoping:
    # The function takes one reading language and does no fallback; the caller decides that.

    @pytest.mark.django_db
    def test_a_preferred_label_absent_in_the_given_language_contributes_no_row(self):
        concept = ConceptFactory(label="Granite")  # only the English default label

        rows = concept_property_rows(concept, "de")

        assert LABEL_CURIES[ConceptLabel.Kind.PREFERRED] not in [
            row["term"] for row in rows
        ]

    @pytest.mark.django_db
    def test_a_preferred_label_present_in_the_given_language_does_appear(self):
        concept = ConceptFactory(label="Granite")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Kristallgestein"
        )

        rows = concept_property_rows(concept, "de")

        preferred_row = next(
            row
            for row in rows
            if row["term"] == LABEL_CURIES[ConceptLabel.Kind.PREFERRED]
        )
        assert preferred_row["value"] == "Kristallgestein"


class TestConceptDetail:
    @pytest.mark.django_db
    def test_a_known_concept_serves_its_page_anonymously(self, client):
        concept = ConceptFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )

        assert response.status_code == 200

    @pytest.mark.django_db
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

    @pytest.mark.django_db
    def test_a_vocabulary_segment_naming_nothing_also_returns_404(self, client):
        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": "no-such-vocabulary", "concept_slug": "whatever"},
            )
        )

        assert response.status_code == 404

    @pytest.mark.django_db
    def test_a_concept_slug_shared_by_two_vocabularies_resolves_to_the_one_named_in_the_address(
        self, client
    ):
        one = ConceptSchemeFactory()
        two = ConceptSchemeFactory()
        ConceptFactory(scheme=one, label="Granite")
        concept_in_two = ConceptFactory(scheme=two, label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": two.slug, "concept_slug": concept_in_two.slug},
            )
        )

        assert response.status_code == 200
        assert response.context["object"] == concept_in_two

    @pytest.mark.django_db
    def test_the_page_shows_no_editing_control(self, client):
        concept = ConceptFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )

        # Every show_<action>_action defaults to False upstream, so this catches that
        # default flipping in a 0.x dependency.
        assert response.context["directory"] == {}

    @pytest.mark.django_db
    def test_the_context_carries_the_concepts_property_rows(self, client):
        concept = ConceptFactory(label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )

        assert response.context["rows"] == concept_property_rows(concept, "en")


class TestConceptDetailBreadcrumbs:
    @pytest.mark.django_db
    def test_the_trail_leads_home_then_to_the_vocabulary_then_the_concept(self, client):
        concept = ConceptFactory(label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )

        trail = response.context["page"]["breadcrumbs"]
        assert [crumb.get("href") for crumb in trail] == [
            "/",
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": concept.scheme.slug},
            ),
            None,
        ]
        assert [crumb["text"] for crumb in trail[1:]] == [
            concept.scheme.name,
            "Granite",
        ]


class TestConceptDetailShowsWhatIsRecorded:
    @pytest.mark.django_db
    def test_a_preferred_label_a_definition_and_a_scope_note_each_show_on_their_own_row(
        self, client
    ):
        concept = ConceptFactory(label="Granite")
        ConceptNoteFactory(
            concept=concept,
            kind=ConceptNote.Kind.DEFINITION,
            value="A coarse-grained igneous rock.",
        )
        ConceptNoteFactory(
            concept=concept,
            kind=ConceptNote.Kind.SCOPE,
            value="Used for building stone.",
        )

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        pairs = [
            (term_text(dt), dt.find_next_sibling("dd").get_text(strip=True))
            for dt in soup.find_all("dt")
        ]

        assert (LABEL_CURIES[ConceptLabel.Kind.PREFERRED], "Granite") in pairs
        assert (
            NOTE_CURIES[ConceptNote.Kind.DEFINITION],
            "A coarse-grained igneous rock.",
        ) in pairs
        assert (
            NOTE_CURIES[ConceptNote.Kind.SCOPE],
            "Used for building stone.",
        ) in pairs

    @pytest.mark.django_db
    def test_alternative_labels_appear_and_no_hidden_label_appears_anywhere(
        self, client
    ):
        concept = ConceptFactory(label="Granite")
        concept.add_label(
            language="en", kind=ConceptLabel.Kind.ALTERNATIVE, text="granitic rock"
        )
        concept.add_label(language="en", kind=ConceptLabel.Kind.HIDDEN, text="granate")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        content = response.content.decode()
        soup = BeautifulSoup(response.content, "html.parser")
        pairs = [
            (term_text(dt), dt.find_next_sibling("dd").get_text(strip=True))
            for dt in soup.find_all("dt")
        ]

        assert (LABEL_CURIES[ConceptLabel.Kind.ALTERNATIVE], "granitic rock") in pairs
        assert "granate" not in content


class TestConceptDetailValuesInTheReadingLanguage:
    @staticmethod
    def _dl_values(response):
        """Read every ``<dd>`` value from a rendered page.

        Args:
            response: The response to parse.

        Returns:
            The stripped text of each ``<dd>``, in page order.
        """
        soup = BeautifulSoup(response.content, "html.parser")
        return [dd.get_text(strip=True) for dd in soup.find_all("dd")]

    @pytest.mark.django_db
    def test_values_present_in_both_languages_show_the_reading_languages_ones(
        self, client
    ):
        concept = ConceptFactory(label="Granite")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.PREFERRED, text="Kristallgestein"
        )
        concept.add_label(
            language="en", kind=ConceptLabel.Kind.ALTERNATIVE, text="granite stone"
        )
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.ALTERNATIVE, text="Granitstein"
        )
        ConceptNoteFactory(
            concept=concept,
            language="en",
            kind=ConceptNote.Kind.DEFINITION,
            value="An igneous rock.",
        )
        ConceptNoteFactory(
            concept=concept,
            language="de",
            kind=ConceptNote.Kind.DEFINITION,
            value="Ein Eruptivgestein.",
        )
        url = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

        with translation.override("de"):
            response = client.get(url)

        values = self._dl_values(response)
        assert "Kristallgestein" in values
        assert "Granitstein" in values
        assert "Ein Eruptivgestein." in values
        assert concept.label not in values
        assert "granite stone" not in values
        assert "An igneous rock." not in values

    @pytest.mark.django_db
    def test_a_concept_with_no_value_in_the_reading_language_falls_back_to_the_vocabularys_default(
        self, client
    ):
        concept = ConceptFactory(label="Granite")
        concept.add_label(
            language="en", kind=ConceptLabel.Kind.ALTERNATIVE, text="granite stone"
        )
        ConceptNoteFactory(
            concept=concept,
            language="en",
            kind=ConceptNote.Kind.DEFINITION,
            value="An igneous rock.",
        )
        url = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

        with translation.override("de"):
            response = client.get(url)

        values = self._dl_values(response)
        assert concept.label in values
        assert "granite stone" in values
        assert "An igneous rock." in values


class TestConceptDetailTypeAndIdentifier:
    @pytest.mark.django_db
    def test_the_type_row_is_keyed_by_the_literal_rdf_type_not_a_skos_curie(
        self, client
    ):
        concept = ConceptFactory(label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        pairs = [
            (term_text(dt), dt.find_next_sibling("dd").get_text(strip=True))
            for dt in soup.find_all("dt")
        ]

        assert TYPE_CURIE == "rdf:type"
        assert (TYPE_CURIE, CONCEPT_TYPE_CURIE) in pairs

    @pytest.mark.django_db
    def test_the_identifier_appears_as_an_anchor_to_the_records_own_uri(self, client):
        concept = ConceptFactory(label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        identifier_link = soup.find("a", href=concept.uri)

        assert identifier_link is not None
        assert concept.uri in identifier_link.get_text(strip=True)

    @pytest.mark.django_db
    def test_an_imported_concept_shows_its_publishers_identifier(self, client):
        concept = ConceptFactory(label="Granite", external=True)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        identifier_link = soup.find("a", href=concept.static_uri)

        assert concept.static_uri.startswith("http://publisher.example.org/")
        assert identifier_link is not None
        assert concept.static_uri in identifier_link.get_text(strip=True)


class TestConceptDetailUnfilledPropertiesProduceNoRow:
    @pytest.mark.django_db
    def test_a_bare_concepts_page_names_exactly_type_label_identifier_and_vocabulary(
        self, client
    ):
        concept = ConceptFactory(label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        terms = [term_text(dt) for dt in soup.find_all("dt")]

        assert terms == [
            TYPE_CURIE,
            LABEL_CURIES[ConceptLabel.Kind.PREFERRED],
            IN_SCHEME_CURIE,
        ]
        assert soup.find("a", href=concept.uri) is not None


class TestConceptDetailQueryCount:
    @pytest.mark.django_db
    def test_query_count_is_flat_as_labels_notes_and_relations_grow(
        self, client, django_assert_num_queries
    ):
        scheme = ConceptSchemeFactory()
        concept = ConceptFactory(scheme=scheme, label="Granite")
        concept.add_label(
            language="de", kind=ConceptLabel.Kind.ALTERNATIVE, text="Granitstein"
        )
        ConceptNoteFactory(
            concept=concept, kind=ConceptNote.Kind.DEFINITION, value="An igneous rock."
        )
        ConceptRelationFactory(
            source=concept,
            target=ConceptFactory(scheme=scheme),
            kind=ConceptRelation.Kind.BROADER,
        )
        ConceptRelationFactory(
            source=ConceptFactory(scheme=scheme),
            target=concept,
            kind=ConceptRelation.Kind.BROADER,
        )
        ConceptRelationFactory(
            source=concept,
            target=ConceptFactory(scheme=scheme),
            kind=ConceptRelation.Kind.RELATED,
        )
        url = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": scheme.slug, "concept_slug": concept.slug},
        )

        with CaptureQueriesContext(connection) as captured:
            client.get(url)
        baseline = len(captured.captured_queries)

        # select_related and prefetch_related on the queryset collapse a query per call
        # site (alternative labels, each note kind, the scheme) into three. A ceiling as well
        # as flatness, because the number of note kinds is fixed and would be flat anyway.
        assert baseline <= 8

        for i in range(5):
            concept.add_label(
                language="fr", kind=ConceptLabel.Kind.ALTERNATIVE, text=f"Label {i}"
            )
            ConceptNoteFactory(
                concept=concept, kind=ConceptNote.Kind.SCOPE, value=f"Note {i}"
            )
            ConceptRelationFactory(
                source=concept,
                target=ConceptFactory(scheme=scheme),
                kind=ConceptRelation.Kind.RELATED,
            )
            # collections() costs one query whatever its length, so a per-collection read
            # added later breaks the equality below.
            CollectionFactory(scheme=scheme, name=f"Collection {i}").add(concept)

        with django_assert_num_queries(baseline):
            client.get(url)


class TestConceptDetailCollectionMembership:
    @pytest.mark.django_db
    def test_a_concept_gathered_by_two_collections_links_to_each_collections_page(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        concept = ConceptFactory(scheme=scheme, label="Granite")
        igneous = CollectionFactory(scheme=scheme, name="Igneous rocks")
        hardness = CollectionFactory(scheme=scheme, name="Hardness scale")
        igneous.add(concept)
        hardness.add(concept)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        for collection in (igneous, hardness):
            expected_href = reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={"slug": scheme.slug, "collection_slug": collection.slug},
            )
            anchor = next(
                a
                for a in soup.find_all("a", href=True)
                if a.get_text(strip=True) == collection.name
            )
            assert anchor["href"] == expected_href

            follow = client.get(anchor["href"])
            assert follow.status_code == 200
            assert follow.context["object"] == collection

    @pytest.mark.django_db
    def test_a_concept_no_collection_gathers_lists_no_collections(self, client):
        concept = ConceptFactory(label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )

        assert list(response.context["concept_collections"]) == []


class TestCollectionDetail:
    @pytest.mark.django_db
    def test_a_known_collection_serves_its_page_anonymously(self, client):
        collection = CollectionFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )

        assert response.status_code == 200

    @pytest.mark.django_db
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

    @pytest.mark.django_db
    def test_a_vocabulary_segment_naming_nothing_also_returns_404(self, client):
        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={"slug": "no-such-vocabulary", "collection_slug": "whatever"},
            )
        )

        assert response.status_code == 404

    @pytest.mark.django_db
    def test_a_concept_and_a_collection_sharing_one_slug_are_both_reachable(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        concept = ConceptFactory(scheme=scheme, label="Granite")
        collection = CollectionFactory(
            scheme=scheme, name=concept.label, slug_is_manual=True, slug=concept.slug
        )

        concept_response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": scheme.slug, "concept_slug": concept.slug},
            )
        )
        collection_response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={"slug": scheme.slug, "collection_slug": collection.slug},
            )
        )

        assert concept_response.status_code == 200
        assert collection_response.status_code == 200
        assert concept_response.context["object"] == concept
        assert collection_response.context["object"] == collection

    @pytest.mark.django_db
    def test_the_page_shows_no_editing_control(self, client):
        collection = CollectionFactory()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )

        assert response.context["directory"] == {}

    @pytest.mark.django_db
    def test_the_context_carries_the_collections_property_rows(self, client):
        collection = CollectionFactory(name="Rock Types")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )

        assert response.context["rows"] == collection_property_rows(collection)


class TestCollectionDetailBreadcrumbs:
    @pytest.mark.django_db
    def test_the_trail_leads_home_then_to_the_vocabulary_then_the_collection(
        self, client
    ):
        collection = CollectionFactory(name="Rock Types")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )

        trail = response.context["page"]["breadcrumbs"]
        assert [crumb.get("href") for crumb in trail] == [
            "/",
            reverse(
                "controlled_vocabularies_ui:vocabulary-detail",
                kwargs={"slug": collection.scheme.slug},
            ),
            None,
        ]
        assert [crumb["text"] for crumb in trail[1:]] == [
            collection.scheme.name,
            "Rock Types",
        ]


class TestCollectionDetailNameTypeAndMembers:
    @staticmethod
    def _dt_dd_pairs(response):
        """Pair each ``<dt>`` term with the text of its ``<dd>``.

        Args:
            response: The response to parse.

        Returns:
            ``(term, value)`` tuples in page order.
        """
        soup = BeautifulSoup(response.content, "html.parser")
        return [
            (term_text(dt), dt.find_next_sibling("dd").get_text(strip=True))
            for dt in soup.find_all("dt")
        ]

    @pytest.mark.django_db
    def test_an_unordered_collection_shows_its_name_type_and_one_row_carrying_every_member(
        self, client
    ):
        # One row carries every member, rather than one row per member.
        collection, members = collection_with_members(
            labels=("Granite", "Basalt", "Gabbro"), ordered=False
        )

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        pairs = self._dt_dd_pairs(response)

        assert (LABEL_CURIES[ConceptLabel.Kind.PREFERRED], collection.name) in pairs
        assert (TYPE_CURIE, COLLECTION_TYPE_CURIE) in pairs
        member_dts = [dt for dt in soup.find_all("dt") if term_text(dt) == MEMBER_CURIE]
        assert len(member_dts) == 1
        assert not any(term == MEMBER_LIST_CURIE for term, _value in pairs)
        member_short_forms = {
            a.get_text(strip=True)
            for a in member_dts[0].find_next_sibling("dd").find_all("a")
        }
        assert member_short_forms == {
            f"{collection.scheme.slug}:{member.slug}" for member in members
        }

    @pytest.mark.django_db
    def test_an_ordered_collections_type_differs_and_its_one_member_row_is_in_position_order(
        self, client
    ):
        # A non-alphabetical sequence, so the order assertion cannot pass by accident.
        collection, members = collection_with_members(
            labels=("Granite", "Basalt", "Gabbro"), ordered=True
        )

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        pairs = [
            (term_text(dt), dt.find_next_sibling("dd").get_text(strip=True))
            for dt in soup.find_all("dt")
        ]
        member_dts = [
            dt for dt in soup.find_all("dt") if term_text(dt) == MEMBER_LIST_CURIE
        ]
        assert len(member_dts) == 1
        # The anchors inside the one <dd> isolate each member's short form.
        member_short_forms = [
            a.get_text(strip=True)
            for a in member_dts[0].find_next_sibling("dd").find_all("a")
        ]

        assert (TYPE_CURIE, ORDERED_COLLECTION_TYPE_CURIE) in pairs
        assert not any(term == MEMBER_CURIE for term, _value in pairs)
        assert member_short_forms == [
            f"{collection.scheme.slug}:{member.slug}" for member in members
        ]

    @pytest.mark.django_db
    def test_the_identifier_appears_as_an_anchor_to_the_records_own_uri(self, client):
        collection = CollectionFactory(name="Rock Types")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        identifier_link = soup.find("a", href=collection.uri)

        assert identifier_link is not None
        assert collection.uri in identifier_link.get_text(strip=True)


class TestCollectionDetailMemberIdentifierDisclosedOnHover:
    @pytest.mark.django_db
    def test_each_members_identifier_is_disclosed_by_a_wrapping_tooltip_not_title(
        self, client
    ):
        collection, members = collection_with_members()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        member_dt = next(
            dt for dt in soup.find_all("dt") if term_text(dt) == MEMBER_CURIE
        )
        dd = member_dt.find_next_sibling("dd")
        anchors = dd.find_all("a")

        assert len(anchors) == len(members)
        seen_hidden_ids = set()
        for anchor, member in zip(anchors, members, strict=True):
            assert "tooltip" not in anchor.get("class", [])
            assert anchor.get("title") is None

            wrapper = anchor.find_parent("span", class_="tooltip")
            assert wrapper is not None
            assert wrapper.get("data-tip") == member.uri

            hidden_id = anchor.get("aria-describedby")
            assert hidden_id
            assert hidden_id not in seen_hidden_ids
            seen_hidden_ids.add(hidden_id)

            hidden_span = wrapper.find("span", id=hidden_id)
            assert hidden_span is not None
            assert "sr-only" in hidden_span.get("class", [])
            assert hidden_span.get_text() == member.uri

        dd_text = visible_text(dd)
        assert all(member.uri not in dd_text for member in members)


class TestCollectionDetailEmptyState:
    @pytest.mark.django_db
    def test_an_unordered_collection_with_no_members_has_no_membership_row(
        self, client
    ):
        collection = CollectionFactory(name="Rock Types", ordered=False)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        terms = [term_text(dt) for dt in soup.find_all("dt")]

        assert MEMBER_CURIE not in terms
        assert MEMBER_LIST_CURIE not in terms
        assert response.context["collection_has_members"] is False

    @pytest.mark.django_db
    def test_an_ordered_collection_with_no_members_has_no_membership_row(self, client):
        collection = CollectionFactory(name="Rock Types", ordered=True)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        terms = [term_text(dt) for dt in soup.find_all("dt")]

        assert MEMBER_CURIE not in terms
        assert MEMBER_LIST_CURIE not in terms
        assert response.context["collection_has_members"] is False

    @pytest.mark.django_db
    def test_a_collection_with_members_is_flagged_as_having_them(self, client):
        collection, _members = collection_with_members(labels=("Granite",))

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )

        assert response.context["collection_has_members"] is True


class TestCollectionDetailQueryCount:
    @pytest.mark.django_db
    def test_query_count_is_flat_as_members_grow(
        self, client, django_assert_num_queries
    ):
        scheme = ConceptSchemeFactory()
        collection, members = collection_with_members(
            scheme=scheme, labels=("Granite", "Basalt")
        )
        url = reverse(
            "controlled_vocabularies_ui:collection-detail",
            kwargs={"slug": scheme.slug, "collection_slug": collection.slug},
        )

        with CaptureQueriesContext(connection) as captured:
            client.get(url)
        baseline = len(captured.captured_queries)

        # A ceiling as well as flatness: the vocabulary lookup, the select_related object
        # fetch and one memberships query.
        assert baseline <= 3

        for i in range(5):
            collection.add(ConceptFactory(scheme=scheme, label=f"Member {i}"))

        with django_assert_num_queries(baseline):
            client.get(url)


class TestConceptDetailRelatedRecordIdentifiers:
    @staticmethod
    def _dd_for(soup, term):
        """Find the ``<dd>`` following a term's ``<dt>``.

        Args:
            soup: The parsed page.
            term: The term as a sighted reader sees it.

        Returns:
            The ``<dd>`` element paired with the term.
        """
        dt = next(dt for dt in soup.find_all("dt") if term_text(dt) == term)
        return dt.find_next_sibling("dd")

    @pytest.mark.django_db
    def test_a_related_records_identifier_is_disclosed_by_a_wrapping_tooltip_not_title(
        self, client
    ):
        concept = ConceptFactory(label="Granite")
        parent = ConceptFactory(scheme=concept.scheme, label="Igneous Rock")
        concept.add_broader(parent)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        broader_dd = self._dd_for(soup, BROADER_CURIE)
        link = broader_dd.find("a")

        assert "tooltip" not in link.get("class", [])
        assert link.get("title") is None

        wrapper = link.find_parent("span", class_="tooltip")
        assert wrapper is not None
        assert wrapper.get("data-tip") == parent.uri

        hidden_span = wrapper.find("span", id=link.get("aria-describedby"))
        assert hidden_span is not None
        assert "sr-only" in hidden_span.get("class", [])
        assert hidden_span.get_text() == parent.uri
        assert parent.uri not in visible_text(broader_dd)
        assert link["href"] == reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": parent.scheme.slug, "concept_slug": parent.slug},
        )

    @pytest.mark.django_db
    def test_an_imported_related_concept_shows_the_publishers_identifier_and_links_here(
        self, client
    ):
        concept = ConceptFactory(label="Granite")
        parent = ConceptFactory(
            scheme=concept.scheme, label="Igneous Rock", external=True
        )
        concept.add_broader(parent)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        broader_dd = self._dd_for(soup, BROADER_CURIE)
        link = broader_dd.find("a")
        wrapper = link.find_parent("span", class_="tooltip")

        assert parent.static_uri.startswith("http://publisher.example.org/")
        assert link.get("title") is None
        assert wrapper.get("data-tip") == parent.static_uri
        hidden_span = wrapper.find("span", id=link.get("aria-describedby"))
        assert hidden_span.get_text() == parent.static_uri
        assert parent.static_uri not in visible_text(broader_dd)
        assert link["href"] == reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": parent.scheme.slug, "concept_slug": parent.slug},
        )

        follow = client.get(link["href"])

        assert follow.status_code == 200
        assert follow.context["object"] == parent

    @pytest.mark.django_db
    def test_two_related_records_hidden_identifier_spans_have_distinct_ids(
        self, client
    ):
        # An id derived from the short form alone could collide across rows; two related
        # records on one page expose that.
        concept = ConceptFactory(label="Granite")
        broader = ConceptFactory(scheme=concept.scheme, label="Igneous Rock")
        related = ConceptFactory(scheme=concept.scheme, label="Basalt")
        concept.add_broader(broader)
        concept.add_related(related)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        broader_link = self._dd_for(soup, BROADER_CURIE).find("a")
        related_link = self._dd_for(soup, RELATED_CURIE).find("a")

        broader_id = broader_link.get("aria-describedby")
        related_id = related_link.get("aria-describedby")

        assert broader_id and related_id
        assert broader_id != related_id
        assert soup.find(id=broader_id).get_text() == broader.uri
        assert soup.find(id=related_id).get_text() == related.uri


class TestConceptDetailBroaderNarrowerAndRelated:
    @staticmethod
    def _links_for(soup, term):
        """Find the anchor in each ``<dd>`` following a term's ``<dt>``.

        Args:
            soup: The parsed page.
            term: The term as a sighted reader sees it.

        Returns:
            One anchor per matching row.
        """
        return [
            dt.find_next_sibling("dd").find("a")
            for dt in soup.find_all("dt")
            if term_text(dt) == term
        ]

    @pytest.mark.django_db
    def test_a_broader_concept_appears_and_following_it_opens_its_page(self, client):
        concept = ConceptFactory(label="Granite")
        parent = ConceptFactory(scheme=concept.scheme, label="Igneous Rock")
        concept.add_broader(parent)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        (link,) = self._links_for(soup, BROADER_CURIE)

        assert link.get_text(strip=True) == f"{parent.scheme.slug}:{parent.slug}"

        follow = client.get(link["href"])

        assert follow.status_code == 200
        assert follow.context["object"] == parent

    @pytest.mark.django_db
    def test_a_concept_broader_of_two_others_shows_both_as_narrower_though_only_broader_is_stored(
        self, client
    ):
        parent = ConceptFactory(label="Igneous Rock")
        child_one = ConceptFactory(scheme=parent.scheme, label="Granite")
        child_two = ConceptFactory(scheme=parent.scheme, label="Basalt")
        # Only the narrower-to-broader direction is stored (FS-003); parent.narrower() reads
        # it back from each child's own broader row.
        child_one.add_broader(parent)
        child_two.add_broader(parent)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": parent.scheme.slug, "concept_slug": parent.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        narrower_links = self._links_for(soup, NARROWER_CURIE)
        narrower_short_forms = {link.get_text(strip=True) for link in narrower_links}

        assert narrower_short_forms == {
            f"{child_one.scheme.slug}:{child_one.slug}",
            f"{child_two.scheme.slug}:{child_two.slug}",
        }

        follow = client.get(narrower_links[0]["href"])

        assert follow.status_code == 200
        assert follow.context["object"] in (child_one, child_two)

    @pytest.mark.django_db
    def test_a_related_concept_appears_and_following_it_opens_its_page(self, client):
        concept = ConceptFactory(label="Granite")
        other = ConceptFactory(scheme=concept.scheme, label="Basalt")
        concept.add_related(other)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        (link,) = self._links_for(soup, RELATED_CURIE)

        assert link.get_text(strip=True) == f"{other.scheme.slug}:{other.slug}"

        follow = client.get(link["href"])

        assert follow.status_code == 200
        assert follow.context["object"] == other


class TestConceptDetailVocabularyRowAndNoAncestorChain:
    @pytest.mark.django_db
    def test_the_vocabulary_row_appears_and_following_it_opens_the_vocabularys_page(
        self, client
    ):
        concept = ConceptFactory(label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        scheme_dt = next(
            dt for dt in soup.find_all("dt") if term_text(dt) == IN_SCHEME_CURIE
        )
        link = scheme_dt.find_next_sibling("dd").find("a")

        assert link.get_text(strip=True) == concept.scheme.name

        follow = client.get(link["href"])

        assert follow.status_code == 200
        assert follow.context["vocabulary"] == concept.scheme

    @pytest.mark.django_db
    def test_a_five_level_chain_names_only_the_middle_concepts_immediate_neighbours(
        self, client
    ):
        # Five levels: the concept needs a neighbour beyond each of its own, or a page that
        # walked two steps would find nothing more to show and still pass.
        great_grandparent = ConceptFactory(label="Material")
        grandparent = ConceptFactory(scheme=great_grandparent.scheme, label="Rock")
        parent = ConceptFactory(scheme=great_grandparent.scheme, label="Igneous Rock")
        child = ConceptFactory(scheme=great_grandparent.scheme, label="Granite")
        grandchild = ConceptFactory(
            scheme=great_grandparent.scheme, label="Pink Granite"
        )
        grandparent.add_broader(great_grandparent)
        parent.add_broader(grandparent)
        child.add_broader(parent)
        grandchild.add_broader(child)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": parent.scheme.slug, "concept_slug": parent.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        relation_pairs = [
            (term_text(dt), dt.find_next_sibling("dd").find("a").get_text(strip=True))
            for dt in soup.find_all("dt")
            if term_text(dt) in (BROADER_CURIE, NARROWER_CURIE)
        ]

        # The great-grandparent and grandchild exist and must be absent.
        assert relation_pairs == [
            (BROADER_CURIE, f"{grandparent.scheme.slug}:{grandparent.slug}"),
            (NARROWER_CURIE, f"{child.scheme.slug}:{child.slug}"),
        ]


class TestPythonSideStringsThisFeatureIntroducedAreTranslatableAndCuriesAreNot:
    # A CURIE is a SKOS identifier, not reader-visible prose, so it stays untranslated.
    # Template text is covered by test_templates.py::TestEveryShippedTemplateWrapsReaderVisibleTextInATranslationTag.

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "view_class,slug_kwarg",
        [
            (ConceptDetailView, "concept_slug"),
            (CollectionDetailView, "collection_slug"),
        ],
    )
    def test_the_unknown_vocabulary_404_message_is_lazily_translatable(
        self, rf, view_class, slug_kwarg
    ):
        view = view_class()
        request = rf.get("/")

        with pytest.raises(Http404) as exc_info:
            view.setup(request, slug="no-such-vocabulary", **{slug_kwarg: "whatever"})

        assert isinstance(exc_info.value.args[0], Promise), (
            "the 404 message this view raises is a plain string, not a lazy translation"
        )

    def test_every_curie_a_row_may_be_keyed_on_is_a_plain_string_not_a_translation(
        self,
    ):
        curies = [
            TYPE_CURIE,
            CONCEPT_TYPE_CURIE,
            COLLECTION_TYPE_CURIE,
            ORDERED_COLLECTION_TYPE_CURIE,
            BROADER_CURIE,
            NARROWER_CURIE,
            RELATED_CURIE,
            IN_SCHEME_CURIE,
            MEMBER_CURIE,
            MEMBER_LIST_CURIE,
            *LABEL_CURIES.values(),
            *NOTE_CURIES.values(),
        ]

        assert curies, (
            "nothing to prove — the CURIE tables this asserts against are empty"
        )
        for curie in curies:
            assert isinstance(curie, str)
            assert not isinstance(curie, Promise), (
                f"{curie!r} is a lazily translated value, but a CURIE is a SKOS identifier and must stay untranslated"
            )


class TestConceptAndCollectionValuesReachTheReaderEscaped:
    # Each test parses the response: a raw substring check passes for an unescaped payload
    # too, since it is a substring of the escaped one.

    # Matches the injected payload only, never the shell's own theme-toggle script.
    _INJECTED_SCRIPT = re.compile(r"alert\(1\)")

    @pytest.mark.django_db
    def test_a_preferred_label_containing_markup_is_escaped_on_the_concept_page(
        self, client
    ):
        concept = ConceptFactory(label="<script>alert(1)</script>")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find("script", string=self._INJECTED_SCRIPT) is None
        assert "<script>alert(1)</script>" in soup.find("dl").get_text()

    @pytest.mark.django_db
    def test_a_note_containing_markup_is_escaped_on_the_concept_page(self, client):
        concept = ConceptFactory(label="Granite")
        ConceptNoteFactory(
            concept=concept,
            kind=ConceptNote.Kind.DEFINITION,
            value="<script>alert(1)</script>",
        )

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find("script", string=self._INJECTED_SCRIPT) is None
        assert "<script>alert(1)</script>" in soup.find("dl").get_text()

    @pytest.mark.django_db
    def test_a_publisher_supplied_identifier_reaches_an_attribute_only_as_a_links_destination(
        self, client
    ):
        # A quote inside the identifier would break out of the href if auto-escaping stopped.
        concept = ConceptFactory(label="Granite", external=True)
        concept.static_uri = 'http://publisher.example.org/x"><script>alert(1)</script>'
        concept.save()

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find("script", string=self._INJECTED_SCRIPT) is None
        identifier_link = soup.find("a", href=concept.static_uri)
        assert identifier_link is not None
        assert concept.static_uri in identifier_link.get_text(strip=True)

    @pytest.mark.django_db
    def test_a_vocabularys_name_containing_markup_is_escaped_on_the_concept_page(
        self, client
    ):
        # The name reaches <c-link>'s text attribute rather than a <dd>. A component
        # attribute is escaped again on render, so the reachable defect is marking it safe
        # in the view, which is what this pins.
        scheme = ConceptSchemeFactory(name="<script>alert(1)</script>")
        concept = ConceptFactory(scheme=scheme, label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find("script", string=self._INJECTED_SCRIPT) is None
        assert "<script>alert(1)</script>" in soup.find("dl").get_text()

    @pytest.mark.django_db
    def test_a_related_records_publisher_supplied_identifier_is_escaped_in_its_tooltip_and_hidden_span(
        self, client
    ):
        # The identifier reaches a data-tip attribute and a hidden span's text.
        concept = ConceptFactory(label="Granite")
        parent = ConceptFactory(
            scheme=concept.scheme, label="Igneous Rock", external=True
        )
        parent.static_uri = 'http://publisher.example.org/x"><script>alert(1)</script>'
        parent.save()
        concept.add_broader(parent)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find("script", string=self._INJECTED_SCRIPT) is None
        wrapper = soup.find("span", attrs={"data-tip": parent.static_uri})
        assert wrapper is not None
        link = wrapper.find("a")
        hidden_span = wrapper.find("span", id=link.get("aria-describedby"))
        assert hidden_span is not None
        assert hidden_span.get_text() == parent.static_uri

    @pytest.mark.django_db
    def test_a_collections_name_containing_markup_is_escaped_on_the_collection_page(
        self, client
    ):
        collection = CollectionFactory(name="<script>alert(1)</script>")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find("script", string=self._INJECTED_SCRIPT) is None
        assert "<script>alert(1)</script>" in soup.find("dl").get_text()


class TestConceptDetailShowsNoCrossVocabularyLink:
    # Nothing stores a concept's exact or close matches. Asserted on a concept imported from
    # a file that offered both, so the test would fail if the importer ever kept them.

    _MAPPING_TURTLE = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

<http://example.org/rocks/> a skos:ConceptScheme ;
    skos:prefLabel "Rocks"@en .

<http://example.org/rocks/granite> a skos:Concept ;
    skos:inScheme <http://example.org/rocks/> ;
    skos:prefLabel "Granite"@en ;
    skos:exactMatch <http://external.example.org/rocks/granite> ;
    skos:closeMatch <http://external.example.org/rocks/granitic-rock> .
"""

    @pytest.mark.django_db
    def test_a_concept_imported_with_exact_and_close_matches_shows_neither(
        self, client, tmp_path
    ):
        source = tmp_path / "rocks.ttl"
        source.write_text(self._MAPPING_TURTLE)
        import_skos(source)
        concept = Concept.objects.get(static_uri="http://example.org/rocks/granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        content = response.content.decode()

        assert "external.example.org" not in content
        terms = [term_text(dt) for dt in soup.find_all("dt")]
        assert terms == [
            TYPE_CURIE,
            LABEL_CURIES[ConceptLabel.Kind.PREFERRED],
            IN_SCHEME_CURIE,
        ]


class TestPropertyTermDisclosesItsOwnURI:
    @staticmethod
    def _term_disclosures(soup):
        """Map each term to the tooltip span wrapping it.

        Args:
            soup: The parsed page.

        Returns:
            ``{term: span or None}`` for every ``<dt>``.
        """
        return {
            term_text(dt): dt.find("span", class_="tooltip")
            for dt in soup.find_all("dt")
        }

    @pytest.mark.django_db
    def test_a_concept_pages_terms_each_disclose_the_uri_they_abbreviate(self, client):
        concept = ConceptFactory(label="Granite")

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        terms = self._term_disclosures(soup)

        assert terms, "the page rendered no terms at all"
        assert (
            terms["rdf:type"].get("data-tip")
            == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        )
        assert (
            terms["skos:prefLabel"].get("data-tip")
            == "http://www.w3.org/2004/02/skos/core#prefLabel"
        )
        for curie, wrapper in terms.items():
            assert wrapper is not None, f"{curie} discloses nothing"
            hidden_span = wrapper.find_next_sibling("span", class_="sr-only")
            assert hidden_span is not None, f"{curie}'s URI is not reachable as text"
            assert hidden_span.get_text() == wrapper.get("data-tip"), (
                f"{curie}'s two disclosures disagree"
            )
            assert wrapper["data-tip"] not in visible_text(soup.find("dl")), (
                f"{curie}'s URI is printed, not hovered"
            )

    @pytest.mark.django_db
    def test_a_collection_pages_terms_do_too(self, client):
        collection, _members = collection_with_members(labels=("Granite",))

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        terms = self._term_disclosures(soup)

        assert (
            terms[MEMBER_CURIE].get("data-tip")
            == "http://www.w3.org/2004/02/skos/core#member"
        )
        for curie, wrapper in terms.items():
            assert wrapper is not None, f"{curie} discloses nothing"


class TestPropertyTermsCarryNoTitle:
    # A title attribute would show the browser's tooltip on top of daisyUI's.

    @pytest.mark.django_db
    def test_no_element_in_a_concept_pages_definition_list_carries_a_title(
        self, client
    ):
        concept = ConceptFactory(label="Granite")
        parent = ConceptFactory(scheme=concept.scheme, label="Igneous Rock")
        concept.add_broader(parent)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find("dl").find(attrs={"title": True}) is None

    @pytest.mark.django_db
    def test_no_element_in_a_collection_pages_definition_list_carries_a_title(
        self, client
    ):
        collection, _members = collection_with_members(labels=("Granite", "Basalt"))

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")

        assert soup.find("dl").find(attrs={"title": True}) is None


class TestEveryTooltipOpensToTheRight:
    @pytest.mark.django_db
    def test_every_tooltip_on_a_concept_page_opens_right(self, client):
        concept = ConceptFactory(label="Granite")
        parent = ConceptFactory(scheme=concept.scheme, label="Igneous Rock")
        concept.add_broader(parent)

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        tooltips = soup.find_all(class_="tooltip")

        assert tooltips, "the page rendered no tooltip at all"
        for tooltip in tooltips:
            assert "tooltip-right" in tooltip.get("class", [])

    @pytest.mark.django_db
    def test_every_tooltip_on_a_collection_page_opens_right(self, client):
        collection, _members = collection_with_members(labels=("Granite", "Basalt"))

        response = client.get(
            reverse(
                "controlled_vocabularies_ui:collection-detail",
                kwargs={
                    "slug": collection.scheme.slug,
                    "collection_slug": collection.slug,
                },
            )
        )
        soup = BeautifulSoup(response.content, "html.parser")
        tooltips = soup.find_all(class_="tooltip")

        assert tooltips, "the page rendered no tooltip at all"
        for tooltip in tooltips:
            assert "tooltip-right" in tooltip.get("class", [])
