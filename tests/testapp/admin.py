"""Admin registrations for the test project's consuming models."""

from django.contrib import admin

from tests.testapp.models import Outcrop, RockSample, Specimen

# Every registration is bare, because declaring the model field must be enough. Admins
# that declare something live on their own sites in tests/test_admin.py (FS-012).


@admin.register(Specimen)
class SpecimenAdmin(admin.ModelAdmin):
    """A model carrying a single-value concept field, declaring nothing."""


@admin.register(Outcrop)
class OutcropAdmin(admin.ModelAdmin):
    """A model carrying a multi-value concept field, declaring nothing."""


@admin.register(RockSample)
class RockSampleAdmin(admin.ModelAdmin):
    """A model carrying both kinds of concept field, declaring nothing."""
