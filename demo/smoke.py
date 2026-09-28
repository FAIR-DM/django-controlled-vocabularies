"""Assertion script that walks a running demo server over HTTP."""

import re
import sys
import urllib.error
import urllib.request

# The demo runs with DEBUG = True: an unbounded body on failure would put Django's technical-500
# page, including settings and the request environment, into a public CI log.
BODY_EXCERPT_LIMIT = 500

#: The seeded vocabularies and their concept counts (demo/seed/*.ttl), so the walk notices when
#: the served page stops agreeing with the seed.
IMPORTED_NAME = "DCMI Type Vocabulary"
IMPORTED_CONCEPT_COUNT = 5
AUTHORED_NAME = "Data Collection Methods"
AUTHORED_CONCEPT_COUNT = 4

#: Appears in the imported vocabulary's name and nowhere in the authored one's, so a search for it
#: proves the list narrowed rather than merely returned something.
SEARCH_TERM = "DCMI"

VOCABULARY_CONCEPT = "Dataset"

#: Present on the unsearched page; a search that narrows correctly must exclude it.
OTHER_VOCABULARY_CONCEPT = "Collection"

#: A misspelling seeded as a hidden label of VOCABULARY_CONCEPT: never shown, findable only by search.
HIDDEN_LABEL_SEARCH_TERM = "Datset"

#: Chosen because its page carries a stored relation, membership in both seeded collections and a
#: German-only note beside an English-only definition, which exercises the language fallback (FS-015).
AUTHORED_CONCEPT = "Fieldwork"

#: Record-valued rows link by short form (``{scheme.slug}:{record.slug}``), never by plain label.
AUTHORED_CONCEPT_SHORT_FORM = "data-collection-methods:fieldwork"

#: The concept narrower than AUTHORED_CONCEPT (research_methods.ttl gives "survey" a
#: ``skos:broader`` to "fieldwork"), shown on its page by short form and derived, not stated.
AUTHORED_RELATED_CONCEPT_SHORT_FORM = "data-collection-methods:survey"

#: A seeded collection gathering AUTHORED_CONCEPT, shown by its plain name because the concept
#: page's membership section is not a property row and carries no short form.
AUTHORED_COLLECTION = "Typical project workflow"

#: Seeded in German only, so it shows when the page is read in German and never otherwise.
GERMAN_SCOPE_NOTE = "Erhoben durch unmittelbare Beobachtung oder Messung am Studienort."

#: Carries no German value, so reading the page in German falls back to it.
ENGLISH_FALLBACK_DEFINITION = (
    "Data collected through direct observation or measurement at a study site."
)


class SmokeCheckFailed(Exception):
    """Raised for a failed check, carrying the URL, status and a bounded body excerpt."""


def fail(url, status, reason, body=""):
    """Raise :class:`SmokeCheckFailed` for a failed check.

    Args:
        url: The address that was requested.
        status: The HTTP status the server returned, or ``None`` when there was none.
        reason: What was expected and did not happen.
        body: The response body, cut to ``BODY_EXCERPT_LIMIT`` characters in the message.

    Raises:
        SmokeCheckFailed: Always.
    """
    raise SmokeCheckFailed(f"{url} [{status}]: {reason}\n{body[:BODY_EXCERPT_LIMIT]}")


def check_list(list_url, status, body):
    """Check that both seeded vocabularies are listed with their concept counts.

    Fails through :func:`fail` when it does not hold.

    Args:
        list_url: The address that was requested.
        status: The HTTP status the server returned.
        body: The response body.
    """
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
    """Check that a search narrows the list to the vocabulary it matches.

    Fails through :func:`fail` when it does not hold.

    Args:
        search_url: The address that was requested.
        status: The HTTP status the server returned.
        body: The response body.
    """
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
    """Check that a vocabulary's page lists a concept it holds.

    Fails through :func:`fail` when it does not hold.

    Args:
        vocabulary_url: The address that was requested.
        status: The HTTP status the server returned.
        body: The response body.
    """
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
    """Check that a search inside a vocabulary finds a concept through its hidden label.

    Fails through :func:`fail` when it does not hold.

    Args:
        search_url: The address that was requested.
        status: The HTTP status the server returned.
        body: The response body.
    """
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
    """Check that the authored vocabulary's page lists the concept the walk follows next.

    Fails through :func:`fail` when it does not hold.

    Args:
        vocabulary_url: The address that was requested.
        status: The HTTP status the server returned.
        body: The response body.
    """
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
    """Check that a concept's page shows its narrower concept and the collection that gathers it.

    Fails through :func:`fail` when it does not hold.

    Args:
        concept_url: The address that was requested.
        status: The HTTP status the server returned.
        body: The response body.
    """
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
    """Check that a concept's page in German shows its German note and falls back to English elsewhere.

    Fails through :func:`fail` when it does not hold.

    Args:
        concept_url: The address that was requested.
        status: The HTTP status the server returned.
        body: The response body.
    """
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
    """Check that a collection's page shows a concept it gathers.

    Fails through :func:`fail` when it does not hold.

    Args:
        collection_url: The address that was requested.
        status: The HTTP status the server returned.
        body: The response body.
    """
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
    """Return the address of the link naming a record on rendered markup.

    Fails through :func:`fail` when no link matches.

    A regex rather than an HTML parser: this module runs against a live server with
    no test-only packages installed.

    Args:
        list_body: The rendered page to search.
        name: The link text to find.

    Returns:
        The link's ``href``.
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
    """Request a page over HTTP.

    Fails through :func:`fail` when the server cannot be reached.

    Args:
        url: The address to request.
        headers: Extra request headers, such as ``Accept-Language``.

    Returns:
        The status and decoded body. An HTTP error status is returned, not raised.

    Raises:
        urllib.error.URLError: Re-raised after :func:`fail`, which always raises first, so callers see
            :class:`SmokeCheckFailed`.
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
    """Walk the list, a vocabulary, a search inside it, a concept in two languages and a collection.

    Fails through :func:`fail` at the first page that does not serve or lacks what the seed provides.

    Args:
        base_url: The address of the running demo server.
    """
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
    """Run the walk and report the outcome.

    Args:
        argv: Command-line arguments; the second, if given, is the server's base URL.

    Returns:
        The process exit status: 0 on success, 1 on a failed check.
    """
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
