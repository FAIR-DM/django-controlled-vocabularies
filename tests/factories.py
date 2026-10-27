"""factory_boy factories for the vocabulary and test-app models."""

import factory

from controlled_vocabularies.models import ConceptScheme, Link, Record
from tests.testapp.models import (
    Artifact,
    Borehole,
    CoreSample,
    Deposit,
    DrillCore,
    FieldNote,
    Fossil,
    IgneousLog,
    Locality,
    Outcrop,
    Photograph,
    RockSample,
    Sample,
    Sketch,
    Specimen,
    Survey,
)


def labelled(name, language="en", statements=None):
    """Return a document naming its subject, with any further statements.

    Args:
        name: The preferred label.
        language: The label's language tag.
        statements: Further predicates, each a CURIE holding a list of entries.

    Returns:
        The document.
    """
    return {
        "skos:prefLabel": [{"@value": name, "@language": language}],
        **(statements or {}),
    }


class ConceptSchemeFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`ConceptScheme` with an app-wide-unique English name.

    Pass ``name`` to choose the name, or ``data`` to give the whole document.
    """

    class Meta:
        model = ConceptScheme

    class Params:
        name = factory.Sequence(lambda n: f"Vocabulary {n}")

    default_language = "en"
    data = factory.LazyAttribute(
        lambda scheme: labelled(scheme.name, scheme.default_language)
    )


class RecordFactory(factory.django.DjangoModelFactory):
    """Build a saved concept :class:`Record`, auto-creating its vocabulary.

    Pass ``label`` to choose its name, ``type`` for a collection, or ``data`` to give
    the whole document.
    """

    class Meta:
        model = Record

    class Params:
        label = factory.Sequence(lambda n: f"Concept {n}")

    scheme = factory.SubFactory(ConceptSchemeFactory)
    type = Record.Type.CONCEPT
    data = factory.LazyAttribute(
        lambda record: labelled(record.label, record.scheme.default_language)
    )


class LinkFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`Link` row from a new record, with a unique target.

    The row is made directly, so it need not match the source record's document.
    """

    class Meta:
        model = Link

    source = factory.SubFactory(RecordFactory)
    predicate = "skos:broader"
    target = factory.Sequence(lambda n: f"https://example.org/target/{n}")


def relation_graph(scheme=None):
    """Build a small navigable graph in one vocabulary and return its concepts.

    A broader/narrower pair (``child`` under ``parent``, stated by the child) and a
    related pair (``left`` and ``right``, stated by ``left``).

    Args:
        scheme: The vocabulary to build the graph in. A new one is created when omitted.

    Returns:
        A dict with keys ``scheme``, ``parent``, ``child``, ``left`` and ``right``.
    """
    scheme = scheme or ConceptSchemeFactory()
    parent = RecordFactory(scheme=scheme, label="Parent")
    right = RecordFactory(scheme=scheme, label="Right")
    child = RecordFactory(
        scheme=scheme,
        data=labelled("Child", statements={"skos:broader": [{"@id": parent.uri}]}),
    )
    left = RecordFactory(
        scheme=scheme,
        data=labelled("Left", statements={"skos:related": [{"@id": right.uri}]}),
    )
    return {
        "scheme": scheme,
        "parent": parent,
        "child": child,
        "left": left,
        "right": right,
    }


def collection_with_members(
    scheme=None, labels=("Granite", "Basalt", "Gabbro"), ordered=False, name=None
):
    """Build a collection of new concepts and return it with its members.

    Args:
        scheme: The vocabulary to build in. A new one is created when omitted.
        labels: The label of each concept to create, in member order.
        ordered: Build an ordered collection, listing its members in
            ``skos:memberList``.
        name: The collection's name. Leave it out for a generated one, and pass it when
            a consuming model's ``collection=`` restriction has to name its slug.

    Returns:
        A ``(collection, members)`` tuple, ``members`` being the concepts in order.
    """
    scheme = scheme or ConceptSchemeFactory()
    members = [RecordFactory(scheme=scheme, label=label) for label in labels]
    predicate = "skos:memberList" if ordered else "skos:member"
    collection = RecordFactory(
        scheme=scheme,
        type=Record.Type.ORDERED_COLLECTION if ordered else Record.Type.COLLECTION,
        data=labelled(
            name or f"Collection of {', '.join(labels)}",
            statements={predicate: [{"@id": member.uri} for member in members]},
        ),
    )
    return collection, members


