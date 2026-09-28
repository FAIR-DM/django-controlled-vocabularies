"""Lookup of the Django admin's related-field widget wrapper, which stays an optional dependency."""

from django.apps import apps


def related_field_widget_wrapper_class():
    """Return the admin's ``RelatedFieldWidgetWrapper`` class, if the admin is installed.

    The import stays inside the function so this module loads without ``django.contrib.admin``
    (docs/adr/0013-the-django-admin-stays-an-optional-dependency.md).

    Returns:
        The wrapper class, or ``None`` when ``django.contrib.admin`` is not installed.
    """
    if not apps.is_installed("django.contrib.admin"):
        return None

    from django.contrib.admin.widgets import RelatedFieldWidgetWrapper

    return RelatedFieldWidgetWrapper
