"""Model fields that attach concepts to a consuming model."""

from functools import partial

from django.core.exceptions import ValidationError
from django.db.models import CASCADE, PROTECT, ForeignKey, ManyToManyField, Model, Q
from django.db.models.fields.related import lazy_related_operation, resolve_relation
from django.db.models.fields.related_descriptors import ManyToManyDescriptor
from django.db.models.signals import m2m_changed
from django.db.models.utils import make_model_tuple
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

#: Refusal messages shared by ConceptField and the ConceptsField write guard, so each msgid
#: appears once in the translation catalogue. One placeholder carries the restriction (Article XII).
RESTRICTED_TO_COLLECTION_MESSAGE = _(
    "%(value)s is not a valid concept in the '%(restriction)s' collection."
)
RESTRICTED_TO_CONCEPTS_MESSAGE = _(
    "%(value)s is not one of the permitted concepts: '%(restriction)s'."
)
RESTRICTED_TO_BRANCH_MESSAGE = _(
    "%(value)s is not a valid concept in the '%(restriction)s' branch."
)
UNRESTRICTED_VOCABULARY_MESSAGE = _(
    "%(value)s is not a valid concept in the '%(vocabulary)s' vocabulary."
)


def _branch_closure(vocabulary, branch):
    """Return the ids of a branch's root concept and every concept narrower than it.

    Walks the stored ``broader`` edges downward, one round at a time, until a round
    adds nothing new. A branch slug that does not resolve within ``vocabulary``
    starts from nothing and returns an empty set.

    Args:
        vocabulary: Slug of the vocabulary holding the branch root.
        branch: Slug of the branch root concept.

    Returns:
        The primary keys of the root and all of its descendants.
    """
    from .models import Concept, ConceptRelation

    # A BROADER row's source is the narrower concept, so walking down matches on target.
    seen = set(
        Concept.objects.filter(scheme__slug=vocabulary, slug=branch).values_list(
            "pk", flat=True
        )
    )
    frontier = set(seen)
    while frontier:
        # Subtracting `seen` is what ends the walk on a cyclic hierarchy.
        frontier = (
            set(
                ConceptRelation.objects.filter(
                    kind=ConceptRelation.Kind.BROADER,
                    target_id__in=frontier,
                ).values_list("source_id", flat=True)
            )
            - seen
        )
        seen |= frontier
    return seen


