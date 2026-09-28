"""App config for the consuming test app."""

from django.apps import AppConfig


# Lives under tests/, not in the package: a consumer of ConceptField belongs to the
# suite, and shipping it would make a fixture part of every install.
class TestappConfig(AppConfig):
    """Configure the consuming test app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "tests.testapp"
    label = "testapp"