def concept_below(parent, label, stated_by="child", **kwargs):
    """Build a concept one level below ``parent``, stating the link in either direction.

    Args:
        parent: The concept it sits under, in the same vocabulary unless ``scheme`` is passed.
        label: The new concept's label.
        stated_by: ``"child"`` to give the new concept ``skos:broader`` the parent,
            ``"parent"`` to add ``skos:narrower`` the new concept to the parent's document.
        **kwargs: Passed to :class:`RecordFactory`, for example ``scheme``.

    Returns:
        The new concept.
    """
    scheme = kwargs.pop("scheme", parent.scheme)
    if stated_by == "child":
        return RecordFactory(
            scheme=scheme,
            data=labelled(label, statements={"skos:broader": [{"@id": parent.uri}]}),
            **kwargs,
        )
    child = RecordFactory(scheme=scheme, label=label, **kwargs)
    parent.data.setdefault("skos:narrower", []).append({"@id": child.uri})
    parent.save()
    return child


class SpecimenFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Specimen` with a required concept."""

    class Meta:
        model = Specimen

    name = factory.Sequence(lambda n: f"Specimen {n}")
    rock_type = factory.SubFactory(RecordFactory)


class LocalityFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Locality`."""

    class Meta:
        model = Locality

    name = factory.Sequence(lambda n: f"Locality {n}")


class SampleFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Sample` with no concept attached."""

    class Meta:
        model = Sample

    name = factory.Sequence(lambda n: f"Sample {n}")


class ArtifactFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Artifact` with no concept attached."""

    class Meta:
        model = Artifact

    name = factory.Sequence(lambda n: f"Artifact {n}")


class DepositFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Deposit` with no concepts attached."""

    class Meta:
        model = Deposit

    name = factory.Sequence(lambda n: f"Deposit {n}")


class SurveyFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Survey` with no concepts attached."""

    class Meta:
        model = Survey

    name = factory.Sequence(lambda n: f"Survey {n}")


class OutcropFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Outcrop` with no concepts attached."""

    class Meta:
        model = Outcrop

    name = factory.Sequence(lambda n: f"Outcrop {n}")


class RockSampleFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.RockSample` with no concepts attached."""

    class Meta:
        model = RockSample

    name = factory.Sequence(lambda n: f"Rock sample {n}")


class FieldNoteFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.FieldNote` with no concepts attached."""

    class Meta:
        model = FieldNote

    name = factory.Sequence(lambda n: f"Field note {n}")


class PhotographFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Photograph` with no concepts attached."""

    class Meta:
        model = Photograph

    name = factory.Sequence(lambda n: f"Photograph {n}")


class BoreholeFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Borehole` with no concept attached."""

    class Meta:
        model = Borehole

    name = factory.Sequence(lambda n: f"Borehole {n}")


class SketchFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Sketch` with no concept attached."""

    class Meta:
        model = Sketch

    name = factory.Sequence(lambda n: f"Sketch {n}")


class FossilFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Fossil` with no concept attached."""

    class Meta:
        model = Fossil

    name = factory.Sequence(lambda n: f"Fossil {n}")


class CoreSampleFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.CoreSample` with no concept attached."""

    class Meta:
        model = CoreSample

    name = factory.Sequence(lambda n: f"Core sample {n}")


class DrillCoreFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.DrillCore` with no concepts attached."""

    class Meta:
        model = DrillCore

    name = factory.Sequence(lambda n: f"Drill core {n}")


class IgneousLogFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.IgneousLog` with no concepts attached."""

    class Meta:
        model = IgneousLog

    name = factory.Sequence(lambda n: f"Igneous log {n}")
