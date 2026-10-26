"""Model fields that attach concepts to a consuming model."""

from functools import partial
from typing import TYPE_CHECKING, ClassVar

from django.core.exceptions import ValidationError
from django.db.models import CASCADE, PROTECT, ForeignKey, ManyToManyField, Model, Q
from django.db.models.fields.related import lazy_related_operation, resolve_relation
from django.db.models.fields.related_descriptors import ManyToManyDescriptor
from django.db.models.signals import m2m_changed
from django.db.models.utils import make_model_tuple
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django_stubs_ext import StrOrPromise


class ConceptFieldMixin:
    """The ``vocabulary`` and ``collection`` contract shared by both concept fields.

    Holds what the two arguments accept, the ``limit_choices_to`` derived from them and how
    they survive :meth:`deconstruct`. Declare it before the Django field in the bases so
    ``deconstruct()``'s ``super()`` reaches the Django field's own.
    """

    #: Static, because ``%`` on a lazy string would evaluate it immediately and lose
    #: per-request translation. Annotated because a lazy proxy is not a ``str``.
    default_help_text: str | Promise | None = None
    default_restricted_help_text: str | Promise | None = None

    default_error_messages: ClassVar[dict[str, "StrOrPromise"]] = {
        "invalid": _(
            "%(value)s is not a valid concept in the '%(vocabulary)s' vocabulary."
        ),
        "invalid_unrestricted": _("%(value)s is not a valid concept."),
        "invalid_restricted": _(
            "%(value)s is not a valid concept in the '%(restriction)s' collection."
        ),
    }

    def normalise_vocabulary(self, vocabulary):
        """Normalise a ``vocabulary`` argument to a tuple of distinct slugs.

        Args:
            vocabulary: One slug, an iterable of slugs, or ``None`` for no restriction.

        Returns:
            The slugs in declaration order with duplicates removed; empty for ``None``.

        Raises:
            TypeError: An element is not a non-empty string.
        """
        if vocabulary is None:
            slugs = ()
        elif isinstance(vocabulary, str):
            slugs = (vocabulary,)
        else:
            slugs = tuple(vocabulary)
        for slug in slugs:
            if not isinstance(slug, str) or not slug:
                raise TypeError(
                    f"{type(self).__name__}() vocabulary elements must be non-empty strings; got {slug!r}."
                )
        return tuple(dict.fromkeys(slugs))

    def apply_collection(self, collection):
        """Validate the ``collection`` restriction and store it as ``self.collection``.

        Must run after ``self.vocabulary`` is set.

        Args:
            collection: Slug of a collection the choices are limited to, or ``None``.

        Raises:
            TypeError: ``collection`` is not a non-empty string, or the declaration does
                not name exactly one vocabulary.
        """
        if collection is not None:
            if not isinstance(collection, str) or not collection:
                raise TypeError(
                    f"{type(self).__name__}() collection must be a non-empty string; got {collection!r}."
                )
            if len(self.vocabulary) != 1:
                raise TypeError(
                    f"{type(self).__name__}() a collection restriction requires the "
                    f"declaration to name exactly one vocabulary; got {len(self.vocabulary)}."
                )
        self.collection = collection

    def resolve_restriction(self):
        """Return the ``Q`` that limits the field's choices, resolved at call time.

        Installed as ``limit_choices_to``, so it is evaluated when a value is validated,
        a form is built, the widget renders or a search runs, never while the declaration
        is only being read.

        Returns:
            A ``Q`` over ``Record``.
        """
        # Deferred import: this runs only after every app's models have loaded.
        from .models import Record

        restriction = Q(type=Record.Type.CONCEPT)
        if self.vocabulary:
            restriction &= Q(scheme__slug__in=self.vocabulary)
        if self.collection is not None:
            (vocabulary,) = self.vocabulary
            collection = Record.objects.filter(
                scheme__slug=vocabulary,
                slug=self.collection,
                type__in=Record.COLLECTION_TYPES,
            ).first()
            restriction &= Q(uri__in=collection.member_uris() if collection else [])
        return restriction

    def refusal(self, value):
        """Build the error for a concept the restriction does not admit.

        Args:
            value: The refused value, as the message should show it.

        Returns:
            The message key, with the parameters its message needs.
        """
        if self.collection is not None:
            return "invalid_restricted", {
                "value": value,
                "restriction": self.collection,
            }
        if self.vocabulary:
            return "invalid", {"value": value, "vocabulary": ", ".join(self.vocabulary)}
        return "invalid_unrestricted", {"value": value}

    def apply_vocabulary(self, vocabulary, collection, kwargs):
        """Store the normalised ``vocabulary`` and restriction, and fill in the kwargs they decide.

        Args:
            vocabulary: One slug, an iterable of slugs, or ``None``.
            collection: Collection restriction, or ``None``.
            kwargs: The field's remaining keyword arguments, updated in place.

        Returns:
            ``kwargs``, now carrying ``to``, ``limit_choices_to`` and ``help_text``.

        Raises:
            TypeError: The consumer supplied ``limit_choices_to``, or the declaration breaks a
                restriction rule.
        """
        if "limit_choices_to" in kwargs:
            raise TypeError(
                f"{type(self).__name__}() sets limit_choices_to itself to constrain choices "
                "to 'vocabulary'; a consumer may not override it."
            )
        self.vocabulary = self.normalise_vocabulary(vocabulary)
        self.apply_collection(collection)
        kwargs["to"] = "controlled_vocabularies.Record"
        kwargs["limit_choices_to"] = self.resolve_restriction
        kwargs.setdefault(
            "help_text",
            self.default_help_text
            if self.collection is None
            else self.default_restricted_help_text,
        )
        return kwargs

    def contribute_accessor(self, cls, attr_name, accessor):
        """Add a derived read to the consuming model unless it already defines that name.

        Args:
            cls: The consuming model class.
            attr_name: The name to add.
            accessor: The function to add under that name.
        """
        if not hasattr(cls, attr_name):
            setattr(cls, attr_name, accessor)

    def formfield(self, **kwargs):
        """Return this package's search-as-you-type form field."""
        # Deferred: forms.py imports models, which may not be loaded when this module is.
        from .forms import ConceptChoiceField, ConceptsChoiceField

        kwargs["model_field"] = self
        kwargs.setdefault(
            "form_class",
            ConceptsChoiceField
            if isinstance(self, ManyToManyField)
            else ConceptChoiceField,
        )
        return super().formfield(**kwargs)

    def deconstruct(self):
        """Record ``vocabulary`` and ``collection`` instead of the kwargs this package fixes."""
        # Field.clone() rebuilds from these kwargs, so they must be ones __init__ accepts.
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("to", None)
        kwargs.pop("on_delete", None)
        kwargs.pop("limit_choices_to", None)
        kwargs["vocabulary"] = self.vocabulary
        if self.collection is not None:
            kwargs["collection"] = self.collection
        return name, path, args, kwargs