class ConceptFieldMixin:
    """The ``vocabulary`` and restriction contract shared by both concept fields.

    Holds what ``vocabulary``, ``collection``, ``concepts`` and ``branch`` accept, how they
    are normalised, the ``limit_choices_to`` derived from them and how they survive
    :meth:`deconstruct`. Declare it before the Django field in the bases so
    ``deconstruct()``'s ``super()`` reaches the Django field's own.
    """

    #: Help text for a field naming no restriction. Static: ``%`` on a lazy string would evaluate it
    #: immediately and lose per-request translation. Annotated because a lazy proxy is not a ``str``.
    default_help_text: str | Promise | None = None

    #: Help text for a restricted field. Names the fact of a restriction, never its value, for the
    #: same laziness reason as ``default_help_text`` (FS-016).
    default_restricted_help_text: str | Promise | None = None

    def _default_help_text(self):
        """Return the help text default that matches the restriction this declaration carries.

        Returns:
            The restricted default when a collection, concept list or branch is named,
            otherwise the unrestricted default.
        """
        if (
            self.collection is not None
            or self.concepts is not None
            or self.branch is not None
        ):
            return self.default_restricted_help_text
        return self.default_help_text

    def _normalise_vocabulary(self, vocabulary):
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

    def _normalise_restriction_slug(self, value, argument_name):
        """Validate a single restriction target such as ``collection`` or ``branch``.

        Args:
            value: The slug the declaration supplied.
            argument_name: The argument's name, for the error message.

        Returns:
            ``value`` unchanged.

        Raises:
            TypeError: ``value`` is not a non-empty string.
        """
        if not isinstance(value, str) or not value:
            raise TypeError(
                f"{type(self).__name__}() {argument_name} must be a non-empty string; got {value!r}."
            )
        return value

    def _normalise_concepts(self, concepts):
        """Validate and normalise the ``concepts`` restriction.

        Args:
            concepts: One slug or an iterable of slugs.

        Returns:
            The slugs in declaration order with duplicates removed.

        Raises:
            TypeError: An element is not a non-empty string, or no slug was given.
        """
        slugs = (concepts,) if isinstance(concepts, str) else tuple(concepts)
        for slug in slugs:
            if not isinstance(slug, str) or not slug:
                raise TypeError(
                    f"{type(self).__name__}() concepts elements must be non-empty strings; got {slug!r}."
                )
        normalised = tuple(dict.fromkeys(slugs))
        if not normalised:
            raise TypeError(
                f"{type(self).__name__}() concepts must not be an empty list; omit the argument for no restriction."
            )
        return normalised

    def _apply_restriction(self, collection, concepts, branch):
        """Normalise the three restriction arguments and enforce the rules that keep them meaningful.

        Stores the results as ``self.collection``, ``self.concepts`` and ``self.branch``,
        each ``None`` when not named. Must run after ``self.vocabulary`` is set.

        Args:
            collection: Slug of a collection the choices are limited to, or ``None``.
            concepts: Slugs of the concepts the choices are limited to, or ``None``.
            branch: Slug of a concept whose descendants the choices are limited to, or ``None``.

        Raises:
            TypeError: A restriction is named without exactly one vocabulary, or more
                than one restriction is named.
        """
        self.collection = (
            None
            if collection is None
            else self._normalise_restriction_slug(collection, "collection")
        )
        self.concepts = None if concepts is None else self._normalise_concepts(concepts)
        self.branch = (
            None
            if branch is None
            else self._normalise_restriction_slug(branch, "branch")
        )

        restriction_names = [
            name
            for name, value in (
                ("collection", self.collection),
                ("concepts", self.concepts),
                ("branch", self.branch),
            )
            if value is not None
        ]

        if restriction_names and len(self.vocabulary) != 1:
            raise TypeError(
                f"{type(self).__name__}() a restriction ({', '.join(restriction_names)}) requires the "
                f"declaration to name exactly one vocabulary; got {len(self.vocabulary)}."
            )
        if len(restriction_names) > 1:
            raise TypeError(
                f"{type(self).__name__}() at most one of collection, concepts, branch may be given; "
                f"got {', '.join(restriction_names)}."
            )

    def _resolve_restriction(self):
        """Return the ``Q`` that limits the field's choices, resolved at call time.

        Installed as ``limit_choices_to``, so it is evaluated when a value is validated,
        a form is built, the widget renders or a search runs, never while the declaration
        is only being read. Every restriction is joined to the vocabulary term, so a slug
        that exists in another vocabulary cannot widen the field.

        Returns:
            A ``Q`` over ``Concept``.
        """
        vocabulary_term = Q(scheme__slug__in=self.vocabulary)
        if self.collection is not None:
            # Deferred import: this runs only after every app's models have loaded.
            from .models import CollectionMember

            # A subquery, not a join: the widget and search endpoint apply this Q bare, and a
            # join would duplicate rows there (FS-016).

            (vocabulary,) = self.vocabulary
            members = CollectionMember.objects.filter(
                collection__slug=self.collection,
                collection__scheme__slug=vocabulary,
            ).values("concept")
            return vocabulary_term & Q(pk__in=members)
        if self.concepts is not None:
            return vocabulary_term & Q(slug__in=self.concepts)
        if self.branch is not None:
            (vocabulary,) = self.vocabulary
            return vocabulary_term & Q(pk__in=_branch_closure(vocabulary, self.branch))
        return vocabulary_term

    def _apply_vocabulary(self, vocabulary, collection, concepts, branch, kwargs):
        """Store the normalised ``vocabulary`` and restriction, and fill in the kwargs they decide.

        Args:
            vocabulary: One slug, an iterable of slugs, or ``None``.
            collection: Collection restriction, or ``None``.
            concepts: Concept-list restriction, or ``None``.
            branch: Branch restriction, or ``None``.
            kwargs: The field's remaining keyword arguments, updated in place.

        Returns:
            ``kwargs``, now carrying ``to``, ``help_text`` and, when a vocabulary is
            named, ``limit_choices_to``.

        Raises:
            TypeError: The consumer supplied ``limit_choices_to``, or the declaration breaks a
                restriction rule.
        """
        if "limit_choices_to" in kwargs:
            raise TypeError(
                f"{type(self).__name__}() sets limit_choices_to itself to constrain choices "
                "to 'vocabulary'; a consumer may not override it."
            )
        self.vocabulary = self._normalise_vocabulary(vocabulary)
        self._apply_restriction(collection, concepts, branch)
        kwargs["to"] = "controlled_vocabularies.Concept"
        if self.vocabulary:
            kwargs["limit_choices_to"] = self._resolve_restriction
        kwargs.setdefault("help_text", self._default_help_text())
        return kwargs

    def _contribute_accessor(self, cls, attr_name, accessor):
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
        """Record ``vocabulary`` and the restriction instead of the kwargs this package fixes."""
        # Field.clone() rebuilds from these kwargs, so they must be ones __init__ accepts.
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("to", None)
        kwargs.pop("on_delete", None)
        kwargs.pop("limit_choices_to", None)
        kwargs["vocabulary"] = self.vocabulary
        if self.collection is not None:
            kwargs["collection"] = self.collection
        if self.concepts is not None:
            kwargs["concepts"] = self.concepts
        if self.branch is not None:
            kwargs["branch"] = self.branch
        return name, path, args, kwargs


