"""Tests proving the ui templates carry no vocabulary link and no untranslated reader-visible
text (T009, FR-013, decisions.md D1, and the repo's every-string-translated convention), and,
from 015-read-single-record T002, the ``property_row`` component's own rendering and CSS.
"""

import re
from pathlib import Path

import mvp
import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.urls import reverse

from tests.factories import ConceptSchemeFactory


def visible_text(element) -> str:
    """``element``'s text with any ``.sr-only`` descendant's own text left out.

    015-read-single-record T029 (corrected): a disclosed identifier's text is a real
    node in the DOM, inside a visually-hidden span a screen reader still reads — so
    ``get_text()`` alone cannot tell "printed for every reader" from "reachable only
    behind a tooltip and an accessible description".
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
# 015-read-single-record T023, FR-006: every template that carries an in-site link, widened
# from the one file ROW_TEMPLATE_PATH named on its own — the two row partials plus
# property_row.html, which composes the in-site link T003's record-valued rows carry.
IN_SITE_LINK_TEMPLATE_PATHS = [
    ROW_TEMPLATE_PATH,
    CONCEPT_ROW_TEMPLATE_PATH,
    PROPERTY_ROW_TEMPLATE_PATH,
]
# mvp is a namespace package (no __init__.py), so it carries no __file__ — its own
# __path__ is the only way to locate the package directory.
MVP_CSS_PATH = Path(mvp.__path__[0]) / "static" / "css" / "django-mvp.css"

# Django syntax that is already known-safe and is stripped before the reader-visible-text scan:
# a developer comment, a blocktrans block (translated, content and all), any remaining tag
# (including a `{% trans %}` — its quoted content is translated, so removing tag and content
# together is correct), and a variable interpolation (dynamic — not a literal string this
# template owns the wording of).
_COMMENT_RE = re.compile(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}", re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCKTRANS_RE = re.compile(r"{%\s*blocktrans.*?{%\s*endblocktrans\s*%}", re.DOTALL)
_TAG_RE = re.compile(r"{%.*?%}", re.DOTALL)
_VAR_RE = re.compile(r"{{.*?}}", re.DOTALL)
_TEXT_NODE_RE = re.compile(r">([^<{]+)<")
_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def bare_reader_visible_text_nodes(source: str) -> list[str]:
    """Every text-node fragment left after Django's own translation and comment syntax is
    stripped out — a non-empty result names a string the convention (every reader-visible
    string wrapped in a translation tag) failed to wrap. Scoped to text nodes (content
    between tags), not attribute values — this app's own templates put every reader-visible
    string there deliberately, for exactly this reason (T009: attribute-value scanning
    cannot tell a literal string from a structural token like a slot name or a size key
    without a real HTML/template parser, which does not earn its cost at this app's size).
    """
    stripped = _COMMENT_RE.sub("", source)
    stripped = _HTML_COMMENT_RE.sub("", stripped)
    stripped = _BLOCKTRANS_RE.sub("", stripped)
    stripped = _TAG_RE.sub("", stripped)
    stripped = _VAR_RE.sub("", stripped)
    return [node for node in _TEXT_NODE_RE.findall(stripped) if _WORD_RE.search(node)]


class TestRowPartialLinksToTheVocabulary:
    """FR-013, T004 — the row partial's own source, the inverse of what #140 asserted here.

    #140 held that no entry may link to a vocabulary, because no address served one; T001
    gives every vocabulary a page, so the entry now leads to it. What remains true from #140
    is the second assertion: the in-site link is reversed from the route's name, never
    composed from the identifier base address, which is a public identifier and may point at
    another site's publisher entirely.
    """

    def test_the_row_partial_source_reverses_the_vocabularys_own_route(self):
        source = ROW_TEMPLATE_PATH.read_text()
        assert "{% url 'controlled_vocabularies_ui:vocabulary-detail'" in source

    def test_the_row_partial_source_contains_no_local_url_reference(self):
        source = ROW_TEMPLATE_PATH.read_text()
        assert "local_url" not in source


class TestRenderedPageLinksToEachVocabulary:
    """FR-013 stated the second way: scanning the page as actually rendered."""

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
    """015-read-single-record T019, FR-015 — the inverse of what T008 asserted here.

    T008 held that a concept's row carries nothing to follow, because no address served
    one; this feature gives every concept a page, so the row now leads to it. The row
    renders in an isolated context holding only the object (`render_list_item` builds a
    fresh context per row), so the address is reversed from ``object.scheme`` and
    ``object.slug`` alone, never from a variable the surrounding page happens to carry.
    """

    def test_the_row_partial_source_reverses_the_concepts_own_route(self):
        source = CONCEPT_ROW_TEMPLATE_PATH.read_text()
        assert "{% url 'controlled_vocabularies_ui:concept-detail'" in source

    def test_the_row_partial_source_contains_no_local_url_reference(self):
        source = CONCEPT_ROW_TEMPLATE_PATH.read_text()
        assert "local_url" not in source


class TestConceptSchemeDetailCollectionsLinkToTheirOwnPages:
    """015-read-single-record T020, FR-015 — the inverse of what
    `TestVocabularyDetailCollections.test_nothing_links_to_a_collection`
    (test_views.py) asserted here: a collection was named but nothing linked to it,
    because no address served one. This feature gives every collection a page, so
    each entry now leads to it.
    """

    def test_the_page_source_reverses_the_collections_own_route(self):
        source = CONCEPTSCHEME_DETAIL_TEMPLATE_PATH.read_text()
        assert "{% url 'controlled_vocabularies_ui:collection-detail'" in source

    def test_the_page_source_contains_no_local_url_reference_for_a_collection(self):
        source = CONCEPTSCHEME_DETAIL_TEMPLATE_PATH.read_text()
        assert "local_url" not in source


class TestEveryTemplateCarryingAnInSiteLinkContainsNoLocalUrlReference:
    """015-read-single-record T023, FR-006 — the guard
    :class:`TestRowPartialLinksToTheVocabulary` and
    :class:`TestConceptRowPartialLinksToItsOwnPage` each make for their own one
    template, widened to every template that carries an in-site link: the two row
    partials plus ``property_row.html``, which composes T003's record-valued rows'
    own in-site link from a caller-supplied ``href`` rather than reversing a route
    itself. A broadening, not a supersession — every one of the per-template
    assertions above still runs unchanged; this adds the coverage none of them gave
    ``property_row.html``.
    """

    @pytest.mark.parametrize(
        "path",
        IN_SITE_LINK_TEMPLATE_PATHS,
        ids=lambda p: str(p.relative_to(TEMPLATES_ROOT)),
    )
    def test_the_template_source_contains_no_local_url_reference(self, path):
        # Stripped of {% comment %} blocks first, the same known-safe syntax
        # bare_reader_visible_text_nodes above already treats as inert: property_row.html's
        # own comment explains in prose why it avoids local_url, which would otherwise read
        # as a false positive of the very thing this guard exists to catch.
        markup = _COMMENT_RE.sub("", path.read_text())
        assert "local_url" not in markup


class TestEveryShippedTemplateWrapsReaderVisibleTextInATranslationTag:
    """Every reader-visible string is translatable (repo convention, checked mechanically per T009)."""

    @pytest.mark.parametrize(
        "path",
        sorted(TEMPLATES_ROOT.rglob("*.html")),
        ids=lambda p: str(p.relative_to(TEMPLATES_ROOT)),
    )
    def test_no_bare_reader_visible_text_outside_a_translation_tag(self, path):
        fragments = bare_reader_visible_text_nodes(path.read_text())
        assert fragments == []


class TestPropertyRowRendersAPlainValue:
    """A term and a plain value render as a ``<dt>``/``<dd>`` pair (T002, FR-016)."""

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
    """A record-valued row also carries the record's short form, its canonical identifier
    as reader-reachable text, and its in-site link (T002, FR-016, plan.md Key design
    decision #6). ``href`` is a plain string here, exactly as :func:`render_to_string`
    receives one in isolation — reversing it through the app's own namespace is the
    caller's job (T003), not this component's.
    """

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
        # 015-read-single-record T029 (corrected): the full identifier is disclosed
        # behind the short form — a tooltip for a pointer, aria-describedby naming a
        # hidden span for a keyboard user and a screen reader — not printed as
        # ordinary text beside it, and never in a title attribute.
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
    """FR-007's later clarification: the full identifier is disclosed behind the short
    form, not printed inline beside it, and reachable by more than a pointer alone
    (015-read-single-record T029, corrected). daisyUI's ``:has(:focus-visible)``
    reveal rule matches a focused *descendant*, so the ``.tooltip`` element must wrap
    the link rather than be a class on the anchor itself, or a keyboard user tabbing
    to the link never sees it. The accessible description is carried by
    ``aria-describedby`` naming a visually-hidden ``.sr-only`` span, not ``title`` —
    ``aria-describedby`` wins where both are present, and a screen reader's
    willingness to announce ``title`` is a per-user setting.
    """

    def test_the_tooltip_wraps_the_link_rather_than_a_class_on_it(self):
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
        # The broken arrangement this replaces put class="tooltip" on the anchor
        # itself — asserting only that data-tip exists somewhere would still pass
        # against that shape, so the anchor's own class is asserted clean of it.
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
    """015-read-single-record second round: the ``<dt>`` lost the ``<abbr title=...>``
    arrangement T031 first used, in favour of the same wrapping-``.tooltip``-span and
    visually-hidden ``.sr-only``-span shape
    :class:`TestPropertyRowRecordValueDisclosesIdentifierOnHover` proves for a ``<dd>``.
    Covers what none of the tests above prove about the ``<dt>`` itself.
    """

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


# A class name never continues past one of these in the shipped stylesheet: the brace of a
# standalone rule, or a combinator, attribute selector, pseudo-class or list separator gluing
# it to the rest of a compound selector. Required so "tooltip-right" cannot match a would-be
# "tooltip-rightmost" — the boundary check is what makes the match a name match rather than a
# prefix match.
_SELECTOR_BOUNDARY = r"[{>:,\[)\s]"


def _tailwind_selector_pattern(class_token: str) -> re.Pattern[str]:
    """A regex matching ``class_token`` as the shipped stylesheet actually spells it, at a
    real selector boundary: Tailwind backslash-escapes a colon or a slash inside a compiled
    class name (memory: "built CSS escapes the colon" — the same is true of the slash a class
    like ``text-base-content/60`` carries), so the escaped spelling is matched, not the raw
    token. And daisyUI's positional tooltip classes such as ``tooltip-right`` never appear as
    a standalone ``.token{`` rule — only glued to a combinator or another selector, e.g.
    ``.tooltip-right>.tooltip-content`` or ``.tooltip-right:after`` — so a bare ``{`` search
    returns a false negative for a class that is plainly shipped and would work.
    """
    escaped = re.escape(class_token.replace("/", r"\/").replace(":", r"\:"))
    return re.compile(rf"\.{escaped}(?={_SELECTOR_BOUNDARY})")


class TestPropertyRowClasses:
    """Every class the component names by hand is present in django-mvp's own shipped
    stylesheet (T002) — this package ships none of its own, and django-mvp's is prebuilt
    from django-mvp's own templates, so an invented class would be silently inert.
    """

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
        # tooltip-right (015-read-single-record second round) never appears as a standalone
        # rule — only as ".tooltip-right>.tooltip-content,.tooltip-right[data-tip]:before" and
        # ".tooltip-right:after". A matcher that only accepted a trailing "{" would report this
        # class absent though it ships and works, which is the false negative this guard exists
        # to fix.
        css = MVP_CSS_PATH.read_text()
        assert _tailwind_selector_pattern("tooltip-right").search(css)

    def test_the_presence_check_discriminates_rather_than_passing_regardless(self):
        # A control class the build has no reason to emit: this package's own component
        # could never legitimately name it, so its absence proves the check above tells a
        # real class from an absent one instead of matching anything handed to it — which
        # is exactly the failure mode an invented class would hit in silence otherwise.
        css = MVP_CSS_PATH.read_text()
        assert (
            _tailwind_selector_pattern("cv-property-row-invented-class").search(css)
            is None
        )

    def test_the_boundary_does_not_let_a_shorter_class_match_inside_a_longer_ones_name(
        self,
    ):
        # Widening the boundary to accept a compound selector must not widen it into a prefix
        # match: a stylesheet naming only ".tooltip-rightmost" never ships "tooltip-right" at
        # all, so the check for the shorter name must still report it absent.
        css = ".tooltip-rightmost{color:red}"
        assert _tailwind_selector_pattern("tooltip-right").search(css) is None


# The tag name portion only — up to the first whitespace, "/" or ">" — so a cotton
# directive's own variables (e.g. <c-vars term term_uri ...>, which legitimately name
# underscored context keys after the tag name) are never mistaken for the tag name itself.
_COTTON_TAG_NAME_RE = re.compile(r"</?c-([A-Za-z0-9_.:-]*)")


class TestNoTemplateNamesACottonComponentWithAnUnderscore:
    """Repo-wide convention: a cotton component tag always uses hyphens, never
    underscores — property_row.html's own three call sites were still written
    ``<c-controlled_vocabularies.property_row />`` until this round (the file path on
    disk keeps its own underscores; this is about what a template writes, not what
    cotton resolves the tag from). Asserted across every shipped template, not only the
    two this feature touched, because the convention holds regardless of which feature
    next writes a cotton tag.
    """

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
