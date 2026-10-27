"""Serve a page's subject as RDF when the request asks for it (FS-018)."""

from django.http import HttpResponse
from django.http.request import MediaType
from django.utils.cache import patch_vary_headers
from django.utils.http import content_disposition_header
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies.exchange.serializations import Serialization

#: The serializations the page head names, in order, by short name. The side panel
#: lists every serialization.
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
        if "format" in request.GET:
            serialization = Serialization.named(request.GET["format"])
            # Resolved before any refusal, so an address naming nothing is a 404 whatever
            # is asked for.
            subject = self.get_representation_subject()
            if serialization is None:
                return self.unknown_format()
            download = True
        else:
            media_type = self.negotiated_media_type(request)
            if media_type == "text/html":
                return super().get(request, *args, **kwargs)
            subject = self.get_representation_subject()
            if media_type is None:
                return self.refusal()
            serialization = Serialization.for_media_type(media_type)
            download = False
        try:
            body = serialization.serialize(subject.to_graph())
        except ValueError:
            # The format cannot express one of the row's terms, as RDF/XML cannot a
            # predicate ending in "/". The row is still served in every other format.
            return self.refusal()
        response = HttpResponse(body, content_type=serialization.media_type)
        if download:
            response["Content-Disposition"] = content_disposition_header(
                as_attachment=True, filename=f"{subject.slug}.{serialization.extension}"
            )
        return response

    def negotiated_media_type(self, request):
        """Choose between the page and the RDF media types from ``Accept``.

        Each offered type takes the quality of the most specific accepted entry it
        matches, with the entry's parameters set aside, so a JSON-LD ``profile`` or a
        ``charset`` still selects its type. The highest quality wins. A tie goes to the
        page, which is offered first, so a client that accepts anything and names Turtle
        first still gets what a browser would.

        Args:
            request: The request.

        Returns:
            ``"text/html"`` for the page, an RDF media type, or None when the request
            accepts nothing the site can produce.
        """
        offered = [
            "text/html",
            *(s.media_type for s in Serialization.all() if s.negotiable),
        ]
        best, best_quality = None, 0.0
        for media_type in offered:
            entry = next(
                (
                    accepted
                    for accepted in request.accepted_types_by_precedence
                    if MediaType(f"{accepted.main_type}/{accepted.sub_type}").match(
                        media_type
                    )
                ),
                None,
            )
            if entry is not None and entry.quality > best_quality:
                best, best_quality = media_type, entry.quality
        return best

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
        """Add the representations the page head names and the side panel lists."""
        context = super().get_context_data(**kwargs)
        context["rdf_alternates"] = [
            {"media_type": s.media_type, "href": f"?format={s.name}"}
            for s in (Serialization.named(name) for name in ALTERNATES)
        ]
        context["rdf_downloads"] = [
            {"label": s.label, "href": f"?format={s.name}"}
            for s in sorted(Serialization.all(), key=lambda s: s.label.casefold())
        ]
        return context
