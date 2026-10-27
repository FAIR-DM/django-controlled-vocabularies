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

#: The name a reader knows each format by. A format rdflib adds later is labelled by its
#: short name until it is named here.
LABELS = {
    "hext": "HexTuples",
    "json-ld": "JSON-LD",
    "longturtle": "Turtle (long form)",
    "n3": "Notation3",
    "nquads": "N-Quads",
    "nt": "N-Triples",
    "nt11": "N-Triples 1.1",
    "trig": "TriG",
    "trix": "TriX",
    "ttl": "Turtle",
    "xml": "RDF/XML",
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

    Attributes:
        name: The shortest registered name without a ``/``, such as ``ttl``.
        names: Every name rdflib registers for the serializer, short and media type.
        media_type: What a response's ``Content-Type`` carries.
        negotiable: Whether rdflib registers a media type for it, so ``Accept`` can pick
            it.
        extension: The file extension, without the dot.
        label: The name a reader knows the format by, such as ``Turtle``.
    """

    name: str
    names: frozenset[str]
    media_type: str
    negotiable: bool
    extension: str
    label: str

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
            label=LABELS.get(name, name),
        )

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

        The statements are written from the default graph of a ``Dataset``, which every
        serializer accepts. A format that names graphs, such as TriG or N-Quads, then
        holds them in its default graph, where a reader expecting one graph finds them.
        A term the format cannot express, as RDF/XML cannot a predicate ending in ``/``,
        raises ``ValueError``.

        Args:
            graph: The statements to write.

        Returns:
            The encoded document.
        """
        dataset = rdflib.Dataset()
        for prefix, namespace in graph.namespaces():
            dataset.bind(prefix, namespace)
        for triple in graph:
            dataset.add(triple)
        return dataset.serialize(format=self.name, encoding="utf-8")
