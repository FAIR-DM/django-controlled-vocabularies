"""The one admin-facing lookup this package owns (T006, FR-004, FR-006).

Registers nothing. ``forms.py``'s declining mixin calls
:func:`related_field_widget_wrapper_class` on every ``widget`` assignment, so
this module is imported on every render regardless of whether the admin is
installed — FR-006 is satisfied by the import inside this function staying
conditional, not by keeping this module itself unimported (plan.md,
"Structure Decision").
"""

from django.apps import apps


def related_field_widget_wrapper_class():
    """``django.contrib.admin.widgets.RelatedFieldWidgetWrapper``, or ``None``
    when ``django.contrib.admin`` is not among the installed applications.
    """
    if not apps.is_installed("django.contrib.admin"):
        return None

    from django.contrib.admin.widgets import RelatedFieldWidgetWrapper

    return RelatedFieldWidgetWrapper
