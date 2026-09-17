"""``ConceptField`` and ``ConceptsField`` — attach concepts to a consuming model.

A ``ForeignKey`` subclass and a ``ManyToManyField`` subclass a consuming project
declares on its own model, each naming its vocabularies by slug. Both fix the
kwargs the consumer does not supply — ``to="controlled_vocabularies.Concept"``,
``on_delete=PROTECT``, and ``limit_choices_to`` restricted to the named
vocabularies — so almost everything FR-002/FR-005/FR-006/FR-007 ask for falls
out of ``limit_choices_to``: it is what ``ForeignKey.validate()`` applies, and
it is a ``Q``, so it is lazy and never queries the database while the
declaration is only being read (FR-003).

Both take the same ``vocabulary`` argument, in the same three shapes, and mean
the same thing by each (#111): one slug, several, or none at all. A declaration
naming none gives up the restriction and keeps every other guarantee.
"""

from functools import partial

from django.core.exceptions import ValidationError
from django.db.models import CASCADE, PROTECT, ForeignKey, ManyToManyField, Model, Q
from django.db.models.fields.related import lazy_related_operation, resolve_relation
from django.db.models.fields.related_descriptors import ManyToManyDescriptor
from django.db.models.signals import m2m_changed
from django.db.models.utils import make_model_tuple
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

