"""Tests for the RDF a vocabulary, concept or collection page returns when asked for it."""

import pytest
import rdflib
from bs4 import BeautifulSoup
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.management import call_command
from django.urls import include, path, reverse
from rdflib.collection import Collection
from rdflib.namespace import SKOS

from controlled_vocabularies.exchange.serializations import Serialization
from controlled_vocabularies.models import ConceptScheme, Record
from controlled_vocabularies.ui import representations
from controlled_vocabularies.ui.views import ConceptDetailView
from demo.management.commands.seed_demo import Command as SeedDemoCommand
from tests.conftest import RdfReadBack
from tests.factories import (
    ConceptSchemeFactory,
    RecordFactory,
    collection_with_members,
    labelled,
)

BROWSER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
TURTLE = Serialization.named("ttl")
NEGOTIABLE = [s for s in Serialization.all() if s.negotiable]


class GuardedConceptView(LoginRequiredMixin, ConceptDetailView):
    """A concept page behind a login requirement, as a consuming project might mount it."""


urlpatterns = [
    path("vocabularies/", include("controlled_vocabularies.ui.urls")),
    path(
        "guarded/<str:slug>/<str:concept_slug>/",
        GuardedConceptView.as_view(),
        name="guarded-concept",
    ),
]


def address(subject):
    """Return the address of a vocabulary's or record's page.

    Args:
        subject: A ``ConceptScheme`` or a ``Record``.

    Returns:
        The path of its page.
    """
    if isinstance(subject, ConceptScheme):
        return reverse(
            "controlled_vocabularies_ui:vocabulary-detail", args=[subject.slug]
        )
    if subject.type in Record.COLLECTION_TYPES:
        name, kwargs = "collection-detail", {"collection_slug": subject.slug}
    else:
        name, kwargs = "concept-detail", {"concept_slug": subject.slug}
    return reverse(
        f"controlled_vocabularies_ui:{name}",
        kwargs={"slug": subject.scheme.slug, **kwargs},
    )


def ask(client, subject, accept=None, **extra):
    """Request a subject's page, optionally with an ``Accept`` header.

    Args:
        client: The test client.
        subject: A ``ConceptScheme`` or a ``Record``.
        accept: The ``Accept`` header, or None to send none.
        **extra: Further request parameters, such as ``headers``.

    Returns:
        The response.
    """
    if accept is not None:
        extra["headers"] = {"Accept": accept}
    return client.get(address(subject), **extra)


def subjects_for():
    """Build a vocabulary with a concept and a collection, keyed by what each is.

    Returns:
        A dict with ``vocabulary``, ``concept`` and ``collection``.
    """
    collection, members = collection_with_members(name="Rocks")
    return {
        "vocabulary": collection.scheme,
        "concept": members[0],
        "collection": collection,
    }


@pytest.fixture
def subjects(db):
    """Return the vocabulary, concept and collection ``subjects_for`` builds."""
    return subjects_for()


@pytest.fixture(params=["vocabulary", "concept", "collection"])
def subject(request, subjects):
    """Return each of the three kinds of page's subject in turn."""
    return subjects[request.param]


def read(response, serialization=TURTLE):
    """Parse a response body, using the shared read-back helper.

    Args:
        response: The response.
        serialization: The ``Serialization`` the body is written in.

    Returns:
        The graph of every statement in the body.
    """
    return RdfReadBack.parse(serialization, response.content)