class ConceptField(ConceptFieldMixin, ForeignKey):
    """A ``ForeignKey`` to ``controlled_vocabularies.Record``, limited to concepts of named vocabularies.

    ``to`` is always the string ``"controlled_vocabularies.Record"`` and ``on_delete``
    is always ``PROTECT``, so a concept a row holds cannot be deleted. The consumer
    supplies neither, nor ``limit_choices_to``, which is derived from the arguments below.

    Args:
        vocabulary: One vocabulary slug, several, or ``None`` for no restriction.
        collection: Limit choices to the members of this collection. Needs exactly one vocabulary.
        **kwargs: Passed to ``ForeignKey``.

    Raises:
        TypeError: The consumer supplied ``on_delete``, ``limit_choices_to`` or an invalid restriction.
    """

    default_help_text = _(
        "A concept from this field's configured vocabulary or vocabularies."
    )
    default_restricted_help_text = _(
        "A concept from a restricted part of this field's configured vocabulary."
    )

    def __init__(self, vocabulary=None, collection=None, **kwargs):
        if "on_delete" in kwargs:
            raise TypeError(
                "ConceptField() sets on_delete=PROTECT itself; a consumer may not override it."
            )
        kwargs["on_delete"] = PROTECT
        super().__init__(**self.apply_vocabulary(vocabulary, collection, kwargs))

    def validate(self, value, model_instance):
        """Refuse a concept outside the restriction, naming what decided the refusal."""
        # ForeignKey.validate() raises without `vocabulary` or `restriction` in params, and
        # ValidationError interpolates lazily, so those placeholders would raise KeyError on read.
        try:
            super().validate(value, model_instance)
        except ValidationError as exc:
            if exc.code != "invalid":
                raise
            key, params = self.refusal(value)
            # Keep the ForeignKey's own params: a consumer's message may use `model`, `pk` or `field`.
            raise ValidationError(
                self.error_messages[key],
                code="invalid",
                params={**(exc.params or {}), **params},
            ) from exc

    def contribute_to_class(self, cls, name, private_only=False, **kwargs):
        """Add ``get_<name>_label()`` and ``get_<name>_uri()`` to the consuming model."""
        super().contribute_to_class(cls, name, private_only=private_only, **kwargs)

        # Three-arg getattr: RelatedObjectDoesNotExist, raised for a required field with nothing
        # attached, subclasses AttributeError, so the default turns it back into None.
        def get_label(instance):
            """Return the attached concept's display label.

            Args:
                instance: The consuming model instance.

            Returns:
                The label, or ``None`` when no concept is attached.
            """
            concept = getattr(instance, name, None)
            return concept.display_label() if concept is not None else None

        def get_uri(instance):
            """Return the attached concept's URI.

            Args:
                instance: The consuming model instance.

            Returns:
                The URI, or ``None`` when no concept is attached.
            """
            concept = getattr(instance, name, None)
            return concept.uri if concept is not None else None

        self.contribute_accessor(cls, f"get_{name}_label", get_label)
        self.contribute_accessor(cls, f"get_{name}_uri", get_uri)