class ConceptField(ConceptFieldMixin, ForeignKey):
    """A ``ForeignKey`` to ``controlled_vocabularies.Concept``, optionally limited to named vocabularies.

    ``to`` is always the string ``"controlled_vocabularies.Concept"`` and ``on_delete``
    is always ``PROTECT``, so a concept a record holds cannot be deleted. The
    consumer supplies neither, nor ``limit_choices_to``, which is derived from the
    arguments below.

    Args:
        vocabulary: One vocabulary slug, several, or ``None`` for no restriction.
        collection: Limit choices to the members of this collection. Needs exactly one vocabulary.
        concepts: Limit choices to these concept slugs. Needs exactly one vocabulary.
        branch: Limit choices to this concept and everything narrower than it.
            Needs exactly one vocabulary.
        **kwargs: Passed to ``ForeignKey``.

    Raises:
        TypeError: The consumer supplied ``on_delete``, ``limit_choices_to`` or an invalid restriction.
    """

    # One message per restriction axis, each naming what decided the refusal. The vocabulary slugs
    # join into one placeholder so the msgid is the same for one vocabulary or several (FS-016).
    default_error_messages = {
        "invalid": UNRESTRICTED_VOCABULARY_MESSAGE,
        "invalid_unrestricted": _("%(value)s is not a valid concept."),
        "invalid_restricted": RESTRICTED_TO_COLLECTION_MESSAGE,
        "invalid_restricted_concepts": RESTRICTED_TO_CONCEPTS_MESSAGE,
        "invalid_restricted_branch": RESTRICTED_TO_BRANCH_MESSAGE,
    }

    default_help_text = _(
        "A concept from this field's configured vocabulary or vocabularies."
    )
    default_restricted_help_text = _(
        "A concept from a restricted part of this field's configured vocabulary."
    )

    def __init__(
        self, vocabulary=None, collection=None, concepts=None, branch=None, **kwargs
    ):
        if "on_delete" in kwargs:
            raise TypeError(
                "ConceptField() sets on_delete=PROTECT itself; a consumer may not override it."
            )
        kwargs["on_delete"] = PROTECT
        super().__init__(
            **self._apply_vocabulary(vocabulary, collection, concepts, branch, kwargs)
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
            # Keep the ForeignKey's own params: a consumer's message may use `model`, `pk` or `field`.
            params = {**(exc.params or {}), "value": value}
            if self.collection is not None:
                message = self.error_messages["invalid_restricted"]
                params["restriction"] = self.collection
            elif self.concepts is not None:
                message = self.error_messages["invalid_restricted_concepts"]
                params["restriction"] = ", ".join(self.concepts)
            elif self.branch is not None:
                message = self.error_messages["invalid_restricted_branch"]
                params["restriction"] = self.branch
            elif self.vocabulary:
                message = self.error_messages["invalid"]
                params["vocabulary"] = ", ".join(self.vocabulary)
            else:
                message = self.error_messages["invalid_unrestricted"]
            raise ValidationError(message, code="invalid", params=params) from exc

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

        self._contribute_accessor(cls, f"get_{name}_label", get_label)
        self._contribute_accessor(cls, f"get_{name}_uri", get_uri)


def _create_membership_model(field, cls):
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

    # Mirrors Django's create_many_to_many_intermediary_model, except the foreign key to Concept
    # is PROTECT (FS-010). auto_created keeps the model out of migration state and deconstruct().
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


def _refuse_concepts_the_restriction_does_not_admit(
    *, field, instance, action, reverse, model, pk_set, **kwargs
):
    """Refuse a write that attaches a concept the field's restriction does not admit.

    An ``m2m_changed`` receiver bound to a :class:`ConceptsField`'s through model.
    Only ``pre_add`` is checked. Both directions are checked, so
    ``concept.deposit_set.add(deposit)`` is refused on the same terms as
    ``deposit.rock_types.add(concept)``. Raising aborts the whole write before any row is inserted.

    Args:
        field: The :class:`ConceptsField` whose restriction applies.
        instance: The record the write was made on.
        action: The ``m2m_changed`` action.
        reverse: Whether the write was made from the ``Concept`` side.
        model: The class of the records being added.
        pk_set: Primary keys of the records being added.
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
    value = ", ".join(str(concept) for concept in invalid)
    if field.collection is not None:
        raise ValidationError(
            RESTRICTED_TO_COLLECTION_MESSAGE,
            code="invalid",
            params={"value": value, "restriction": field.collection},
        )
    if field.concepts is not None:
        raise ValidationError(
            RESTRICTED_TO_CONCEPTS_MESSAGE,
            code="invalid",
            params={"value": value, "restriction": ", ".join(field.concepts)},
        )
    if field.branch is not None:
        raise ValidationError(
            RESTRICTED_TO_BRANCH_MESSAGE,
            code="invalid",
            params={"value": value, "restriction": field.branch},
        )
    raise ValidationError(
        UNRESTRICTED_VOCABULARY_MESSAGE,
        code="invalid",
        params={"value": value, "vocabulary": ", ".join(field.vocabulary)},
    )


def _install_required_set_check(cls):
    """Make ``full_clean()`` report each empty required :class:`ConceptsField`, once per class.

    ``full_clean()`` skips many-to-many fields, so a required :class:`ConceptsField`
    has no hook into model validation without this.

    Args:
        cls: The consuming model class to wrap.
    """
    # A subclass inherits an installed wrapper; wrapping it again would report each field twice.
    if getattr(cls.full_clean, "_concepts_field_required_set_check", False):
        return
    original_full_clean = cls.full_clean

    def full_clean(self, exclude=None, validate_unique=True, validate_constraints=True):
        """Run the wrapped ``full_clean()``, then add an error for each empty required field."""
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

        # Skipped for an unsaved record (its m2m manager raises ValueError) and for
        # ModelForm._post_clean(), the only caller passing validate_unique=False, which runs
        # before save_m2m() attaches the submission (#124).
        if self.pk is not None and validate_unique:
            # Fields are read per call: a wrapper closed over one field would miss a second one.
            for field in type(self)._meta.get_fields():
                if (
                    isinstance(field, ConceptsField)
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

    full_clean._concepts_field_required_set_check = True
    cls.full_clean = full_clean


class ConceptsField(ConceptFieldMixin, ManyToManyField):
    """A ``ManyToManyField`` to ``controlled_vocabularies.Concept``, optionally limited to named vocabularies.

    The generated through model protects its concepts from deletion, so ``through`` is
    not the consumer's to supply, nor are ``to`` and ``limit_choices_to``. Takes the
    same ``vocabulary`` shapes and restrictions as :class:`ConceptField`, and a
    required field must hold at least one concept.

    Args:
        vocabulary: One vocabulary slug, several, or ``None`` for no restriction.
        collection: Limit choices to the members of this collection. Needs exactly one vocabulary.
        concepts: Limit choices to these concept slugs. Needs exactly one vocabulary.
        branch: Limit choices to this concept and everything narrower than it.
            Needs exactly one vocabulary.
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

    def __init__(
        self, vocabulary=None, collection=None, concepts=None, branch=None, **kwargs
    ):
        if "through" in kwargs:
            raise TypeError(
                "ConceptsField() generates its own through model with PROTECT on the "
                "foreign key to Concept; a consumer may not override it."
            )
        super().__init__(
            **self._apply_vocabulary(vocabulary, collection, concepts, branch, kwargs)
        )

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
            self.remote_field.through = _create_membership_model(self, cls)
            _install_required_set_check(cls)
            # Connected here so a declaration cannot exist without its guard: an auto_created
            # through model with no receiver takes bulk_create's fast path, which skips m2m_changed.
            # weak=False because the partial has no other reference to keep it alive.
            if self.vocabulary:
                m2m_changed.connect(
                    partial(
                        _refuse_concepts_the_restriction_does_not_admit, field=self
                    ),
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

            self._contribute_accessor(cls, f"get_{name}_labels", get_labels)
            self._contribute_accessor(cls, f"get_{name}_uris", get_uris)

        setattr(cls, self.name, ManyToManyDescriptor(self.remote_field, reverse=False))
        self.m2m_db_table = partial(self._get_m2m_db_table, cls._meta)