@pytest.mark.django_db
class TestAcceptReturnsRdf:
    def test_turtle_is_served_as_the_subjects_own_graph(
        self, client, subject, rdf_read_back
    ):
        response = ask(client, subject, "text/turtle")

        assert response.status_code == 200
        assert response["Content-Type"].split(";")[0] == "text/turtle"
        assert rdf_read_back.same_statements(read(response), subject.to_graph())

    def test_it_is_inline_not_a_download(self, client, subject):
        response = ask(client, subject, "text/turtle")

        assert "Content-Disposition" not in response

    def test_a_concept_states_its_labels_definition_and_broader_concept(self, client):
        parent = RecordFactory(label="Rock")
        concept = RecordFactory(
            scheme=parent.scheme,
            data=labelled(
                "Granite",
                statements={
                    "skos:prefLabel": [
                        {"@value": "Granite", "@language": "en"},
                        {"@value": "Granit", "@language": "de"},
                    ],
                    "skos:definition": [{"@value": "An igneous rock."}],
                    "skos:broader": [{"@id": parent.uri}],
                },
            ),
        )

        graph = read(ask(client, concept, "text/turtle"))
        subject = rdflib.URIRef(concept.uri)

        assert (subject, SKOS.prefLabel, rdflib.Literal("Granite", lang="en")) in graph
        assert (subject, SKOS.prefLabel, rdflib.Literal("Granit", lang="de")) in graph
        assert (subject, SKOS.definition, rdflib.Literal("An igneous rock.")) in graph
        assert (subject, SKOS.broader, rdflib.URIRef(parent.uri)) in graph

    def test_a_vocabularys_response_has_no_triple_about_its_records(
        self, client, subjects
    ):
        graph = read(ask(client, subjects["vocabulary"], "text/turtle"))
        record_uris = {
            rdflib.URIRef(uri) for uri in Record.objects.values_list("uri", flat=True)
        }

        assert record_uris
        assert not {s for s in graph.subjects() if s in record_uris}

    def test_an_ordered_collections_members_are_a_list_in_stored_order(self, client):
        collection, members = collection_with_members(
            ordered=True, labels=("Third", "First", "Second")
        )

        graph = read(ask(client, collection, "text/turtle"))
        head = graph.value(rdflib.URIRef(collection.uri), SKOS.memberList)

        assert list(Collection(graph, head)) == [
            rdflib.URIRef(member.uri) for member in members
        ]

    def test_a_concept_named_narrower_by_another_gets_no_broader_it_did_not_state(
        self, client
    ):
        scheme = ConceptSchemeFactory()
        concept = RecordFactory(scheme=scheme, label="Granite")
        RecordFactory(
            scheme=scheme,
            data=labelled("Rock", statements={"skos:narrower": [{"@id": concept.uri}]}),
        )
        collection, _members = collection_with_members(scheme=scheme)
        collection.data["skos:member"].append({"@id": concept.uri})
        collection.save()

        graph = read(ask(client, concept, "text/turtle"))

        assert not list(graph.objects(rdflib.URIRef(concept.uri), SKOS.broader))
        assert not [
            triple for triple in graph if rdflib.URIRef(collection.uri) in triple
        ]

    def test_hidden_labels_are_present(self, client):
        concept = RecordFactory(
            data=labelled(
                "Granite",
                statements={
                    "skos:hiddenLabel": [{"@value": "granit", "@language": "de"}]
                },
            )
        )

        graph = read(ask(client, concept, "text/turtle"))

        assert (
            rdflib.URIRef(concept.uri),
            SKOS.hiddenLabel,
            rdflib.Literal("granit", lang="de"),
        ) in graph

    def test_a_record_of_an_imported_vocabulary_is_described_by_its_own_identifier(
        self, client
    ):
        scheme = ConceptSchemeFactory(uri="http://publisher.example.org/vocab-1")
        concept = RecordFactory(
            scheme=scheme, uri="http://publisher.example.org/vocab-1/granite"
        )

        graph = read(ask(client, concept, "text/turtle"))

        assert set(graph.subjects()) == {
            rdflib.URIRef("http://publisher.example.org/vocab-1/granite")
        }

    def test_head_gives_the_same_status_and_type_with_an_empty_body(
        self, client, subject
    ):
        response = client.head(address(subject), headers={"Accept": "text/turtle"})

        assert response.status_code == 200
        assert response["Content-Type"].split(";")[0] == "text/turtle"
        assert response.content == b""