def create_membership_model(field, cls):
    """Build the through model for a :class:`ConceptsField`.

    Args:
        field: The field the model is generated for.
        cls: The consuming model class that owns ``field``.

    Returns:
        The generated model class.
    """

    def set_managed(model, related, through):
        """Copy the managed flag from the two related models onto the through model."""
        through._meta.managed = model._meta.managed or related._meta.managed

    to_model = resolve_relation(cls, field.remote_field.model)
    name = f"{cls._meta.object_name}_{field.name}"
    lazy_related_operation(set_managed, cls, to_model, name)

    to = make_model_tuple(to_model)[1]
    from_ = cls._meta.model_name
    if to == from_:
        to = f"to_{to}"
        from_ = f"from_{from_}"

    # Mirrors Django's create_many_to_many_intermediary_model, except the foreign key to the
    # concept is PROTECT (FS-010). auto_created keeps the model out of migration state and deconstruct().
    meta = type(
        "Meta",
        (),
        {
            "db_table": field._get_m2m_db_table(cls._meta),
            "auto_created": cls,
            "app_label": cls._meta.app_label,
            "db_tablespace": cls._meta.db_tablespace,
            "unique_together": (from_, to),
            "verbose_name": _("%(from)s-%(to)s relationship")
            % {"from": from_, "to": to},
            "verbose_name_plural": _("%(from)s-%(to)s relationships")
            % {"from": from_, "to": to},
            "apps": field.model._meta.apps,
        },
    )
    return type(
        name,
        (Model,),
        {
            "Meta": meta,
            "__module__": cls.__module__,
            from_: ForeignKey(
                cls,
                related_name=f"{name}+",
                db_tablespace=field.db_tablespace,
                db_constraint=field.remote_field.db_constraint,
                on_delete=CASCADE,
            ),
            to: ForeignKey(
                to_model,
                related_name=f"{name}+",
                db_tablespace=field.db_tablespace,
                db_constraint=field.remote_field.db_constraint,
                on_delete=PROTECT,
            ),
        },
    )


