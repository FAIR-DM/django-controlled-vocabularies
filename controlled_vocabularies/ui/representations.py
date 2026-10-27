"""Serve a page's subject as RDF when the request asks for it (FS-018)."""

from django.http import HttpResponse
from django.utils.cache import patch_vary_headers
from django.utils.http import content_disposition_header
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
            The page, the subject as RDF (a download when ``?format=`` asked for it), a
            400 naming the formats the site offers, or a 406 naming the types it offers.
        """
        serialization = self.requested_serialization(request)
        if serialization is None:
            return super().get(request, *args, **kwargs)
        # Resolved before any refusal, so an address naming nothing is a 404 whatever is asked.
        subject = self.get_representation_subject()
        if serialization is False:
            return self.refusal()
        if serialization == "unknown":
            return self.unknown_format()
        response = HttpResponse(
            serialization.serialize(subject.to_graph()),
            content_type=serialization.media_type,
        )
        if "format" in request.GET:
            response["Content-Disposition"] = content_disposition_header(
                as_attachment=True, filename=f"{subject.slug}.{serialization.extension}"
            )
        return response

    def requested_serialization(self, request):
        """Decide which serialization the request asks for, if any.

        ``?format=`` decides alone: ``Accept`` is not consulted when it is present.

        Args:
            request: The request.

        Returns:
            A ``Serialization``, None when the page is wanted, False when the request
            accepts nothing the site can produce, or ``"unknown"`` when ``?format=``
            names nothing the site offers.
        """
        if "format" in request.GET:
            return Serialization.named(request.GET["format"]) or "unknown"
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

    def unknown_format(self):
        """Build the 400 response for a ``?format=`` the site does not offer.

        Returns:
            A plain-text response naming every short name on offer.
        """
        offered = ", ".join(sorted(s.name for s in Serialization.all()))
        return HttpResponse(
            _("This address can be downloaded with ?format= set to: %(offered)s.")
            % {"offered": offered},
            status=400,
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
