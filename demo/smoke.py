"""The guard's assertion script (T013-T017, FR-017, FR-019, User Story 3 scenarios 1, 3, 5, 9;
015-read-single-record T024, FR-005, FR-010, FR-013, FR-014, SC-008).

Speaks real HTTP against a running demo server. It follows the vocabulary list to one
vocabulary's own page and searches inside it, then follows the authored vocabulary to one of its
own concepts and one of its own collections, because those are the pages this feature ships. It
asserts on the served response, never on the code that produced it, because the failure it
exists to catch is the one every unit test passes through: a template that renders in a test
client and not in a browser.

The assertions themselves (:func:`check_list`, :func:`check_search`, :func:`check_vocabulary_page`,
:func:`check_concept_search`, :func:`check_authored_vocabulary_page`, :func:`check_concept_page`,
:func:`check_concept_page_in_a_second_language`, :func:`check_collection_page`) and the
link-following helper (:func:`extract_vocabulary_url`) are separated from the HTTP transport
(:func:`get`) so they can be exercised against an in-process response too
(``tests/test_demo/test_smoke.py``) — "a broken assertion fails here rather than only in CI".

Not a test module: standard library only, run directly against a live server, not under pytest
(conventions; constitution Article VII).
"""

import re
import sys
import urllib.error
import urllib.request

# The demo runs with DEBUG = True: an unbounded body on failure would put Django's technical-500
# page, including settings and the request environment, into a public CI log.
BODY_EXCERPT_LIMIT = 500

#: The demo's two seeded vocabularies and how many concepts each carries (demo/seed/*.ttl,
#: demo/management/commands/seed_demo.py) — named here once rather than re-derived, since the
#: walk's whole job is to notice when the served page stops agreeing with them.
IMPORTED_NAME = "DCMI Type Vocabulary"
IMPORTED_CONCEPT_COUNT = 5
AUTHORED_NAME = "Data Collection Methods"
AUTHORED_CONCEPT_COUNT = 4

#: A word that appears in the imported vocabulary's own name and nowhere in the authored one's
#: name or description — narrow enough that a search for it proves the search narrowed rather
#: than merely returned something.
SEARCH_TERM = "DCMI"

#: A concept the demo seeds into the imported vocabulary (demo/seed/dcmi_types.ttl, T016),
#: named here to prove the vocabulary's own page lists a concept it actually holds.
VOCABULARY_CONCEPT = "Dataset"

#: Another concept in the same vocabulary — present on the unsearched page, and what a search
#: narrowing correctly must exclude.
OTHER_VOCABULARY_CONCEPT = "Collection"

#: The hidden label seeded onto VOCABULARY_CONCEPT (demo/seed/dcmi_types.ttl, T016): a
#: plausible misspelling of the term itself, never shown on the page, findable only by search
#: (User Story 3 scenario 3).
HIDDEN_LABEL_SEARCH_TERM = "Datset"

#: A concept in the authored vocabulary (demo/seed/research_methods.ttl, 015-read-single-record
#: T024) whose own page the walk follows next — chosen because it carries every one of the
#: things this feature's closing task added to the seed: a stored relation, membership in both
#: seeded collections, and the German-only note that exercises FR-005's language fallback
#: alongside its own English-only definition, on the one page.
AUTHORED_CONCEPT = "Fieldwork"

#: AUTHORED_CONCEPT's own short form (T003, T016: ``{scheme.slug}:{record.slug}``) — a
#: record-valued row (an in-site relation, a collection's member) carries this as its
#: link text, never the plain label AUTHORED_CONCEPT itself names.
AUTHORED_CONCEPT_SHORT_FORM = "data-collection-methods:fieldwork"

#: AUTHORED_CONCEPT's narrower concept (research_methods.ttl: "survey" carries
#: ``skos:broader`` to "fieldwork") — shown on AUTHORED_CONCEPT's own page under
#: ``skos:narrower``, derived rather than separately stated (FR-010), by its own short
#: form rather than its plain label, for the same reason AUTHORED_CONCEPT_SHORT_FORM
#: exists.
AUTHORED_RELATED_CONCEPT_SHORT_FORM = "data-collection-methods:survey"

#: One of the two collections research_methods.ttl already seeded (T020) that gathers
#: AUTHORED_CONCEPT — named on AUTHORED_CONCEPT's own page, below its definition list
#: (FR-014), and the walk's own destination for AUTHORED_CONCEPT's page (FR-013). Named
#: there by its plain ``name`` (concept_detail.html's membership section is not a
#: property_row, so it carries no short form of its own).
AUTHORED_COLLECTION = "Typical project workflow"

#: The German-only note seeded onto AUTHORED_CONCEPT (research_methods.ttl,
#: 015-read-single-record T024): shown when the page is read in German, never in the
#: unseeded reading language the rest of this walk uses (FR-005).
GERMAN_SCOPE_NOTE = "Erhoben durch unmittelbare Beobachtung oder Messung am Studienort."