def refuse_concepts_the_restriction_does_not_admit(
    *, field, instance, action, reverse, model, pk_set, **kwargs
) -> None:
    """Refuse a write that attaches a concept the field's restriction does not admit.

    An ``m2m_changed`` receiver bound to a :class:`ConceptsField`'s through model.
    Only ``pre_add`` is checked. Both directions are checked, so
    ``concept.deposit_set.add(deposit)`` is refused on the same terms as
    ``deposit.rock_types.add(concept)``. Raising aborts the whole write before any row is inserted.

    Args:
        field: The :class:`ConceptsField` whose restriction applies.
        instance: The row the write was made on.
        action: The ``m2m_changed`` action.
        reverse: Whether the write was made from the record side.
        model: The class of the rows being added.
        pk_set: Primary keys of the rows being added.
        **kwargs: Other ``m2m_changed`` arguments, ignored.

    Raises:
        ValidationError: An incoming concept falls outside the restriction.
    """
    if action != "pre_add":
        return
    restriction = field.get_limit_choices_to()
    # On a reverse write pk_set holds the owner's keys and `instance` is the concept, so `model`
    # is the wrong class to query.
    if reverse:
        invalid = (
            []
            if type(instance)
            .objects.filter(pk=instance.pk)
            .filter(restriction)
            .exists()
            else [instance]
        )
    else:
        invalid = list(model.objects.filter(pk__in=pk_set).exclude(restriction))
    if not invalid:
        return
    key, params = field.refusal(", ".join(str(concept) for concept in invalid))
    raise ValidationError(field.error_messages[key], code="invalid", params=params)


class ConceptsField(ConceptFieldMixin, ManyToManyField):
    """A ``ManyToManyField`` to ``controlled_vocabularies.Record``, limited to concepts of named vocabularies.

    The generated through model protects its concepts from deletion, so ``through`` is
    not the consumer's to supply, nor are ``to`` and ``limit_choices_to``. Takes the
    same arguments as :class:`ConceptField`.

    Args:
        vocabulary: One vocabulary slug, several, or ``None`` for no restriction.
        collection: Limit choices to the members of this collection. Needs exactly one vocabulary.
        **kwargs: Passed to ``ManyToManyField``.

    Raises:
        TypeError: The consumer supplied ``through``, ``limit_choices_to`` or an invalid restriction.
    """

    default_help_text = _(
        "Concepts from this field's configured vocabulary or vocabularies."
    )
    default_restricted_help_text = _(
        "Concepts from a restricted part of this field's configured vocabulary."
    )

    def __init__(self, vocabulary=None, collection=None, **kwargs):
        if "through" in kwargs:
            raise TypeError(
                "ConceptsField() generates its own through model with PROTECT on the "
                "foreign key to the concept; a consumer may not override it."
            )
        super().__init__(**self.apply_vocabulary(vocabulary, collection, kwargs))

    def contribute_to_class(self, cls, name, **kwargs):
        """Attach the field, generate its protected through model and add the label and URI accessors."""
        # Skipping ManyToManyField's own contribute_to_class avoids it registering a second
        # through model of the same name, so its hidden related_name rewrite is repeated here (FS-010).
        if self.remote_field.hidden:
            self.remote_field.related_name = (
                f"_{cls._meta.app_label}_{cls.__name__.lower()}_{name}_+"
            )
        super(ManyToManyField, self).contribute_to_class(cls, name, **kwargs)

        if not cls._meta.abstract and not cls._meta.swapped:
            self.remote_field.through = create_membership_model(self, cls)
            # Connected here so a declaration cannot exist without its guard: an auto_created
            # through model with no receiver takes bulk_create's fast path, which skips m2m_changed.
            # weak=False because the partial has no other reference to keep it alive.
            m2m_changed.connect(
                partial(refuse_concepts_the_restriction_does_not_admit, field=self),
                sender=self.remote_field.through,
                weak=False,
            )

            def get_labels(instance):
                """Return the display labels of the attached concepts.

                Args:
                    instance: The consuming model instance.

                Returns:
                    The labels, empty when the instance is unsaved.
                """
                if instance.pk is None:
                    return []
                return [
                    concept.display_label() for concept in getattr(instance, name).all()
                ]

            def get_uris(instance):
                """Return the URIs of the attached concepts.

                Args:
                    instance: The consuming model instance.

                Returns:
                    The URIs, empty when the instance is unsaved.
                """
                if instance.pk is None:
                    return []
                return [concept.uri for concept in getattr(instance, name).all()]

            self.contribute_accessor(cls, f"get_{name}_labels", get_labels)
            self.contribute_accessor(cls, f"get_{name}_uris", get_uris)

        setattr(cls, self.name, ManyToManyDescriptor(self.remote_field, reverse=False))
        self.m2m_db_table = partial(self._get_m2m_db_table, cls._meta)
