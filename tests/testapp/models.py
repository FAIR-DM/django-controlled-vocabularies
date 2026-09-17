"""Models exercising :class:`~controlled_vocabularies.fields.ConceptField`'s
and :class:`~controlled_vocabularies.fields.ConceptsField`'s public APIs.

Three models carry ``ConceptField`` (FS-009, T002), a different way US-1
through US-5 there need to test against:

- :class:`Specimen` — a required ``ConceptField``.
- :class:`Sample` — an optional ``ConceptField`` with a ``related_name``.
- :class:`Artifact` — an optional ``ConceptField`` on a model that already
  defines ``get_mineral_label`` itself, so US-5's ``contribute_to_class()``
  collision guard (T011) has a real pre-existing definition to leave alone
  rather than a synthetic one.

Two more carry ``ConceptField`` in the shapes #111 added to it, mirroring
``ConceptsField``'s own:

- :class:`Borehole` — a ``ConceptField`` naming two vocabularies.
- :class:`Sketch` — a ``ConceptField`` naming no vocabulary at all.

Six more models carry ``ConceptsField`` (FS-010 Phase F), one per shape
`tasks.md` T001 lists:

- :class:`Deposit` — a required ``ConceptsField`` (T003, T009's enforced
  half).
- :class:`Survey` — two required ``ConceptsField``s against the same
  vocabulary, both ``related_name="+"`` (T003, T009's enumeration case).
- :class:`Outcrop` — an optional ``ConceptsField`` with a ``related_name``
  (US-1's reverse accessor, US-5's permissive half).
- :class:`RockSample` — both a ``ConceptField`` and a ``ConceptsField``
  against the same vocabulary on one model, the collision case `plan.md`'s
  Risks section refuses to assume away.
- :class:`FieldNote` — a ``ConceptsField`` naming two vocabularies (T012).
- :class:`Photograph` — a ``ConceptsField`` naming no vocabulary at all — the
  keywords shape (T012).

:class:`Deposit` and :class:`Survey` were added in T003, since T003's own
acceptance needs a real declaration to test the generated membership model
against (`decisions.md` D10). The remaining four are T001's.

Two more carry a ``collection`` restriction (FS-016 US-1):

- :class:`CoreSample` — an optional ``ConceptField`` restricted to the
  "core-samples" collection within the "rock-type" vocabulary (T007, T009,
  T010, T011).
- :class:`DrillCore` — an optional ``ConceptsField`` restricted the same
  way, for the many-valued write guard (T012).

Two more carry a ``concepts`` restriction (FS-016 US-2):

- :class:`ChipSample` — an optional ``ConceptField`` restricted to the
  "granite" and "basalt" concepts of the "rock-type" vocabulary (T013,
  T014).
- :class:`ChipTray` — an optional ``ConceptsField`` restricted the same
  way, for the many-valued write guard (T013).

Two more carry a ``branch`` restriction (FS-016 US-3):

- :class:`BranchSample` — an optional ``ConceptField`` restricted to the
  "igneous" branch of the "rock-type" vocabulary's hierarchy (T017, T018).
- :class:`BranchTray` — an optional ``ConceptsField`` restricted the same
  way, for the many-valued write guard (T017).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from controlled_vocabularies.fields import ConceptField, ConceptsField


class Specimen(models.Model):
    """Carries a required concept from the "rock-type" vocabulary."""

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
        return self.name


class Sample(models.Model):
    """Carries an optional concept from the "mineral" vocabulary, with a
    reverse accessor (``mineral.samples``)."""

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
        return self.name


class Artifact(models.Model):
    """Carries an optional concept from the "mineral" vocabulary, on a model
    that already defines ``get_mineral_label()`` — the name US-5's
    ``contribute_to_class()`` (T011) would generate for a field named
    ``mineral``. The collision guard is tested against this real, pre-existing
    definition rather than a synthetic one.
    """

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
        return self.name

    def get_mineral_label(self) -> str:
        """Pre-existing — must survive T011's ``contribute_to_class()`` guard untouched."""
        return "this artifact's own label, not the field's"


class Deposit(models.Model):
    """Carries a required ``ConceptsField`` against the "rock-type" vocabulary
    (T003, T009's enforced half)."""

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
        return self.name


