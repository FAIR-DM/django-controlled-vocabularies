"""Models that carry concept fields, for the test project to consume."""

from pathlib import Path

from django.db import models
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies.fields import ConceptField, MultiConceptField, Vocabulary

FIXTURES = Path(__file__).parent.parent / "fixtures" / "skos"

# Published under the addresses the test settings compose for a vocabulary named "Rock Type"
# or "Mineral", so a factory-built vocabulary and the shipped file are the same vocabulary.
ROCK_TYPE = Vocabulary(
    "https://example.org/vocabularies/rock-type", source=FIXTURES / "rock-type.ttl"
)
MINERAL = Vocabulary(
    "https://example.org/vocabularies/mineral", source=FIXTURES / "mineral.ttl"
)
CORE_SAMPLES = "https://example.org/vocabularies/rock-type/collection/core-samples"
# Named only by the abstract models below.
ERA = Vocabulary("https://example.org/vocabularies/era", source=FIXTURES / "era.ttl")
UNUSED = "https://example.org/vocabularies/unused"


class Specimen(models.Model):
    """Carry a required concept from the "rock-type" vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The specimen's catalogue name."),
    )
    rock_type = ConceptField(
        vocabulary=ROCK_TYPE,
        verbose_name=_("rock type"),
        help_text=_("The rock type this specimen is classified as."),
    )
    locality = models.ForeignKey(
        "Locality",
        null=True,
        blank=True,
        related_name="specimens",
        on_delete=models.CASCADE,
        verbose_name=_("locality"),
        help_text=_("The locality where this specimen was collected, if recorded."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Sample(models.Model):
    """Carry an optional concept from the "mineral" vocabulary, with a reverse accessor."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The sample's catalogue name."),
    )
    mineral = ConceptField(
        vocabulary=MINERAL,
        null=True,
        blank=True,
        related_name="samples",
        verbose_name=_("mineral"),
        help_text=_("The mineral this sample is classified as, if known."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Artifact(models.Model):
    """Carry an optional "mineral" concept on a model that defines ``get_mineral_label()`` itself."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The artifact's catalogue name."),
    )
    mineral = ConceptField(
        vocabulary=MINERAL,
        null=True,
        blank=True,
        verbose_name=_("mineral"),
        help_text=_("The mineral this artifact is classified as, if known."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name

    def get_mineral_label(self) -> str:
        """Return a label of the artifact's own."""
        # Pre-existing on purpose: the field's generated getter must not overwrite it.
        return "this artifact's own label, not the field's"


class Deposit(models.Model):
    """Carry a required ``MultiConceptField`` against the "rock-type" vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The deposit's catalogue name."),
    )
    rock_types = MultiConceptField(
        vocabulary=ROCK_TYPE,
        verbose_name=_("rock types"),
        help_text=_("The rock types present at this deposit."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Survey(models.Model):
    """Carry two required ``MultiConceptField``s against the same vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The survey's catalogue name."),
    )
    primary_minerals = MultiConceptField(
        vocabulary=MINERAL,
        related_name="+",
        verbose_name=_("primary minerals"),
        help_text=_("The minerals this survey primarily targets."),
    )
    secondary_minerals = MultiConceptField(
        vocabulary=MINERAL,
        related_name="+",
        verbose_name=_("secondary minerals"),
        help_text=_("The minerals this survey secondarily targets."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Outcrop(models.Model):
    """Carry an optional ``MultiConceptField`` against the "mineral" vocabulary, with a reverse accessor."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The outcrop's catalogue name."),
    )
    minerals = MultiConceptField(
        vocabulary=MINERAL,
        blank=True,
        related_name="outcrops",
        verbose_name=_("minerals"),
        help_text=_("The minerals observed at this outcrop, if any."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class RockSample(models.Model):
    """Carry a ``ConceptField`` and a ``MultiConceptField`` against the same "mineral" vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The rock sample's catalogue name."),
    )
    primary_mineral = ConceptField(
        vocabulary=MINERAL,
        null=True,
        blank=True,
        verbose_name=_("primary mineral"),
        help_text=_(
            "The single mineral this sample is primarily classified as, if known."
        ),
    )
    associated_minerals = MultiConceptField(
        vocabulary=MINERAL,
        blank=True,
        related_name="+",
        verbose_name=_("associated minerals"),
        help_text=_("Any additional minerals observed in this sample."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class FieldNote(models.Model):
    """Carry a ``MultiConceptField`` naming two vocabularies."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The field note's catalogue name."),
    )
    keywords = MultiConceptField(
        vocabulary=[ROCK_TYPE, MINERAL],
        blank=True,
        related_name="+",
        verbose_name=_("keywords"),
        help_text=_(
            "Keywords drawn from either the rock-type or the mineral vocabulary."
        ),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Borehole(models.Model):
    """Carry a ``ConceptField`` naming two vocabularies."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The borehole's catalogue name."),
    )
    dominant_material = ConceptField(
        vocabulary=[ROCK_TYPE, MINERAL],
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("dominant material"),
        help_text=_(
            "The material logged as dominant, from either the rock-type or the mineral vocabulary."
        ),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Sketch(models.Model):
    """Carry a ``ConceptField`` naming no vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The sketch's catalogue name."),
    )
    subject = ConceptField(
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("subject"),
        help_text=_(
            "The sketch's subject, drawn from any vocabulary; this field names none in particular."
        ),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Photograph(models.Model):
    """Carry a ``MultiConceptField`` naming no vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The photograph's catalogue name."),
    )
    keywords = MultiConceptField(
        blank=True,
        related_name="+",
        verbose_name=_("keywords"),
        help_text=_(
            "Keywords drawn from any vocabulary; this field names none in particular."
        ),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class CoreSample(models.Model):
    """Carry an optional ``ConceptField`` restricted to a collection of the "rock-type" vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The core sample's catalogue name."),
    )
    rock_type = ConceptField(
        vocabulary=ROCK_TYPE,
        collection=CORE_SAMPLES,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("rock type"),
        help_text=_(
            "The rock type this core sample is classified as, drawn from the core-samples collection."
        ),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class DrillCore(models.Model):
    """Carry an optional ``MultiConceptField`` restricted to a collection, with a reverse accessor."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The drill core's catalogue name."),
    )
    rock_types = MultiConceptField(
        vocabulary=ROCK_TYPE,
        collection=CORE_SAMPLES,
        blank=True,
        related_name="drill_cores",
        verbose_name=_("rock types"),
        help_text=_(
            "The rock types logged for this drill core, drawn from the core-samples collection."
        ),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Locality(models.Model):
    """The parent of :class:`Specimen` in the inline relationship, carrying its own concept field."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The locality's catalogue name."),
    )
    primary_mineral = ConceptField(
        vocabulary=MINERAL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("primary mineral"),
        help_text=_(
            "The mineral this locality is primarily characterised by, if known."
        ),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Dated(models.Model):
    """An abstract model of the kind a reusable app ships, naming a vocabulary with its source."""

    era = ConceptField(
        vocabulary=ERA,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("era"),
        help_text=_("The era this record dates from, if known."),
    )

    class Meta:
        abstract = True


class Fossil(Dated):
    """Inherit the ``era`` field from :class:`Dated`."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The fossil's catalogue name."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Undated(models.Model):
    """An abstract model nothing inherits, naming a vocabulary no concrete model names."""

    era = ConceptField(
        vocabulary=UNUSED,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("era"),
        help_text=_("The era this record dates from, if known."),
    )

    class Meta:
        abstract = True