#: The refusal wording for a concept the field's declaration does not admit,
#: one message per restriction axis plus the unrestricted case. Named here
#: rather than written out where they are raised, because each is needed in two
#: places that cannot share a class: :attr:`ConceptField.default_error_messages`
#: for the single-valued path, and :func:`_refuse_concepts_the_restriction_does_not_admit`
#: for the many-valued write guard, which runs as a signal receiver on
#: :class:`ConceptsField`. Two copies of a msgid is two entries in the
#: translation catalogue that a translator has to keep in step by hand, and one
#: reworded copy is a refusal whose wording depends on how many values the field
#: holds. Each is one static msgid with the restriction carried through a single
#: named placeholder (Article XII), so the identifier stays the same whatever
#: the declaration names.
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
    """The branch axis's downward closure (plan.md A3, research.md R5): the
    concept named ``branch`` within ``vocabulary``, plus everything narrower
    than it at any depth.

    Iterative widening over the stored ``broader`` edges, never a single
    recursive statement (Article II, research.md R5 — both backends support
    a recursive CTE and neither is used anywhere in this package, and this
    function is deliberately the only thing R7 would have to replace). The
    direction is not obvious and is easy to invert: a ``BROADER`` row's
    ``source`` is the *narrower* concept and its ``target`` the broader one
    (``models.py:1161-1174``), and ``narrower`` is a reverse read rather
    than a stored edge. Walking downward means matching each round's
    frontier against ``target`` and collecting ``source`` as the next one.

    Each round is subtracted against everything already seen before it is
    added to the frontier — that subtraction, not a depth counter or a
    separate guard, is what terminates the walk on a cyclic hierarchy
    (FR-004, decisions.md D5): a two-edge cycle is storable through the
    public API today, and a round that could re-add an already-seen concept
    would loop forever without it.

    A ``branch`` slug that does not resolve within ``vocabulary`` — absent
    altogether, or belonging to a different one — starts with an empty
    frontier and returns the empty set, the same unresolvable-target shape
    the other two axes already give (plan.md A2).
    """
    from .models import Concept, ConceptRelation

    seen = set(
        Concept.objects.filter(scheme__slug=vocabulary, slug=branch).values_list(
            "pk", flat=True
        )
    )
    frontier = set(seen)
    while frontier:
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
    """The ``vocabulary`` contract both concept fields keep, held in one place.

    #111 made the two fields take the same three shapes and mean the same thing
    by each. Leaving each class to implement that separately is what let them
    drift apart the first time, so the contract lives here and each field
    inherits it rather than restating it: what ``vocabulary`` accepts, what it
    normalises to, the restriction derived from it, the ``to`` this package
    fixes, and how all three survive :meth:`deconstruct`.

    Deliberately a mixin of helpers rather than a base class owning
    ``__init__``. The two fields subclass different Django fields, take
    different signatures, refuse different kwargs (``on_delete`` against
    ``through``) and enforce the restriction by different mechanisms — a
    ``validate()`` override against an ``m2m_changed`` receiver. Only the
    vocabulary contract is genuinely common, so only the vocabulary contract is
    here, and each ``__init__`` still reads top to bottom.

    Declare it first in the bases (``ConceptField(ConceptFieldMixin,
    ForeignKey)``) so :meth:`deconstruct`'s ``super()`` resolves to the Django
    field's own.
    """

    #: The ``help_text`` a declaration gets when it supplies none, for a field
    #: naming no restriction. A static message, never one interpolating
    #: ``vocabulary``: ``%`` on a gettext_lazy() proxy evaluates it
    #: immediately, which would defeat the laziness this default exists to
    #: keep (translation happens at access time, per request). Annotated
    #: rather than inferred: both subclasses assign a ``gettext_lazy()``
    #: proxy, which is not a ``str``.
    default_help_text: str | Promise | None = None

    #: The ``help_text`` a restricted declaration gets when it supplies none
    #: (T023, US-7, FR-013). One static message per field, shared by all
    #: three restriction axes — it names the fact of a restriction, never the
    #: restriction itself, for the same reason ``default_help_text`` stays
    #: static: interpolating ``self.collection``/``self.concepts``/
    #: ``self.branch`` here would apply ``%`` to a ``gettext_lazy()`` proxy at
    #: read time and evaluate it immediately, the exact laziness these
    #: defaults exist to keep.
    default_restricted_help_text: str | Promise | None = None

    def _default_help_text(self):
        """The ``help_text`` default for the restriction this declaration
        does or does not carry (T023). ``self.collection``, ``self.concepts``
        and ``self.branch`` are already normalised by the time
        :meth:`_apply_vocabulary` calls this, so which one is set (if any) is
        read, never which value it holds — the value itself never reaches
        either default.
        """
        if (
            self.collection is not None
            or self.concepts is not None
            or self.branch is not None
        ):
            return self.default_restricted_help_text
        return self.default_help_text

    def _normalise_vocabulary(self, vocabulary):
        """Normalise a ``vocabulary`` argument to a tuple of slugs.

        One code path for all three shapes (FR-002, ``decisions.md`` D9, #111):
        a single slug becomes a one-element tuple so ``__in`` serves both the
        one- and several-vocabulary cases, a list collapses duplicates with
        order left insignificant, and an omitted (``None``) vocabulary
        normalises to the empty tuple — the fields' only real branch, and
        everywhere it appears the answer is to do nothing rather than something
        weaker.

        An empty slug is refused rather than normalised away. No
        :class:`~controlled_vocabularies.models.ConceptScheme` can carry one, so
        a declaration holding it would offer no choices at all while reading as
        a restricted field — the opposite of the unrestricted shape a consumer
        who writes ``vocabulary=""`` is reaching for.
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
        """Validate a single restriction target (``collection``, ``branch``) by
        the same rule :meth:`_normalise_vocabulary` applies to a vocabulary
        slug: a non-empty string, or a ``TypeError`` naming the class.
        """
        if not isinstance(value, str) or not value:
            raise TypeError(
                f"{type(self).__name__}() {argument_name} must be a non-empty string; got {value!r}."
            )
        return value

    def _normalise_concepts(self, concepts):
        """Validate and normalise the ``concepts`` restriction (FR-003).

        Every element must be a non-empty string, duplicates are collapsed
        with the same ``dict.fromkeys`` idiom :meth:`_normalise_vocabulary`
        uses, and an empty list is refused — the same reasoning that already
        refuses an empty vocabulary slug: it reads as a restriction and
        offers nothing (``decisions.md`` D4).

        A single slug is accepted as a one-element restriction, the shape
        :meth:`_normalise_vocabulary` already accepts. Without that branch a
        string is iterated character by character, so ``concepts="granite"``
        would become seven one-letter slugs and pass every check here — a
        declaration that is wrong in a way nothing downstream can name.
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
        """Normalise the three restriction arguments and enforce the two
        declaration rules that keep them meaningful (FR-005, FR-006).

        Stores the normalised values as ``self.collection``, ``self.concepts``
        and ``self.branch`` — ``None`` when the declaration did not name that
        restriction. Must run after ``self.vocabulary`` is set, since FR-005
        reads it. Resolving a restriction into a queryset is a later story's
        work; this only decides whether the declaration is one this package
        accepts.
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
        """The callable installed as ``limit_choices_to`` (research.md R2):
        resolved at validation time, form-build time, widget-render time and
        search time alike, never while the declaration is merely being read
        (FR-007).

        The vocabulary term is always present and never dropped (plan.md A2):
        a collection slug that happens to exist in another vocabulary cannot
        widen the field, because every restriction is joined to it with
        ``&``. The collection axis (T006, research.md R3) narrows further
        with a ``pk__in`` subquery over :class:`~controlled_vocabularies.models.CollectionMember`
        — a subquery rather than a ``collection_memberships__…`` join, since
        this package's own widget and search endpoint call
        ``complex_filter()`` bare, where Django wraps a ``ModelChoiceField``'s
        own ``Q`` in ``Exists()``: a join-shaped ``Q`` would duplicate rows in
        exactly those two places. The concepts axis (T013) needs none of
        that: ``slug__in`` is a plain column filter on ``Concept`` itself, so
        it cannot duplicate a row and is joined to the vocabulary term
        directly rather than through a subquery. The branch axis (T018)
        also needs a subquery, for the same reason as the collection axis:
        it narrows with ``pk__in`` over :func:`_branch_closure`'s
        materialised id set.

        The import is local, not top-level, for the same reason
        :meth:`formfield` defers its own: this method runs only once every
        app's models have loaded (validation time, form-build time,
        widget-render time, search time), so a top-level import here would
        tie the *consuming* project's app-loading order to something a
        top-level import cannot assume.
        """
        vocabulary_term = Q(scheme__slug__in=self.vocabulary)
        if self.collection is not None:
            from .models import CollectionMember

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
        """Store the normalised ``vocabulary`` and restriction, and fill in the
        kwargs they decide.

        ``limit_choices_to`` is set only when the declaration named at least one
        vocabulary — an empty restriction is not set at all, rather than a
        restriction that matches everything by accident. It is also refused from
        a consumer, because the vocabulary constraint *is* ``limit_choices_to``,
        so accepting one would silently discard either theirs or the constraint.

        Installed as a **callable** (research.md R2) rather than a bare ``Q``,
        so it is re-resolved at every one of the four paths research.md R1
        found, and never evaluated while the declaration is only being read.
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
        """Add a derived read to the consuming model unless it defines that name
        itself (FR-008, FR-009), the way Django's own ``get_FOO_display()`` is
        added. A model that already defines the name keeps its own definition
        rather than having it silently overwritten.
        """
        if not hasattr(cls, attr_name):
            setattr(cls, attr_name, accessor)

    def formfield(self, **kwargs):
        """Return this package's form field so an ordinary ``ModelForm`` gets the
        search-as-you-type control from the model declaration alone (T004, FR-001,
        plan.md A3) — nothing declared per field or per form.

        The import is deferred: ``forms.py`` imports ``Concept`` from this
        package's own ``models.py``, and ``formfield()`` runs only once every
        app's models have loaded, so a top-level import here would tie the
        *consuming* project's app-loading order to something a top-level import
        cannot assume.

        ``model_field`` — this field instance itself — is passed through so the
        widget's own ``get_queryset()`` can build the validation queryset
        directly from it, with no request consulted (decisions.md D12, plan.md
        A6 path two). Everything Django itself supplies — ``required``,
        ``label``, ``help_text``, ``limit_choices_to`` — passes through
        unchanged (FR-009): this method only decides which form field class
        renders and hands it the one extra thing it needs.
        """
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
        """Strip the kwargs this package fixes and record ``vocabulary`` instead.

        ``ForeignKey.deconstruct()`` emits ``to`` and ``on_delete``;
        ``RelatedField.deconstruct()`` emits ``limit_choices_to`` whenever it is
        truthy. Left alone, every generated migration would carry a redundant
        ``to``, a redundant ``on_delete``, and a ``Q`` literal that duplicates
        ``vocabulary`` and drifts from it the moment either changes. Worse,
        ``Field.clone()`` — called by ``ModelState.from_model()`` on every
        ``makemigrations``, ``makemigrations --check``, ``migrate`` and
        pytest-django's own test-database build — could not rebuild the field at
        all: ``__init__`` would receive kwargs it refuses and no ``vocabulary``
        to rebuild the restriction from.

        ``on_delete`` is popped unconditionally. ``ManyToManyField`` never emits
        it, so the pop is a no-op there rather than a branch worth writing.
        ``through`` needs no pop either: the generated membership model is
        ``auto_created``, and ``ManyToManyField.deconstruct()`` only emits
        ``through`` when it is not.
        """
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
    """A ``ForeignKey`` to ``controlled_vocabularies.Concept``, optionally
    constrained to one or more named vocabularies.

    ``vocabulary`` is optional (#111) and takes the same three shapes
    :class:`ConceptsField` takes, through the
    :class:`ConceptFieldMixin` contract both fields inherit: a single
    :class:`~controlled_vocabularies.models.ConceptScheme` slug, a list of
    slugs, or omitted entirely. A declaration naming no vocabulary is a
    supported shape rather than an error — it keeps the delete protection and
    the label/URI readback, and gives up only the restriction. ``to``,
    ``on_delete`` and ``limit_choices_to`` are not the consumer's to supply:
    ``on_delete`` is refused outright (FR-007's guarantee is not theirs to
    weaken), while ``to`` is overwritten and ``limit_choices_to`` is derived
    from ``vocabulary``, set only when the declaration named at least one (an
    empty restriction is not set at all, rather than a restriction that matches
    everything by accident).

    ``to`` is always the *string* ``"controlled_vocabularies.Concept"``, never
    the imported class — deliberately, not a detail. Migration state rejects a
    resolved model class in a field's ``to``: ``ModelState`` has to be
    rebuildable without every referenced model already loaded, and raises
    ``ValueError`` the moment one holds a live class rather than a string. An
    ordinary ``ForeignKey`` never hits this, because its own ``deconstruct()``
    stringifies a live-class ``to`` before anything rebuilds from it — but
    this field's :meth:`deconstruct` strips ``to`` from the emitted kwargs
    entirely (T003), so ``__init__`` is the only place the string can come
    from. The consequence is real: with a string ``to``,
    ``remote_field.model`` only resolves once the field is attached to a
    model class (``RelatedField.contribute_to_class()`` defers to
    ``lazy_related_operation``), so an *unbound* field cannot run
    ``validate()`` — that assertion belongs to a task with a real consuming
    model (T005), not this one. The string form also means this module never
    imports :class:`~controlled_vocabularies.models.Concept`, which removes a
    circular-import risk.
    """

    default_error_messages = {
        # The vocabulary slugs join into ONE placeholder (Article XII) so the
        # message identifier stays the same whether the declaration names one
        # vocabulary or several — the same shape the many-valued field's own
        # refusal uses.
        "invalid": UNRESTRICTED_VOCABULARY_MESSAGE,
        # A declaration naming no vocabulary has none to name in a refusal, so
        # it needs its own message rather than the one above with an empty
        # interpolation. Both are overridable through `error_messages`.
        "invalid_unrestricted": _("%(value)s is not a valid concept."),
        # T008 (US-1): a collection-restricted field names the collection,
        # not the vocabulary — the restriction is what actually decided the
        # refusal.
        "invalid_restricted": RESTRICTED_TO_COLLECTION_MESSAGE,
        # T013 (US-2): a concepts-restricted field names the permitted
        # concepts themselves — a distinct msgid from `invalid_restricted`
        # because that one's text names a *collection*, which would
        # misdescribe this axis.
        "invalid_restricted_concepts": RESTRICTED_TO_CONCEPTS_MESSAGE,
        # T017 (US-3, decisions.md D11's invalid_restricted_<axis> pattern):
        # a branch-restricted field names the branch root, not the
        # collection or concept list `invalid_restricted`/
        # `invalid_restricted_concepts` would misdescribe it as.
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
        """Refuse a concept outside the named vocabulary, with a message that
        actually reads.

        ``ForeignKey.validate()`` builds its ``ValidationError``'s ``params``
        itself — ``model``, ``pk``, ``field``, ``value``, and nothing else
        (Django 5.2.16, ``django/db/models/fields/related.py``).
        ``ValidationError`` defers ``%``-substitution to iteration time
        (``message %= error.params`` in ``core/exceptions.py.__iter__``, which
        backs both ``.messages`` and ``str()``), so
        ``error_messages["invalid"]`` carrying ``%(vocabulary)s`` constructs
        fine and raises ``KeyError: 'vocabulary'`` the first time anything
        reads it. Catching the ``code="invalid"`` error here and re-raising
        with ``vocabulary`` in ``params`` is what gives the placeholder
        something to interpolate. This is a message concern only — the
        refusal itself is still ``limit_choices_to``. Only reachable on a
        field bound to a model (``remote_field.model`` must be resolved);
        proved end-to-end by T005 against a real test-app model.

        A declaration naming no vocabulary reaches here too (#111), for the
        one refusal that survives without a restriction: a primary key no
        concept carries. It has no vocabulary to name, so it re-raises with
        ``invalid_unrestricted`` — the same ``KeyError`` would otherwise fire
        on a placeholder nothing could fill.

        A collection-restricted field (T008, US-1) names the collection
        instead of the vocabulary — that is what actually decided the
        refusal, and naming the wider vocabulary would tell a curator
        nothing about why a same-vocabulary concept was rejected. A
        concepts-restricted field (T013, US-2) names the permitted concepts,
        and a branch-restricted field (T017, US-3) names the branch root,
        on the same reasoning.
        """
        try:
            super().validate(value, model_instance)
        except ValidationError as exc:
            if exc.code != "invalid":
                raise
            # Carry the ForeignKey's own params through. A consumer's
            # error_messages["invalid"]/["invalid_restricted"]/
            # ["invalid_restricted_concepts"]/["invalid_restricted_branch"]
            # is free to use `model`, `pk` or `field`, and dropping them
            # would reproduce the same KeyError-on-read this override
            # exists to prevent.
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
        """Add ``get_<name>_label()`` and ``get_<name>_uri()`` to the
        consuming model (FR-008, FR-009), named the way Django's own
        ``get_FOO_display()`` is (``Field.contribute_to_class``'s own
        precedent for a derived read named after a field).

        ``get_<name>_label()`` delegates to
        :meth:`~controlled_vocabularies.models.Concept.display_label`;
        ``get_<name>_uri()`` returns the attached concept's ``uri``
        unchanged. Both return ``None``, never raise, when nothing is
        attached. The ``setattr`` is guarded: a model that already defines
        either name keeps its own definition rather than having it
        silently overwritten.
        """
        super().contribute_to_class(cls, name, private_only=private_only, **kwargs)

        # Three-arg getattr, not two: on a required field with nothing attached
        # Django's forward descriptor raises RelatedObjectDoesNotExist rather
        # than returning None. It subclasses AttributeError, so a default turns
        # that back into the None both accessors promise.
        def get_label(instance):
            concept = getattr(instance, name, None)
            return concept.display_label() if concept is not None else None

        def get_uri(instance):
            concept = getattr(instance, name, None)
            return concept.uri if concept is not None else None

        self._contribute_accessor(cls, f"get_{name}_label", get_label)
        self._contribute_accessor(cls, f"get_{name}_uri", get_uri)


def _create_membership_model(field, cls):
    """Build the through model for a :class:`ConceptsField`, generated the way
    ``django.db.models.fields.related.create_many_to_many_intermediary_model``
    generates ``ManyToManyField``'s own — same ``<Owner>_<fieldname>`` naming,
    same ``unique_together``, same hidden ``related_name="…+"`` accessors,
    same ``Meta.apps``, same ``db_table`` — with one change: the foreign key
    to ``Concept`` is ``on_delete=PROTECT`` rather than ``CASCADE`` (FR-007,
    T003, US-3), so a concept some record holds cannot be deleted out from
    under it. The foreign key to the owning model stays ``CASCADE``: deleting
    the consuming record removes its own memberships and leaves every concept
    it held intact (FR-007).

    ``Meta.auto_created`` is set to the owning model class, exactly as
    Django's own factory sets it — that one attribute is what keeps the model
    out of migration state (``ProjectState.from_apps`` calls
    ``apps.get_models()``, which excludes auto-created models) and out of
    ``deconstruct()`` (``ManyToManyField.deconstruct()`` emits ``through``
    only when ``not …auto_created``), while still having its table created
    and dropped with the owner by the schema editor.
    """

    def set_managed(model, related, through):
        through._meta.managed = model._meta.managed or related._meta.managed

    to_model = resolve_relation(cls, field.remote_field.model)
    name = f"{cls._meta.object_name}_{field.name}"
    lazy_related_operation(set_managed, cls, to_model, name)

    to = make_model_tuple(to_model)[1]
    from_ = cls._meta.model_name
    if to == from_:
        to = f"to_{to}"
        from_ = f"from_{from_}"

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
    """``m2m_changed`` receiver for a :class:`ConceptsField`'s generated
    through model (FR-005, D2, R1, R3, R6, T012): refuse the whole write when
    any incoming concept falls outside ``field``'s resolved restriction — of
    which the vocabulary-only case (no ``collection``/``concepts``/``branch``
    named) is one, not a separate check.

    Connected only against a field whose declaration named at least one
    vocabulary (:meth:`ConceptsField.contribute_to_class`) — a field naming
    none has nothing to enforce, and this receiver is never bound to its
    through model in that case.

    Bound with the field itself (T012), not with ``vocabulary`` alone: both
    branches below read ``field.get_limit_choices_to()``, so this and every
    other enforcement path (research.md R1) resolve the same restriction and
    cannot drift apart the way ``ConceptField`` and ``ConceptsField``
    themselves once did (#111).

    Only ``pre_add`` is checked. ``post_add``, ``pre_remove``, ``post_remove``,
    ``pre_clear`` and ``post_clear`` all reach this same receiver and are
    ignored.

    Both directions are checked, but they are not the same check. Django
    gives every relation a live reverse accessor unless the declaration hides
    it, so ``concept.deposit_set.add(a_deposit)`` reaches the same through
    model as ``deposit.rock_types.add(a_concept)`` and has to be refused on
    the same terms. What differs is where the concept is: on a forward write
    ``pk_set`` holds the incoming concepts' primary keys, so ``model``
    (``Concept``) is queried directly; on a reverse write ``pk_set`` holds the
    *owner* model's keys instead, and the single concept being attached is
    ``instance`` (D16) — so its own admission is checked with ``type(instance)``,
    never with ``model``, which is the *owner*'s class on that branch.

    Raising here aborts the whole write before any row is inserted (FR-005).
    ``QuerySet.set()`` is implemented as ``remove()`` then ``add()``, so the
    same receiver refuses a mixed write whole, leaving the record's existing
    set untouched (D2).
    """
    if action != "pre_add":
        return
    restriction = field.get_limit_choices_to()
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
    # The same four messages the single-valued path raises, named once at the
    # top of this module rather than written out twice: a refusal should not
    # read differently depending on how many values the field holds, and one
    # msgid in two places is two catalogue entries for a translator to keep in
    # step by hand.
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
    """Install the required-set rule onto ``cls.full_clean`` (FR-010, D3, D8,
    R2, R5), once per class.

    ``full_clean()``'s own ``clean_fields()`` walks ``_meta.fields``, which
    excludes ``ManyToManyField`` by an explicit filter (R2), so a required
    :class:`ConceptsField` has no hook into model validation without this.

    The wrapper resolves the required ``ConceptsField``s from
    ``type(self)._meta.get_fields()`` *at call time* rather than closing
    over the field instance that triggered this install — the install runs
    once per class, so a wrapper bound to one field would leave a second
    required ``ConceptsField`` on the same class silently unenforced, with
    nothing raising and no test failing.

    That call-time resolution is also why the guard tests the resolved
    ``full_clean`` itself rather than a flag on the class. A subclass
    inherits a wrapper that already enumerates ``type(self)``'s fields, so
    it needs no wrapper of its own, and installing a second one around the
    first would report every empty required field twice on a multi-table
    child. A subclass that overrides ``full_clean`` itself gets an untagged
    method and is wrapped normally.

    An unsaved record (``pk`` is ``None``) is skipped outright: touching a
    many-to-many manager before the instance has a primary key raises
    ``ValueError``, which ``full_clean`` does not catch, and a record's
    memberships cannot exist before the record does (D3). The wrapped
    ``full_clean``'s own errors survive — this only adds to the error
    dictionary it raises, under each empty required field's own name, and
    re-raises the merged whole.

    A *saved* record is skipped too, but only for the call
    ``ModelForm._post_clean()`` makes (#124). That call happens before
    ``save_m2m()`` attaches anything a submission carries, so this check
    would otherwise read the relation exactly as it stood before the
    submission — refusing the one write that would have populated it, on an
    existing record whose relation happens to still be empty. Django's own
    ``forms/models.py`` has exactly one caller of ``Model.full_clean()``
    (``BaseModelForm._post_clean``, confirmed against the installed wheel),
    and it is the only caller that passes ``validate_unique=False`` — every
    other path, direct or otherwise, takes that parameter's default of
    ``True``. That makes it the one signal available to tell a ModelForm's
    own call apart from a direct one without threading form state through
    ``full_clean``'s call chain. It is safe to key off: the required half of
    FR-010's "by any form built from the model" clause is already carried by
    ``ManyToManyField.formfield()``'s own ``required=not blank``, which
    Django's ``ModelMultipleChoiceField`` checks against the *submitted*
    data rather than the instance, so it is unaffected by where ``save_m2m``
    falls in the lifecycle. A direct ``full_clean()`` call — the other half
    of FR-010 — keeps ``validate_unique`` at its default and stays checked.
    """
    if getattr(cls.full_clean, "_concepts_field_required_set_check", False):
        return
    original_full_clean = cls.full_clean

    def full_clean(self, exclude=None, validate_unique=True, validate_constraints=True):
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

        if self.pk is not None and validate_unique:
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
    """A ``ManyToManyField`` to ``controlled_vocabularies.Concept``, optionally
    constrained to one or more named vocabularies.

    ``vocabulary`` is optional (FR-002, ``decisions.md`` D9) and takes three
    shapes, through the :class:`ConceptFieldMixin` contract both fields
    inherit: a single slug, a list of slugs, or omitted entirely. A declaration naming no vocabulary is
    a supported shape rather than an error — it keeps the delete protection
    T003 builds, the label/URI readback, and the required-set rule, and gives
    up only the restriction. :class:`ConceptField` takes the same three shapes
    and means the same thing by each (#111).

    ``to`` and ``limit_choices_to`` are not the consumer's to supply: ``to``
    is fixed and ``limit_choices_to`` is derived from ``vocabulary``, set only
    when the declaration named at least one (an empty restriction is not set
    at all, rather than a restriction that matches everything by accident).
    ``through`` is refused outright, for the same reason ``ConceptField``
    refuses ``on_delete`` — a consumer-supplied membership model would
    silently drop the delete guarantee T003 provides.

    ``to`` stays the *string* ``"controlled_vocabularies.Concept"``, never the
    imported class — see :class:`ConceptField`'s docstring for why.
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
        """Attach the field, then generate the ``PROTECT`` membership model in
        place of ``ManyToManyField``'s own ``CASCADE`` one (T003, FR-007).

        ``ManyToManyField.contribute_to_class`` generates and registers its
        own through model inside its own body, after its ``super()`` call and
        before returning — there is no seam an ordinary ``super()`` call
        leaves open to substitute a different one. Calling it and then
        generating a second model of the same name registers that name twice,
        and Django's app registry warns ``Model … was already registered`` on
        every consuming declaration. The way through is entering the MRO one
        class higher,
        ``super(ManyToManyField, self).contribute_to_class(cls, name,
        **kwargs)``, which attaches the field without generating anything.

        That skip drops ``ManyToManyField.contribute_to_class``'s own hidden
        ``related_name`` rewrite (the branch that keeps
        ``related_name="+"`` from clashing between two such fields on one
        model, FR-011), so it is replicated here, before the ``super()``
        call. The symmetrical branch (self-referential relations) is not
        replicated: the target is always ``Concept`` and never the owner, so
        that condition can never hold for this field.

        Once the through model exists, an ``m2m_changed`` receiver is
        connected against it (FR-005, D2, T005) — but only when the
        declaration named at least one vocabulary; a field naming none has
        nothing to enforce, and connecting a receiver that would return
        immediately keeps Django's ``bulk_create`` fast path permanently
        disabled for no guarantee gained (R6). Connecting it here, rather
        than in ``AppConfig.ready()`` or on import of some other module, is
        load-bearing: R6 found that a truthy ``auto_created`` re-enables
        that fast path, which skips ``m2m_changed`` entirely whenever no
        receiver is connected for the through model. Binding the receiver
        at the moment the through model is generated means a declaration
        cannot exist without its own guard. ``weak=False`` because the
        receiver is a fresh ``partial`` with no other reference keeping it
        alive — a weak reference would let it be garbage-collected before
        any write ever reaches it.

        Alongside the through generation, ``get_<name>_labels()`` and
        ``get_<name>_uris()`` are contributed to the consuming model
        (FR-008, FR-009, T008) — plural, named the way ``ConceptField``'s
        own singular ``get_<name>_label()``/``get_<name>_uri()`` are.
        Labels come from each attached concept's
        :meth:`~controlled_vocabularies.models.Concept.display_label`,
        which already resolves the active language with fallback to the
        vocabulary's default; URIs are each concept's ``uri`` unchanged.
        An unsaved instance (``pk`` is ``None``) is guarded explicitly:
        Django's many-to-many manager raises ``ValueError`` the moment its
        queryset is touched before the instance has a primary key, and
        both accessors promise an empty result rather than a raise for a
        record holding nothing. The ``setattr`` is guarded exactly like
        ``ConceptField``'s: a model that already defines either name keeps
        its own definition.
        """
        if self.remote_field.hidden:
            self.remote_field.related_name = (
                f"_{cls._meta.app_label}_{cls.__name__.lower()}_{name}_+"
            )
        super(ManyToManyField, self).contribute_to_class(cls, name, **kwargs)

        if not cls._meta.abstract and not cls._meta.swapped:
            self.remote_field.through = _create_membership_model(self, cls)
            _install_required_set_check(cls)
            if self.vocabulary:
                m2m_changed.connect(
                    partial(
                        _refuse_concepts_the_restriction_does_not_admit, field=self
                    ),
                    sender=self.remote_field.through,
                    weak=False,
                )

            def get_labels(instance):
                if instance.pk is None:
                    return []
                return [
                    concept.display_label() for concept in getattr(instance, name).all()
                ]

            def get_uris(instance):
                if instance.pk is None:
                    return []
                return [concept.uri for concept in getattr(instance, name).all()]

            self._contribute_accessor(cls, f"get_{name}_labels", get_labels)
            self._contribute_accessor(cls, f"get_{name}_uris", get_uris)

        setattr(cls, self.name, ManyToManyDescriptor(self.remote_field, reverse=False))
        self.m2m_db_table = partial(self._get_m2m_db_table, cls._meta)