class Survey(models.Model):
    """Carries two required ``ConceptsField``s against the same vocabulary
    (T003, T009): one required field enforced and the other silently skipped
    is the failure T009's enumeration case exists to catch, and it needs two
    of them on one model to be visible at all. Both declare
    ``related_name="+"`` so T003's hidden related_name rewrite has two live
    fields that would otherwise clash to prove itself against."""

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
        return self.name


class Outcrop(models.Model):
    """Carries an optional ``ConceptsField`` against the "mineral" vocabulary,
    with a reverse accessor (``mineral.outcrops``) — US-1's reverse accessor
    and US-5's permissive half."""

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
        return self.name


class RockSample(models.Model):
    """Carries both a ``ConceptField`` and a ``ConceptsField`` against the
    same "mineral" vocabulary — the collision case `plan.md`'s Risks section
    refuses to assume away: two declarations on one model must generate
    distinct membership tables and non-clashing reverse accessors."""

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
        return self.name


class FieldNote(models.Model):
    """Carries a ``ConceptsField`` naming two vocabularies — "keywords from
    GCMD or AGU" is a boundary (`decisions.md` D9); here "rock-type" or
    "mineral" (T012)."""

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
        return self.name


class Borehole(models.Model):
    """Carries a ``ConceptField`` naming two vocabularies (#111) — the
    single-value counterpart of :class:`FieldNote`: one concept drawn from
    either of the schemes the project accepts."""

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
        return self.name


class Sketch(models.Model):
    """Carries a ``ConceptField`` naming no vocabulary at all (#111) — the
    single-value counterpart of :class:`Photograph`: the restriction is given
    up, the delete protection and the label/URI readback are not."""

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
        return self.name


class Photograph(models.Model):
    """Carries a ``ConceptsField`` naming no vocabulary at all — the keywords
    shape (T012, `decisions.md` D9): the restriction is given up, but the
    delete protection, the readback, and the required-set rule are not."""

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
        return self.name


class CoreSample(models.Model):
    """Carries an optional ``ConceptField`` restricted to the "core-samples"
    collection within the "rock-type" vocabulary (FS-016 US-1, T007, T009,
    T010, T011)."""

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
        return self.name


class DrillCore(models.Model):
    """Carries an optional ``ConceptsField`` restricted to the "core-samples"
    collection within the "rock-type" vocabulary (FS-016 US-1, T012's
    many-valued write guard). ``related_name`` is a real name, not ``"+"``,
    so T012 has a live reverse accessor (``concept.drill_cores``) to drive
    the reverse-write branch of the guard through, the way
    :class:`Outcrop`'s ``minerals``/``outcrops`` already does for the
    vocabulary-only case."""

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
        return self.name


class ChipSample(models.Model):
    """Carries an optional ``ConceptField`` restricted to the "granite" and
    "basalt" concepts of the "rock-type" vocabulary (FS-016 US-2, T013)."""

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
        return self.name


class ChipTray(models.Model):
    """Carries an optional ``ConceptsField`` restricted the same way, for the
    many-valued write guard (FS-016 US-2, T013). ``related_name`` is a real
    name, not ``"+"``, so the reverse-write branch of the guard has a live
    accessor (``concept.chip_trays``) to drive it through."""

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
        return self.name


class BranchSample(models.Model):
    """Carries an optional ``ConceptField`` restricted to the "igneous"
    branch of the "rock-type" vocabulary's hierarchy (FS-016 US-3, T017).
    The concept named "igneous" and everything narrower than it are built
    per test, through ``add_broader()`` — this declaration only names the
    root, exactly as ``CoreSample`` and ``ChipSample`` only name a
    collection or a concept list without knowing its members."""

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
        return self.name


class BranchTray(models.Model):
    """Carries an optional ``ConceptsField`` restricted the same way, for the
    many-valued write guard (FS-016 US-3, T017). ``related_name`` is a real
    name, not ``"+"``, so the reverse-write branch of the guard has a live
    accessor (``concept.branch_trays``) to drive it through."""

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
        return self.name


class Locality(models.Model):
    """The parent side of the inline relationship US-3 (T008) exercises:
    :class:`Specimen` rows may belong to one, through the ``locality`` foreign
    key added there. Carries its own ``ConceptField`` against a vocabulary
    distinct from ``Specimen.rock_type``, so a saved inline row's own
    autocomplete reference can be told apart from the parent form's own field
    (spec.md US-3 scenario 4)."""

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
        return self.name
