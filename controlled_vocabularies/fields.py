"""Model fields that attach concepts to a consuming model."""

import os
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlsplit

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

__all__ = [
    "ConceptField",
    "ConceptFieldMixin",
    "MultiConceptField",
    "Vocabulary",
]


def require_uri(value, owner, argument):
    """Refuse a value that is not an absolute URI.

    Args:
        value: The value to check.
        owner: The name of the class it was passed to, for the message.
        argument: The argument it was passed as, for the message.

    Raises:
        TypeError: ``value`` is not a string, or names no scheme. A one-character scheme
            is a Windows drive letter, not a URI scheme.
    """
    if not isinstance(value, str) or len(urlsplit(value).scheme) <= 1:
        raise TypeError(
            f"{owner}() {argument} must be a URI; got {value!r}. Name a vocabulary, "
            "collection or branch by its URI, not by its slug."
        )


@dataclass(frozen=True)
class Vocabulary:
    """A vocabulary a concept field names: its URI, and where it is published.

    ``manage.py sync_vocabularies`` loads every vocabulary a concept field names. It
    reads one from ``source`` when given, and from ``uri`` itself otherwise.

    Args:
        uri: The URI the vocabulary's concept scheme is published under.
        source: A local path or an http(s) address the vocabulary can be read from.
        format: The serialization ``source`` is in, when its name or the server does
            not say.

    Raises:
        TypeError: ``uri`` is not an absolute URI.
    """

    uri: str
    source: str | os.PathLike | None = None
    format: str | None = None

    def __post_init__(self):
        require_uri(self.uri, type(self).__name__, "uri")