#: AUTHORED_CONCEPT's English-only definition — carries no German value of its own, so
#: reading the same page in German falls back to this rather than showing nothing
#: (FR-005, the other half of the fallback GERMAN_SCOPE_NOTE's own presence proves).
ENGLISH_FALLBACK_DEFINITION = (
    "Data collected through direct observation or measurement at a study site."
)


class SmokeCheckFailed(Exception):
    """The URL, status and a bounded body excerpt of a failed check (FR-017)."""


def fail(url, status, reason, body=""):
    raise SmokeCheckFailed(f"{url} [{status}]: {reason}\n{body[:BODY_EXCERPT_LIMIT]}")


def check_list(list_url, status, body):
    """Both seeded vocabularies are named on the list and carry their concept counts
    (FR-016, User Story 3 scenario 2)."""
    if status != 200:
        fail(list_url, status, "the vocabulary list did not serve", body)
    for name, count in (
        (IMPORTED_NAME, IMPORTED_CONCEPT_COUNT),
        (AUTHORED_NAME, AUTHORED_CONCEPT_COUNT),
    ):
        if name not in body:
            fail(
                list_url,
                status,
                f"the seeded vocabulary {name!r} is not on the list — the seed did not load",
                body,
            )
        if f"{count} concept" not in body:
            fail(
                list_url,
                status,
                f"{name!r}'s concept count ({count}) is not on the page",
                body,
            )


def check_search(search_url, status, body):
    """A search narrows the list to the vocabulary it matches and excludes the other
    (User Story 3 scenario 5)."""
    if status != 200:
        fail(search_url, status, "a search did not serve", body)
    if IMPORTED_NAME not in body:
        fail(
            search_url,
            status,
            f"a search for {SEARCH_TERM!r} does not narrow to {IMPORTED_NAME!r}",
            body,
        )
    if AUTHORED_NAME in body:
        fail(
            search_url,
            status,
            f"a search for {SEARCH_TERM!r} still shows {AUTHORED_NAME!r} — the search did not narrow",
            body,
        )


def check_vocabulary_page(vocabulary_url, status, body):
    """The vocabulary's own page lists a concept it actually holds (FR-019, User Story 3
    scenario 1)."""
    if status != 200:
        fail(vocabulary_url, status, "the vocabulary's page did not serve", body)
    if VOCABULARY_CONCEPT not in body:
        fail(
            vocabulary_url,
            status,
            f"the seeded concept {VOCABULARY_CONCEPT!r} is not on the vocabulary's page — the seed did not load",
            body,
        )


def check_concept_search(search_url, status, body):
    """A search inside the vocabulary narrows to the concept it matches, including one found
    only through its hidden label (FR-019, User Story 3 scenarios 3, 9)."""
    if status != 200:
        fail(search_url, status, "a concept search did not serve", body)
    if VOCABULARY_CONCEPT not in body:
        fail(
            search_url,
            status,
            f"searching {HIDDEN_LABEL_SEARCH_TERM!r} does not narrow to {VOCABULARY_CONCEPT!r}",
            body,
        )
    if OTHER_VOCABULARY_CONCEPT in body:
        fail(
            search_url,
            status,
            f"searching {HIDDEN_LABEL_SEARCH_TERM!r} still shows {OTHER_VOCABULARY_CONCEPT!r} "
            "— the search did not narrow",
            body,
        )


def check_authored_vocabulary_page(vocabulary_url, status, body):
    """The authored vocabulary's own page lists the concept the walk follows next
    (015-read-single-record T024)."""
    if status != 200:
        fail(
            vocabulary_url, status, "the authored vocabulary's page did not serve", body
        )
    if AUTHORED_CONCEPT not in body:
        fail(
            vocabulary_url,
            status,
            f"the seeded concept {AUTHORED_CONCEPT!r} is not on the authored vocabulary's page — the seed did not load",
            body,
        )


def check_concept_page(concept_url, status, body):
    """A concept's own page shows its relation and the collections that gather it
    (015-read-single-record T024, FR-010, FR-014)."""
    if status != 200:
        fail(concept_url, status, "the concept's page did not serve", body)
    if AUTHORED_RELATED_CONCEPT_SHORT_FORM not in body:
        fail(
            concept_url,
            status,
            f"{AUTHORED_RELATED_CONCEPT_SHORT_FORM!r}, {AUTHORED_CONCEPT!r}'s narrower concept, is not "
            "shown — the seeded relation did not load",
            body,
        )
    if AUTHORED_COLLECTION not in body:
        fail(
            concept_url,
            status,
            f"{AUTHORED_COLLECTION!r}, one of the collections that gathers {AUTHORED_CONCEPT!r}, is not named",
            body,
        )


