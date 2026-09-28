"""Tests for the shipped ui templates and the ``property_row`` Cotton component."""

import re
from pathlib import Path

import mvp
import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.urls import reverse

from tests.factories import ConceptSchemeFactory


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


TEMPLATES_ROOT = (
    Path(__file__).resolve().parents[2] / "controlled_vocabularies" / "ui" / "templates"
)
ROW_TEMPLATE_PATH = (
    TEMPLATES_ROOT / "controlled_vocabularies" / "ui" / "conceptscheme_list_item.html"
)
CONCEPT_ROW_TEMPLATE_PATH = (
    TEMPLATES_ROOT / "controlled_vocabularies" / "ui" / "concept_list_item.html"
)
CONCEPTSCHEME_DETAIL_TEMPLATE_PATH = (
    TEMPLATES_ROOT / "controlled_vocabularies" / "ui" / "conceptscheme_detail.html"
)
PROPERTY_ROW_TEMPLATE = "cotton/controlled_vocabularies/property_row.html"
PROPERTY_ROW_TEMPLATE_PATH = (
    TEMPLATES_ROOT / "cotton" / "controlled_vocabularies" / "property_row.html"
)
# Every template that carries an in-site link (FS-015).
IN_SITE_LINK_TEMPLATE_PATHS = [
    ROW_TEMPLATE_PATH,
    CONCEPT_ROW_TEMPLATE_PATH,
    PROPERTY_ROW_TEMPLATE_PATH,
]
# mvp is a namespace package with no __file__, so __path__ is the only way to find it.
MVP_CSS_PATH = Path(mvp.__path__[0]) / "static" / "css" / "django-mvp.css"

