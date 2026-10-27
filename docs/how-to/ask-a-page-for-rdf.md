# Ask a page for RDF

A vocabulary's page, a concept's page and a collection's page can each be returned as RDF, at the
same address, by sending an `Accept` header that names an RDF media type. Software that holds a
record's identifier can fetch the record's statements without knowing anything else about the
site. The vocabulary list is not affected.

```bash
curl -H 'Accept: text/turtle' http://127.0.0.1:8000/browse/data-collection-methods/fieldwork/
```

The response holds the statements the record's own document makes about itself, with the
record's identifier as their subject: its labels in every language, its definition and notes, and
the links it states to other concepts, collections and mappings. A vocabulary's response holds the
vocabulary's own statements and none of its records'. A collection's members are written as they
were stored, an ordered collection's as an RDF list in its stored order. The response leaves out
what other records say about the subject: a concept that another concept names `skos:narrower`
gets no `skos:broader` it did not state itself, and it carries no statement about the collections
gathering it. A record imported from a publisher is described by the publisher's identifier, not
by an address on this site.

The media types a page answers to are the ones the installed rdflib can write and has a media type
for, which are listed here as of this release:

| Media type | Format |
|---|---|
| `text/turtle` | Turtle |
| `application/rdf+xml` | RDF/XML |
| `application/ld+json` | JSON-LD |
| `application/n-triples` | N-Triples |
| `application/n-quads` | N-Quads |
| `application/trig` | TriG |
| `application/trix` | TriX |
| `text/n3` | Notation3 |

N-Triples is negotiated as `application/n-triples`, so a client that asks only for `text/plain`
is not given it: it gets a 406, described under [Which one a request gets](#which-one-a-request-gets).

## Which one a request gets

- A browser's header, a request with no `Accept` header and `*/*` all get the HTML page.
- When the header names an RDF type and HTML at the same quality, the page is returned.
  `Accept: text/turtle, text/html` and `Accept: text/turtle, */*` both give the page, because
  HTML is as acceptable as Turtle. Giving HTML a lower quality, as in
  `Accept: text/html;q=0.5, text/turtle`, gives Turtle.
- Parameters on an accepted type do not stop it matching:
  `Accept: application/ld+json; profile="http://www.w3.org/ns/json-ld#expanded"` and
  `Accept: text/turtle; charset=utf-8` get JSON-LD and Turtle.
- A header that names only types the site cannot produce, such as `Accept: application/json`,
  gets a plain-text `406 Not Acceptable` that lists the types on offer.
- A row holding a term one format cannot express gets the same `406` for that format, by
  `Accept` or by `?format=`, and is served in every other. RDF/XML, for one, cannot write a
  property whose address ends in `/` or whose last part starts with a digit.
- An entry with `q=0` is ignored rather than read as a refusal, so
  `Accept: text/html;q=0, */*` still gets the page. Name the RDF type you want instead.
- An address that names no vocabulary or record is a 404 whatever the header says.

The RDF is returned inline, with no `Content-Disposition` header. Every response from these three
pages, the HTML page included, carries `Vary: Accept`, so a cache keeps the page and each RDF
type apart. A view that a project has put behind a login requirement answers an RDF request the
way it answers a browser: the requirement runs first.

## Downloading a file with `?format=`

Adding `?format=` to the address of any of the three pages returns the same statements as a file
download. The value is a short name or a media type that the installed rdflib can write:

| `?format=` | Format | File extension |
|---|---|---|
| `ttl` | Turtle | `.ttl` |
| `xml` | RDF/XML | `.rdf` |
| `json-ld` | JSON-LD | `.jsonld` |
| `nt` | N-Triples | `.nt` |

Every other serializer rdflib registers answers to its own name as well, and a media type such as
`?format=text/turtle` is accepted as a name.

```bash
curl -OJ 'http://127.0.0.1:8000/browse/data-collection-methods/fieldwork/?format=ttl'
```

The response carries a `Content-Disposition: attachment` header and the file is named after the
subject's slug and the format's extension, so the example above saves `fieldwork.ttl`. A concept or
collection is named by its own slug alone, not the vocabulary's. On a vocabulary's page the
download holds the vocabulary's own statements, whatever `?q=` or the other list parameters say.

`?format=` decides on its own: when it is present the `Accept` header is not read, so
`?format=xml` with `Accept: text/turtle` returns RDF/XML. A name the site does not offer, including
an empty one, gets a plain-text `400 Bad Request` that lists the short names on offer. An address
that names no vocabulary or record is a 404 whatever `?format=` says.

## Finding the RDF from the page

Each of the three pages lists every format the site offers under **Alternate representations** in
its side panel, by the name readers know it by. Following one downloads the file, exactly as
`?format=` does. On a narrow screen the concept and collection pages open the panel from a button
beside the title.


Each of the three pages names its RDF alternatives in its `<head>`, in the order Turtle, RDF/XML,
JSON-LD, N-Triples:

```html
<link rel="alternate" type="text/turtle" href="?format=ttl">
<link rel="alternate" type="application/rdf+xml" href="?format=xml">
<link rel="alternate" type="application/ld+json" href="?format=json-ld">
<link rel="alternate" type="application/n-triples" href="?format=nt">
```

Each `href` is relative to the page's address and returns the media type named beside it.

## On a view of your own

The three pages get this from `RepresentationMixin`, in `controlled_vocabularies.ui.representations`.
A project that serves a vocabulary or record from a view of its own can list the mixin before
the view class in its bases and say what the subject is:

```python
from django.views.generic import DetailView

from controlled_vocabularies.models import Record
from controlled_vocabularies.ui.representations import RepresentationMixin


class TermView(RepresentationMixin, DetailView):
    model = Record
    template_name = "myproject/term.html"

    def get_representation_subject(self):
        return self.get_object()
```

The mixin also puts `rdf_alternates` in the template context, the list the page head's alternate
links are drawn from.

The mixin answers in `get()`, after the view's `dispatch()`, so an access rule such as
`LoginRequiredMixin` applies to the RDF exactly as it does to the page.