@pytest.mark.django_db
class TestAcceptKeepsThePage:
    @pytest.mark.parametrize(
        "accept", [BROWSER, None, "*/*"], ids=["browser", "none", "any"]
    )
    def test_a_request_that_does_not_ask_for_rdf_gets_the_page(
        self, client, subject, accept
    ):
        response = ask(client, subject, accept)

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/html")

    def test_equal_quality_between_html_and_turtle_gives_the_page(
        self, client, subject
    ):
        response = ask(client, subject, "text/turtle, text/html")

        assert response["Content-Type"].startswith("text/html")

    def test_a_lower_quality_for_html_gives_turtle(self, client, subject):
        response = ask(client, subject, "text/html;q=0.5, text/turtle")

        assert response["Content-Type"].split(";")[0] == "text/turtle"

    @pytest.mark.parametrize(
        ("accept", "media_type"),
        [
            (
                'application/ld+json; profile="http://www.w3.org/ns/json-ld#expanded"',
                "application/ld+json",
            ),
            (
                'application/ld+json;profile="http://www.w3.org/ns/json-ld#compacted", '
                "text/html;q=0.5",
                "application/ld+json",
            ),
            ("text/turtle; charset=utf-8", "text/turtle"),
        ],
    )
    def test_parameters_on_an_accepted_type_do_not_stop_it_matching(
        self, client, subject, accept, media_type
    ):
        response = ask(client, subject, accept)

        assert response.status_code == 200
        assert response["Content-Type"].split(";")[0] == media_type

    def test_turtle_with_a_wildcard_at_the_same_quality_gives_the_page(
        self, client, subject
    ):
        # Deliberate: the wildcard accepts HTML as readily as Turtle, so the page wins the tie.
        response = ask(client, subject, "text/turtle, */*")

        assert response["Content-Type"].startswith("text/html")

    def test_the_page_renders_the_same_template_as_before(self, client, subjects):
        response = ask(client, subjects["concept"], BROWSER)

        assert "controlled_vocabularies/ui/concept_detail.html" in [
            template.name for template in response.templates
        ]

    def test_a_browser_request_resolves_no_subject_of_its_own(
        self, client, subject, monkeypatch
    ):
        def fail(self):
            raise AssertionError("the page path looked the subject up")

        monkeypatch.setattr(
            representations.RepresentationMixin, "get_representation_subject", fail
        )

        assert ask(client, subject, BROWSER).status_code == 200


@pytest.mark.django_db
class TestAcceptRefusal:
    def test_a_type_the_site_cannot_produce_is_406_and_not_html(self, client, subject):
        response = ask(client, subject, "application/json")

        assert response.status_code == 406
        assert response["Content-Type"].startswith("text/plain")

    def test_a_row_a_format_cannot_express_is_refused_not_a_server_error(
        self, client, db
    ):
        # RDF/XML cannot write a predicate ending in "/", which an import keeps.
        concept = RecordFactory(
            data=labelled(
                "Granite",
                statements={"http://example.org/p/": [{"@value": "x"}]},
            )
        )

        by_accept = ask(client, concept, "application/rdf+xml")
        by_format = client.get(address(concept), {"format": "xml"})

        for response in (by_accept, by_format):
            assert response.status_code == 406
            assert response["Content-Type"].startswith("text/plain")
            assert "Content-Disposition" not in response
        assert ask(client, concept, "text/turtle").status_code == 200

    def test_text_plain_alone_is_not_taken_for_ntriples(self, client, subject):
        response = ask(client, subject, "text/plain")

        assert response.status_code == 406


@pytest.mark.django_db
class TestVaryHeader:
    @pytest.mark.parametrize(
        "accept", [None, BROWSER, "text/turtle", "application/json"]
    )
    def test_every_response_varies_on_accept(self, client, subject, accept):
        response = ask(client, subject, accept)

        assert "Accept" in response["Vary"]