class ConceptFieldMixin:
    """The ``vocabulary``, ``collection`` and ``branch`` contract shared by both concept fields.

    Holds what the two arguments accept, the ``limit_choices_to`` derived from them and
    how they survive :meth:`deconstruct`. Declare it before the Django field in the
    bases so ``deconstruct()``'s ``super()`` reaches the Django field's own.
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
        """Normalise a ``vocabulary`` argument to a tuple of distinct vocabularies.

        Args:
            vocabulary: One URI or :class:`Vocabulary`, an iterable of them, or ``None``
                for no restriction.

        Returns:
            The vocabularies in declaration order, the first of each URI kept; empty for
            ``None``.

        Raises:
            TypeError: An element is neither a :class:`Vocabulary` nor a URI.
        """
        if vocabulary is None:
            elements = ()
        elif isinstance(vocabulary, (str, Vocabulary)):
            elements = (vocabulary,)
        else:
            elements = tuple(vocabulary)
        vocabularies = {}
        for element in elements:
            if not isinstance(element, Vocabulary):
                require_uri(element, type(self).__name__, "vocabulary")
                element = Vocabulary(element)
            vocabularies.setdefault(element.uri, element)
        return tuple(vocabularies.values())

    def apply_restriction(self, collection, branch):
        """Validate the ``collection`` and ``branch`` restrictions and store them.

        Must run after ``self.vocabulary`` is set. Stores ``self.collection`` and
        ``self.branch``.

        Args:
            collection: URI of a collection the choices are limited to, or ``None``.
            branch: URI of the concept whose branch the choices are limited to, or
                ``None``.

        Raises:
            TypeError: A restriction is not a URI, both are given, or the declaration
                does not name exactly one vocabulary.
        """
        if collection is not None and branch is not None:
            raise TypeError(
                f"{type(self).__name__}() a field carries at most one restriction; got "
                "both collection and branch."
            )
        for argument, value in (("collection", collection), ("branch", branch)):
            if value is None:
                continue
            require_uri(value, type(self).__name__, argument)
            if len(self.vocabulary) != 1:
                raise TypeError(
                    f"{type(self).__name__}() a {argument} restriction requires the "
                    "declaration to name exactly one vocabulary; got "
                    f"{len(self.vocabulary)}."
                )
        self.collection = collection
        self.branch = branch

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
            restriction &= Q(scheme__uri__in=self.vocabulary_uris())
        if self.collection is not None:
            (vocabulary,) = self.vocabulary
            collection = Record.objects.filter(
                scheme__uri=vocabulary.uri,
                uri=self.collection,
                type__in=Record.COLLECTION_TYPES,
            ).first()
            restriction &= Q(uri__in=collection.member_uris() if collection else [])
        if self.branch is not None:
            (vocabulary,) = self.vocabulary
            restriction &= Q(
                uri__in=Record.objects.in_branch(vocabulary.uri, self.branch).values(
                    "uri"
                )
            )
        return restriction

    def vocabulary_uris(self):
        """Return the URIs of the vocabularies the field names, in declaration order."""
        return tuple(vocabulary.uri for vocabulary in self.vocabulary)

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
            return "invalid", {
                "value": value,
                "vocabulary": ", ".join(self.vocabulary_uris()),
            }
        return "invalid_unrestricted", {"value": value}

    def apply_vocabulary(self, vocabulary, collection, branch, kwargs):
        """Store the normalised ``vocabulary`` and restriction, and fill in the kwargs they decide.

        Args:
            vocabulary: One URI or :class:`Vocabulary`, an iterable of them, or ``None``.
            collection: URI of the collection restriction, or ``None``.
            branch: URI of the branch restriction, or ``None``.
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
        self.apply_restriction(collection, branch)
        kwargs["to"] = "controlled_vocabularies.Record"
        kwargs["limit_choices_to"] = self.resolve_restriction
        kwargs.setdefault(
            "help_text",
            self.default_restricted_help_text
            if self.collection is not None or self.branch is not None
            else self.default_help_text,
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
        from .forms import ConceptChoiceField, MultiConceptChoiceField

        kwargs["model_field"] = self
        kwargs.setdefault(
            "form_class",
            MultiConceptChoiceField
            if isinstance(self, ManyToManyField)
            else ConceptChoiceField,
        )
        return super().formfield(**kwargs)

    def deconstruct(self):
        """Record ``vocabulary``, ``collection`` and ``branch`` rather than the kwargs it fixes."""
        # Field.clone() rebuilds from these kwargs, so they must be ones __init__ accepts.
        # Only the URIs are recorded: a source says where a vocabulary is published and
        # changes nothing in the schema, so moving one must not need a migration.
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("to", None)
        kwargs.pop("to_field", None)
        kwargs.pop("on_delete", None)
        kwargs.pop("limit_choices_to", None)
        kwargs["vocabulary"] = self.vocabulary_uris()
        if self.collection is not None:
            kwargs["collection"] = self.collection
        if self.branch is not None:
            kwargs["branch"] = self.branch
        return name, path, args, kwargs


class ConceptField(ConceptFieldMixin, ForeignKey):
    """A ``ForeignKey`` to ``controlled_vocabularies.Record`` in named vocabularies.

    ``to`` is always the string ``"controlled_vocabularies.Record"``, ``to_field`` is
    always ``"uri"``, so the column holds the concept's URI, and ``on_delete`` is
    always ``PROTECT``, so a concept a row holds cannot be deleted. The consumer
    supplies none of them, nor ``limit_choices_to``, which is derived from the
    arguments below.

    Args:
        vocabulary: One vocabulary's URI or :class:`Vocabulary`, several, or ``None`` for
            no restriction.
        collection: Limit choices to the members of the collection with this URI. Needs
            exactly one vocabulary.
        branch: Limit choices to the concept with this URI and every concept below it. Needs
            exactly one vocabulary, and cannot be combined with ``collection``.
        **kwargs: Passed to ``ForeignKey``.

    Raises:
        TypeError: The consumer supplied ``on_delete``, ``to_field``,
            ``limit_choices_to`` or an invalid restriction.
    """

    default_help_text = _(
        "A concept from this field's configured vocabulary or vocabularies."
    )
    default_restricted_help_text = _(
        "A concept from a restricted part of this field's configured vocabulary."
    )

    def __init__(self, vocabulary=None, collection=None, branch=None, **kwargs):
        if "on_delete" in kwargs:
            raise TypeError(
                "ConceptField() sets on_delete=PROTECT itself; a consumer may not override it."
            )
        if "to_field" in kwargs:
            raise TypeError(
                "ConceptField() sets to_field='uri' itself; a consumer may not override it."
            )
        kwargs["on_delete"] = PROTECT
        kwargs["to_field"] = "uri"
        super().__init__(
            **self.apply_vocabulary(vocabulary, collection, branch, kwargs)
        )

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

        attname = self.attname

        def get_uri(instance):
            """Return the attached concept's URI, read from the row's own column.

            Args:
                instance: The consuming model instance.

            Returns:
                The URI, or ``None`` when no concept is attached.
            """
            return getattr(instance, attname)

        self.contribute_accessor(cls, f"get_{name}_label", get_label)
        self.contribute_accessor(cls, f"get_{name}_uri", get_uri)


def create_membership_model(field, cls):
    """Build the through model for a :class:`MultiConceptField`.

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

    # Mirrors Django's create_many_to_many_intermediary_model, except the foreign key to
    # the concept is PROTECT (FS-010) and holds the concept's URI (#220). auto_created keeps the model out of migration
    # state and deconstruct().
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
                to_field="uri",
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

    An ``m2m_changed`` receiver bound to a :class:`MultiConceptField`'s through model.
    Only ``pre_add`` is checked. Both directions are checked, so
    ``concept.deposit_set.add(deposit)`` is refused on the same terms as
    ``deposit.rock_types.add(concept)``. Raising aborts the whole write before any row is inserted.

    Args:
        field: The :class:`MultiConceptField` whose restriction applies.
        instance: The row the write was made on.
        action: The ``m2m_changed`` action.
        reverse: Whether the write was made from the record side.
        model: The class of the rows being added.
        pk_set: Keys of the rows being added: concept URIs on a forward write, the
            owners' primary keys on a reverse one.
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
        invalid = list(model.objects.filter(uri__in=pk_set).exclude(restriction))
    if not invalid:
        return
    key, params = field.refusal(", ".join(str(concept) for concept in invalid))
    raise ValidationError(field.error_messages[key], code="invalid", params=params)


class MultiConceptField(ConceptFieldMixin, ManyToManyField):
    """A ``ManyToManyField`` to a ``controlled_vocabularies.Record`` set.

    The generated through model protects its concepts from deletion, so ``through`` is
    not the consumer's to supply, nor are ``to`` and ``limit_choices_to``. Takes the
    same arguments as :class:`ConceptField`, and a required field must hold at least
    one concept when the consuming model is cleaned.

    Args:
        vocabulary: One vocabulary's URI or :class:`Vocabulary`, several, or ``None`` for
            no restriction.
        collection: Limit choices to the members of the collection with this URI. Needs
            exactly one vocabulary.
        branch: Limit choices to the concept with this URI and every concept below it. Needs
            exactly one vocabulary, and cannot be combined with ``collection``.
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

    def __init__(self, vocabulary=None, collection=None, branch=None, **kwargs):
        if "through" in kwargs:
            raise TypeError(
                "MultiConceptField() generates its own through model with PROTECT on the "
                "foreign key to the concept; a consumer may not override it."
            )
        super().__init__(
            **self.apply_vocabulary(vocabulary, collection, branch, kwargs)
        )

    @staticmethod
    def install_required_set_check(cls):
        """Make ``full_clean()`` report each empty required field, once per class.

        ``full_clean()`` skips many-to-many fields, so a required :class:`MultiConceptField`
        has no hook into model validation without this.

        Args:
            cls: The consuming model class to wrap.
        """
        # A subclass inherits an installed wrapper; wrapping again would report twice.
        if getattr(cls.full_clean, "multi_concept_field_required_set_check", False):
            return
        original_full_clean = cls.full_clean

        def full_clean(
            self, exclude=None, validate_unique=True, validate_constraints=True
        ):
            """Run the wrapped ``full_clean()``, then report each empty required one."""
            try:
                original_full_clean(
                    self,
                    exclude=exclude,
                    validate_unique=validate_unique,
                    validate_constraints=validate_constraints,
                )
            except ValidationError as exc:
                errors = exc.update_error_dict({})
            else:
                errors = {}

            # Skipped for an unsaved row (its m2m manager raises ValueError) and for
            # ModelForm._post_clean(), the only caller passing validate_unique=False,
            # which runs before save_m2m() attaches the submission (#124).
            if self.pk is not None and validate_unique:
                # Read per call: a wrapper closed over one field would miss a second.
                for field in type(self)._meta.get_fields():
                    if (
                        isinstance(field, MultiConceptField)
                        and not field.blank
                        and not getattr(self, field.name).exists()
                    ):
                        errors.setdefault(field.name, []).append(
                            ValidationError(
                                _("%(field)s requires at least one concept."),
                                code="required",
                                params={"field": field.verbose_name},
                            )
                        )

            if errors:
                raise ValidationError(errors)

        full_clean.multi_concept_field_required_set_check = True
        cls.full_clean = full_clean

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
            self.install_required_set_check(cls)
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
