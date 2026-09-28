"""Models that carry concept fields, for the test project to consume."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies.fields import ConceptField, ConceptsField


class Specimen(models.Model):
    """Carry a required concept from the "rock-type" vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The specimen's catalogue name."),
    )
    rock_type = ConceptField(
        vocabulary="rock-type",
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
        vocabulary="mineral",
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
        vocabulary="mineral",
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
    """Carry a required ``ConceptsField`` against the "rock-type" vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The deposit's catalogue name."),
    )
    rock_types = ConceptsField(
        vocabulary="rock-type",
        verbose_name=_("rock types"),
        help_text=_("The rock types present at this deposit."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Survey(models.Model):
    """Carry two required ``ConceptsField``s against the same vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The survey's catalogue name."),
    )
    primary_minerals = ConceptsField(
        vocabulary="mineral",
        related_name="+",
        verbose_name=_("primary minerals"),
        help_text=_("The minerals this survey primarily targets."),
    )
    secondary_minerals = ConceptsField(
        vocabulary="mineral",
        related_name="+",
        verbose_name=_("secondary minerals"),
        help_text=_("The minerals this survey secondarily targets."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class Outcrop(models.Model):
    """Carry an optional ``ConceptsField`` against the "mineral" vocabulary, with a reverse accessor."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The outcrop's catalogue name."),
    )
    minerals = ConceptsField(
        vocabulary="mineral",
        blank=True,
        related_name="outcrops",
        verbose_name=_("minerals"),
        help_text=_("The minerals observed at this outcrop, if any."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class RockSample(models.Model):
    """Carry a ``ConceptField`` and a ``ConceptsField`` against the same "mineral" vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The rock sample's catalogue name."),
    )
    primary_mineral = ConceptField(
        vocabulary="mineral",
        null=True,
        blank=True,
        verbose_name=_("primary mineral"),
        help_text=_(
            "The single mineral this sample is primarily classified as, if known."
        ),
    )
    associated_minerals = ConceptsField(
        vocabulary="mineral",
        blank=True,
        related_name="+",
        verbose_name=_("associated minerals"),
        help_text=_("Any additional minerals observed in this sample."),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class FieldNote(models.Model):
    """Carry a ``ConceptsField`` naming two vocabularies."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The field note's catalogue name."),
    )
    keywords = ConceptsField(
        vocabulary=["rock-type", "mineral"],
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
        vocabulary=["rock-type", "mineral"],
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
    """Carry a ``ConceptsField`` naming no vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The photograph's catalogue name."),
    )
    keywords = ConceptsField(
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
        vocabulary="rock-type",
        collection="core-samples",
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
    """Carry an optional ``ConceptsField`` restricted to a collection, with a reverse accessor."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The drill core's catalogue name."),
    )
    rock_types = ConceptsField(
        vocabulary="rock-type",
        collection="core-samples",
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


class ChipSample(models.Model):
    """Carry an optional ``ConceptField`` restricted to two named concepts of the "rock-type" vocabulary."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The chip sample's catalogue name."),
    )
    rock_type = ConceptField(
        vocabulary="rock-type",
        concepts=["granite", "basalt"],
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("rock type"),
        help_text=_(
            "The rock type this chip sample is classified as, restricted to granite and basalt."
        ),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class ChipTray(models.Model):
    """Carry an optional ``ConceptsField`` restricted to two named concepts, with a reverse accessor."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The chip tray's catalogue name."),
    )
    rock_types = ConceptsField(
        vocabulary="rock-type",
        concepts=["granite", "basalt"],
        blank=True,
        related_name="chip_trays",
        verbose_name=_("rock types"),
        help_text=_(
            "The rock types logged for this chip tray, restricted to granite and basalt."
        ),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class BranchSample(models.Model):
    """Carry an optional ``ConceptField`` restricted to a branch of the "rock-type" hierarchy."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The branch sample's catalogue name."),
    )
    rock_type = ConceptField(
        vocabulary="rock-type",
        branch="igneous",
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("rock type"),
        help_text=_(
            "The rock type this sample is classified as, drawn from the igneous branch."
        ),
    )

    def __str__(self) -> str:
        """Return the name."""
        return self.name


class BranchTray(models.Model):
    """Carry an optional ``ConceptsField`` restricted to a branch, with a reverse accessor."""

    name = models.CharField(
        max_length=255,
        verbose_name=_("name"),
        help_text=_("The branch tray's catalogue name."),
    )
    rock_types = ConceptsField(
        vocabulary="rock-type",
        branch="igneous",
        blank=True,
        related_name="branch_trays",
        verbose_name=_("rock types"),
        help_text=_(
            "The rock types logged for this tray, drawn from the igneous branch."
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
        vocabulary="mineral",
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