def check_concept_page_in_a_second_language(concept_url, status, body):
    """Read in German, the same page shows a value carried only in German directly, and
    falls back to English for a value carried only there (015-read-single-record T024,
    FR-005)."""
    if status != 200:
        fail(concept_url, status, "the concept's page did not serve in German", body)
    if GERMAN_SCOPE_NOTE not in body:
        fail(
            concept_url,
            status,
            "the German-only note is not shown when the page is read in German",
            body,
        )
    if ENGLISH_FALLBACK_DEFINITION not in body:
        fail(
            concept_url,
            status,
            "the English-only definition did not fall back to English when the page is read in German",
            body,
        )


def check_collection_page(collection_url, status, body):
    """A collection's own page shows a concept it gathers (015-read-single-record T024,
    FR-013)."""
    if status != 200:
        fail(collection_url, status, "the collection's page did not serve", body)
    if AUTHORED_CONCEPT_SHORT_FORM not in body:
        fail(
            collection_url,
            status,
            f"{AUTHORED_CONCEPT_SHORT_FORM!r} is not shown as a member of {AUTHORED_COLLECTION!r}",
            body,
        )


def extract_vocabulary_url(list_body, name):
    """The href of the anchor naming ``name`` on rendered markup — the way the walk
    follows the list to a vocabulary's own page, and equally how it follows a
    vocabulary's own page to one of its concepts or one of its collections
    (015-read-single-record T024): every one of those rows is a plain ``<a>`` naming
    the record and nothing else.

    A small regex, not an HTML-parser dependency: this module runs against a live server with
    no test-only packages installed (module docstring), so it reads the same served markup a
    browser would rather than depending on one more thing that could itself be missing.
    """
    match = re.search(
        rf'<a\s+href="([^"]+)"[^>]*>\s*{re.escape(name)}\s*</a>', list_body
    )
    if match is None:
        fail(
            "(vocabulary list)",
            200,
            f"no link naming {name!r} found on the rendered list",
            list_body,
        )
    return match.group(1)


def get(url, headers=None):
    """GET ``url`` and return ``(status, body)``, failing on a connection error (FR-017).

    ``headers`` (015-read-single-record T024) lets the walk ask for a page in a reading
    language other than the demo's own default — ``Accept-Language``, the same header a
    real browser sends, rather than a URL parameter this package's routes carry no
    concept of.
    """
    request = urllib.request.Request(url, headers=headers or {})  # noqa: S310 — http(s) only, built from argv
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 — http(s) only, built from argv
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        fail(url, None, f"could not connect: {exc.reason}")
        raise  # pragma: no cover — fail() always raises; this satisfies the type checker


def walk(base_url):
    """Request the list, search it, follow it to the imported vocabulary's page and search
    inside it — including a search matching only a hidden label (User Story 3 scenarios 1, 3,
    5, 9) — then follow the authored vocabulary to one of its own concepts and one of its own
    collections, reading the concept's page once in the demo's own default language and once
    in German (015-read-single-record T024, FR-005, FR-010, FR-013, FR-014)."""
    base_url = base_url.rstrip("/")
    list_url = f"{base_url}/browse/"
    status, list_body = get(list_url)
    check_list(list_url, status, list_body)

    search_url = f"{list_url}?q={SEARCH_TERM}"
    status, body = get(search_url)
    check_search(search_url, status, body)

    vocabulary_url = base_url + extract_vocabulary_url(list_body, IMPORTED_NAME)
    status, body = get(vocabulary_url)
    check_vocabulary_page(vocabulary_url, status, body)

    concept_search_url = f"{vocabulary_url}?q={HIDDEN_LABEL_SEARCH_TERM}"
    status, body = get(concept_search_url)
    check_concept_search(concept_search_url, status, body)

    authored_url = base_url + extract_vocabulary_url(list_body, AUTHORED_NAME)
    status, authored_body = get(authored_url)
    check_authored_vocabulary_page(authored_url, status, authored_body)

    concept_url = base_url + extract_vocabulary_url(authored_body, AUTHORED_CONCEPT)
    status, concept_body = get(concept_url)
    check_concept_page(concept_url, status, concept_body)

    status, concept_body_de = get(concept_url, headers={"Accept-Language": "de"})
    check_concept_page_in_a_second_language(concept_url, status, concept_body_de)

    collection_url = base_url + extract_vocabulary_url(
        authored_body, AUTHORED_COLLECTION
    )
    status, collection_body = get(collection_url)
    check_collection_page(collection_url, status, collection_body)


def main(argv):
    base_url = argv[1] if len(argv) > 1 else "http://127.0.0.1:8000"
    try:
        walk(base_url)
    except SmokeCheckFailed as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK: walked the demo vocabulary list, a vocabulary's page, a search inside it, a "
        f"concept's own page (in the demo's default language and in German), and a "
        f"collection's own page, at {base_url}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