@pytest.mark.django_db
class TestMissingSubject:
    def test_an_unknown_vocabulary_is_404_whatever_is_asked_for(self, client):
        for accept in ("text/turtle", BROWSER):
            response = client.get(
                reverse("controlled_vocabularies_ui:vocabulary-detail", args=["nope"]),
                headers={"Accept": accept},
            )
            assert response.status_code == 404

    def test_an_unknown_concept_is_404_with_turtle(self, client, subjects):
        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={"slug": subjects["vocabulary"].slug, "concept_slug": "nope"},
            ),
            headers={"Accept": "text/turtle"},
        )

        assert response.status_code == 404

    def test_a_collections_slug_at_a_concepts_address_is_404_with_turtle(
        self, client, subjects
    ):
        response = client.get(
            reverse(
                "controlled_vocabularies_ui:concept-detail",
                kwargs={
                    "slug": subjects["vocabulary"].slug,
                    "concept_slug": subjects["collection"].slug,
                },
            ),
            headers={"Accept": "text/turtle"},
        )

        assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.urls("tests.test_ui.test_representations")
class TestAccessControl:
    def test_a_login_requirement_answers_rdf_requests_as_it_answers_a_browser(
        self, client, subjects
    ):
        concept = subjects["concept"]
        url = reverse(
            "guarded-concept",
            kwargs={"slug": concept.scheme.slug, "concept_slug": concept.slug},
        )

        browser = client.get(url, headers={"Accept": BROWSER})
        turtle = client.get(url, headers={"Accept": "text/turtle"})

        assert browser.status_code == turtle.status_code == 302
        assert browser.url == turtle.url


@pytest.mark.django_db
class TestAlternateLinks:
    def test_the_head_names_the_four_alternatives_in_order(self, client, subject):
        soup = BeautifulSoup(ask(client, subject, BROWSER).content, "html.parser")

        links = soup.head.find_all("link", rel="alternate")

        assert [link["type"] for link in links] == [
            Serialization.named(name).media_type
            for name in ("ttl", "xml", "json-ld", "nt")
        ]

    def test_each_link_returns_the_media_type_it_names(self, client, subject):
        soup = BeautifulSoup(ask(client, subject, BROWSER).content, "html.parser")

        for link in soup.head.find_all("link", rel="alternate"):
            response = client.get(address(subject) + link["href"])

            assert response.status_code == 200
            assert response["Content-Type"].split(";")[0] == link["type"]


@pytest.fixture
def demo(db):
    """Seed the demo's two vocabularies."""
    call_command(SeedDemoCommand())


@pytest.mark.django_db
class TestDemoRoundTrip:
    @pytest.mark.parametrize("serialization", NEGOTIABLE, ids=lambda s: s.name)
    def test_every_row_reads_back_to_its_own_statements(
        self, client, demo, serialization, rdf_read_back
    ):
        rows = [*ConceptScheme.objects.all(), *Record.objects.select_related("scheme")]

        assert rows
        for row in rows:
            response = ask(client, row, serialization.media_type)

            assert response["Content-Type"].split(";")[0] == serialization.media_type, (
                row
            )
            assert rdf_read_back.same_statements(
                read(response, serialization), row.to_graph()
            ), row

    @pytest.mark.parametrize("serialization", Serialization.all(), ids=lambda s: s.name)
    def test_every_row_reads_back_through_format(
        self, client, demo, serialization, rdf_read_back
    ):
        rows = [*ConceptScheme.objects.all(), *Record.objects.select_related("scheme")]

        assert rows
        for row in rows:
            response = client.get(address(row), {"format": serialization.name})

            assert response.status_code == 200, row
            assert response["Content-Type"].split(";")[0] == serialization.media_type, (
                row
            )
            assert rdf_read_back.same_statements(
                read(response, serialization), row.to_graph()
            ), row