# Django syntax stripped before the reader-visible-text scan: comments, blocktrans blocks,
# any remaining tag (a `{% trans %}` carries its translated text inside the tag) and variables.
_COMMENT_RE = re.compile(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}", re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCKTRANS_RE = re.compile(r"{%\s*blocktrans.*?{%\s*endblocktrans\s*%}", re.DOTALL)
_TAG_RE = re.compile(r"{%.*?%}", re.DOTALL)
_VAR_RE = re.compile(r"{{.*?}}", re.DOTALL)
_TEXT_NODE_RE = re.compile(r">([^<{]+)<")
_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def bare_reader_visible_text_nodes(source: str) -> list[str]:
    """Find text-node fragments left once translation and comment syntax is stripped.

    Only text nodes are scanned, not attribute values: without a real template parser an
    attribute value cannot be told from a structural token such as a slot name.

    Args:
        source: The raw template source.

    Returns:
        Fragments containing letters, which a translation tag should have wrapped.
    """
    stripped = _COMMENT_RE.sub("", source)
    stripped = _HTML_COMMENT_RE.sub("", stripped)
    stripped = _BLOCKTRANS_RE.sub("", stripped)
    stripped = _TAG_RE.sub("", stripped)
    stripped = _VAR_RE.sub("", stripped)
    return [node for node in _TEXT_NODE_RE.findall(stripped) if _WORD_RE.search(node)]


class TestRowPartialLinksToTheVocabulary:
    def test_the_row_partial_source_reverses_the_vocabularys_own_route(self):
        source = ROW_TEMPLATE_PATH.read_text()
        assert "{% url 'controlled_vocabularies_ui:vocabulary-detail'" in source

    def test_the_row_partial_source_contains_no_local_url_reference(self):
        # The base address is a public identifier and may point at another site's publisher,
        # so the in-site link is reversed from the route name instead.
        source = ROW_TEMPLATE_PATH.read_text()
        assert "local_url" not in source


class TestRenderedPageLinksToEachVocabulary:
    @pytest.mark.django_db
    def test_every_entry_on_the_page_carries_an_anchor_to_its_own_page(self, client):
        schemes = [ConceptSchemeFactory(), ConceptSchemeFactory()]

        response = client.get(reverse("controlled_vocabularies_ui:vocabulary-list"))
        content = response.content.decode()

        hrefs = re.findall(r'href="([^"]*)"', content)
        for scheme in schemes:
            assert (
                reverse(
                    "controlled_vocabularies_ui:vocabulary-detail",
                    kwargs={"slug": scheme.slug},
                )
                in hrefs
            )


class TestConceptRowPartialLinksToItsOwnPage:
    def test_the_row_partial_source_reverses_the_concepts_own_route(self):
        # The row renders in a fresh context holding only the object, so the address comes
        # from object.scheme and object.slug alone.
        source = CONCEPT_ROW_TEMPLATE_PATH.read_text()
        assert "{% url 'controlled_vocabularies_ui:concept-detail'" in source

    def test_the_row_partial_source_contains_no_local_url_reference(self):
        source = CONCEPT_ROW_TEMPLATE_PATH.read_text()
        assert "local_url" not in source


class TestConceptSchemeDetailCollectionsLinkToTheirOwnPages:
    def test_the_page_source_reverses_the_collections_own_route(self):
        source = CONCEPTSCHEME_DETAIL_TEMPLATE_PATH.read_text()
        assert "{% url 'controlled_vocabularies_ui:collection-detail'" in source

    def test_the_page_source_contains_no_local_url_reference_for_a_collection(self):
        source = CONCEPTSCHEME_DETAIL_TEMPLATE_PATH.read_text()
        assert "local_url" not in source


class TestEveryTemplateCarryingAnInSiteLinkContainsNoLocalUrlReference:
    @pytest.mark.parametrize(
        "path",
        IN_SITE_LINK_TEMPLATE_PATHS,
        ids=lambda p: str(p.relative_to(TEMPLATES_ROOT)),
    )
    def test_the_template_source_contains_no_local_url_reference(self, path):
        # Comment blocks are stripped first: property_row.html explains in a comment why it
        # avoids local_url.
        markup = _COMMENT_RE.sub("", path.read_text())
        assert "local_url" not in markup


class TestEveryShippedTemplateWrapsReaderVisibleTextInATranslationTag:
    @pytest.mark.parametrize(
        "path",
        sorted(TEMPLATES_ROOT.rglob("*.html")),
        ids=lambda p: str(p.relative_to(TEMPLATES_ROOT)),
    )
    def test_no_bare_reader_visible_text_outside_a_translation_tag(self, path):
        fragments = bare_reader_visible_text_nodes(path.read_text())
        assert fragments == []


class TestPropertyRowRendersAPlainValue:
    def test_emits_a_dt_dd_pair_carrying_the_term_and_the_value(self):
        html = render_to_string(
            PROPERTY_ROW_TEMPLATE,
            {"term": "skos:definition", "value": "A coarse-grained igneous rock."},
        )
        soup = BeautifulSoup(html, "html.parser")

        dt = soup.find("dt")
        dd = soup.find("dd")
        assert dt is not None
        assert dd is not None
        assert dt.get_text(strip=True) == "skos:definition"
        assert "A coarse-grained igneous rock." in dd.get_text()
        # A plain value never composes a link — that only happens for a record-valued row.
        assert dd.find("a") is None


class TestPropertyRowRendersARecordValue:
    def test_renders_the_short_form_as_the_in_site_links_own_text(self):
        html = render_to_string(
            PROPERTY_ROW_TEMPLATE,
            {
                "term": "skos:broader",
                "short_form": "geology:granite",
                "uri": "http://publisher.example.org/concept/granite",
                "href": "/vocabularies/geology/granite/",
            },
        )
        soup = BeautifulSoup(html, "html.parser")

        anchor = soup.find("dd").find("a", href="/vocabularies/geology/granite/")
        assert anchor is not None
        assert anchor.get_text(strip=True) == "geology:granite"

    def test_the_canonical_identifier_is_disclosed_on_hover_not_printed_as_text(self):
        # A title attribute is announced only for some screen-reader users, so the identifier
        # is disclosed through a tooltip plus aria-describedby naming a hidden span.
        html = render_to_string(
            PROPERTY_ROW_TEMPLATE,
            {
                "term": "skos:broader",
                "short_form": "geology:granite",
                "uri": "http://publisher.example.org/concept/granite",
                "href": "/vocabularies/geology/granite/",
                "identifier_id": "identifier-0",
            },
        )
        soup = BeautifulSoup(html, "html.parser")
        dd = soup.find("dd")

        assert "http://publisher.example.org/concept/granite" not in visible_text(dd)
        anchor = dd.find("a")
        assert anchor.get("title") is None
        hidden_span = soup.find(id=anchor.get("aria-describedby"))
        assert hidden_span is not None
        assert hidden_span.get_text() == "http://publisher.example.org/concept/granite"


class TestPropertyRowRecordValueDisclosesIdentifierOnHover:
    def test_the_tooltip_wraps_the_link_rather_than_a_class_on_it(self):
        # daisyUI reveals a tooltip on a focused descendant, so the tooltip element has to
        # wrap the link or a keyboard user tabbing to it never sees the identifier.
        html = render_to_string(
            PROPERTY_ROW_TEMPLATE,
            {
                "term": "skos:broader",
                "short_form": "geology:granite",
                "uri": "http://publisher.example.org/concept/granite",
                "href": "/vocabularies/geology/granite/",
                "identifier_id": "identifier-0",
            },
        )
        soup = BeautifulSoup(html, "html.parser")
        dd = soup.find("dd")
        anchor = dd.find("a", href="/vocabularies/geology/granite/")

        assert anchor is not None
        assert "tooltip" not in anchor.get("class", [])
        assert anchor.get("title") is None

        wrapper = anchor.find_parent("span", class_="tooltip")
        assert wrapper is not None
        assert wrapper.get("data-tip") == "http://publisher.example.org/concept/granite"

        hidden_id = anchor.get("aria-describedby")
        assert hidden_id
        hidden_span = wrapper.find("span", id=hidden_id)
        assert hidden_span is not None
        assert "sr-only" in hidden_span.get("class", [])
        assert hidden_span.get_text() == "http://publisher.example.org/concept/granite"
        assert "http://publisher.example.org/concept/granite" not in visible_text(dd)


class TestPropertyRowTermDisclosesItsOwnURI:
    def test_the_dt_carries_neither_text_xs_nor_uppercase(self):
        html = render_to_string(
            PROPERTY_ROW_TEMPLATE,
            {
                "term": "skos:broader",
                "term_uri": "http://publisher.example.org/broader",
                "value": "x",
            },
        )
        soup = BeautifulSoup(html, "html.parser")
        dt = soup.find("dt")

        classes = dt.get("class", [])
        assert "text-xs" not in classes
        assert "uppercase" not in classes

    def test_the_terms_uri_is_reachable_as_text_and_carries_no_title(self):
        html = render_to_string(
            PROPERTY_ROW_TEMPLATE,
            {
                "term": "skos:broader",
                "term_uri": "http://publisher.example.org/broader",
                "value": "x",
            },
        )
        soup = BeautifulSoup(html, "html.parser")
        dt = soup.find("dt")

        assert dt.get("title") is None
        assert dt.find(attrs={"title": True}) is None
        hidden_span = dt.find("span", class_="sr-only")
        assert hidden_span is not None
        assert hidden_span.get_text() == "http://publisher.example.org/broader"
        assert "http://publisher.example.org/broader" not in visible_text(dt)


# A class name ends at one of these in the stylesheet, so "tooltip-right" cannot match
# "tooltip-rightmost".
_SELECTOR_BOUNDARY = r"[{>:,\[)\s]"


def _tailwind_selector_pattern(class_token: str) -> re.Pattern[str]:
    """Build a regex matching a class as the shipped stylesheet spells it.

    Tailwind backslash-escapes a colon or slash in a compiled class name, and daisyUI's
    positional tooltip classes only appear glued to another selector, never as a standalone
    rule, so both are handled here.

    Args:
        class_token: The class name as written in a template.

    Returns:
        A pattern matching the class at a selector boundary.
    """
    escaped = re.escape(class_token.replace("/", r"\/").replace(":", r"\:"))
    return re.compile(rf"\.{escaped}(?={_SELECTOR_BOUNDARY})")


class TestPropertyRowClasses:
    def test_every_class_the_component_names_is_present_in_the_shipped_stylesheet(self):
        source = PROPERTY_ROW_TEMPLATE_PATH.read_text()
        css = MVP_CSS_PATH.read_text()

        tokens = {
            token
            for group in re.findall(r'class="([^"]*)"', source)
            for token in group.split()
        }

        assert tokens, (
            "the component names no class at all — nothing for this test to prove"
        )
        for token in tokens:
            assert _tailwind_selector_pattern(token).search(css), (
                f"{token!r} is not in the shipped stylesheet"
            )

    def test_a_class_shipped_only_inside_a_compound_selector_is_still_found(self):
        # tooltip-right only ships inside compound selectors such as ".tooltip-right:after".
        css = MVP_CSS_PATH.read_text()
        assert _tailwind_selector_pattern("tooltip-right").search(css)

    def test_the_presence_check_discriminates_rather_than_passing_regardless(self):
        # A class the build never emits proves the check can tell a real class from an absent
        # one.
        css = MVP_CSS_PATH.read_text()
        assert (
            _tailwind_selector_pattern("cv-property-row-invented-class").search(css)
            is None
        )

    def test_the_boundary_does_not_let_a_shorter_class_match_inside_a_longer_ones_name(
        self,
    ):
        # A stylesheet naming only ".tooltip-rightmost" does not ship "tooltip-right".
        css = ".tooltip-rightmost{color:red}"
        assert _tailwind_selector_pattern("tooltip-right").search(css) is None


# The tag name only, so the underscored variables in ``<c-vars term term_uri>`` never match.
_COTTON_TAG_NAME_RE = re.compile(r"</?c-([A-Za-z0-9_.:-]*)")


class TestNoTemplateNamesACottonComponentWithAnUnderscore:
    @pytest.mark.parametrize(
        "path",
        sorted(TEMPLATES_ROOT.rglob("*.html")),
        ids=lambda p: str(p.relative_to(TEMPLATES_ROOT)),
    )
    def test_no_cotton_tag_name_contains_an_underscore(self, path):
        offenders = [
            name
            for name in _COTTON_TAG_NAME_RE.findall(path.read_text())
            if "_" in name
        ]
        assert offenders == [], (
            f"{path.relative_to(TEMPLATES_ROOT)} names a cotton tag with an underscore: {offenders}"
        )
