"""factory_boy factories for the vocabulary and test-app models."""

import factory
from django.utils.text import slugify

from controlled_vocabularies.models import (
    Collection,
    CollectionMember,
    Concept,
    ConceptLabel,
    ConceptNote,
    ConceptRelation,
    ConceptScheme,
)
from tests.testapp.models import (
    Artifact,
    Borehole,
    BranchSample,
    BranchTray,
    ChipSample,
    ChipTray,
    CoreSample,
    Deposit,
    DrillCore,
    FieldNote,
    Locality,
    Outcrop,
    Photograph,
    RockSample,
    Sample,
    Sketch,
    Specimen,
    Survey,
)


class ConceptSchemeFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`ConceptScheme` with an app-wide-unique name."""

    class Meta:
        model = ConceptScheme

    name = factory.Sequence(lambda n: f"Vocabulary {n}")
    # Derived here as well as in save(), so an unsaved .build() scheme has the slug it
    # would get once saved. A blank slug makes any URL reversal against it raise
    # NoReverseMatch.
    slug = factory.LazyAttribute(
        lambda scheme: slugify(scheme.name, allow_unicode=True)
    )

    class Params:
        external = factory.Trait(
            static_uri=factory.Sequence(
                lambda n: f"http://publisher.example.org/vocab/{n}"
            ),
        )


class ConceptFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`Concept`, auto-creating its owning scheme."""

    class Meta:
        model = Concept

    scheme = factory.SubFactory(ConceptSchemeFactory)
    label = factory.Sequence(lambda n: f"Concept {n}")

    class Params:
        external = factory.Trait(
            static_uri=factory.Sequence(
                lambda n: f"http://publisher.example.org/concept/{n}"
            ),
        )
        multilingual = factory.Trait(
            # The en preferred label is ``label`` above; de is a real ConceptLabel row,
            # because the field owns only the default language.
            german_label=factory.RelatedFactory(
                "tests.factories.ConceptLabelFactory",
                factory_related_name="concept",
                language="de",
                kind=ConceptLabel.Kind.PREFERRED,
                text=factory.Sequence(lambda n: f"Konzept {n}"),
            ),
            english_note=factory.RelatedFactory(
                "tests.factories.ConceptNoteFactory",
                factory_related_name="concept",
                language="en",
                kind=ConceptNote.Kind.DEFINITION,
                value=factory.Sequence(lambda n: f"Definition {n}"),
            ),
            german_note=factory.RelatedFactory(
                "tests.factories.ConceptNoteFactory",
                factory_related_name="concept",
                language="de",
                kind=ConceptNote.Kind.DEFINITION,
                value=factory.Sequence(lambda n: f"Definition {n}"),
            ),
        )


class ConceptLabelFactory(factory.django.DjangoModelFactory):
    """Build a saved German preferred :class:`ConceptLabel` on an auto-created concept."""

    class Meta:
        model = ConceptLabel

    concept = factory.SubFactory(ConceptFactory)
    language = "de"
    kind = ConceptLabel.Kind.PREFERRED
    text = factory.Sequence(lambda n: f"Label {n}")


class ConceptNoteFactory(factory.django.DjangoModelFactory):
    """Build a saved English definition :class:`ConceptNote` on an auto-created concept."""

    class Meta:
        model = ConceptNote

    concept = factory.SubFactory(ConceptFactory)
    language = "en"
    kind = ConceptNote.Kind.DEFINITION
    value = factory.Sequence(lambda n: f"Definition {n}")


class ConceptRelationFactory(factory.django.DjangoModelFactory):
    """Build a saved broader :class:`ConceptRelation` between two concepts of one scheme."""

    class Meta:
        model = ConceptRelation

    source = factory.SubFactory(ConceptFactory)
    target = factory.SubFactory(
        ConceptFactory, scheme=factory.SelfAttribute("..source.scheme")
    )
    kind = ConceptRelation.Kind.BROADER


def relation_graph(scheme=None):
    """Build a small navigable graph in one vocabulary and return its concepts.

    A broader/narrower pair (``child`` under ``parent``) and a separate related pair
    (``left`` and ``right``), built through ``add_broader`` and ``add_related``.

    Args:
        scheme: The scheme to build the graph in. A new one is created when omitted.

    Returns:
        A dict with keys ``scheme``, ``parent``, ``child``, ``left`` and ``right``.
    """
    scheme = scheme or ConceptSchemeFactory()
    parent = ConceptFactory(scheme=scheme)
    child = ConceptFactory(scheme=scheme)
    left = ConceptFactory(scheme=scheme)
    right = ConceptFactory(scheme=scheme)
    child.add_broader(parent)
    left.add_related(right)
    return {
        "scheme": scheme,
        "parent": parent,
        "child": child,
        "left": left,
        "right": right,
    }


class CollectionFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`Collection`, auto-creating its owning scheme."""

    class Meta:
        model = Collection

    scheme = factory.SubFactory(ConceptSchemeFactory)
    name = factory.Sequence(lambda n: f"Collection {n}")

    class Params:
        external = factory.Trait(
            static_uri=factory.Sequence(
                lambda n: f"http://publisher.example.org/collection/{n}"
            ),
        )


class CollectionMemberFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`CollectionMember` joining a collection to a concept of its scheme."""

    class Meta:
        model = CollectionMember

    collection = factory.SubFactory(CollectionFactory)
    concept = factory.SubFactory(
        ConceptFactory, scheme=factory.SelfAttribute("..collection.scheme")
    )


def collection_with_members(
    scheme=None, labels=("Granite", "Basalt", "Gabbro"), ordered=False, name=None
):
    """Build a collection populated with concepts and return it with its members.

    The concepts are created in the collection's own scheme and added through
    :meth:`Collection.add`, so validation and, for an ordered collection, positions apply.

    Args:
        scheme: The scheme to build in. A new one is created when omitted.
        labels: The label of each concept to create, in the order they are added.
        ordered: Build an ordered collection.
        name: The collection's name. Leave it out for the factory's own sequence, and pass
            it when a consuming model's ``collection=`` restriction has to name its slug.

    Returns:
        A ``(collection, members)`` tuple, ``members`` being the concepts in the order
        they were added.
    """
    scheme = scheme or ConceptSchemeFactory()
    collection = CollectionFactory(
        scheme=scheme, ordered=ordered, **({"name": name} if name is not None else {})
    )
    members = [ConceptFactory(scheme=scheme, label=label) for label in labels]
    for concept in members:
        collection.add(concept)
    return collection, members


class SpecimenFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.Specimen` with a required concept."""

    class Meta:
        model = Specimen

    name = factory.Sequence(lambda n: f"Specimen {n}")
    rock_type = factory.SubFactory(ConceptFactory)


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


class ChipSampleFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.ChipSample` with no concept attached."""

    class Meta:
        model = ChipSample

    name = factory.Sequence(lambda n: f"Chip sample {n}")


class ChipTrayFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.ChipTray` with no concepts attached."""

    class Meta:
        model = ChipTray

    name = factory.Sequence(lambda n: f"Chip tray {n}")


class BranchSampleFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.BranchSample` with no concept attached."""

    class Meta:
        model = BranchSample

    name = factory.Sequence(lambda n: f"Branch sample {n}")


class BranchTrayFactory(factory.django.DjangoModelFactory):
    """Build a saved :class:`~tests.testapp.models.BranchTray` with no concepts attached."""

    class Meta:
        model = BranchTray

    name = factory.Sequence(lambda n: f"Branch tray {n}")