@pytest.mark.django_db
class TestFormatDownload:
    def test_a_concept_is_a_turtle_attachment_named_by_its_slug(self, client, subjects):
        concept = subjects["concept"]

        response = client.get(address(concept), {"format": "ttl"})

        assert response.status_code == 200
        assert response["Content-Type"].split(";")[0] == "text/turtle"
        disposition = response["Content-Disposition"]
        assert disposition.startswith("attachment")
        assert f"{concept.slug}.ttl" in disposition

    def test_a_vocabulary_is_named_by_its_slug_and_the_serializations_extension(
        self, client, subjects
    ):
        vocabulary = subjects["vocabulary"]

        response = client.get(address(vocabulary), {"format": "xml"})

        assert f"{vocabulary.slug}.rdf" in response["Content-Disposition"]

    @pytest.mark.parametrize("serialization", Serialization.all(), ids=lambda s: s.name)
    def test_every_short_name_gives_that_serializations_content_type(
        self, client, subjects, serialization
    ):
        response = client.get(
            address(subjects["vocabulary"]), {"format": serialization.name}
        )

        assert response.status_code == 200
        assert response["Content-Type"].split(";")[0] == serialization.media_type

    def test_format_wins_over_accept(self, client, subject, rdf_read_back):
        xml = Serialization.named("xml")

        response = client.get(
            address(subject), {"format": "xml"}, headers={"Accept": "text/turtle"}
        )

        assert response["Content-Type"].split(";")[0] == xml.media_type
        assert rdf_read_back.same_statements(read(response, xml), subject.to_graph())

    def test_format_wins_over_a_browsers_accept(self, client, subject):
        response = client.get(
            address(subject), {"format": "ttl"}, headers={"Accept": BROWSER}
        )

        assert response["Content-Type"].split(";")[0] == "text/turtle"

    def test_a_media_type_is_accepted_as_a_name(self, client, subject):
        response = client.get(address(subject), {"format": "text/turtle"})

        assert response.status_code == 200
        assert response["Content-Type"].split(";")[0] == "text/turtle"

    def test_an_empty_format_is_an_unknown_name(self, client, subject):
        assert client.get(address(subject), {"format": ""}).status_code == 400

    def test_the_vocabulary_download_ignores_a_search(
        self, client, subjects, rdf_read_back
    ):
        vocabulary = subjects["vocabulary"]

        response = client.get(address(vocabulary), {"format": "ttl", "q": "zzzz"})

        assert rdf_read_back.same_statements(read(response), vocabulary.to_graph())

    def test_head_gives_the_download_headers_with_an_empty_body(self, client, subject):
        response = client.head(address(subject), {"format": "ttl"})

        assert response.status_code == 200
        assert "attachment" in response["Content-Disposition"]
        assert response.content == b""


@pytest.mark.django_db
class TestFormatRefusal:
    def test_an_unknown_name_is_400_not_html_and_names_the_choices(
        self, client, subject
    ):
        response = client.get(address(subject), {"format": "nonsense"})

        assert response.status_code == 400
        assert not response["Content-Type"].startswith("text/html")
        body = response.content.decode()
        names = body.rsplit(":", 1)[1].strip(" .\n").split(", ")
        for name in ("ttl", "xml", "json-ld", "nt"):
            assert name in names

    def test_an_unknown_name_is_not_settled_by_accept(self, client, subject):
        response = client.get(
            address(subject), {"format": "nonsense"}, headers={"Accept": "text/turtle"}
        )

        assert response.status_code == 400

    @pytest.mark.parametrize("name", ["ttl", "nonsense"])
    def test_an_address_naming_no_record_is_404_before_anything_else(
        self, client, subjects, name
    ):
        missing = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": subjects["vocabulary"].slug, "concept_slug": "nope"},
        )
        no_vocabulary = reverse(
            "controlled_vocabularies_ui:vocabulary-detail", args=["nope"]
        )

        for url in (missing, no_vocabulary):
            assert client.get(url, {"format": name}).status_code == 404

    def test_an_unacceptable_type_at_a_missing_address_is_404(self, client, subjects):
        missing = reverse(
            "controlled_vocabularies_ui:concept-detail",
            kwargs={"slug": subjects["vocabulary"].slug, "concept_slug": "nope"},
        )

        response = client.get(missing, headers={"Accept": "application/json"})

        assert response.status_code == 404
