"""Serve a page's subject as RDF when the request asks for it (FS-018)."""

from django.http import HttpResponse
from django.utils.cache import patch_vary_headers
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies.exchange.serializations import Serialization

#: The short names of the serializations the page head offers, in order.
ALTERNATES = ("ttl", "xml", "json-ld", "nt")

__all__ = ["RepresentationMixin"]


class RepresentationMixin:
    """Answer ``Accept`` and ``?format=`` with the subject's own statements as RDF.

    Put leftmost in a detail view's bases. A request that does not ask for RDF is
    answered by the page, with nothing looked up first.
    """

    def get_representation_subject(self):
        """Return the vocabulary or record whose statements are served.

        Returns:
            A ``ConceptScheme`` or a ``Record``.

        Raises:
            NotImplementedError: When the view does not say what its subject is.
        """
        raise NotImplementedError

    def dispatch(self, request, *args, **kwargs):
        """Mark every response as varying with the ``Accept`` header."""
        response = super().dispatch(request, *args, **kwargs)
        patch_vary_headers(response, ["Accept"])
        return response

    def get(self, request, *args, **kwargs):
        """Serve the page, an RDF serialization of the subject, or a refusal.

        Args:
            request: The request.
            *args: Passed to the page.
            **kwargs: Passed to the page.

        Returns:
            The page, the subject as RDF, or a 406 naming the types the site offers.
        """
        serialization = self.requested_serialization(request)
        if serialization is None:
            return super().get(request, *args, **kwargs)
        if serialization is False:
            return self.refusal()
        subject = self.get_representation_subject()
        return HttpResponse(
            serialization.serialize(subject.to_graph()),
            content_type=serialization.media_type,
        )

    def requested_serialization(self, request):
        """Decide which serialization the request asks for, if any.

        Args:
            request: The request.

        Returns:
            A ``Serialization``, None when the page is wanted, or False when the request
            accepts nothing the site can produce.
        """
        named = Serialization.named(request.GET.get("format", ""))
        if named is not None:
            return named
        negotiable = {s.media_type: s for s in Serialization.all() if s.negotiable}
        chosen = request.get_preferred_type(["text/html", *negotiable])
        if chosen is None:
            return False
        if chosen == "text/html":
            return None
        # A tie between HTML and RDF goes to the page, so a client that accepts anything
        # and names Turtle first still gets what a browser would.
        html = request.accepted_type("text/html")
        if html is not None and html.quality == request.accepted_type(chosen).quality:
            return None
        return negotiable[chosen]

    def refusal(self):
        """Build the 406 response for a request that accepts nothing on offer.

        Returns:
            A plain-text response.
        """
        offered = ", ".join(
            ["text/html", *(s.media_type for s in Serialization.all() if s.negotiable)]
        )
        return HttpResponse(
            _("This address can be served as: %(offered)s.") % {"offered": offered},
            status=406,
            content_type="text/plain; charset=utf-8",
        )

    def get_context_data(self, **kwargs):
        """Add the four alternate representations the page head links to."""
        context = super().get_context_data(**kwargs)
        context["rdf_alternates"] = [
            {"media_type": s.media_type, "href": f"?format={s.name}"}
            for s in (Serialization.named(name) for name in ALTERNATES)
        ]
        return context
