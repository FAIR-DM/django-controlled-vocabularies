"""The RDF serializations the installed rdflib can write a graph in (FS-018)."""

from __future__ import annotations

import functools
from collections import defaultdict
from dataclasses import dataclass

import rdflib
import rdflib.plugin
import rdflib.util
from rdflib.serializer import Serializer

#: Serializers that are not offered. ``patch`` writes a change set, not the statements
#: of a graph. ``pretty-xml`` writes a stray duplicate of part of an RDF list in some
#: runs.
EXCLUDED = frozenset({"patch", "pretty-xml"})

#: The media type to send for a serializer rdflib registers no media type for.
MEDIA_TYPES = {
    "longturtle": "text/turtle",
    "nt11": "application/n-triples",
    "hext": "application/x-ndjson",
}

#: The file extension where the first one rdflib maps to the format is not the usual.
EXTENSIONS = {
    "xml": "rdf",
    "json-ld": "jsonld",
    "longturtle": "ttl",
    "nt11": "nt",
    "hext": "hext",
}


@dataclass(frozen=True)
class Serialization:
    """One way to write a graph, as rdflib registers it.

    Args:
        name: The shortest registered name without a ``/``, such as ``ttl``.
        names: Every name rdflib registers for the serializer, short and media type.
        media_type: What a response's ``Content-Type`` carries.
        negotiable: Whether rdflib registers a media type for it, so ``Accept`` can pick
            it.
        extension: The file extension, without the dot.
        quads: Whether it is written from a ``Dataset`` rather than a ``Graph``.
    """

    name: str
    names: frozenset[str]
    media_type: str
    negotiable: bool
    extension: str
    quads: bool

    @classmethod
    @functools.cache
    def all(cls) -> list[Serialization]:
        """List every serialization rdflib offers, cached for the process.

        Returns:
            The serializations, ordered by name.
        """
        grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
        for plugin in rdflib.plugin.plugins(kind=Serializer):
            grouped[(plugin.module_path, plugin.class_name)].add(plugin.name)
        found = [cls.build(names) for names in grouped.values() if not names & EXCLUDED]
        return sorted(found, key=lambda serialization: serialization.name)

    @classmethod
    def build(cls, names: set[str]) -> Serialization:
        """Describe the serializer registered under ``names``.

        Args:
            names: Every name rdflib registers for the one serializer.

        Returns:
            Its serialization.
        """
        name = min((n for n in names if "/" not in n), key=lambda n: (len(n), n))
        slashed = sorted(n for n in names if "/" in n)
        suffixes = (
            suffix
            for suffix, fmt in rdflib.util.SUFFIX_FORMAT_MAP.items()
            if fmt in names
        )
        return cls(
            name=name,
            names=frozenset(names),
            media_type=(slashed or [MEDIA_TYPES.get(name, "text/plain")])[0],
            negotiable=bool(slashed),
            extension=EXTENSIONS.get(name) or next(suffixes, name),
            quads=cls.refuses_a_graph(name),
        )

    @staticmethod
    def refuses_a_graph(name: str) -> bool:
        """Return whether a serializer refuses a plain graph.

        Args:
            name: A name the serializer is registered under.

        Returns:
            True when writing an empty ``Graph`` with it raises, as ``nquads`` and
            ``trix`` do because they only make sense for a store of several graphs.
        """
        try:
            rdflib.Graph().serialize(format=name)
        except Exception:
            return True
        return False

    @classmethod
    def named(cls, name: str) -> Serialization | None:
        """Find a serialization by any name rdflib registers for it.

        Args:
            name: A short name such as ``ttl``, or a registered media type.

        Returns:
            The serialization, or None when none is offered under that name.
        """
        return next((s for s in cls.all() if name in s.names), None)

    @classmethod
    def for_media_type(cls, media_type: str) -> Serialization | None:
        """Find the negotiable serialization for a media type.

        Args:
            media_type: A media type such as ``text/turtle``.

        Returns:
            The serialization, or None when none is registered under that media type.
        """
        return next(
            (s for s in cls.all() if s.negotiable and media_type in s.names), None
        )

    def serialize(self, graph: rdflib.Graph) -> bytes:
        """Write a graph in this serialization.

        Args:
            graph: The statements to write.

        Returns:
            The encoded document. A quads serialization holds the statements in its
            default graph.
        """
        source: rdflib.Graph = graph
        if self.quads:
            source = rdflib.Dataset()
            for prefix, namespace in graph.namespaces():
                source.bind(prefix, namespace)
            for triple in graph:
                source.add(triple)
        return source.serialize(format=self.name, encoding="utf-8")
